"""
Invoice calculation engine for OpenZEV.

Algorithm:
1. Collect participant IN readings and participant OUT production readings in period.
2. For each timestamp, compute ZEV total consumption and production.
3. Allocate local energy per timestamp (not only per-period) using participant share of that timestamp.
4. Price local/grid energy consumption and producer compensation per timestamp (HT/NT aware).
5. Build invoice totals and line items.
"""
import logging
from datetime import date, datetime, timezone as tz, timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.db import models, transaction
from django.utils import timezone

from accounts.models import VatRate
from zev.models import Zev, Participant, MeteringPoint, MeteringPointType, MeteringPointAssignment
from tariffs.models import BillingMode, EnergyType, PeriodType, Tariff, TariffCategory
from metering.models import MeterReading, ReadingDirection
from .models import Invoice, InvoiceItem, InvoiceStatus

logger = logging.getLogger(__name__)


def _period_to_dt(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=tz.utc)


CATEGORY_SORT_ORDER = {
    TariffCategory.ENERGY: 100,
    TariffCategory.GRID_FEES: 200,
    TariffCategory.LEVIES: 300,
}

ENERGY_TYPE_SORT_ORDER = {
    EnergyType.LOCAL: 10,
    EnergyType.GRID: 20,
    EnergyType.FEED_IN: 30,
    None: 40,
}


def _tariff_is_active(tariff: Tariff, day: date) -> bool:
    return tariff.valid_from <= day and (tariff.valid_to is None or tariff.valid_to >= day)


def _get_tariff_price(tariff: Tariff, ts: datetime) -> Decimal | None:
    """Find the applicable price for a given tariff and timestamp."""
    periods = list(tariff.periods.all())
    if not periods:
        return None

    # Find matching period (HT/NT or flat)
    t_time = ts.time()
    weekday = ts.weekday()  # 0 = Monday
    for period in periods:
        if period.period_type == PeriodType.FLAT:
            return period.price_chf_per_kwh
        if period.time_from and period.time_to:
            allowed_weekdays = (
                [int(d) for d in period.weekdays.split(",") if d.strip()]
                if period.weekdays else list(range(7))
            )
            if weekday in allowed_weekdays and period.time_from <= t_time < period.time_to:
                return period.price_chf_per_kwh

    # Fall back to first period
    return periods[0].price_chf_per_kwh


def _resolve_vat_rate(zev: Zev, period_end: date) -> Decimal:
    if not zev.vat_number:
        return Decimal("0")
    active_rate = VatRate.active_for_day(period_end)
    return Decimal(active_rate.rate) if active_rate else Decimal("0")


def _month_start(day: date) -> date:
    return date(day.year, day.month, 1)


def _next_month(day: date) -> date:
    if day.month == 12:
        return date(day.year + 1, 1, 1)
    return date(day.year, day.month + 1, 1)


def _count_intersecting_months(start: date, end: date) -> int:
    if start > end:
        return 0

    count = 0
    cursor = _month_start(start)
    last_month = _month_start(end)
    while cursor <= last_month:
        count += 1
        cursor = _next_month(cursor)
    return count


def _count_billable_months(tariff: Tariff, period_start: date, period_end: date) -> int:
    overlap_start = max(period_start, tariff.valid_from)
    overlap_end = min(period_end, tariff.valid_to or period_end)
    return _count_intersecting_months(overlap_start, overlap_end)


def _month_has_active_participant_metering_points(participant: Participant, month_first_day: date, month_last_day: date) -> bool:
    return MeteringPointAssignment.objects.filter(
        participant=participant,
        valid_from__lte=month_last_day,
    ).filter(
        models.Q(valid_to__isnull=True) | models.Q(valid_to__gte=month_first_day),
        metering_point__is_active=True,
    ).exists()


