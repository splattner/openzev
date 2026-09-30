"""Unit tests for the pure vZEV feasibility calculator.

No Django/DB dependency — these are plain function calls against hand-computed
expected values.
"""
from decimal import Decimal

import pytest

from .calculator import (
    FeasibilityInput,
    ParticipantInput,
    compute_feasibility,
)


def _typical_input(**overrides) -> FeasibilityInput:
    """production=10'000 kWh, consumption=8'000 kWh, sigma=50% -> self-consumed=5'000 kWh."""
    defaults = dict(
        annual_production_kwh=Decimal("10000"),
        annual_consumption_kwh=Decimal("8000"),
        self_consumption_rate=Decimal("0.5"),
        retail_price_chf_per_kwh=Decimal("0.32"),
        feed_in_price_chf_per_kwh=Decimal("0.09"),
        internal_energy_price_chf_per_kwh=Decimal("0.20"),
        annual_opex_chf=Decimal("300"),
        capex_chf=Decimal("2000"),
        horizon_years=20,
        discount_rate=Decimal("0.03"),
    )
    defaults.update(overrides)
    return FeasibilityInput(**defaults)


class TestTypicalScenario:
    """Hand-computed reference scenario, see module docstring math:

    self_consumed = min(0.5*10000, 8000) = 5000
    net_unit_benefit = 0.32 - 0.09 = 0.23
    gross_benefit = 5000 * 0.23 = 1150.00
    """

    def test_energy_balance(self):
        result = compute_feasibility(_typical_input())
        assert result.self_consumed_kwh == Decimal("5000.00")
        assert result.grid_import_kwh == Decimal("3000.00")
        assert result.grid_export_kwh == Decimal("5000.00")
        assert result.autarky_rate == Decimal("0.625")  # 5000/8000

    def test_baseline_costs(self):
        result = compute_feasibility(_typical_input())
        assert result.baseline_consumer_cost_chf == Decimal("2560.00")  # 8000*0.32
        assert result.baseline_producer_revenue_chf == Decimal("900.00")  # 10000*0.09

    def test_vzev_costs_and_split(self):
        result = compute_feasibility(_typical_input())
        # 3000*0.32 + 5000*0.20 = 960 + 1000
        assert result.vzev_consumer_cost_chf == Decimal("1960.00")
        # 5000*0.09 + 5000*0.20 = 450 + 1000
        assert result.vzev_producer_revenue_chf == Decimal("1450.00")
        assert result.consumer_savings_chf == Decimal("600.00")
        assert result.producer_gain_chf == Decimal("550.00")

    def test_gross_and_net_benefit(self):
        result = compute_feasibility(_typical_input())
        assert result.annual_gross_benefit_chf == Decimal("1150.00")
        assert result.annual_net_benefit_chf == Decimal("850.00")  # 1150 - 300 opex

    def test_payback_and_roi(self):
        result = compute_feasibility(_typical_input())
        expected_payback = (Decimal("2000") / Decimal("850")).quantize(Decimal("0.0001"))
        assert result.payback_years.quantize(Decimal("0.0001")) == expected_payback
        assert result.roi == Decimal("0.425")  # 850/2000

    def test_npv_matches_independent_annuity_sum(self):
        result = compute_feasibility(_typical_input())
        expected = Decimal("-2000")
        for year in range(1, 21):
            expected += Decimal("850") / (Decimal("1.03") ** year)
        assert result.npv_chf == expected.quantize(Decimal("0.01"))

    def test_break_even_self_consumption_rate(self):
        # plateau at sigma=1: S=min(10000,8000)=8000 -> gross=1840, net=1540 > 0, so a
        # break-even exists in the unconstrained (linear) region: opex / (P*net_unit_benefit)
        # = 300 / (10000*0.23) = 3/23, which does not land on the 5%-step sampling grid, so
        # compare against an independently computed (not hardcoded-literal) expected value.
        result = compute_feasibility(_typical_input())
        expected = Decimal("300") / (Decimal("10000") * Decimal("0.23"))
        assert result.break_even_self_consumption_rate == expected

    def test_sensitivity_curve_shape(self):
        result = compute_feasibility(_typical_input())
        assert len(result.sensitivity) == 21
        assert result.sensitivity[0].self_consumption_rate == Decimal("0")
        assert result.sensitivity[0].annual_net_benefit_chf == Decimal("-300.00")  # S=0, net=-opex
        assert result.sensitivity[-1].self_consumption_rate == Decimal("1")

    def test_cashflow_by_year(self):
        result = compute_feasibility(_typical_input())
        assert len(result.cashflow_by_year) == 21  # horizon_years + 1 (year 0 = -capex)
        assert result.cashflow_by_year[0] == Decimal("-2000.00")
        assert result.cashflow_by_year[1] == Decimal("-1150.00")  # -2000 + 850
        assert result.cashflow_by_year[-1] == Decimal("-2000.00") + 20 * Decimal("850.00")


