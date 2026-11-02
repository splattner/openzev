"""Best-effort feasibility inputs from a ZEV's readings and active tariffs.

Participant energy uses all assigned-meter history, extrapolated to 365 days.
Participants with neither eligible production nor consumption use default
consumption. Self-consumption is measured per timestamp across all ZEV meters.

Retail includes grid energy, fees and levies; feed-in and local prices use the
existing tariff approximations. Users should review the estimates.
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from django.db.models import Max, Min, Q, Sum
from django.db.models.functions import Least

from allocation.validity import active_on
from allocation.split import local_pool_kwh
from metering.models import MeterReading, ReadingDirection
from invoices.engine import _active_vat_rate, _tariff_bears_input_vat
from tariffs.models import BillingMode, EnergyType, Tariff, TariffCategory
from tariffs.periods import average_percentage
from zev.models import MeteringPointAssignment, MeteringPointType, Participant, VatMode, Zev

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


def _grid_vat_rate(zev: Zev, today: dt.date) -> Decimal:
    """The VAT folded into a participant's grid prices: non-zero only for a
    ZEV on ``VatMode.INCLUSIVE``, the one mode whose invoices bill the grid
    lines with VAT included (the engine grosses the same lines)."""
    return _active_vat_rate(today) if zev.vat_mode == VatMode.INCLUSIVE else Decimal("0")


def _flat_energy_price_sum(
    zev: Zev,
    *,
    energy_type: str,
    today: dt.date,
    categories: list[str] | None = None,
    vat_rate: Decimal = Decimal("0"),
) -> Decimal | None:
    """Sum of representative per-kWh prices across every currently-active flat
    (billing_mode=ENERGY) tariff of the given energy type. With ``categories``
    it restricts to those tariff categories (energy-only); without, it spans
    all of them (energy + grid fees + levies), matching the invoice engine's
    ``grid_base_price_sum``. With ``vat_rate`` each tariff the engine would
    gross is multiplied by ``1 + vat_rate``. None when no such tariff exists
    at all."""
    qs = active_on(
        Tariff.objects.filter(
            zev=zev,
            energy_type=energy_type,
            billing_mode=BillingMode.ENERGY,
        ),
        today,
    )
    if categories is not None:
        qs = qs.filter(category__in=categories)

    total = Decimal("0")
    found = False
    for tariff in qs:
        price = _representative_price(tariff)
        if price is not None:
            total += price * (1 + vat_rate) if _tariff_bears_input_vat(tariff) else price
            found = True
    return total if found else None


def _percentage_of_energy_sum(
    zev: Zev, *, energy_type: str, today: dt.date, categories: list[str] | None = None
) -> Decimal:
    """Summed percentages across active percentage-of-energy tariffs (0 if none).

    Each tariff's own percentage is its time-weighted band average
    (``tariffs.periods.average_percentage``) rather than a single stored
    value, since a percentage tariff can now carry several time-of-use bands.
    """
    qs = active_on(
        Tariff.objects.filter(
            zev=zev,
            energy_type=energy_type,
            billing_mode=BillingMode.PERCENTAGE_OF_ENERGY,
        ),
        today,
    ).prefetch_related("periods")

    if categories is not None:
        qs = qs.filter(category__in=categories)
    return sum((average_percentage(tariff) for tariff in qs), Decimal("0"))


def _all_in_retail_price(zev: Zev, today: dt.date) -> Decimal | None:
    """Full per-kWh price a consumer pays for grid energy: the flat
    energy-based GRID tariffs (energy + grid fees + levies) plus every
    percentage-of-energy GRID tariff applied to that base — exactly how the
    invoice engine bills grid consumption. None when there's no flat GRID
    energy tariff to anchor it."""
    base = _flat_energy_price_sum(
        zev, energy_type=EnergyType.GRID, today=today, vat_rate=_grid_vat_rate(zev, today)
    )
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
        # With VAT folded in for an inclusive ZEV: the share is of what the
        # participant would otherwise pay, as on the invoice.
        grid_base = _flat_energy_price_sum(
            zev, energy_type=EnergyType.GRID, today=today, vat_rate=_grid_vat_rate(zev, today)
        )
        if grid_base is not None:
            total += grid_base * local_pct / Decimal("100")
            found = True

    return total.quantize(FIVE_PLACES) if found else None


def _reading_summaries_by_participant(participants: list[Participant]) -> dict:
    """Map participant IDs to meter/direction summaries.

    Each summary has direction, metering_point__meter_type, total, first and last.
    """
    # Ignore window ordering so DISTINCT means one participant/meter pair.
    bindings = list(
        MeteringPointAssignment.objects.filter(participant__in=participants)
        .order_by().values_list("participant_id", "metering_point_id").distinct()
    )
    by_meter = defaultdict(list)
    for row in (
        MeterReading.objects.filter(metering_point_id__in={mp_id for _, mp_id in bindings})
        .values("metering_point_id", "metering_point__meter_type", "direction")
        .annotate(total=Sum("energy_kwh"), first=Min("timestamp"), last=Max("timestamp"))
        .order_by()
    ):
        by_meter[row["metering_point_id"]].append(row)
    by_participant = defaultdict(list)
    for participant_id, mp_id in bindings:
        by_participant[participant_id].extend(by_meter[mp_id])
    return by_participant


def _extrapolated_annual_kwh(
    summaries, *, meter_types: list[str], direction: str
) -> tuple[Decimal, bool]:
    """Return (annual_kwh, found) from the combined eligible meter histories.

    ``found`` means the eligible readings have a nonzero total.
    """
    rows = [
        row for row in summaries
        if row["direction"] == direction and row["metering_point__meter_type"] in meter_types
    ]
    total = sum((row["total"] for row in rows), Decimal("0"))
    if not total:
        return Decimal("0"), False

    first = min(row["first"] for row in rows)
    last = max(row["last"] for row in rows)
    span_days = max((last - first).days, 1)
    return total * Decimal(365) / Decimal(span_days), True


def _measured_self_consumption_rate(zev: Zev) -> Decimal | None:
    """Return Σ min(production_ts, consumption_ts) / Σ production_ts.

    Uses all available history, including unassigned meters. Rejects negative
    timestamp totals; returns None if production or consumption totals are zero.
    """
    totals = (
        MeterReading.objects.filter(metering_point__zev=zev)
        .values("timestamp")
        .annotate(
            produced=Sum("energy_kwh", filter=Q(direction=ReadingDirection.OUT), default=Decimal("0")),
            consumed=Sum("energy_kwh", filter=Q(direction=ReadingDirection.IN), default=Decimal("0")),
        )
        .order_by()
        .aggregate(
            total_produced=Sum("produced"), total_consumed=Sum("consumed"),
            self_consumed=Sum(Least("produced", "consumed")),
            min_produced=Min("produced"), min_consumed=Min("consumed"),
        )
    )
    if totals["min_produced"] is None:
        return None
    # Reject negative timestamp totals, even when period totals are positive.
    local_pool_kwh(totals["min_produced"], totals["min_consumed"])
    if totals["total_produced"] <= 0 or totals["total_consumed"] <= 0:
        return None

    return (totals["self_consumed"] / totals["total_produced"]).quantize(FOUR_PLACES)


def build_prefill(zev: Zev) -> FeasibilityPrefill:
    today = dt.date.today()

    active_participants = list(active_on(zev.participants, today))
    summaries = _reading_summaries_by_participant(active_participants)

    participants = []
    for participant in active_participants:
        production, has_production_data = _extrapolated_annual_kwh(
            summaries.get(participant.pk, ()),
            meter_types=[MeteringPointType.PRODUCTION, MeteringPointType.BIDIRECTIONAL],
            direction=ReadingDirection.OUT,
        )
        consumption, has_consumption_data = _extrapolated_annual_kwh(
            summaries.get(participant.pk, ()),
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
        # Feed-in and internal prices use only the ENERGY category.
        feed_in_price_chf_per_kwh=_flat_energy_price_sum(
            zev, energy_type=EnergyType.FEED_IN, today=today, categories=[TariffCategory.ENERGY]
        ),
        internal_energy_price_chf_per_kwh=_internal_energy_price(zev, today),
    )
