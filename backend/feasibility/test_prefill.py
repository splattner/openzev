"""Tests for the best-effort ZEV -> feasibility calculator prefill."""
import random
from datetime import date, datetime, timedelta, timezone as dt_timezone
from decimal import Decimal

import pytest

from accounts.models import VatRate
from allocation.errors import InvalidAllocationInputError
from allocation.split import local_pool_kwh
from metering.models import MeterReading, ReadingDirection
from tariffs.models import BillingMode, EnergyType, PeriodType, TariffCategory
from testing import factories
from testing.helpers import clear_vat_rates
from zev.models import MeteringPointType, VatMode

from .defaults import DEFAULT_PARTICIPANT_CONSUMPTION_KWH
from .prefill import build_prefill

pytestmark = pytest.mark.django_db


def _reading(metering_point, day_offset: int, energy_kwh: str, direction: str) -> MeterReading:
    return MeterReading.objects.create(
        metering_point=metering_point,
        timestamp=datetime(2026, 1, 1, 12, 0, tzinfo=dt_timezone.utc) + timedelta(days=day_offset),
        energy_kwh=Decimal(energy_kwh),
        direction=direction,
    )


class TestParticipantEnergyPrefill:
    def test_falls_back_to_default_consumption_when_no_readings_exist(self):
        zev = factories.ZevFactory()
        participant = factories.ParticipantFactory(zev=zev)
        # Assigned metering points, but no MeterReadings at all yet.
        consumption_mp = factories.MeteringPointFactory(zev=zev, meter_type=MeteringPointType.CONSUMPTION)
        factories.MeteringPointAssignmentFactory(metering_point=consumption_mp, participant=participant)

        prefill = build_prefill(zev)

        assert len(prefill.participants) == 1
        row = prefill.participants[0]
        assert row.name == participant.full_name
        assert row.has_metering_data is False
        assert row.annual_production_kwh == Decimal("0")
        assert row.annual_consumption_kwh == DEFAULT_PARTICIPANT_CONSUMPTION_KWH

    def test_extrapolates_partial_history_to_a_full_year(self):
        zev = factories.ZevFactory()
        participant = factories.ParticipantFactory(zev=zev)
        consumption_mp = factories.MeteringPointFactory(zev=zev, meter_type=MeteringPointType.CONSUMPTION)
        factories.MeteringPointAssignmentFactory(metering_point=consumption_mp, participant=participant)

        # 10 kWh/day readings spanning exactly 30 days (day 0 .. day 30) -> 300 kWh
        # total over a 30-day span, extrapolated: 300 * 365/30 = 3650.
        for day in range(0, 31, 30):
            _reading(consumption_mp, day, "150", ReadingDirection.IN)

        prefill = build_prefill(zev)
        row = prefill.participants[0]
        assert row.has_metering_data is True
        assert row.annual_consumption_kwh == Decimal("3650")

    def test_production_and_consumption_tracked_independently_for_a_prosumer(self):
        zev = factories.ZevFactory()
        participant = factories.ParticipantFactory(zev=zev)
        bidirectional_mp = factories.MeteringPointFactory(zev=zev, meter_type=MeteringPointType.BIDIRECTIONAL)
        factories.MeteringPointAssignmentFactory(metering_point=bidirectional_mp, participant=participant)

        # Exactly a 365-day span so extrapolation is a no-op: totals pass straight through.
        _reading(bidirectional_mp, 0, "1000", ReadingDirection.IN)
        _reading(bidirectional_mp, 365, "500", ReadingDirection.IN)
        _reading(bidirectional_mp, 0, "2000", ReadingDirection.OUT)
        _reading(bidirectional_mp, 365, "1000", ReadingDirection.OUT)

        prefill = build_prefill(zev)
        row = prefill.participants[0]
        assert row.has_metering_data is True
        assert row.annual_consumption_kwh == Decimal("1500")
        assert row.annual_production_kwh == Decimal("3000")

    def test_excludes_participants_no_longer_active(self):
        zev = factories.ZevFactory()
        factories.ParticipantFactory(zev=zev, valid_to=date(2025, 1, 1))  # ended before "today"

        prefill = build_prefill(zev)
        assert prefill.participants == []

    def test_combines_meter_spans_before_extrapolation(self):
        zev = factories.ZevFactory()
        participant = factories.ParticipantFactory(zev=zev)
        meters = [factories.MeteringPointFactory(zev=zev) for _ in range(2)]
        for meter in meters:
            factories.MeteringPointAssignmentFactory(metering_point=meter, participant=participant)
        _reading(meters[0], 0, "1", ReadingDirection.IN)
        _reading(meters[0], 30, "1", ReadingDirection.IN)
        _reading(meters[1], 15, "1", ReadingDirection.IN)

        row = build_prefill(zev).participants[0]
        assert row.annual_consumption_kwh == Decimal("36.5")

    def test_repeated_assignments_count_meter_history_once_per_participant(self):
        zev = factories.ZevFactory()
        alice = factories.ParticipantFactory(zev=zev)
        bob = factories.ParticipantFactory(zev=zev)
        meter = factories.MeteringPointFactory(zev=zev)
        for participant, start, end in (
            (alice, date(2023, 1, 1), date(2023, 12, 31)),
            (bob, date(2024, 1, 1), date(2024, 12, 31)),
            (alice, date(2025, 1, 1), None),
        ):
            factories.MeteringPointAssignmentFactory(
                metering_point=meter, participant=participant, valid_from=start, valid_to=end,
            )
        _reading(meter, 0, "100", ReadingDirection.IN)
        _reading(meter, 30, "200", ReadingDirection.IN)

        rows = build_prefill(zev).participants
        assert len(rows) == 2
        # Planning prefill uses all assigned-meter history, not billing's windows.
        assert all(row.annual_consumption_kwh == Decimal("3650") for row in rows)

    def test_zero_and_ineligible_directions_keep_the_default(self):
        zev = factories.ZevFactory()
        participant = factories.ParticipantFactory(zev=zev)
        consumption = factories.MeteringPointFactory(zev=zev, meter_type=MeteringPointType.CONSUMPTION)
        production = factories.MeteringPointFactory(zev=zev, meter_type=MeteringPointType.PRODUCTION)
        for meter in (consumption, production):
            factories.MeteringPointAssignmentFactory(metering_point=meter, participant=participant)
        _reading(consumption, 0, "0", ReadingDirection.IN)
        _reading(consumption, 0, "10", ReadingDirection.OUT)
        _reading(production, 0, "10", ReadingDirection.IN)

        row = build_prefill(zev).participants[0]
        assert row.has_metering_data is False
        assert row.annual_consumption_kwh == DEFAULT_PARTICIPANT_CONSUMPTION_KWH
        assert row.annual_production_kwh == 0