class TestPriceSensitivity:
    """The internal-price sweep (self-consumed kWh fixed at 5000, per
    TestTypicalScenario): producer_gain and consumer_savings are exactly
    linear in price since self_consumed doesn't depend on it. There is no
    internal grid fee in this model — within a vZEV, locally consumed
    energy is only ever priced as energy.

    equal_split_price = (retail + feed_in) / 2 = (0.32+0.09)/2 = 0.205
    fair range: low = feed_in + opex/S = 0.09 + 300/5000 = 0.15
                high = retail = 0.32
    """

    def test_price_sensitivity_curve_endpoints(self):
        result = compute_feasibility(_typical_input())
        assert len(result.price_sensitivity) == 21

        zero_price = result.price_sensitivity[0]
        assert zero_price.internal_price_chf_per_kwh == Decimal("0.00000")
        assert zero_price.producer_gain_chf == Decimal("-450.00")  # 5000*(0-0.09)
        assert zero_price.consumer_savings_chf == Decimal("1600.00")  # 5000*(0.32-0)

        full_retail = result.price_sensitivity[-1]
        assert full_retail.internal_price_chf_per_kwh == Decimal("0.32000")
        assert full_retail.producer_gain_chf == Decimal("1150.00")  # 5000*(0.32-0.09)
        assert full_retail.consumer_savings_chf == Decimal("0.00")  # 5000*(0.32-0.32)

    def test_equal_split_price(self):
        result = compute_feasibility(_typical_input())
        assert result.equal_split_price_chf_per_kwh == Decimal("0.20500")

        # Sanity: at the equal-split price, producer_gain really does equal
        # consumer_savings (independently recomputed, not read off the
        # 5%-step sample grid, since 0.205 doesn't land on one of those steps).
        price = result.equal_split_price_chf_per_kwh
        self_consumed = result.self_consumed_kwh
        producer_gain = self_consumed * (price - Decimal("0.09"))
        consumer_savings = self_consumed * (Decimal("0.32") - price)
        assert producer_gain == consumer_savings

    def test_fair_price_range(self):
        result = compute_feasibility(_typical_input())
        assert result.fair_price_range is not None
        assert result.fair_price_range.low_chf_per_kwh == Decimal("0.15000")
        assert result.fair_price_range.high_chf_per_kwh == Decimal("0.32000")
        # The naive equal split (0.205) sits inside the recommended range, but
        # nearer its floor than its ceiling -- it is not itself the "fair" pick.
        assert result.fair_price_range.low_chf_per_kwh < result.equal_split_price_chf_per_kwh < result.fair_price_range.high_chf_per_kwh

    def test_fair_price_range_none_when_opex_too_high(self):
        # Max possible producer gain span is S*(upper-feed_in) = 5000*0.23 = 1150;
        # an opex above that leaves no price that both compensates the producer
        # and still saves the consumer money.
        result = compute_feasibility(_typical_input(annual_opex_chf=Decimal("1200")))
        assert result.fair_price_range is None

    def test_fair_price_range_none_when_no_self_consumption(self):
        result = compute_feasibility(_typical_input(self_consumption_rate=Decimal("0")))
        assert result.fair_price_range is None

    def test_equal_split_price_none_when_no_net_benefit(self):
        # feed_in at or above retail: no win-win price exists at all.
        result = compute_feasibility(_typical_input(feed_in_price_chf_per_kwh=Decimal("0.35")))
        assert result.equal_split_price_chf_per_kwh is None


