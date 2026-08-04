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
from typing import Iterable, NamedTuple

from django.db import models, transaction
from django.utils import timezone

from billiard.exceptions import SoftTimeLimitExceeded

from accounts.models import VatRate
from allocation.split import split_consumption, split_production
from allocation.windows import AssignmentWindows
from zev.models import Zev, Participant, MeteringPoint, MeteringPointType, MeteringPointAssignment
from tariffs.models import BillingMode, EnergyType, PeriodType, Tariff, TariffCategory
from metering.models import MeterReading, ReadingDirection
from .models import Invoice, InvoiceItem, InvoiceStatus

logger = logging.getLogger(__name__)


# ─── Allocation ───────────────────────────────────────────────────────────────
#
# How the community's solar output is divided between its members at a single
# timestamp lives in ``allocation.split`` (ADR 0013); the imports above keep
# existing importers working.


# ─── Gathering ────────────────────────────────────────────────────────────────


CONSUMPTION_METER_TYPES = [MeteringPointType.CONSUMPTION, MeteringPointType.BIDIRECTIONAL]
PRODUCTION_METER_TYPES = [MeteringPointType.PRODUCTION, MeteringPointType.BIDIRECTIONAL]


class PeriodReadings(NamedTuple):
    """Everything the pricing loops need to read, fetched once per invoice.

    The two ``*_by_ts`` maps are community-wide totals per timestamp; the two
    querysets are the individual participant's own readings. ``assignment_windows``
    resolves which of those readings the participant actually held at their
    timestamp (readings before an assignment started — or inside a gap — are
    skipped by the pricing loops).
    """

    participant_consumption: models.QuerySet
    participant_production: models.QuerySet
    zev_consumption_by_ts: dict
    zev_production_by_ts: dict
    assignment_windows: AssignmentWindows


def _assigned_metering_points(zev, meter_types, period_start, period_end, participant=None):
    """Metering points of ``meter_types`` assigned during the period.

    An assignment counts if it began on or before the period ended and had not
    already finished before it began. Passing ``participant`` narrows this to
    one member; omitting it covers the whole community.

    Bidirectional points appear in both the consumption and production sets,
    which is how a single meter can feed the pool and draw from it.
    """
    filters = {
        "zev": zev,
        "meter_type__in": meter_types,
        "assignments__valid_from__lte": period_end,
    }
    if participant is not None:
        filters["assignments__participant"] = participant
    return MeteringPoint.objects.filter(**filters).filter(
        models.Q(assignments__valid_to__isnull=True)
        | models.Q(assignments__valid_to__gte=period_start)
    ).distinct()


def _readings_in_period(metering_points, start_dt, end_dt, direction):
    return MeterReading.objects.filter(
        metering_point__in=metering_points,
        timestamp__gte=start_dt,
        timestamp__lt=end_dt,
        direction=direction,
    )


def _totals_by_timestamp(readings) -> dict:
    """Sum ``readings`` per timestamp, so a share can be worked out per interval."""
    return {
        row["timestamp"]: row["total_kwh"] or Decimal("0")
        for row in readings.values("timestamp").annotate(total_kwh=models.Sum("energy_kwh"))
    }


def _gather_period_readings(participant, period_start, period_end) -> PeriodReadings:
    """Fetch the participant's own readings and the community-wide totals."""
    zev = participant.zev
    start_dt = _period_to_dt(period_start)
    end_dt = _period_to_dt(period_end) + timedelta(days=1)  # exclusive upper bound

    def own_points(meter_types):
        return _assigned_metering_points(
            zev, meter_types, period_start, period_end,
            participant=participant,
        )

    def community_points(meter_types):
        # The pool covers every metering point of the ZEV regardless of
        # assignment (ADR 0013): a never-assigned meter still feeds the
        # community pool, even though its readings are billed to nobody.
        return MeteringPoint.objects.filter(zev=zev, meter_type__in=meter_types)

    return PeriodReadings(
        participant_consumption=_readings_in_period(
            own_points(CONSUMPTION_METER_TYPES), start_dt, end_dt, ReadingDirection.IN),
        participant_production=_readings_in_period(
            own_points(PRODUCTION_METER_TYPES), start_dt, end_dt, ReadingDirection.OUT),
        zev_consumption_by_ts=_totals_by_timestamp(_readings_in_period(
            community_points(CONSUMPTION_METER_TYPES), start_dt, end_dt, ReadingDirection.IN)),
        zev_production_by_ts=_totals_by_timestamp(_readings_in_period(
            community_points(PRODUCTION_METER_TYPES), start_dt, end_dt, ReadingDirection.OUT)),
        assignment_windows=AssignmentWindows.for_participant(participant, period_start, period_end),
    )


