"""Tests for the best-effort ZEV -> feasibility calculator prefill."""
from datetime import date, datetime, timedelta, timezone as dt_timezone
from decimal import Decimal

import pytest

from metering.models import MeterReading, ReadingDirection
from tariffs.models import BillingMode, EnergyType, PeriodType, TariffCategory
from testing import factories
from zev.models import MeteringPointType

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