class TestSelfConsumptionRatePrefill:
    """Measured ZEV-level self-consumption rate = self-consumed / produced,
    where self-consumed is the per-timestamp min(production, consumption)."""

    def test_measures_rate_from_per_timestamp_local_pool(self):
        zev = factories.ZevFactory()
        production_mp = factories.MeteringPointFactory(zev=zev, meter_type=MeteringPointType.PRODUCTION)
        consumption_mp = factories.MeteringPointFactory(zev=zev, meter_type=MeteringPointType.CONSUMPTION)

        # ts day0: produced 100, consumed 40 -> self-consumed min = 40
        # ts day1: produced 20,  consumed 80 -> self-consumed min = 20
        # total produced = 120, self-consumed = 60 -> rate = 60/120 = 0.5
        _reading(production_mp, 0, "100", ReadingDirection.OUT)
        _reading(production_mp, 1, "20", ReadingDirection.OUT)
        _reading(consumption_mp, 0, "40", ReadingDirection.IN)
        _reading(consumption_mp, 1, "80", ReadingDirection.IN)

        prefill = build_prefill(zev)
        assert prefill.self_consumption_rate == Decimal("0.5000")

    def test_none_when_no_production(self):
        zev = factories.ZevFactory()
        consumption_mp = factories.MeteringPointFactory(zev=zev, meter_type=MeteringPointType.CONSUMPTION)
        _reading(consumption_mp, 0, "50", ReadingDirection.IN)

        prefill = build_prefill(zev)
        assert prefill.self_consumption_rate is None

    def test_none_when_no_consumption(self):
        # Production but no consumption: reporting 0% would be misleading (we
        # simply don't know what was consumed), so it stays None.
        zev = factories.ZevFactory()
        production_mp = factories.MeteringPointFactory(zev=zev, meter_type=MeteringPointType.PRODUCTION)
        _reading(production_mp, 0, "50", ReadingDirection.OUT)

        prefill = build_prefill(zev)
        assert prefill.self_consumption_rate is None

    def test_none_when_no_readings_at_all(self):
        zev = factories.ZevFactory()
        prefill = build_prefill(zev)
        assert prefill.self_consumption_rate is None

    def test_full_self_consumption_when_production_never_exceeds_consumption(self):
        zev = factories.ZevFactory()
        production_mp = factories.MeteringPointFactory(zev=zev, meter_type=MeteringPointType.PRODUCTION)
        consumption_mp = factories.MeteringPointFactory(zev=zev, meter_type=MeteringPointType.CONSUMPTION)
        # Consumption always meets or exceeds production -> everything produced is used locally.
        _reading(production_mp, 0, "30", ReadingDirection.OUT)
        _reading(production_mp, 1, "30", ReadingDirection.OUT)
        _reading(consumption_mp, 0, "50", ReadingDirection.IN)
        _reading(consumption_mp, 1, "50", ReadingDirection.IN)

        prefill = build_prefill(zev)
        assert prefill.self_consumption_rate == Decimal("1.0000")

    def test_sql_rate_matches_decimal_interval_reference(self):
        zev = factories.ZevFactory()
        meters = [
            factories.MeteringPointFactory(zev=zev, meter_type=MeteringPointType.BIDIRECTIONAL)
            for _ in range(3)
        ]
        rng = random.Random(41)
        total_produced = Decimal("0")
        local = Decimal("0")
        for day in range(12):
            produced = consumed = Decimal("0")
            for meter in meters:
                for direction in (ReadingDirection.IN, ReadingDirection.OUT):
                    energy = Decimal(rng.randrange(0, 20000)) / Decimal("10000")
                    _reading(meter, day, str(energy), direction)
                    if direction == ReadingDirection.IN:
                        consumed += energy
                    else:
                        produced += energy
            total_produced += produced
            local += local_pool_kwh(produced, consumed)

        expected = (local / total_produced).quantize(Decimal("0.0001"))
        assert build_prefill(zev).self_consumption_rate == expected

    @pytest.mark.parametrize("direction", [ReadingDirection.IN, ReadingDirection.OUT])
    def test_rejects_negative_timestamp_totals_even_when_period_total_is_positive(self, direction):
        zev = factories.ZevFactory()
        meter = factories.MeteringPointFactory(zev=zev, meter_type=MeteringPointType.BIDIRECTIONAL)
        _reading(meter, 0, "-1", direction)
        _reading(meter, 1, "10", direction)

        with pytest.raises(InvalidAllocationInputError):
            build_prefill(zev)

    def test_disjoint_production_and_consumption_have_no_local_pool(self):
        zev = factories.ZevFactory()
        meter = factories.MeteringPointFactory(zev=zev, meter_type=MeteringPointType.BIDIRECTIONAL)
        _reading(meter, 0, "10", ReadingDirection.OUT)
        _reading(meter, 1, "10", ReadingDirection.IN)

        assert build_prefill(zev).self_consumption_rate == Decimal("0.0000")

    @pytest.mark.parametrize("fraction, expected", [("0.0250", "0.1250"), ("0.0251", "0.1252")])
    def test_preserves_decimal_half_even_rounding(self, fraction, expected):
        zev = factories.ZevFactory()
        meters = [
            factories.MeteringPointFactory(zev=zev, meter_type=MeteringPointType.BIDIRECTIONAL)
            for _ in range(2)
        ]
        for day in (0, 1):
            _reading(meters[0], day, "0.3", ReadingDirection.OUT)
            _reading(meters[1], day, "0.7", ReadingDirection.OUT)
            _reading(meters[0], day, "0.1", ReadingDirection.IN)
            _reading(meters[1], day, str(Decimal(fraction) + day * Decimal("0.0001")), ReadingDirection.IN)

        assert build_prefill(zev).self_consumption_rate == Decimal(expected)

    def test_ignores_other_zevs_and_includes_unassigned_pool_readings(self):
        zev = factories.ZevFactory()
        own = factories.MeteringPointFactory(zev=zev, meter_type=MeteringPointType.BIDIRECTIONAL)
        other = factories.MeteringPointFactory(meter_type=MeteringPointType.PRODUCTION)
        _reading(own, 0, "10", ReadingDirection.OUT)
        _reading(own, 0, "4", ReadingDirection.IN)
        _reading(other, 0, "1000", ReadingDirection.OUT)

        assert build_prefill(zev).self_consumption_rate == Decimal("0.4000")