def _discard_replaceable_invoices(participant, period_start, period_end) -> None:
    """Clear the way for a regeneration, or refuse to.

    A draft or cancelled invoice overlapping this period is replaced; anything
    further along its lifecycle has been sent to somebody and must not be
    silently rewritten.
    """
    overlapping = Invoice.objects.filter(
        participant=participant,
        period_start__lte=period_end,
        period_end__gte=period_start,
    )
    locked = overlapping.exclude(
        status__in=[InvoiceStatus.DRAFT, InvoiceStatus.CANCELLED]
    ).first()
    if locked:
        raise ValueError(
            f"Invoice {locked.invoice_number} already has status '{locked.status}' and cannot be regenerated."
        )
    overlapping.filter(status__in=[InvoiceStatus.DRAFT, InvoiceStatus.CANCELLED]).delete()


# ─── Pricing state ────────────────────────────────────────────────────────────


class TariffResolver:
    """Answers "which tariffs apply on this day" without rescanning the list.

    The pricing loops ask that question once per reading, so the tariffs are
    bucketed by billing mode and energy type up front and the per-day validity
    filter is memoised. Only the two energy-priced modes are bucketed; fixed
    fees are handled separately and once, not per reading.
    """

    def __init__(self, tariffs: Iterable[Tariff]):
        self._energy: dict[str, list[Tariff]] = {}
        self._percentage: dict[str, list[Tariff]] = {}
        for tariff in tariffs:
            if tariff.billing_mode == BillingMode.ENERGY:
                self._energy.setdefault(tariff.energy_type, []).append(tariff)
            elif tariff.billing_mode == BillingMode.PERCENTAGE_OF_ENERGY and tariff.percentage:
                self._percentage.setdefault(tariff.energy_type, []).append(tariff)
        self._active_cache: dict[tuple[str, str, date], list[Tariff]] = {}

    def _active(self, bucket: str, buckets: dict, energy_type: str, day: date) -> list[Tariff]:
        key = (bucket, energy_type, day)
        if key not in self._active_cache:
            self._active_cache[key] = [
                tariff for tariff in buckets.get(energy_type, []) if _tariff_is_active(tariff, day)
            ]
        return self._active_cache[key]

    def energy(self, energy_type: str, day: date) -> list[Tariff]:
        """Tariffs priced per kWh of ``energy_type`` and valid on ``day``."""
        return self._active("energy", self._energy, energy_type, day)

    def percentage(self, energy_type: str, day: date) -> list[Tariff]:
        """Tariffs charging a percentage of the grid rate, valid on ``day``."""
        return self._active("pct", self._percentage, energy_type, day)


