"""Best-effort prefill of feasibility calculator inputs from a real ZEV.

Not authoritative — a starting point to review and adjust, not a substitute
for entering real numbers. Three independent approximations:

1. Per-participant production/consumption: sums each participant's assigned
   metering points' readings and extrapolates whatever history exists
   (however short) to a full year. Participants with no readings at all yet
   (a brand-new ZEV) fall back to a generic default and are flagged via
   ``has_metering_data=False`` so the frontend can call that out.
2. Self-consumption rate: measured from the actual metering time series, not
   guessed. It is the single biggest driver of the whole result, and for a
   ZEV that already has readings we can compute it exactly instead of asking
   the user for a number — using the same per-timestamp local-pool logic as
   the dashboard (``metering.analytics``) and real invoices
   (``allocation.split.local_pool_kwh``):
   self-consumed energy is ``Σ min(production_ts, consumption_ts)`` and the
   rate is ``self-consumed / produced``. Returns None when there isn't enough
   data to measure it (no production, or no consumption).
3. Tariff prices, from the currently-active tariffs:
   - Retail is the full *all-in* price a consumer pays for grid energy —
     energy + grid fees (Netznutzung) + levies (Abgaben) — mirroring the
     invoice engine (``invoices.engine``): the sum of every flat
     (billing_mode=ENERGY) GRID tariff across all categories, times
     ``(1 + Σ percentage-of-energy GRID tariffs)``. Loading only the energy
     component would understate retail, and therefore understate the whole
     vZEV benefit (which is proportional to retail − feed_in).
   - Feed-in is energy-only: the flat ENERGY-category FEED_IN tariff.
   - Internal (local) is energy-only too, but is commonly configured as a
     percentage of the grid energy price ("local = 60% of Netzstrom") rather
     than a flat rate, so a percentage-of-energy LOCAL tariff is resolved
     against the grid energy base, and a flat LOCAL energy tariff added on top.
   HT/NT splits within a tariff are approximated with a representative period,
   and fixed-fee (per-month/-metering-point) tariffs are ignored. Returns None
   for a price it can't determine — the caller then falls back to the
   calculator's own Swiss defaults, exactly as it does for any blank field.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from django.db.models import Max, Min, Q, Sum

from allocation.split import local_pool_kwh
from metering.models import MeterReading, ReadingDirection
from tariffs.models import BillingMode, EnergyType, Tariff, TariffCategory
from zev.models import MeteringPoint, MeteringPointType, Participant, Zev

from . import defaults

FOUR_PLACES = Decimal("0.0001")
FIVE_PLACES = Decimal("0.00001")


@dataclass(frozen=True)
class ParticipantPrefill:
    name: str
    annual_production_kwh: Decimal
    annual_consumption_kwh: Decimal
    has_metering_data: bool


@dataclass(frozen=True)
class FeasibilityPrefill:
    participants: list[ParticipantPrefill]
    self_consumption_rate: Decimal | None
    retail_price_chf_per_kwh: Decimal | None
    feed_in_price_chf_per_kwh: Decimal | None
    internal_energy_price_chf_per_kwh: Decimal | None


def _representative_price(tariff: Tariff) -> Decimal | None:
    """A single per-kWh price standing in for one flat energy tariff.

    TariffPeriod.Meta orders by period_type, and 'flat' sorts before
    'high'/'low' alphabetically, so ``.first()`` picks the flat rate when one
    exists and an arbitrary HT/NT band otherwise — a rough approximation.
    """
    period = tariff.periods.first()
    return period.price_chf_per_kwh if period else None


def _flat_energy_price_sum(
    zev: Zev, *, energy_type: str, today: dt.date, categories: list[str] | None = None
) -> Decimal | None:
    """Sum of representative per-kWh prices across every currently-active flat
    (billing_mode=ENERGY) tariff of the given energy type. With ``categories``
    it restricts to those tariff categories (energy-only); without, it spans
    all of them (energy + grid fees + levies), matching the invoice engine's
    ``grid_base_price_sum``. None when no such tariff exists at all."""
    qs = Tariff.objects.filter(
        zev=zev,
        energy_type=energy_type,
        billing_mode=BillingMode.ENERGY,
        valid_from__lte=today,
    ).filter(Q(valid_to__isnull=True) | Q(valid_to__gte=today))
    if categories is not None:
        qs = qs.filter(category__in=categories)

    total = Decimal("0")
    found = False
    for tariff in qs:
        price = _representative_price(tariff)
        if price is not None:
            total += price
            found = True
    return total if found else None


def _percentage_of_energy_sum(
    zev: Zev, *, energy_type: str, today: dt.date, categories: list[str] | None = None
) -> Decimal:
    """Total of the percentages across currently-active percentage-of-energy
    tariffs of the given energy type (0 when there are none)."""
    qs = Tariff.objects.filter(
        zev=zev,
        energy_type=energy_type,
        billing_mode=BillingMode.PERCENTAGE_OF_ENERGY,
        valid_from__lte=today,
    ).filter(Q(valid_to__isnull=True) | Q(valid_to__gte=today))
    if categories is not None:
        qs = qs.filter(category__in=categories)
    return sum((tariff.percentage or Decimal("0") for tariff in qs), Decimal("0"))


def _all_in_retail_price(zev: Zev, today: dt.date) -> Decimal | None:
    """Full per-kWh price a consumer pays for grid energy: the flat
    energy-based GRID tariffs (energy + grid fees + levies) plus every
    percentage-of-energy GRID tariff applied to that base — exactly how the
    invoice engine bills grid consumption. None when there's no flat GRID
    energy tariff to anchor it."""
    base = _flat_energy_price_sum(zev, energy_type=EnergyType.GRID, today=today)
    if base is None:
        return None
    total_pct = _percentage_of_energy_sum(zev, energy_type=EnergyType.GRID, today=today)
    return (base * (1 + total_pct / Decimal("100"))).quantize(FIVE_PLACES)


def _internal_energy_price(zev: Zev, today: dt.date) -> Decimal | None:
    """Per-kWh price a participant pays for locally consumed (LOCAL) energy,
    energy-only per the vZEV pricing rule.

    Very often this is configured as a *percentage of the grid energy price*
    ("local = 60% of Netzstrom") rather than a flat rate, so — mirroring the
    invoice engine — a percentage-of-energy LOCAL tariff is resolved against
    the grid energy base (percentage × grid_base), and a flat LOCAL energy
    tariff is added on top. None when neither is configured.
    """
    total = Decimal("0")
    found = False

    flat = _flat_energy_price_sum(
        zev, energy_type=EnergyType.LOCAL, today=today, categories=[TariffCategory.ENERGY]
    )
    if flat is not None:
        total += flat
        found = True

    local_pct = _percentage_of_energy_sum(
        zev, energy_type=EnergyType.LOCAL, today=today, categories=[TariffCategory.ENERGY]
    )
    if local_pct > 0:
        grid_base = _flat_energy_price_sum(zev, energy_type=EnergyType.GRID, today=today)
        if grid_base is not None:
            total += grid_base * local_pct / Decimal("100")
            found = True

    return total.quantize(FIVE_PLACES) if found else None


def _extrapolated_annual_kwh(
    participant: Participant, *, meter_types: list[str], direction: str
) -> tuple[Decimal, bool]:
    """Sum this participant's readings of the given direction/meter type and
    extrapolate to a full year based on however much history actually spans.
    Returns (annual_kwh, whether any readings were found at all)."""
    metering_point_ids = participant.metering_point_assignments.filter(
        metering_point__meter_type__in=meter_types,
    ).values_list("metering_point_id", flat=True)

    aggregate = MeterReading.objects.filter(
        metering_point_id__in=metering_point_ids,
        direction=direction,
    ).aggregate(total=Sum("energy_kwh"), first=Min("timestamp"), last=Max("timestamp"))

    if not aggregate["total"] or aggregate["first"] is None or aggregate["last"] is None:
        return Decimal("0"), False

    span_days = max((aggregate["last"] - aggregate["first"]).days, 1)
    annual = aggregate["total"] * Decimal(365) / Decimal(span_days)
    return annual, True


def _measured_self_consumption_rate(zev: Zev) -> Decimal | None:
    """ZEV-level self-consumption rate (self-consumed / produced) measured
    from all available metering data.

    Mirrors the canonical per-timestamp local-pool allocation used by the
    dashboard (``metering.analytics.owner_dashboard_summary``) and real
    invoices (``allocation.split.local_pool_kwh``): at each timestamp the
    locally self-consumed energy is ``min(total production, total
    consumption)`` across every metering point in the ZEV. Because it's a
    dimensionless ratio, it does not matter that the per-participant kWh
    totals are separately extrapolated to a year — the rate is the same over
    the raw period.

    Returns None when it can't be measured: no production (rate undefined),
    or no consumption at all (we'd otherwise report a misleading 0%).
    """
    metering_point_ids = MeteringPoint.objects.filter(zev=zev).values_list("id", flat=True)

    # DB sums per (timestamp, direction); Python does the per-timestamp min.
    ts_pivot: dict = {}
    for row in (
        MeterReading.objects.filter(metering_point_id__in=metering_point_ids)
        .values("timestamp", "direction")
        .annotate(total_kwh=Sum("energy_kwh"))
    ):
        entry = ts_pivot.setdefault(row["timestamp"], {})
        entry[row["direction"]] = row["total_kwh"] or Decimal("0")

    total_produced = Decimal("0")
    total_consumed = Decimal("0")
    self_consumed = Decimal("0")
    for entry in ts_pivot.values():
        produced = entry.get(ReadingDirection.OUT, Decimal("0"))
        consumed = entry.get(ReadingDirection.IN, Decimal("0"))
        total_produced += produced
        total_consumed += consumed
        self_consumed += local_pool_kwh(produced, consumed)

    if total_produced <= 0 or total_consumed <= 0:
        return None

    # self_consumed <= total_produced by construction, so this is always in [0, 1].
    return (self_consumed / total_produced).quantize(FOUR_PLACES)


def build_prefill(zev: Zev) -> FeasibilityPrefill:
    today = dt.date.today()

    active_participants = zev.participants.filter(valid_from__lte=today).filter(
        Q(valid_to__isnull=True) | Q(valid_to__gte=today)
    )

    participants = []
    for participant in active_participants:
        production, has_production_data = _extrapolated_annual_kwh(
            participant,
            meter_types=[MeteringPointType.PRODUCTION, MeteringPointType.BIDIRECTIONAL],
            direction=ReadingDirection.OUT,
        )
        consumption, has_consumption_data = _extrapolated_annual_kwh(
            participant,
            meter_types=[MeteringPointType.CONSUMPTION, MeteringPointType.BIDIRECTIONAL],
            direction=ReadingDirection.IN,
        )
        has_data = has_production_data or has_consumption_data
        if not has_data:
            consumption = defaults.DEFAULT_PARTICIPANT_CONSUMPTION_KWH

        participants.append(
            ParticipantPrefill(
                name=participant.full_name,
                annual_production_kwh=production,
                annual_consumption_kwh=consumption,
                has_metering_data=has_data,
            )
        )

    return FeasibilityPrefill(
        participants=participants,
        self_consumption_rate=_measured_self_consumption_rate(zev),
        retail_price_chf_per_kwh=_all_in_retail_price(zev, today),
        # Feed-in is energy-only (ENERGY category). Internal, too, but it's
        # often a percentage of the grid price rather than a flat rate.
        feed_in_price_chf_per_kwh=_flat_energy_price_sum(
            zev, energy_type=EnergyType.FEED_IN, today=today, categories=[TariffCategory.ENERGY]
        ),
        internal_energy_price_chf_per_kwh=_internal_energy_price(zev, today),
    )
