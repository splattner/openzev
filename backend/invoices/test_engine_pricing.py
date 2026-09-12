"""Tests for HT/NT (peak/off-peak) and weekday-aware tariff pricing.

The existing ``test_engine.py`` only exercises ``PeriodType.FLAT``. This module
covers ``_resolve_tariff_band`` directly (the time-of-day / weekday matching logic)
and an end-to-end ``generate_invoice`` run that splits consumption across a
high-tariff and low-tariff window.
"""

from datetime import date, datetime, time, timezone
from decimal import Decimal

import pytest

from metering.models import MeterReading, ReadingDirection
from tariffs.models import (
    BillingMode,
    EnergyType,
    PeriodType,
    Tariff,
    TariffCategory,
    TariffPeriod,
)
from testing import factories

from .engine import _resolve_tariff_band, generate_invoice

pytestmark = pytest.mark.django_db


def _ht_nt_tariff(zev, *, energy_type=EnergyType.GRID, category=TariffCategory.ENERGY):
    """Create a GRID tariff with an HT window (06:00-22:00) and NT window (rest)."""
    tariff = Tariff.objects.create(
        zev=zev,
        name="HT/NT tariff",
        category=category,
        billing_mode=BillingMode.ENERGY,
        energy_type=energy_type,
        valid_from=date(2026, 1, 1),
    )
    TariffPeriod.objects.create(
        tariff=tariff,
        period_type=PeriodType.HIGH,
        price_chf_per_kwh=Decimal("0.30000"),
        time_from=time(6, 0),
        time_to=time(22, 0),
    )
    TariffPeriod.objects.create(
        tariff=tariff,
        period_type=PeriodType.LOW,
        price_chf_per_kwh=Decimal("0.10000"),
        time_from=time(22, 0),
        time_to=time(23, 59, 59),
    )
    return tariff


# ---------------------------------------------------------------------------
# _resolve_tariff_band — unit-level
# ---------------------------------------------------------------------------


def _resolved_price(tariff, ts):
    period = _resolve_tariff_band(tariff, ts)
    return period.price_chf_per_kwh if period is not None else None