class ItemAccumulator:
    """Collects priced quantities per tariff until the invoice is written.

    One tariff can produce more than one invoice line: a participant with a
    bidirectional meter is charged for what they drew and credited for what
    they sold under the same tariff, which is what ``bucket`` separates.

    Iteration yields entries in the order they were first seen, which the
    caller's stable sort relies on to break ties.
    """

    def __init__(self):
        self._entries: dict[str, dict] = {}

    def add(
        self,
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
        entry = self._entries.get(key)
        if entry is None:
            entry = self._entries[key] = {
                "tariff": tariff,
                "quantity": Decimal("0"),
                "total": Decimal("0"),
                "unit": unit,
                "base_total": Decimal("0"),
            }
        entry["quantity"] += quantity
        entry["total"] += total
        if base_total is not None:
            entry["base_total"] += base_total

    def __iter__(self):
        return iter(self._entries.values())

    def __len__(self) -> int:
        return len(self._entries)


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


def _count_billable_metering_points_by_month(participant: Participant, tariff: Tariff, period_start: date, period_end: date) -> int:
    overlap_start = max(period_start, tariff.valid_from)
    overlap_end = min(period_end, tariff.valid_to or period_end)
    if overlap_start > overlap_end:
        return 0

    # Single fetch: month-by-month activity is computed in Python instead of
    # issuing two queries per month.
    assignments = list(
        MeteringPointAssignment.objects.filter(
            participant=participant,
            metering_point__is_active=True,
        ).values_list("metering_point_id", "valid_from", "valid_to")
    )

    total_metering_points = 0
    cursor = _month_start(overlap_start)
    last_month = _month_start(overlap_end)
    while cursor <= last_month:
        next_month = _next_month(cursor)
        month_first_day = cursor
        month_last_day = next_month - timedelta(days=1)

        month_start = max(month_first_day, overlap_start)
        month_end = min(month_last_day, overlap_end)
        month_has_active = any(
            vf <= month_last_day and (vt is None or vt >= month_first_day)
            for _mp_id, vf, vt in assignments
        )
        if month_start <= month_end and month_has_active:
            total_metering_points += len({
                mp_id
                for mp_id, vf, vt in assignments
                if vf <= month_end and (vt is None or vt >= month_start)
            })

        cursor = next_month

    return total_metering_points


def _overlaps(valid_from: date, valid_to: date | None, start: date, end: date) -> bool:
    """Whether a ``valid_from``/``valid_to`` window touches ``start``..``end``."""
    return valid_from <= end and (valid_to is None or valid_to >= start)


def _billable_months(tariff: Tariff, period_start: date, period_end: date):
    """Yield ``(month, billed_from, billed_to)`` for each month the fee covers.

    ``month`` is the first of the month and identifies it; the other two are
    clamped to the part of it that is actually billed, which is what membership
    is tested against. A period opening mid-month bills only from that day.
    """
    overlap_start = max(period_start, tariff.valid_from)
    overlap_end = min(period_end, tariff.valid_to or period_end)
    if overlap_start > overlap_end:
        return

    cursor = _month_start(overlap_start)
    last_month = _month_start(overlap_end)
    while cursor <= last_month:
        next_month = _next_month(cursor)
        yield (
            cursor,
            max(cursor, overlap_start),
            min(next_month - timedelta(days=1), overlap_end),
        )
        cursor = next_month


def _count_active_participants_by_month(zev: Zev, tariff: Tariff, period_start: date, period_end: date) -> dict[date, int]:
    """How many participants each billed month is shared between.

    Keyed by the first day of the month. A month with nobody active is absent
    rather than zero, so the caller cannot divide by it.

    Counted per month, not once over the period: somebody joining in February
    must not retroactively dilute January's share. This is also what makes the
    fee reconcile against ``generate_invoices_for_zev``, which invoices anyone
    active at *any* point in the period — a member who left in January is
    charged for January alone, and the months after that are divided between
    the members who remain.

    The count comes from the ZEV rather than from whichever invoices happen to
    exist, so generating one participant's invoice on its own yields the same
    share as a full run.
    """
    # Single fetch, then month-by-month in Python — same shape as the
    # per-metering-point count above.
    windows = list(
        Participant.objects.filter(zev=zev).values_list("valid_from", "valid_to")
    )

    counts: dict[date, int] = {}
    for month, billed_from, billed_to in _billable_months(tariff, period_start, period_end):
        # Membership is tested against the billed part of the month, so someone
        # who left before the period opened is not counted into the first
        # month's denominator — they receive no invoice, and counting them
        # would leave the community short.
        active = sum(
            1 for valid_from, valid_to in windows
            if _overlaps(valid_from, valid_to, billed_from, billed_to)
        )
        if active:
            counts[month] = active

    return counts


_ENERGY_BILLING_MODES = {BillingMode.ENERGY, BillingMode.PERCENTAGE_OF_ENERGY}
_SHARED_BILLING_MODES = {BillingMode.SHARED_MONTHLY_FEE, BillingMode.SHARED_YEARLY_FEE}


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
        "shared_monthly_sg": "Monat, Gemeinschaftskosten anteilig",
        "shared_monthly_pl": "Monate, Gemeinschaftskosten anteilig",
        "shared_yearly_sg": "monatliche Rate der Jahresgebühr, Gemeinschaftskosten anteilig",
        "shared_yearly_pl": "monatliche Raten der Jahresgebühr, Gemeinschaftskosten anteilig",
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
        "shared_monthly_sg": "mois, quote-part des frais communs",
        "shared_monthly_pl": "mois, quote-part des frais communs",
        "shared_yearly_sg": "mensualité de la redevance annuelle, quote-part des frais communs",
        "shared_yearly_pl": "mensualités de la redevance annuelle, quote-part des frais communs",
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
        "shared_monthly_sg": "mese, quota dei costi comuni",
        "shared_monthly_pl": "mesi, quota dei costi comuni",
        "shared_yearly_sg": "rata mensile della tariffa annuale, quota dei costi comuni",
        "shared_yearly_pl": "rate mensili della tariffa annuale, quota dei costi comuni",
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
        "shared_monthly_sg": "month, share of community costs",
        "shared_monthly_pl": "months, share of community costs",
        "shared_yearly_sg": "monthly installment of annual fee, share of community costs",
        "shared_yearly_pl": "monthly installments of annual fee, share of community costs",
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

    # The shared modes carry no participant count in the text: the denominator
    # is per month and can differ between the months on one line. The unit
    # price column already shows the average share.
    if tariff.billing_mode == BillingMode.SHARED_MONTHLY_FEE:
        suffix = t["shared_monthly_sg"] if months == 1 else t["shared_monthly_pl"]
        return f"{tariff.name} ({months} {suffix})"

    if tariff.billing_mode == BillingMode.SHARED_YEARLY_FEE:
        suffix = t["shared_yearly_sg"] if months == 1 else t["shared_yearly_pl"]
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
        BillingMode.SHARED_MONTHLY_FEE: 6,
        BillingMode.SHARED_YEARLY_FEE: 7,
    }.get(tariff.billing_mode, 9)
    return category_rank + energy_rank + mode_rank