class TestSinglePeriodNpv:
    """A scenario chosen so the year-1 discounting divides out exactly:
    1030 / 1.03 == 1000 with no rounding, giving NPV == 0 by hand."""

    def test_npv_zero_at_break_even_single_year(self):
        inputs = FeasibilityInput(
            annual_production_kwh=Decimal("1000"),
            annual_consumption_kwh=Decimal("1000"),
            self_consumption_rate=Decimal("1"),
            retail_price_chf_per_kwh=Decimal("1.33"),
            feed_in_price_chf_per_kwh=Decimal("0.30"),
            internal_energy_price_chf_per_kwh=Decimal("0.50"),
            annual_opex_chf=Decimal("0"),
            capex_chf=Decimal("1000"),
            horizon_years=1,
            discount_rate=Decimal("0.03"),
        )
        result = compute_feasibility(inputs)
        assert result.annual_net_benefit_chf == Decimal("1030.00")  # 1000*(1.33-0.30)
        assert result.npv_chf == Decimal("0.00")
        assert result.roi == Decimal("1.03")
        assert result.payback_years.quantize(Decimal("0.0001")) == (
            Decimal("1000") / Decimal("1030")
        ).quantize(Decimal("0.0001"))


class TestInternalPriceInvariant:
    """internal_energy_price only redistributes value between producer and
    consumers; it must never change the total pie."""

    def test_gross_benefit_unaffected_by_internal_energy_price(self):
        cheap = compute_feasibility(_typical_input(internal_energy_price_chf_per_kwh=Decimal("0.10")))
        expensive = compute_feasibility(_typical_input(internal_energy_price_chf_per_kwh=Decimal("0.28")))

        assert cheap.annual_gross_benefit_chf == expensive.annual_gross_benefit_chf
        assert cheap.annual_net_benefit_chf == expensive.annual_net_benefit_chf
        # but the split between producer and consumers does change
        assert cheap.producer_gain_chf != expensive.producer_gain_chf
        assert cheap.consumer_savings_chf != expensive.consumer_savings_chf
        assert cheap.producer_gain_chf + cheap.consumer_savings_chf == cheap.annual_gross_benefit_chf
        assert expensive.producer_gain_chf + expensive.consumer_savings_chf == expensive.annual_gross_benefit_chf


class TestEdgeCases:
    def test_zero_self_consumption_rate_yields_zero_gross_benefit(self):
        result = compute_feasibility(_typical_input(self_consumption_rate=Decimal("0")))
        assert result.self_consumed_kwh == Decimal("0.00")
        assert result.annual_gross_benefit_chf == Decimal("0.00")
        assert result.annual_net_benefit_chf == Decimal("-300.00")  # just -opex
        # payback is undefined without a positive net benefit, regardless of capex...
        assert result.payback_years is None
        # ...but ROI is defined purely from capex, independent of benefit sign.
        assert result.roi == Decimal("-0.15")  # -300/2000

    def test_zero_production_gives_zero_benefit_regardless_of_rate(self):
        result = compute_feasibility(
            _typical_input(annual_production_kwh=Decimal("0"), self_consumption_rate=Decimal("1"))
        )
        assert result.self_consumed_kwh == Decimal("0.00")
        assert result.grid_export_kwh == Decimal("0.00")
        assert result.grid_import_kwh == Decimal("8000.00")
        assert result.producer_gain_chf == Decimal("0.00")
        assert result.consumer_savings_chf == Decimal("0.00")

    def test_zero_consumption_gives_zero_benefit(self):
        result = compute_feasibility(
            _typical_input(annual_consumption_kwh=Decimal("0"), self_consumption_rate=Decimal("1"))
        )
        assert result.self_consumed_kwh == Decimal("0.00")
        assert result.grid_import_kwh == Decimal("0.00")
        assert result.grid_export_kwh == Decimal("10000.00")
        assert result.autarky_rate == Decimal("0")
        assert result.annual_gross_benefit_chf == Decimal("0.00")

    def test_self_consumption_capped_by_consumption_not_production(self):
        # sigma=1 with production >> consumption: self-consumed can't exceed consumption.
        result = compute_feasibility(
            _typical_input(
                annual_production_kwh=Decimal("10000"),
                annual_consumption_kwh=Decimal("2000"),
                self_consumption_rate=Decimal("1"),
            )
        )
        assert result.self_consumed_kwh == Decimal("2000.00")
        assert result.grid_import_kwh == Decimal("0.00")
        assert result.grid_export_kwh == Decimal("8000.00")

    def test_break_even_none_when_unreachable(self):
        # opex so high that even 100% self-consumption (capped at consumption=8000)
        # can't cover it: plateau = 8000*0.23 - 5000 = -3160 < 0.
        result = compute_feasibility(_typical_input(annual_opex_chf=Decimal("5000")))
        assert result.break_even_self_consumption_rate is None

    def test_payback_zero_when_no_capex_but_positive_benefit(self):
        result = compute_feasibility(_typical_input(capex_chf=Decimal("0")))
        assert result.payback_years == Decimal("0")
        assert result.roi is None  # ROI undefined without an investment base

    def test_npv_ignores_capex_when_zero(self):
        result = compute_feasibility(_typical_input(capex_chf=Decimal("0")))
        expected = Decimal("0")
        for year in range(1, 21):
            expected += Decimal("850") / (Decimal("1.03") ** year)
        assert result.npv_chf == expected.quantize(Decimal("0.01"))