class TestGetTariffPriceHtNt:
    def test_high_tariff_window_returns_ht_price(self):
        zev = factories.ZevFactory()
        tariff = _ht_nt_tariff(zev)
        # 2026-01-05 is a Monday, 10:00 → inside 06:00-22:00 HT window.
        ts = datetime(2026, 1, 5, 10, 0, tzinfo=timezone.utc)
        assert _resolved_price(tariff, ts) == Decimal("0.30000")

    def test_low_tariff_window_returns_nt_price(self):
        zev = factories.ZevFactory()
        tariff = _ht_nt_tariff(zev)
        # 22:30 → inside the NT window.
        ts = datetime(2026, 1, 5, 22, 30, tzinfo=timezone.utc)
        assert _resolved_price(tariff, ts) == Decimal("0.10000")

    def test_boundary_is_exclusive_on_time_to(self):
        zev = factories.ZevFactory()
        tariff = _ht_nt_tariff(zev)
        # Exactly 22:00 is NOT in HT (time_to is exclusive); it falls into NT.
        ts = datetime(2026, 1, 5, 22, 0, tzinfo=timezone.utc)
        assert _resolved_price(tariff, ts) == Decimal("0.10000")
        # Exactly 06:00 IS in HT (time_from is inclusive).
        ts_start = datetime(2026, 1, 5, 6, 0, tzinfo=timezone.utc)
        assert _resolved_price(tariff, ts_start) == Decimal("0.30000")

    def test_weekday_restriction_excludes_weekend(self):
        zev = factories.ZevFactory()
        tariff = Tariff.objects.create(
            zev=zev,
            name="Weekday HT",
            category=TariffCategory.ENERGY,
            billing_mode=BillingMode.ENERGY,
            energy_type=EnergyType.GRID,
            valid_from=date(2026, 1, 1),
        )
        # HT only on Mon-Fri (0-4); falls back to NT/first period otherwise.
        TariffPeriod.objects.create(
            tariff=tariff,
            period_type=PeriodType.HIGH,
            price_chf_per_kwh=Decimal("0.40000"),
            time_from=time(0, 0),
            time_to=time(23, 59, 59),
            weekdays="0,1,2,3,4",
        )
        TariffPeriod.objects.create(
            tariff=tariff,
            period_type=PeriodType.LOW,
            price_chf_per_kwh=Decimal("0.12000"),
            time_from=time(0, 0),
            time_to=time(23, 59, 59),
            weekdays="5,6",
        )
        # 2026-01-05 Monday → weekday HT applies.
        monday = datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)
        assert _resolved_price(tariff, monday) == Decimal("0.40000")
        # 2026-01-10 Saturday → weekend NT applies.
        saturday = datetime(2026, 1, 10, 12, 0, tzinfo=timezone.utc)
        assert _resolved_price(tariff, saturday) == Decimal("0.12000")

    def test_no_periods_returns_none(self):
        zev = factories.ZevFactory()
        tariff = Tariff.objects.create(
            zev=zev,
            name="Empty",
            category=TariffCategory.ENERGY,
            billing_mode=BillingMode.ENERGY,
            energy_type=EnergyType.GRID,
            valid_from=date(2026, 1, 1),
        )
        ts = datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)
        assert _resolved_price(tariff, ts) is None

    def test_falls_back_to_first_period_when_no_window_matches(self):
        zev = factories.ZevFactory()
        tariff = Tariff.objects.create(
            zev=zev,
            name="Gappy",
            category=TariffCategory.ENERGY,
            billing_mode=BillingMode.ENERGY,
            energy_type=EnergyType.GRID,
            valid_from=date(2026, 1, 1),
        )
        # Single narrow window 06:00-07:00; anything else falls back to it.
        TariffPeriod.objects.create(
            tariff=tariff,
            period_type=PeriodType.HIGH,
            price_chf_per_kwh=Decimal("0.50000"),
            time_from=time(6, 0),
            time_to=time(7, 0),
        )
        ts = datetime(2026, 1, 5, 18, 0, tzinfo=timezone.utc)  # outside the window
        assert _resolved_price(tariff, ts) == Decimal("0.50000")

    def test_flat_period_short_circuits(self):
        zev = factories.ZevFactory()
        tariff = factories.flat_tariff(zev, energy_type=EnergyType.GRID, price="0.22000")
        ts = datetime(2026, 1, 5, 3, 0, tzinfo=timezone.utc)
        assert _resolved_price(tariff, ts) == Decimal("0.22000")


# ---------------------------------------------------------------------------
# generate_invoice — HT/NT integration
# ---------------------------------------------------------------------------

class TestHtNtInvoiceGeneration:
    def test_grid_consumption_priced_by_time_of_day(self):
        """Consumption in the HT window costs more than the same kWh in NT."""
        participant = factories.ParticipantFactory(valid_from=date(2026, 1, 1))
        zev = participant.zev

        consumption_mp = factories.MeteringPointFactory(zev=zev)
        factories.MeteringPointAssignmentFactory(
            metering_point=consumption_mp,
            participant=participant,
            valid_from=date(2026, 1, 1),
        )

        # GRID energy tariff with HT/NT split (no local production → all grid).
        _ht_nt_tariff(zev, energy_type=EnergyType.GRID)

        # 10 kWh at 10:00 (HT @ 0.30) and 10 kWh at 23:00 (NT @ 0.10).
        MeterReading.objects.create(
            metering_point=consumption_mp,
            timestamp=datetime(2026, 1, 15, 10, 0, tzinfo=timezone.utc),
            energy_kwh=Decimal("10.0"),
            direction=ReadingDirection.IN,
        )
        MeterReading.objects.create(
            metering_point=consumption_mp,
            timestamp=datetime(2026, 1, 15, 23, 0, tzinfo=timezone.utc),
            energy_kwh=Decimal("10.0"),
            direction=ReadingDirection.IN,
        )

        invoice = generate_invoice(participant, date(2026, 1, 1), date(2026, 1, 31))

        # 20 kWh of grid energy total.
        assert invoice.total_grid_kwh == Decimal("20.0000")
        # 10 * 0.30 + 10 * 0.10 = 3.00 + 1.00 = 4.00 CHF.
        assert invoice.subtotal_chf == Decimal("4.00")