def _price_fixed_fees(participant, tariffs, period_start, period_end, accumulator) -> None:
    """Charge the tariffs that bill by time rather than by energy.

    Counted once per invoice, not once per reading: a fee applies to every
    calendar month the period touches, and the per-metering-point variants
    multiply that by how many points the participant held in those months.
    Yearly fees are charged as twelfths.

    The shared variants divide one community-wide amount between the members
    active in each month, so their total is built month by month rather than as
    ``quantity * unit_price``.
    """
    for tariff in tariffs:
        if tariff.billing_mode in _ENERGY_BILLING_MODES:
            continue
        month_count = _count_billable_months(tariff, period_start, period_end)
        if month_count <= 0:
            continue

        per_metering_point = tariff.billing_mode in (
            BillingMode.PER_METERING_POINT_MONTHLY_FEE,
            BillingMode.PER_METERING_POINT_YEARLY_FEE,
        )
        shared = tariff.billing_mode in _SHARED_BILLING_MODES
        yearly = tariff.billing_mode in (
            BillingMode.YEARLY_FEE,
            BillingMode.PER_METERING_POINT_YEARLY_FEE,
            BillingMode.SHARED_YEARLY_FEE,
        )

        if per_metering_point:
            quantity = Decimal(_count_billable_metering_points_by_month(
                participant, tariff, period_start, period_end))
            if quantity <= 0:
                continue
        else:
            quantity = Decimal(month_count)

        unit_price = tariff.fixed_price_chf or Decimal("0")
        if yearly:
            unit_price = unit_price / Decimal("12")

        if shared:
            shares = _count_active_participants_by_month(
                participant.zev, tariff, period_start, period_end)
            total = Decimal("0")
            charged_months = 0
            for month, billed_from, billed_to in _billable_months(tariff, period_start, period_end):
                count = shares.get(month)
                # Only the months this participant was actually a member of:
                # the denominator is community-wide, but the numerator is not.
                # Charging every month the fee was live would bill a mid-period
                # joiner for the months before they arrived.
                if not count or not _overlaps(
                    participant.valid_from, participant.valid_to, billed_from, billed_to
                ):
                    continue
                total += unit_price / count
                charged_months += 1
            if charged_months == 0:
                continue
            # Quantity is the months this participant is charged for, so the
            # line reads "2 months" and the derived unit price comes out as
            # their average monthly share — the figure they want to see.
            quantity = Decimal(charged_months)
        else:
            total = quantity * unit_price

        accumulator.add(
            tariff=tariff,
            quantity=quantity,
            total=total,
            unit="month",
        )


def _build_item_payloads(accumulator) -> tuple[list, Decimal]:
    """Turn accumulated totals into rounded line-item payloads plus the subtotal.

    Each line is rounded to the centime and the subtotal is the sum of those
    rounded lines, so an invoice adds up to what is printed on it rather than
    to a more precise figure rounded once at the end.
    """
    payloads = []
    subtotal = Decimal("0")
    for entry in accumulator:
        quantity = Decimal(entry["quantity"])
        total = Decimal(entry["total"])
        if quantity == 0 and total == 0:
            continue

        quantized_total = total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        subtotal += quantized_total
        if quantity != 0:
            unit_price = (total / quantity).quantize(Decimal("0.00001"), rounding=ROUND_HALF_UP)
        else:
            unit_price = Decimal("0")

        raw_base_total = entry.get("base_total", Decimal("0"))
        payloads.append({
            "tariff": entry["tariff"],
            "quantity": quantity.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
            "unit": str(entry["unit"]),
            "unit_price": unit_price,
            "total": quantized_total,
            "base_rate": (raw_base_total / quantity).quantize(Decimal("0.00001"), rounding=ROUND_HALF_UP) if quantity and raw_base_total else None,
        })

    return payloads, subtotal.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@transaction.atomic