class TestTariffPrefill:
    def test_reads_flat_energy_tariffs_for_each_relevant_type(self):
        zev = factories.ZevFactory()
        for energy_type, price in (
            (EnergyType.GRID, "0.31000"),
            (EnergyType.FEED_IN, "0.08000"),
            (EnergyType.LOCAL, "0.18000"),
        ):
            tariff = factories.TariffFactory(zev=zev, category=TariffCategory.ENERGY, energy_type=energy_type)
            factories.TariffPeriodFactory(tariff=tariff, period_type=PeriodType.FLAT, price_chf_per_kwh=Decimal(price))

        prefill = build_prefill(zev)

        # No grid fees or levies here, so all-in retail == the energy price.
        assert prefill.retail_price_chf_per_kwh == Decimal("0.31000")
        assert prefill.feed_in_price_chf_per_kwh == Decimal("0.08000")
        assert prefill.internal_energy_price_chf_per_kwh == Decimal("0.18000")

    def test_retail_is_all_in_energy_plus_grid_fees_plus_levies(self):
        zev = factories.ZevFactory()
        grid_energy = factories.TariffFactory(
            zev=zev, category=TariffCategory.ENERGY, energy_type=EnergyType.GRID
        )
        factories.TariffPeriodFactory(tariff=grid_energy, price_chf_per_kwh=Decimal("0.30000"))
        # A flat per-kWh grid usage fee (Netznutzung), same energy type.
        grid_fee = factories.TariffFactory(
            zev=zev, category=TariffCategory.GRID_FEES, energy_type=EnergyType.GRID
        )
        factories.TariffPeriodFactory(tariff=grid_fee, price_chf_per_kwh=Decimal("0.10000"))
        # A levy priced as a percentage of the grid energy base (like the demo ZEV).
        levy = factories.TariffFactory(
            zev=zev,
            category=TariffCategory.LEVIES,
            energy_type=EnergyType.GRID,
            billing_mode=BillingMode.PERCENTAGE_OF_ENERGY,
        )
        factories.TariffPeriodFactory(
            tariff=levy, period_type=PeriodType.FLAT,
            price_chf_per_kwh=None, percentage=Decimal("20.00"),
        )

        prefill = build_prefill(zev)
        # base = 0.30 + 0.10 = 0.40; all-in = 0.40 * (1 + 20%) = 0.48000
        assert prefill.retail_price_chf_per_kwh == Decimal("0.48000")

    def test_internal_energy_stays_energy_only_ignoring_local_grid_fees(self):
        # A ZEV could still have a reduced grid-fee tariff configured for local
        # energy in the real invoicing system, but the vZEV feasibility model
        # prices local energy as energy only — so it must not be folded in.
        zev = factories.ZevFactory()
        local_energy = factories.TariffFactory(
            zev=zev, category=TariffCategory.ENERGY, energy_type=EnergyType.LOCAL
        )
        factories.TariffPeriodFactory(tariff=local_energy, price_chf_per_kwh=Decimal("0.18000"))
        local_grid_fee = factories.TariffFactory(
            zev=zev, category=TariffCategory.GRID_FEES, energy_type=EnergyType.LOCAL
        )
        factories.TariffPeriodFactory(tariff=local_grid_fee, price_chf_per_kwh=Decimal("0.05000"))

        prefill = build_prefill(zev)
        assert prefill.internal_energy_price_chf_per_kwh == Decimal("0.18000")

    def test_internal_price_resolved_from_a_percentage_of_grid_tariff(self):
        # A very common vZEV setup: local energy priced as a percentage of the
        # grid energy price ("local = 60% of Netzstrom"), not a flat rate.
        zev = factories.ZevFactory()
        grid_energy = factories.TariffFactory(
            zev=zev, category=TariffCategory.ENERGY, energy_type=EnergyType.GRID
        )
        factories.TariffPeriodFactory(tariff=grid_energy, price_chf_per_kwh=Decimal("0.30000"))
        local_pct = factories.TariffFactory(
            zev=zev,
            category=TariffCategory.ENERGY,
            energy_type=EnergyType.LOCAL,
            billing_mode=BillingMode.PERCENTAGE_OF_ENERGY,
        )
        factories.TariffPeriodFactory(
            tariff=local_pct, period_type=PeriodType.FLAT,
            price_chf_per_kwh=None, percentage=Decimal("60.00"),
        )

        prefill = build_prefill(zev)
        # 60% of the 0.30 grid energy base = 0.18000
        assert prefill.internal_energy_price_chf_per_kwh == Decimal("0.18000")

    def test_internal_price_none_when_percentage_has_no_grid_base(self):
        # A local percentage tariff with no grid energy tariff to anchor it
        # can't be resolved, so the internal price stays None (default kept).
        zev = factories.ZevFactory()
        local_pct = factories.TariffFactory(
            zev=zev,
            category=TariffCategory.ENERGY,
            energy_type=EnergyType.LOCAL,
            billing_mode=BillingMode.PERCENTAGE_OF_ENERGY,
        )
        factories.TariffPeriodFactory(
            tariff=local_pct, period_type=PeriodType.FLAT,
            price_chf_per_kwh=None, percentage=Decimal("60.00"),
        )

        prefill = build_prefill(zev)
        assert prefill.internal_energy_price_chf_per_kwh is None

    def test_retail_none_when_only_a_percentage_tariff_exists(self):
        # A percentage-of-energy tariff has nothing to anchor to without a flat
        # grid energy base, so retail can't be determined and stays None.
        zev = factories.ZevFactory()
        grid_pct = factories.TariffFactory(
            zev=zev,
            category=TariffCategory.ENERGY,
            energy_type=EnergyType.GRID,
            billing_mode=BillingMode.PERCENTAGE_OF_ENERGY,
        )
        factories.TariffPeriodFactory(
            tariff=grid_pct, period_type=PeriodType.FLAT,
            price_chf_per_kwh=None, percentage=Decimal("50.00"),
        )

        prefill = build_prefill(zev)
        assert prefill.retail_price_chf_per_kwh is None

    def test_none_when_no_matching_tariff_exists(self):
        zev = factories.ZevFactory()
        prefill = build_prefill(zev)
        assert prefill.retail_price_chf_per_kwh is None
        assert prefill.feed_in_price_chf_per_kwh is None
        assert prefill.internal_energy_price_chf_per_kwh is None

    def test_ignores_expired_tariffs(self):
        zev = factories.ZevFactory()
        expired = factories.TariffFactory(
            zev=zev,
            category=TariffCategory.ENERGY,
            energy_type=EnergyType.GRID,
            valid_from=date(2020, 1, 1),
            valid_to=date(2020, 12, 31),
        )
        factories.TariffPeriodFactory(tariff=expired, price_chf_per_kwh=Decimal("0.99000"))

        prefill = build_prefill(zev)
        assert prefill.retail_price_chf_per_kwh is None