def _count_billable_metering_points_by_month(participant: Participant, tariff: Tariff, period_start: date, period_end: date) -> int:
    overlap_start = max(period_start, tariff.valid_from)
    overlap_end = min(period_end, tariff.valid_to or period_end)
    if overlap_start > overlap_end:
        return 0

    total_metering_points = 0
    cursor = _month_start(overlap_start)
    last_month = _month_start(overlap_end)
    while cursor <= last_month:
        next_month = _next_month(cursor)
        month_first_day = cursor
        month_last_day = next_month - timedelta(days=1)

        month_start = max(month_first_day, overlap_start)
        month_end = min(month_last_day, overlap_end)
        if month_start <= month_end and _month_has_active_participant_metering_points(participant, month_first_day, month_last_day):
            month_points = MeteringPointAssignment.objects.filter(
                participant=participant,
                valid_from__lte=month_end,
            ).filter(
                models.Q(valid_to__isnull=True) | models.Q(valid_to__gte=month_start),
                metering_point__is_active=True,
            ).values("metering_point_id").distinct().count()
            total_metering_points += month_points

        cursor = next_month

    return total_metering_points


_ENERGY_BILLING_MODES = {BillingMode.ENERGY, BillingMode.PERCENTAGE_OF_ENERGY}


def _get_item_type(tariff: Tariff) -> str:
    if tariff.billing_mode not in _ENERGY_BILLING_MODES:
        return InvoiceItem.ItemType.CREDIT if (tariff.fixed_price_chf or Decimal("0")) < 0 else InvoiceItem.ItemType.FEE
    if tariff.energy_type == EnergyType.FEED_IN:
        return InvoiceItem.ItemType.FEED_IN
    if tariff.energy_type == EnergyType.GRID:
        return InvoiceItem.ItemType.GRID_ENERGY
    return InvoiceItem.ItemType.LOCAL_ENERGY


# Translations for billing mode description suffixes used in invoice line items.
# Each language maps singular/plural forms for each billing mode.
DESCRIPTION_TRANSLATIONS: dict[str, dict] = {
    "de": {
        "yearly_fee_sg": "monatliche Rate der Jahresgebühr",
        "yearly_fee_pl": "monatliche Raten der Jahresgebühr",
        "mp_yearly_sg": "monatliche Rate pro Messpunkt",
        "mp_yearly_pl": "monatliche Raten pro Messpunkt",
        "mp_monthly_sg": "Messpunkt-Monat",
        "mp_monthly_pl": "Messpunkt-Monate",
        "monthly_sg": "Monat",
        "monthly_pl": "Monate",
        "pct_of": "von CHF",
    },
    "fr": {
        "yearly_fee_sg": "mensualité de la redevance annuelle",
        "yearly_fee_pl": "mensualités de la redevance annuelle",
        "mp_yearly_sg": "mensualité par point de mesure",
        "mp_yearly_pl": "mensualités par point de mesure",
        "mp_monthly_sg": "mois-point de mesure",
        "mp_monthly_pl": "mois-points de mesure",
        "monthly_sg": "mois",
        "monthly_pl": "mois",
        "pct_of": "de CHF",
    },
    "it": {
        "yearly_fee_sg": "rata mensile della tariffa annuale",
        "yearly_fee_pl": "rate mensili della tariffa annuale",
        "mp_yearly_sg": "rata mensile per punto di misurazione",
        "mp_yearly_pl": "rate mensili per punto di misurazione",
        "mp_monthly_sg": "mese-punto di misurazione",
        "mp_monthly_pl": "mesi-punto di misurazione",
        "monthly_sg": "mese",
        "monthly_pl": "mesi",
        "pct_of": "di CHF",
    },
    "en": {
        "yearly_fee_sg": "monthly installment of annual fee",
        "yearly_fee_pl": "monthly installments of annual fee",
        "mp_yearly_sg": "monthly installment per metering point",
        "mp_yearly_pl": "monthly installments per metering point",
        "mp_monthly_sg": "metering-point month",
        "mp_monthly_pl": "metering-point months",
        "monthly_sg": "month",
        "monthly_pl": "months",
        "pct_of": "of CHF",
    },
}