def generate_invoice(participant: Participant, period_start: date, period_end: date) -> Invoice:
    """
    Generate (or regenerate) an invoice for a participant for the given period.
    Existing DRAFT invoice for the same period will be replaced.
    Raises ValueError if a non-draft, non-cancelled invoice already exists.
    """
    zev = participant.zev

    _discard_replaceable_invoices(participant, period_start, period_end)

    readings = _gather_period_readings(participant, period_start, period_end)
    zev_consumption_by_ts = readings.zev_consumption_by_ts
    zev_production_by_ts = readings.zev_production_by_ts

    # ─── 6. Fetch applicable tariffs ─────────────────────────────────────
    tariffs_list = list(
        Tariff.objects.filter(zev=zev).prefetch_related("periods")
    )
    tariffs = TariffResolver(tariffs_list)
    # ─── 7. Per-reading HT/NT-aware pricing with timestamp allocation ─────
    local_kwh_acc = Decimal("0")
    grid_kwh_acc = Decimal("0")

    skipped_consumption_readings = 0
    skipped_consumption_kwh = Decimal("0")

    items_accumulator = ItemAccumulator()

    for reading in readings.participant_consumption.order_by("timestamp").iterator():
        ts = reading.timestamp
        if not readings.assignment_windows.is_held_by(participant.id, reading.metering_point_id, ts):
            # Reading predates this participant's assignment (or falls in an
            # assignment gap): it belongs to nobody in this billing run.
            skipped_consumption_readings += 1
            skipped_consumption_kwh += reading.energy_kwh
            continue
        participant_kwh = reading.energy_kwh
        zev_consumption_at_ts = zev_consumption_by_ts.get(ts, Decimal("0"))
        zev_production_at_ts = zev_production_by_ts.get(ts, Decimal("0"))

        r_local, r_grid = split_consumption(
            participant_kwh, zev_consumption_at_ts, zev_production_at_ts
        )

        local_kwh_acc += r_local
        grid_kwh_acc += r_grid

        # Compute GRID energy base sum once per timestamp.
        # Percentage-of-energy tariffs price any energy type as a fraction of
        # what a participant would normally pay for grid energy.
        grid_base_price_sum = sum(
            (_get_tariff_price(t, ts) or Decimal("0"))
            for t in tariffs.energy(EnergyType.GRID, ts.date())
        )

        for energy_type, quantity in ((EnergyType.LOCAL, r_local), (EnergyType.GRID, r_grid)):
            if quantity <= 0:
                continue
            for tariff in tariffs.energy(energy_type, ts.date()):
                price = _get_tariff_price(tariff, ts) or Decimal("0")
                items_accumulator.add(
                    tariff=tariff,
                    quantity=quantity,
                    total=quantity * price,
                    unit="kWh",
                )

            # Percentage-of-energy tariffs: base is always the GRID rate sum,
            # applied to whichever energy_type the tariff is configured for.
            for tariff in tariffs.percentage(energy_type, ts.date()):
                effective_price = grid_base_price_sum * (tariff.percentage / Decimal("100"))
                items_accumulator.add(
                    tariff=tariff,
                    quantity=quantity,
                    total=quantity * effective_price,
                    unit="kWh",
                    base_total=quantity * grid_base_price_sum,
                )

    exported_kwh_acc = Decimal("0")

    skipped_production_readings = 0
    skipped_production_kwh = Decimal("0")

    for reading in readings.participant_production.order_by("timestamp").iterator():
        ts = reading.timestamp
        if not readings.assignment_windows.is_held_by(participant.id, reading.metering_point_id, ts):
            skipped_production_readings += 1
            skipped_production_kwh += reading.energy_kwh
            continue
        produced_kwh = reading.energy_kwh

        zev_production_at_ts = zev_production_by_ts.get(ts, Decimal("0"))
        zev_consumption_at_ts = zev_consumption_by_ts.get(ts, Decimal("0"))

        local_sold_kwh, exported_kwh = split_production(
            produced_kwh, zev_production_at_ts, zev_consumption_at_ts
        )

        exported_kwh_acc += exported_kwh

        grid_base_price_sum = sum(
            (_get_tariff_price(t, ts) or Decimal("0"))
            for t in tariffs.energy(EnergyType.GRID, ts.date())
        )

        if local_sold_kwh > 0:
            for tariff in tariffs.energy(EnergyType.LOCAL, ts.date()):
                price = _get_tariff_price(tariff, ts) or Decimal("0")
                items_accumulator.add(
                    tariff=tariff,
                    quantity=local_sold_kwh,
                    total=-(local_sold_kwh * price),
                    unit="kWh",
                    bucket="producer_credit",
                )

            for tariff in tariffs.percentage(EnergyType.LOCAL, ts.date()):
                effective_price = grid_base_price_sum * (tariff.percentage / Decimal("100"))
                items_accumulator.add(
                    tariff=tariff,
                    quantity=local_sold_kwh,
                    total=-(local_sold_kwh * effective_price),
                    unit="kWh",
                    base_total=(local_sold_kwh * grid_base_price_sum),
                    bucket="producer_credit",
                )

        if exported_kwh > 0:
            for tariff in tariffs.energy(EnergyType.FEED_IN, ts.date()):
                price = _get_tariff_price(tariff, ts) or Decimal("0")
                items_accumulator.add(
                    tariff=tariff,
                    quantity=exported_kwh,
                    total=-(exported_kwh * price),
                    unit="kWh",
                )

    _price_fixed_fees(participant, tariffs_list, period_start, period_end, items_accumulator)

    if skipped_consumption_readings or skipped_production_readings:
        logger.warning(
            "Invoice for participant %s (period %s..%s) excluded %d consumption "
            "reading(s) / %s kWh and %d production reading(s) / %s kWh that fall "
            "outside assignment windows (gaps or unassigned metering points)",
            participant.id,
            period_start,
            period_end,
            skipped_consumption_readings,
            skipped_consumption_kwh,
            skipped_production_readings,
            skipped_production_kwh,
        )

    local_kwh = local_kwh_acc.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    grid_kwh = grid_kwh_acc.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

    item_payloads, subtotal = _build_item_payloads(items_accumulator)

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
        due_date=timezone.localdate() + timedelta(days=zev.payment_term_days),
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