class TestInclusiveVatTariffPrefill:
    """An inclusive-VAT ZEV bills its grid lines with VAT folded in (#1173)."""

    def _zev(self, vat_mode):
        clear_vat_rates()
        VatRate.objects.create(rate=Decimal("0.0810"), valid_from=date(2020, 1, 1))
        zev = factories.ZevFactory(vat_mode=vat_mode)
        grid = factories.TariffFactory(zev=zev, category=TariffCategory.ENERGY, energy_type=EnergyType.GRID)
        factories.TariffPeriodFactory(tariff=grid, price_chf_per_kwh=Decimal("0.20000"))
        factories.percentage_tariff(
            zev, category=TariffCategory.ENERGY, energy_type=EnergyType.LOCAL, percentage="65.00",
        )
        return zev

    def test_inclusive_zev_takes_the_percentage_of_the_grid_price_with_vat(self):
        prefill = build_prefill(self._zev(VatMode.INCLUSIVE))

        assert prefill.retail_price_chf_per_kwh == Decimal("0.21620")
        assert prefill.internal_energy_price_chf_per_kwh == Decimal("0.14053")

    @pytest.mark.parametrize("vat_mode", [VatMode.NOT_REGISTERED, VatMode.REGISTERED])
    def test_other_vat_modes_keep_the_price_without_vat(self, vat_mode):
        prefill = build_prefill(self._zev(vat_mode))

        assert prefill.retail_price_chf_per_kwh == Decimal("0.20000")
        assert prefill.internal_energy_price_chf_per_kwh == Decimal("0.13000")
