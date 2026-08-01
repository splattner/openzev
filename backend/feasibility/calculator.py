"""Pure profitability calculator for vZEV planning ("should we form a vZEV?").

Models the *incremental* decision to form a vZEV over the baseline where PV
production is sold entirely to the grid at the feed-in tariff and every
participant buys 100% of consumption from the grid at retail. No metering
data is required — self-consumption is driven by a single planning-stage
assumption, the self-consumption rate::

    self_consumption_rate (sigma) = self-consumed kWh / produced kWh

which mirrors the per-timestamp local-pool allocation used for real invoices
(``allocation.split``: ``min(production, consumption)``) but collapsed to one
annual assumption since no readings exist yet.

Value created by the vZEV is proportional to self-consumed energy, priced at
``retail - feed_in`` — the internal energy price only redistributes that
value between producer and consumers, it does not change the total (see
``test_calculator.py`` for the invariant check). There is no separate
internal grid fee: within a vZEV, locally consumed energy is only ever
priced as energy, never a network fee — unlike a real invoice's tariffs,
which may still bill grid fees separately.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from allocation.split import proportional_share

TWO_PLACES = Decimal("0.01")
FIVE_PLACES = Decimal("0.00001")

# Resolution of the self-consumption sensitivity curve: 0%, 5%, ..., 100%.
SENSITIVITY_STEPS = 21


def _money(value: Decimal) -> Decimal:
    return value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def _price(value: Decimal) -> Decimal:
    """Quantize a CHF/kWh price to 5 decimal places, matching the precision
    tariff prices are entered at elsewhere in the app."""
    return value.quantize(FIVE_PLACES, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class ParticipantInput:
    """One named participant, for the optional per-participant breakdown.

    A participant can be a pure producer, a pure consumer, or a prosumer
    (both fields non-zero) — a household with its own PV system that also
    draws from the grid is one row, not two.
    """

    name: str
    annual_production_kwh: Decimal = Decimal("0")
    annual_consumption_kwh: Decimal = Decimal("0")


@dataclass(frozen=True)
class FeasibilityInput:
    """Inputs for a single vZEV feasibility scenario.

    All prices are "all-in" CHF/kWh (energy + grid fees + levies) unless
    noted otherwise, matching how a participant actually reads their grid
    bill today.

    ``annual_production_kwh``/``annual_consumption_kwh`` are always the
    source of truth for the aggregate scenario math (payback, ROI, NPV,
    sensitivity curves, ...) — nothing about the core model changes whether
    or not ``participants`` is supplied. ``participants`` is purely additive:
    when given, it drives a per-participant breakdown of who gains what,
    proportional to each participant's share of the group's total production
    and consumption. The caller (the API layer) is responsible for keeping
    the participant list's sums consistent with the aggregate totals, the
    same way it already resolves kWp-derived production or percentage-of-
    retail pricing before this dataclass is built — this function does not
    cross-validate the two.
    """

    annual_production_kwh: Decimal
    annual_consumption_kwh: Decimal
    self_consumption_rate: Decimal
    retail_price_chf_per_kwh: Decimal
    feed_in_price_chf_per_kwh: Decimal
    internal_energy_price_chf_per_kwh: Decimal
    annual_opex_chf: Decimal = Decimal("0")
    capex_chf: Decimal = Decimal("0")
    horizon_years: int = 20
    discount_rate: Decimal = Decimal("0.03")
    participants: tuple[ParticipantInput, ...] = ()

    def __post_init__(self) -> None:
        _validate(self)


def _validate(inputs: FeasibilityInput) -> None:
    if not (Decimal("0") <= inputs.self_consumption_rate <= Decimal("1")):
        raise ValueError("self_consumption_rate must be between 0 and 1")

    for participant in inputs.participants:
        if participant.annual_production_kwh < 0:
            raise ValueError(f"participant {participant.name!r}: annual_production_kwh must not be negative")
        if participant.annual_consumption_kwh < 0:
            raise ValueError(f"participant {participant.name!r}: annual_consumption_kwh must not be negative")

    non_negative_fields = (
        "annual_production_kwh",
        "annual_consumption_kwh",
        "retail_price_chf_per_kwh",
        "feed_in_price_chf_per_kwh",
        "internal_energy_price_chf_per_kwh",
        "annual_opex_chf",
        "capex_chf",
    )
    for name in non_negative_fields:
        if getattr(inputs, name) < 0:
            raise ValueError(f"{name} must not be negative")

    if inputs.horizon_years < 1:
        raise ValueError("horizon_years must be at least 1")
    if inputs.discount_rate < 0:
        raise ValueError("discount_rate must not be negative")


@dataclass(frozen=True)
class SensitivityPoint:
    self_consumption_rate: Decimal
    annual_net_benefit_chf: Decimal


@dataclass(frozen=True)
class PriceSensitivityPoint:
    """One point on the internal-price sweep: how the split between producer
    and consumer changes as the internal energy price moves, at the user's
    chosen self-consumption rate (self-consumed kWh is held constant)."""

    internal_price_pct_of_retail: Decimal
    internal_price_chf_per_kwh: Decimal
    producer_gain_chf: Decimal
    consumer_savings_chf: Decimal


@dataclass(frozen=True)
class FairPriceRange:
    """A recommended internal-price range, narrower than the trivial
    win-win range because it also requires the producer's gain to cover
    their share of the vZEV's running costs (annual_opex_chf) — not just be
    better than feed-in. See ``_fair_price_range`` for the derivation."""

    low_chf_per_kwh: Decimal
    high_chf_per_kwh: Decimal


@dataclass(frozen=True)
class ParticipantResult:
    """One participant's share of the group's energy flows and money.

    Each participant's own production/consumption is allocated a share of
    the group's aggregate self-consumed pool proportional to their share of
    total production (for what they contribute) and total consumption (for
    what they draw), exactly mirroring the per-timestamp local-pool
    allocation from ``allocation.split`` (via ``proportional_share``), just
    collapsed to one annual split since there's no metering data yet.
    """

    name: str
    annual_production_kwh: Decimal
    annual_consumption_kwh: Decimal
    self_consumed_from_own_production_kwh: Decimal
    exported_kwh: Decimal
    from_local_pool_kwh: Decimal
    from_grid_kwh: Decimal
    producer_gain_chf: Decimal
    consumer_savings_chf: Decimal
    net_benefit_chf: Decimal


@dataclass(frozen=True)
class FeasibilityResult:
    self_consumed_kwh: Decimal
    grid_import_kwh: Decimal
    grid_export_kwh: Decimal
    autarky_rate: Decimal

    baseline_consumer_cost_chf: Decimal
    baseline_producer_revenue_chf: Decimal
    vzev_consumer_cost_chf: Decimal
    vzev_producer_revenue_chf: Decimal
    consumer_savings_chf: Decimal
    producer_gain_chf: Decimal

    annual_gross_benefit_chf: Decimal
    annual_net_benefit_chf: Decimal
    payback_years: Decimal | None
    roi: Decimal | None
    npv_chf: Decimal
    cashflow_by_year: list[Decimal]

    sensitivity: list[SensitivityPoint]
    break_even_self_consumption_rate: Decimal | None

    price_sensitivity: list[PriceSensitivityPoint]
    equal_split_price_chf_per_kwh: Decimal | None
    fair_price_range: FairPriceRange | None

    participants: list[ParticipantResult]


def _self_consumed_kwh(rate: Decimal, production_kwh: Decimal, consumption_kwh: Decimal) -> Decimal:
    """Self-consumed energy can never exceed total consumption, even if
    ``rate * production`` would suggest otherwise."""
    return min(rate * production_kwh, consumption_kwh)


def _net_unit_benefit(inputs: FeasibilityInput) -> Decimal:
    return inputs.retail_price_chf_per_kwh - inputs.feed_in_price_chf_per_kwh


def _annual_net_benefit_for_rate(rate: Decimal, inputs: FeasibilityInput) -> Decimal:
    self_consumed = _self_consumed_kwh(rate, inputs.annual_production_kwh, inputs.annual_consumption_kwh)
    return self_consumed * _net_unit_benefit(inputs) - inputs.annual_opex_chf


def _build_sensitivity(inputs: FeasibilityInput) -> list[SensitivityPoint]:
    points = []
    for i in range(SENSITIVITY_STEPS):
        rate = Decimal(i) / Decimal(SENSITIVITY_STEPS - 1)
        benefit = _annual_net_benefit_for_rate(rate, inputs)
        points.append(SensitivityPoint(self_consumption_rate=rate, annual_net_benefit_chf=_money(benefit)))
    return points


def _break_even_rate(sensitivity: list[SensitivityPoint]) -> Decimal | None:
    """Linearly interpolate the self-consumption rate where net benefit
    crosses zero. The underlying function is piecewise-linear with at most
    one kink (where self-consumption saturates at total consumption), so
    interpolation between sampled points is exact except within a single
    sampling step around that kink.
    """
    for prev, curr in zip(sensitivity, sensitivity[1:]):
        v0, v1 = prev.annual_net_benefit_chf, curr.annual_net_benefit_chf
        if v0 <= 0 <= v1:
            if v1 == v0:
                return prev.self_consumption_rate
            fraction = (Decimal("0") - v0) / (v1 - v0)
            span = curr.self_consumption_rate - prev.self_consumption_rate
            return prev.self_consumption_rate + fraction * span
    return None


def _build_price_sensitivity(inputs: FeasibilityInput, self_consumed: Decimal) -> list[PriceSensitivityPoint]:
    """Sweep the internal energy price from 0% to 100% of the retail price,
    holding self-consumed energy constant at the user's chosen scenario, and
    show how the value splits between producer and consumer at each price.

    Both lines are exactly linear in price (no kink, unlike the self-
    consumption sweep), since self_consumed doesn't depend on price.
    """
    points = []
    for i in range(SENSITIVITY_STEPS):
        pct = Decimal(i) / Decimal(SENSITIVITY_STEPS - 1)
        price = pct * inputs.retail_price_chf_per_kwh
        producer_gain = self_consumed * (price - inputs.feed_in_price_chf_per_kwh)
        consumer_savings = self_consumed * (inputs.retail_price_chf_per_kwh - price)
        points.append(
            PriceSensitivityPoint(
                internal_price_pct_of_retail=pct,
                internal_price_chf_per_kwh=_price(price),
                producer_gain_chf=_money(producer_gain),
                consumer_savings_chf=_money(consumer_savings),
            )
        )
    return points


def _equal_split_price(inputs: FeasibilityInput) -> Decimal | None:
    """The internal price where producer_gain == consumer_savings exactly.

    Explicitly NOT the recommended "fair" price: the producer carries the
    vZEV's capex and operational responsibility that the consumer doesn't,
    so an equal split under-compensates them. See ``_fair_price_range``.
    """
    if _net_unit_benefit(inputs) <= 0:
        return None
    return (inputs.retail_price_chf_per_kwh + inputs.feed_in_price_chf_per_kwh) / 2


def _fair_price_range(inputs: FeasibilityInput, self_consumed: Decimal) -> FairPriceRange | None:
    """A recommended internal-price range that is narrower than the trivial
    win-win range [feed_in, retail] on its lower end: the producer's price
    floor is raised so their gain also covers their share of
    annual_opex_chf, not merely beats feed-in. Returns None if there is
    no price that does this while still saving the consumer money (the
    scenario's running costs outweigh the value it creates).
    """
    if self_consumed <= 0:
        return None
    upper = inputs.retail_price_chf_per_kwh
    lower = inputs.feed_in_price_chf_per_kwh + inputs.annual_opex_chf / self_consumed
    if lower > upper:
        return None
    return FairPriceRange(low_chf_per_kwh=_price(lower), high_chf_per_kwh=_price(upper))


def _build_participant_results(inputs: FeasibilityInput, self_consumed_total: Decimal) -> list[ParticipantResult]:
    """Allocate the aggregate self-consumed pool across participants.

    Shares are computed against the *participant list's own* totals (not
    ``inputs.annual_production_kwh``/``annual_consumption_kwh`` directly) so
    that, by construction, the per-participant producer_gain/consumer_savings
    always sum exactly back to the aggregate figures — see the invariant
    test in ``test_calculator.py``.
    """
    if not inputs.participants:
        return []

    total_production = sum((p.annual_production_kwh for p in inputs.participants), Decimal("0"))
    total_consumption = sum((p.annual_consumption_kwh for p in inputs.participants), Decimal("0"))

    results = []
    for participant in inputs.participants:
        self_consumed_from_own = proportional_share(
            self_consumed_total, participant.annual_production_kwh, total_production
        )
        exported = participant.annual_production_kwh - self_consumed_from_own

        from_local_pool = proportional_share(
            self_consumed_total, participant.annual_consumption_kwh, total_consumption
        )
        from_grid = participant.annual_consumption_kwh - from_local_pool

        baseline_producer_revenue = participant.annual_production_kwh * inputs.feed_in_price_chf_per_kwh
        vzev_producer_revenue = (
            exported * inputs.feed_in_price_chf_per_kwh
            + self_consumed_from_own * inputs.internal_energy_price_chf_per_kwh
        )
        producer_gain = vzev_producer_revenue - baseline_producer_revenue

        baseline_consumer_cost = participant.annual_consumption_kwh * inputs.retail_price_chf_per_kwh
        vzev_consumer_cost = (
            from_grid * inputs.retail_price_chf_per_kwh
            + from_local_pool * inputs.internal_energy_price_chf_per_kwh
        )
        consumer_savings = baseline_consumer_cost - vzev_consumer_cost

        results.append(
            ParticipantResult(
                name=participant.name,
                annual_production_kwh=_money(participant.annual_production_kwh),
                annual_consumption_kwh=_money(participant.annual_consumption_kwh),
                self_consumed_from_own_production_kwh=_money(self_consumed_from_own),
                exported_kwh=_money(exported),
                from_local_pool_kwh=_money(from_local_pool),
                from_grid_kwh=_money(from_grid),
                producer_gain_chf=_money(producer_gain),
                consumer_savings_chf=_money(consumer_savings),
                net_benefit_chf=_money(producer_gain + consumer_savings),
            )
        )
    return results


def _payback_years(annual_net_benefit: Decimal, capex: Decimal) -> Decimal | None:
    if annual_net_benefit <= 0:
        return None
    if capex <= 0:
        return Decimal("0")
    return capex / annual_net_benefit


def _roi(annual_net_benefit: Decimal, capex: Decimal) -> Decimal | None:
    if capex <= 0:
        return None
    return annual_net_benefit / capex


def _npv(annual_net_benefit: Decimal, capex: Decimal, horizon_years: int, discount_rate: Decimal) -> Decimal:
    npv = -capex
    for year in range(1, horizon_years + 1):
        npv += annual_net_benefit / (Decimal("1") + discount_rate) ** year
    return npv


def _cashflow_by_year(annual_net_benefit: Decimal, capex: Decimal, horizon_years: int) -> list[Decimal]:
    cashflow = [-capex]
    for _ in range(horizon_years):
        cashflow.append(cashflow[-1] + annual_net_benefit)
    return cashflow


def compute_feasibility(inputs: FeasibilityInput) -> FeasibilityResult:
    """Compute the full vZEV feasibility result for a single scenario."""
    self_consumed = _self_consumed_kwh(
        inputs.self_consumption_rate, inputs.annual_production_kwh, inputs.annual_consumption_kwh
    )
    grid_import = inputs.annual_consumption_kwh - self_consumed
    grid_export = inputs.annual_production_kwh - self_consumed
    autarky_rate = (
        self_consumed / inputs.annual_consumption_kwh if inputs.annual_consumption_kwh > 0 else Decimal("0")
    )

    baseline_consumer_cost = inputs.annual_consumption_kwh * inputs.retail_price_chf_per_kwh
    baseline_producer_revenue = inputs.annual_production_kwh * inputs.feed_in_price_chf_per_kwh

    vzev_consumer_cost = (
        grid_import * inputs.retail_price_chf_per_kwh
        + self_consumed * inputs.internal_energy_price_chf_per_kwh
    )
    vzev_producer_revenue = (
        grid_export * inputs.feed_in_price_chf_per_kwh + self_consumed * inputs.internal_energy_price_chf_per_kwh
    )

    consumer_savings = baseline_consumer_cost - vzev_consumer_cost
    producer_gain = vzev_producer_revenue - baseline_producer_revenue
    annual_gross_benefit = consumer_savings + producer_gain
    annual_net_benefit = annual_gross_benefit - inputs.annual_opex_chf

    sensitivity = _build_sensitivity(inputs)

    return FeasibilityResult(
        self_consumed_kwh=_money(self_consumed),
        grid_import_kwh=_money(grid_import),
        grid_export_kwh=_money(grid_export),
        autarky_rate=autarky_rate,
        baseline_consumer_cost_chf=_money(baseline_consumer_cost),
        baseline_producer_revenue_chf=_money(baseline_producer_revenue),
        vzev_consumer_cost_chf=_money(vzev_consumer_cost),
        vzev_producer_revenue_chf=_money(vzev_producer_revenue),
        consumer_savings_chf=_money(consumer_savings),
        producer_gain_chf=_money(producer_gain),
        annual_gross_benefit_chf=_money(annual_gross_benefit),
        annual_net_benefit_chf=_money(annual_net_benefit),
        payback_years=_payback_years(annual_net_benefit, inputs.capex_chf),
        roi=_roi(annual_net_benefit, inputs.capex_chf),
        npv_chf=_money(_npv(annual_net_benefit, inputs.capex_chf, inputs.horizon_years, inputs.discount_rate)),
        cashflow_by_year=[
            _money(v) for v in _cashflow_by_year(annual_net_benefit, inputs.capex_chf, inputs.horizon_years)
        ],
        sensitivity=sensitivity,
        break_even_self_consumption_rate=_break_even_rate(sensitivity),
        price_sensitivity=_build_price_sensitivity(inputs, self_consumed),
        equal_split_price_chf_per_kwh=_equal_split_price(inputs),
        fair_price_range=_fair_price_range(inputs, self_consumed),
        participants=_build_participant_results(inputs, self_consumed),
    )


def estimate_annual_production_kwh(pv_kwp: Decimal, specific_yield_kwh_per_kwp: Decimal) -> Decimal:
    """Estimate annual PV production from installed capacity and a specific-yield assumption."""
    return pv_kwp * specific_yield_kwh_per_kwp