def _build_description(
    tariff: Tariff,
    period_start: date,
    period_end: date,
    quantity: Decimal,
    lang: str = "de",
    *,
    base_rate: Decimal | None = None,
) -> str:
    if tariff.billing_mode == BillingMode.ENERGY:
        return tariff.name
    if tariff.billing_mode == BillingMode.PERCENTAGE_OF_ENERGY:
        pct = tariff.percentage or Decimal("0")
        # Format: remove trailing zeros (50.00 → 50, 33.50 → 33.5)
        pct_str = f"{pct:f}".rstrip("0").rstrip(".")
        if base_rate is not None:
            t = DESCRIPTION_TRANSLATIONS.get(lang, DESCRIPTION_TRANSLATIONS["de"])
            base_str = f"{base_rate:f}".rstrip("0").rstrip(".")
            return f"{tariff.name} ({pct_str}% {t['pct_of']} {base_str}/kWh)"
        return f"{tariff.name} ({pct_str}%)"

    t = DESCRIPTION_TRANSLATIONS.get(lang, DESCRIPTION_TRANSLATIONS["de"])
    months = int(quantity)

    if tariff.billing_mode == BillingMode.YEARLY_FEE:
        suffix = t["yearly_fee_sg"] if months == 1 else t["yearly_fee_pl"]
        return f"{tariff.name} ({months} {suffix})"

    if tariff.billing_mode == BillingMode.PER_METERING_POINT_YEARLY_FEE:
        suffix = t["mp_yearly_sg"] if months == 1 else t["mp_yearly_pl"]
        return f"{tariff.name} ({months} {suffix})"

    if tariff.billing_mode == BillingMode.PER_METERING_POINT_MONTHLY_FEE:
        suffix = t["mp_monthly_sg"] if months == 1 else t["mp_monthly_pl"]
        return f"{tariff.name} ({months} {suffix})"

    suffix = t["monthly_sg"] if months == 1 else t["monthly_pl"]
    return f"{tariff.name} ({months} {suffix})"


def _build_sort_order(tariff: Tariff) -> int:
    category_rank = CATEGORY_SORT_ORDER.get(tariff.category, 900)
    energy_rank = ENERGY_TYPE_SORT_ORDER.get(tariff.energy_type, 40)
    mode_rank = {
        BillingMode.ENERGY: 0,
        BillingMode.PERCENTAGE_OF_ENERGY: 1,
        BillingMode.MONTHLY_FEE: 2,
        BillingMode.YEARLY_FEE: 3,
        BillingMode.PER_METERING_POINT_MONTHLY_FEE: 4,
        BillingMode.PER_METERING_POINT_YEARLY_FEE: 5,
    }.get(tariff.billing_mode, 9)
    return category_rank + energy_rank + mode_rank