class TestValidation:
    @pytest.mark.parametrize(
        "field,value",
        [
            ("self_consumption_rate", Decimal("-0.01")),
            ("self_consumption_rate", Decimal("1.01")),
            ("annual_production_kwh", Decimal("-1")),
            ("annual_consumption_kwh", Decimal("-1")),
            ("retail_price_chf_per_kwh", Decimal("-0.01")),
            ("feed_in_price_chf_per_kwh", Decimal("-0.01")),
            ("internal_energy_price_chf_per_kwh", Decimal("-0.01")),
            ("annual_opex_chf", Decimal("-1")),
            ("capex_chf", Decimal("-1")),
            ("discount_rate", Decimal("-0.01")),
        ],
    )
    def test_invalid_field_raises(self, field, value):
        with pytest.raises(ValueError):
            _typical_input(**{field: value})

    def test_zero_horizon_years_raises(self):
        with pytest.raises(ValueError):
            _typical_input(horizon_years=0)

    def test_boundary_self_consumption_rate_allowed(self):
        # 0 and 1 are valid boundaries, must not raise.
        compute_feasibility(_typical_input(self_consumption_rate=Decimal("0")))
        compute_feasibility(_typical_input(self_consumption_rate=Decimal("1")))


class TestMultiParticipant:
    """Two producers + two consumers whose totals exactly match the
    TestTypicalScenario aggregate (production=10'000, consumption=8'000),
    so the per-participant breakdown can be cross-checked against those
    already-verified aggregate numbers.

    Shares: producer A=6000/10000=60%, B=4000/10000=40%.
             consumer C=5000/8000=62.5%, D=3000/8000=37.5%.
    self_consumed_total=5000 (unchanged from the typical scenario).
    """

    def _multi_participant_input(self, **overrides) -> FeasibilityInput:
        return _typical_input(
            participants=(
                ParticipantInput(name="Producer A", annual_production_kwh=Decimal("6000")),
                ParticipantInput(name="Producer B", annual_production_kwh=Decimal("4000")),
                ParticipantInput(name="Consumer C", annual_consumption_kwh=Decimal("5000")),
                ParticipantInput(name="Consumer D", annual_consumption_kwh=Decimal("3000")),
            ),
            **overrides,
        )

    def test_energy_allocation_per_participant(self):
        result = compute_feasibility(self._multi_participant_input())
        by_name = {p.name: p for p in result.participants}

        assert by_name["Producer A"].self_consumed_from_own_production_kwh == Decimal("3000.00")  # 5000*0.6
        assert by_name["Producer A"].exported_kwh == Decimal("3000.00")  # 6000-3000
        assert by_name["Producer B"].self_consumed_from_own_production_kwh == Decimal("2000.00")  # 5000*0.4
        assert by_name["Producer B"].exported_kwh == Decimal("2000.00")  # 4000-2000

        assert by_name["Consumer C"].from_local_pool_kwh == Decimal("3125.00")  # 5000*0.625
        assert by_name["Consumer C"].from_grid_kwh == Decimal("1875.00")  # 5000-3125
        assert by_name["Consumer D"].from_local_pool_kwh == Decimal("1875.00")  # 5000*0.375
        assert by_name["Consumer D"].from_grid_kwh == Decimal("1125.00")  # 3000-1875

    def test_money_per_participant(self):
        result = compute_feasibility(self._multi_participant_input())
        by_name = {p.name: p for p in result.participants}

        # Producer A: baseline 6000*0.09=540; vzev 3000*0.09+3000*0.20=870; gain=330
        assert by_name["Producer A"].producer_gain_chf == Decimal("330.00")
        # Producer B: baseline 4000*0.09=360; vzev 2000*0.09+2000*0.20=580; gain=220
        assert by_name["Producer B"].producer_gain_chf == Decimal("220.00")
        # Consumer C: baseline 5000*0.32=1600; vzev 1875*0.32+3125*0.20=1225; savings=375
        assert by_name["Consumer C"].consumer_savings_chf == Decimal("375.00")
        # Consumer D: baseline 3000*0.32=960; vzev 1125*0.32+1875*0.20=735; savings=225
        assert by_name["Consumer D"].consumer_savings_chf == Decimal("225.00")

        # Pure producers have zero consumer_savings; pure consumers have zero producer_gain.
        assert by_name["Producer A"].consumer_savings_chf == Decimal("0.00")
        assert by_name["Consumer C"].producer_gain_chf == Decimal("0.00")

    def test_per_participant_sums_match_aggregate(self):
        """The whole point of the allocation: it must be an exact decomposition
        of the aggregate figures already verified in TestTypicalScenario, not
        a separately-computed number that could silently drift."""
        result = compute_feasibility(self._multi_participant_input())

        total_producer_gain = sum(p.producer_gain_chf for p in result.participants)
        total_consumer_savings = sum(p.consumer_savings_chf for p in result.participants)
        total_net_benefit = sum(p.net_benefit_chf for p in result.participants)

        assert total_producer_gain == result.producer_gain_chf == Decimal("550.00")
        assert total_consumer_savings == result.consumer_savings_chf == Decimal("600.00")
        assert total_net_benefit == result.annual_gross_benefit_chf == Decimal("1150.00")

    def test_prosumer_gets_both_producer_gain_and_consumer_savings(self):
        prosumer_input = _typical_input(
            participants=(
                ParticipantInput(
                    name="Prosumer",
                    annual_production_kwh=Decimal("10000"),
                    annual_consumption_kwh=Decimal("8000"),
                ),
            ),
        )
        result = compute_feasibility(prosumer_input)
        assert len(result.participants) == 1
        prosumer = result.participants[0]

        # Sole participant holds 100% of both production and consumption shares,
        # so they receive the entire aggregate result.
        assert prosumer.producer_gain_chf == result.producer_gain_chf == Decimal("550.00")
        assert prosumer.consumer_savings_chf == result.consumer_savings_chf == Decimal("600.00")
        assert prosumer.net_benefit_chf == Decimal("1150.00")

    def test_empty_participants_list_by_default(self):
        result = compute_feasibility(_typical_input())
        assert result.participants == []

    def test_no_producers_among_participants_does_not_divide_by_zero(self):
        result = compute_feasibility(
            _typical_input(
                participants=(
                    ParticipantInput(name="Consumer only", annual_consumption_kwh=Decimal("8000")),
                ),
            )
        )
        only = result.participants[0]
        assert only.self_consumed_from_own_production_kwh == Decimal("0.00")
        assert only.exported_kwh == Decimal("0.00")

    def test_no_consumers_among_participants_does_not_divide_by_zero(self):
        result = compute_feasibility(
            _typical_input(
                participants=(
                    ParticipantInput(name="Producer only", annual_production_kwh=Decimal("10000")),
                ),
            )
        )
        only = result.participants[0]
        assert only.from_local_pool_kwh == Decimal("0.00")
        assert only.from_grid_kwh == Decimal("0.00")

    def test_negative_participant_production_raises(self):
        with pytest.raises(ValueError):
            _typical_input(
                participants=(ParticipantInput(name="Bad", annual_production_kwh=Decimal("-1")),),
            )

    def test_negative_participant_consumption_raises(self):
        with pytest.raises(ValueError):
            _typical_input(
                participants=(ParticipantInput(name="Bad", annual_consumption_kwh=Decimal("-1")),),
            )