class BulkGenerationResult(NamedTuple):
    """Outcome of a ZEV-wide invoice run: the invoices generated plus one
    entry per participant whose invoice failed."""

    invoices: list[Invoice]
    failures: list[dict]


def generate_invoices_for_zev(zev: Zev, period_start: date, period_end: date) -> BulkGenerationResult:
    """Generate invoices for ALL active participants in a ZEV.

    Failures are isolated per participant (see ADR 0011) and returned in
    ``failures`` as ``{"participant_id": ..., "participant_name": ..., "error": ...}``.
    """
    participants = zev.participants.filter(
        valid_from__lte=period_end,
    ).filter(
        models.Q(valid_to__isnull=True) | models.Q(valid_to__gte=period_start)
    )
    invoices = []
    failures = []
    for participant in participants:
        try:
            invoices.append(generate_invoice(participant, period_start, period_end))
        except SoftTimeLimitExceeded:
            # A soft time limit must abort the whole run, not be recorded as one
            # participant's failure; swallowing it would let the loop run into the
            # hard limit and drop the audit event entirely.
            raise
        except Exception as exc:
            logger.exception("Invoice generation failed for participant %s", participant.full_name)
            # next_invoice_number() bumps zev.invoice_counter in memory; the
            # savepoint rollback restores the row but not the instance, and every
            # participant shares the same zev object (p.zev is zev). Re-sync so the
            # next participant reuses the number the failed one gave back instead of
            # skipping it and then colliding on a stale +1.
            try:
                zev.refresh_from_db(fields=["invoice_counter"])
            except Exception:
                # Don't mask the original failure; if we cannot re-sync, subsequent
                # participants will fail early on the (likely unreachable) DB anyway.
                logger.exception(
                    "Could not re-sync invoice counter after failure for participant %s",
                    participant.full_name,
                )
            failures.append({
                "participant_id": str(participant.id),
                "participant_name": participant.full_name,
                "error": str(exc),
            })
    return BulkGenerationResult(invoices, failures)