@transaction.atomic
def generate_invoice(participant: Participant, period_start: date, period_end: date) -> Invoice:
    """
    Generate (or regenerate) an invoice for a participant for the given period.
    Existing DRAFT invoice for the same period will be replaced.
    Raises ValueError if a non-draft, non-cancelled invoice already exists.
    """
    zev = participant.zev
    start_dt = _period_to_dt(period_start)
    end_dt = _period_to_dt(period_end) + timedelta(days=1)  # exclusive upper bound

    # Guard: do not overwrite already-approved/sent/paid invoices
    locked = Invoice.objects.filter(
        participant=participant,
        period_start=period_start,
        period_end=period_end,
    ).exclude(status__in=[InvoiceStatus.DRAFT, InvoiceStatus.CANCELLED]).first()
    if locked:
        raise ValueError(
            f"Invoice {locked.invoice_number} already has status '{locked.status}' and cannot be regenerated."
        )

    # Delete any existing draft or cancelled invoice for this period
    Invoice.objects.filter(
        participant=participant,
        period_start=period_start,
        period_end=period_end,
        status__in=[InvoiceStatus.DRAFT, InvoiceStatus.CANCELLED],
    ).delete()

    # ─── 1. Collect participant consumption readings ───────────────────────
    consumption_mps = MeteringPoint.objects.filter(
        participant=participant,
        meter_type__in=[MeteringPointType.CONSUMPTION, MeteringPointType.BIDIRECTIONAL],
    )
    participant_readings = MeterReading.objects.filter(
        metering_point__in=consumption_mps,
        timestamp__gte=start_dt,
        timestamp__lt=end_dt,
        direction=ReadingDirection.IN,
    )
    total_participant_kwh = sum(r.energy_kwh for r in participant_readings) or Decimal("0")

    # ─── 2. Collect participant production (OUT) readings ──────────────────
    production_mps = MeteringPoint.objects.filter(
        participant=participant,
        meter_type__in=[MeteringPointType.PRODUCTION, MeteringPointType.BIDIRECTIONAL],
    )
    feedin_readings = MeterReading.objects.filter(
        metering_point__in=production_mps,
        timestamp__gte=start_dt,
        timestamp__lt=end_dt,
        direction=ReadingDirection.OUT,
    )
    # ─── 3. Calculate ZEV total production/consumption by timestamp ───────
    all_production_mps = MeteringPoint.objects.filter(
        participant__zev=zev,
        meter_type__in=[MeteringPointType.PRODUCTION, MeteringPointType.BIDIRECTIONAL],
    )
    zev_production_by_ts = {
        row["timestamp"]: row["total_kwh"] or Decimal("0")
        for row in MeterReading.objects.filter(
            metering_point__in=all_production_mps,
            timestamp__gte=start_dt,
            timestamp__lt=end_dt,
            direction=ReadingDirection.OUT,
        )
        .values("timestamp")
        .annotate(total_kwh=models.Sum("energy_kwh"))
    }

    all_consumption_mps = MeteringPoint.objects.filter(
        participant__zev=zev,
        meter_type__in=[MeteringPointType.CONSUMPTION, MeteringPointType.BIDIRECTIONAL],
    )
    zev_consumption_by_ts = {
        row["timestamp"]: row["total_kwh"] or Decimal("0")
        for row in MeterReading.objects.filter(
            metering_point__in=all_consumption_mps,
            timestamp__gte=start_dt,
            timestamp__lt=end_dt,
            direction=ReadingDirection.IN,
        )
        .values("timestamp")
        .annotate(total_kwh=models.Sum("energy_kwh"))
    }

    # ─── 6. Fetch applicable tariffs ─────────────────────────────────────
    tariffs_list = list(
        Tariff.objects.filter(zev=zev).prefetch_related("periods")
    )

    # ─── 7. Per-reading HT/NT-aware pricing with timestamp allocation ─────
    local_kwh_acc = Decimal("0")
    grid_kwh_acc = Decimal("0")

    item_accumulators: dict[str, dict[str, Decimal | str | Tariff]] = {}

    def accumulate_item(
        *,
        tariff: Tariff,
        quantity: Decimal,
        total: Decimal,
        unit: str,
        base_total: Decimal | None = None,
        bucket: str = "default",
    ) -> None:
        if quantity == 0 and total == 0:
            return
        key = f"{tariff.id}:{bucket}"
        if key not in item_accumulators:
            item_accumulators[key] = {
                "tariff": tariff,
                "quantity": Decimal("0"),
                "total": Decimal("0"),
                "unit": unit,
                "base_total": Decimal("0"),
            }
        item_accumulators[key]["quantity"] += quantity
        item_accumulators[key]["total"] += total
        if base_total is not None:
            item_accumulators[key]["base_total"] += base_total

    for reading in participant_readings.order_by("timestamp").iterator():
        ts = reading.timestamp
        participant_kwh = reading.energy_kwh
        zev_consumption_at_ts = zev_consumption_by_ts.get(ts, Decimal("0"))
        zev_production_at_ts = zev_production_by_ts.get(ts, Decimal("0"))
        local_pool_at_ts = min(zev_production_at_ts, zev_consumption_at_ts)

        if zev_consumption_at_ts > 0 and local_pool_at_ts > 0:
            participant_share = participant_kwh / zev_consumption_at_ts
            r_local = min(participant_kwh, local_pool_at_ts * participant_share)
        else:
            r_local = Decimal("0")
        r_grid = max(participant_kwh - r_local, Decimal("0"))

        local_kwh_acc += r_local
        grid_kwh_acc += r_grid

        # Compute GRID energy base sum once per timestamp.
        # Percentage-of-energy tariffs price any energy type as a fraction of
        # what a participant would normally pay for grid energy.
        active_grid_energy_tariffs = [
            t for t in tariffs_list
            if t.billing_mode == BillingMode.ENERGY
            and t.energy_type == EnergyType.GRID
            and _tariff_is_active(t, ts.date())
        ]
        grid_base_price_sum = sum(
            (_get_tariff_price(t, ts) or Decimal("0")) for t in active_grid_energy_tariffs
        )

        for energy_type, quantity in ((EnergyType.LOCAL, r_local), (EnergyType.GRID, r_grid)):
            if quantity <= 0:
                continue
            active_energy_tariffs = [
                tariff for tariff in tariffs_list
                if tariff.billing_mode == BillingMode.ENERGY
                and tariff.energy_type == energy_type
                and _tariff_is_active(tariff, ts.date())
            ]
            for tariff in active_energy_tariffs:
                price = _get_tariff_price(tariff, ts) or Decimal("0")
                accumulate_item(
                    tariff=tariff,
                    quantity=quantity,
                    total=quantity * price,
                    unit="kWh",
                )

            # Percentage-of-energy tariffs: base is always the GRID rate sum,
            # applied to whichever energy_type the tariff is configured for.
            for tariff in tariffs_list:
                if (
                    tariff.billing_mode == BillingMode.PERCENTAGE_OF_ENERGY
                    and tariff.energy_type == energy_type
                    and tariff.percentage
                    and _tariff_is_active(tariff, ts.date())
                ):
                    effective_price = grid_base_price_sum * (tariff.percentage / Decimal("100"))
                    accumulate_item(
                        tariff=tariff,
                        quantity=quantity,
                        total=quantity * effective_price,
                        unit="kWh",
                        base_total=quantity * grid_base_price_sum,
                    )

    exported_kwh_acc = Decimal("0")

    for reading in feedin_readings.order_by("timestamp").iterator():
        ts = reading.timestamp
        produced_kwh = reading.energy_kwh

        zev_production_at_ts = zev_production_by_ts.get(ts, Decimal("0"))
        zev_consumption_at_ts = zev_consumption_by_ts.get(ts, Decimal("0"))
        local_pool_at_ts = min(zev_production_at_ts, zev_consumption_at_ts)
        export_pool_at_ts = max(zev_production_at_ts - zev_consumption_at_ts, Decimal("0"))

        if zev_production_at_ts > 0:
            producer_share = produced_kwh / zev_production_at_ts
            local_sold_kwh = local_pool_at_ts * producer_share
            exported_kwh = export_pool_at_ts * producer_share
        else:
            local_sold_kwh = Decimal("0")
            exported_kwh = Decimal("0")

        exported_kwh_acc += exported_kwh

        active_grid_energy_tariffs = [
            t for t in tariffs_list
            if t.billing_mode == BillingMode.ENERGY
            and t.energy_type == EnergyType.GRID
            and _tariff_is_active(t, ts.date())
        ]
        grid_base_price_sum = sum(
            (_get_tariff_price(t, ts) or Decimal("0")) for t in active_grid_energy_tariffs
        )

        if local_sold_kwh > 0:
            active_local_energy_tariffs = [
                tariff for tariff in tariffs_list
                if tariff.billing_mode == BillingMode.ENERGY
                and tariff.energy_type == EnergyType.LOCAL
                and _tariff_is_active(tariff, ts.date())
            ]
            for tariff in active_local_energy_tariffs:
                price = _get_tariff_price(tariff, ts) or Decimal("0")
                accumulate_item(
                    tariff=tariff,
                    quantity=local_sold_kwh,
                    total=-(local_sold_kwh * price),
                    unit="kWh",
                    bucket="producer_credit",
                )

            for tariff in tariffs_list:
                if (
                    tariff.billing_mode == BillingMode.PERCENTAGE_OF_ENERGY
                    and tariff.energy_type == EnergyType.LOCAL
                    and tariff.percentage
                    and _tariff_is_active(tariff, ts.date())
                ):
                    effective_price = grid_base_price_sum * (tariff.percentage / Decimal("100"))
                    accumulate_item(
                        tariff=tariff,
                        quantity=local_sold_kwh,
                        total=-(local_sold_kwh * effective_price),
                        unit="kWh",
                        base_total=(local_sold_kwh * grid_base_price_sum),
                        bucket="producer_credit",
                    )

        if exported_kwh > 0:
            active_feed_in_tariffs = [
                tariff for tariff in tariffs_list
                if tariff.billing_mode == BillingMode.ENERGY
                and tariff.energy_type == EnergyType.FEED_IN
                and _tariff_is_active(tariff, ts.date())
            ]
            for tariff in active_feed_in_tariffs:
                price = _get_tariff_price(tariff, ts) or Decimal("0")
                accumulate_item(
                    tariff=tariff,
                    quantity=exported_kwh,
                    total=-(exported_kwh * price),
                    unit="kWh",
                )

    for tariff in tariffs_list:
        if tariff.billing_mode in _ENERGY_BILLING_MODES:
            continue
        month_count = _count_billable_months(tariff, period_start, period_end)
        if month_count <= 0:
            continue

        quantity = Decimal(month_count)
        if tariff.billing_mode == BillingMode.MONTHLY_FEE:
            unit_price = tariff.fixed_price_chf or Decimal("0")
        elif tariff.billing_mode == BillingMode.YEARLY_FEE:
            unit_price = (tariff.fixed_price_chf or Decimal("0")) / Decimal("12")
        elif tariff.billing_mode == BillingMode.PER_METERING_POINT_MONTHLY_FEE:
            quantity = Decimal(_count_billable_metering_points_by_month(participant, tariff, period_start, period_end))
            if quantity <= 0:
                continue
            unit_price = tariff.fixed_price_chf or Decimal("0")
        else:
            quantity = Decimal(_count_billable_metering_points_by_month(participant, tariff, period_start, period_end))
            if quantity <= 0:
                continue
            unit_price = (tariff.fixed_price_chf or Decimal("0")) / Decimal("12")

        accumulate_item(
            tariff=tariff,
            quantity=quantity,
            total=quantity * unit_price,
            unit="month",
        )

    Q = Decimal("0.01")
    local_kwh = local_kwh_acc.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    grid_kwh = grid_kwh_acc.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

    item_payloads = []
    subtotal = Decimal("0")
    for accumulator in item_accumulators.values():
        tariff = accumulator["tariff"]
        quantity = Decimal(accumulator["quantity"])
        total = Decimal(accumulator["total"])
        if quantity == 0 and total == 0:
            continue

        quantized_total = total.quantize(Q, rounding=ROUND_HALF_UP)
        subtotal += quantized_total
        if quantity != 0:
            unit_price = (total / quantity).quantize(Decimal("0.00001"), rounding=ROUND_HALF_UP)
        else:
            unit_price = Decimal("0")

        raw_base_total = accumulator.get("base_total", Decimal("0"))
        item_payloads.append({
            "tariff": tariff,
            "quantity": quantity.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
            "unit": str(accumulator["unit"]),
            "unit_price": unit_price,
            "total": quantized_total,
            "base_rate": (raw_base_total / quantity).quantize(Decimal("0.00001"), rounding=ROUND_HALF_UP) if quantity and raw_base_total else None,
        })

    subtotal = subtotal.quantize(Q, rounding=ROUND_HALF_UP)

    vat_rate = _resolve_vat_rate(zev, period_end)
    vat_chf = (subtotal * vat_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    total_chf = subtotal + vat_chf

    # ─── 8. Create invoice ────────────────────────────────────────────────
    invoice_number = zev.next_invoice_number()
    invoice = Invoice.objects.create(
        invoice_number=invoice_number,
        zev=zev,
        participant=participant,
        period_start=period_start,
        period_end=period_end,
        status=InvoiceStatus.DRAFT,
        total_local_kwh=local_kwh,
        total_grid_kwh=grid_kwh,
        total_feed_in_kwh=exported_kwh_acc.quantize(Decimal("0.0001")),
        subtotal_chf=subtotal,
        vat_rate=vat_rate,
        vat_chf=vat_chf,
        total_chf=total_chf,
    )

    # ─── 9. Create line items ─────────────────────────────────────────────
    items = []
    for payload in sorted(item_payloads, key=lambda entry: (_build_sort_order(entry["tariff"]), entry["tariff"].name.lower())):
        tariff = payload["tariff"]
        lang = participant.zev.invoice_language or "de"
        items.append(InvoiceItem(
            invoice=invoice,
            item_type=_get_item_type(tariff),
            tariff_category=tariff.category,
            description=_build_description(
                tariff, period_start, period_end, payload["quantity"], lang,
                base_rate=payload.get("base_rate"),
            ),
            quantity_kwh=payload["quantity"],
            unit=payload["unit"],
            unit_price_chf=payload["unit_price"],
            total_chf=payload["total"],
            sort_order=_build_sort_order(tariff),
        ))
    InvoiceItem.objects.bulk_create(items)

    logger.info("Generated invoice %s for %s: %s CHF", invoice_number, participant.full_name, total_chf)
    return invoice


def generate_invoices_for_zev(zev: Zev, period_start: date, period_end: date) -> list:
    """Generate invoices for ALL active participants in a ZEV."""
    participants = zev.participants.filter(
        valid_from__lte=period_end,
    ).filter(
        models.Q(valid_to__isnull=True) | models.Q(valid_to__gte=period_start)
    )
    return [generate_invoice(p, period_start, period_end) for p in participants]
