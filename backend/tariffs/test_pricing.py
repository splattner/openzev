"""``tariffs.pricing``: which tariffs apply, at what price, with which VAT."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from accounts.models import VatRate
from tariffs.models import BillingMode, EnergyType, Tariff, TariffCategory
from tariffs.pricing import (
    DynamicSeries,
    bears_input_vat,
    daily_vat_rate,
    invoice_vat_rate,
    is_active,
    is_active_during,
    percentage_base,
    price_at,
    with_input_vat,
)
from testing import factories
from testing.helpers import clear_vat_rates

D = Decimal
UTC = timezone.utc


def _tariff(**fields) -> Tariff:
    return Tariff(valid_from=date(2026, 1, 1), **fields)


class TestActivity:
    def test_both_ends_are_inclusive(self):
        tariff = _tariff(valid_to=date(2026, 6, 30))
        assert not is_active(tariff, date(2025, 12, 31))
        assert is_active(tariff, date(2026, 1, 1))
        assert is_active(tariff, date(2026, 6, 30))
        assert not is_active(tariff, date(2026, 7, 1))

    def test_an_open_end_never_expires(self):
        assert is_active(_tariff(valid_to=None), date(2099, 12, 31))

    def test_a_range_counts_when_one_day_overlaps(self):
        tariff = _tariff(valid_to=date(2026, 6, 30))
        assert is_active_during(tariff, date(2025, 12, 1), date(2026, 1, 1))
        assert is_active_during(tariff, date(2026, 6, 30), date(2026, 7, 31))
        assert not is_active_during(tariff, date(2025, 1, 1), date(2025, 12, 31))
        assert not is_active_during(tariff, date(2026, 7, 1), date(2026, 7, 31))


@pytest.mark.django_db
class TestVatRate:
    @pytest.fixture(autouse=True)
    def rates(self):
        clear_vat_rates()
        return [
            VatRate.objects.create(rate=D("0.0770"), valid_from=date(2018, 1, 1), valid_to=date(2023, 12, 31)),
            VatRate.objects.create(rate=D("0.0810"), valid_from=date(2024, 1, 1)),
        ]

    def test_an_invoice_takes_the_rate_on_its_period_end(self):
        assert invoice_vat_rate(date(2023, 12, 31)) == D("0.0770")
        assert invoice_vat_rate(date(2024, 1, 1)) == D("0.0810")

    def test_the_daily_rate_steps_on_the_day_of_the_change(self, rates):
        assert daily_vat_rate(rates, date(2023, 12, 31)) == D("0.0770")
        assert daily_vat_rate(rates, date(2024, 1, 1)) == D("0.0810")

    def test_no_rate_in_force_is_zero(self, rates):
        assert invoice_vat_rate(date(2017, 12, 31)) == D("0")
        assert daily_vat_rate(rates, date(2017, 12, 31)) == D("0")


class TestInputVat:
    def test_grid_side_costs_bear_input_vat_and_own_energy_does_not(self):
        assert bears_input_vat(_tariff(category=TariffCategory.ENERGY, energy_type=EnergyType.GRID))
        for category in (TariffCategory.GRID_FEES, TariffCategory.LEVIES, TariffCategory.METERING):
            assert bears_input_vat(_tariff(category=category, energy_type=EnergyType.LOCAL)), category
        assert not bears_input_vat(_tariff(category=TariffCategory.ENERGY, energy_type=EnergyType.LOCAL))
        assert not bears_input_vat(_tariff(category=TariffCategory.ENERGY, energy_type=EnergyType.FEED_IN))

    def test_only_a_bearing_tariff_is_grossed(self):
        grid = _tariff(category=TariffCategory.GRID_FEES, energy_type=EnergyType.GRID)
        local = _tariff(category=TariffCategory.ENERGY, energy_type=EnergyType.LOCAL)
        assert with_input_vat(grid, D("0.10"), D("0.081")) == D("0.10810")
        assert with_input_vat(local, D("0.10"), D("0.081")) == D("0.10")

    def test_a_bearing_percentage_tariff_takes_the_net_base_and_others_the_gross(self):
        levy = _tariff(category=TariffCategory.LEVIES, energy_type=EnergyType.LOCAL,
                       billing_mode=BillingMode.PERCENTAGE_OF_ENERGY)
        local = _tariff(category=TariffCategory.ENERGY, energy_type=EnergyType.LOCAL,
                        billing_mode=BillingMode.PERCENTAGE_OF_ENERGY)
        assert percentage_base(levy, D("0.30"), D("0.3243")) == D("0.30")
        assert percentage_base(local, D("0.30"), D("0.3243")) == D("0.3243")


class TestPriceAt:
    START = datetime(2026, 1, 1, tzinfo=UTC)

    def _series(self, *prices):
        step = timedelta(minutes=15)
        return DynamicSeries([
            (self.START + step * index, self.START + step * (index + 1), D(price))
            for index, price in enumerate(prices)
        ])

    def test_a_dynamic_price_is_raised_to_the_floor(self):
        feed_in = _tariff(dynamic_source_id=1, minimum_price_chf_per_kwh=D("0.05000"))
        series = self._series("0.08000", "0.02000", "-0.01000")
        assert price_at(feed_in, self.START, series=series) == (D("0.08000"), None)
        assert price_at(feed_in, self.START + timedelta(minutes=15), series=series) == (D("0.05000"), None)
        assert price_at(feed_in, self.START + timedelta(minutes=30), series=series) == (D("0.05000"), None)

    def test_without_a_floor_a_negative_price_stands(self):
        grid = _tariff(dynamic_source_id=1)
        assert price_at(grid, self.START, series=self._series("-0.01000")) == (D("-0.01000"), None)

    def test_a_gap_in_the_series_is_none(self):
        grid = _tariff(dynamic_source_id=1, minimum_price_chf_per_kwh=D("0.05000"))
        series = self._series("0.08000")
        assert price_at(grid, self.START - timedelta(minutes=1), series=series) == (None, None)
        assert price_at(grid, self.START + timedelta(minutes=15), series=series) == (None, None)

    def test_a_dynamic_tariff_needs_its_series(self):
        with pytest.raises(ValueError):
            price_at(_tariff(dynamic_source_id=1), self.START)

    @pytest.mark.django_db
    def test_a_static_tariff_is_priced_by_its_band(self):
        tariff = factories.TariffFactory()
        band = factories.TariffPeriodFactory(tariff=tariff, price_chf_per_kwh=D("0.21000"))
        assert price_at(tariff, self.START) == (D("0.21000"), band)

    @pytest.mark.django_db
    def test_a_static_tariff_without_a_band_bills_zero(self):
        assert price_at(factories.TariffFactory(), self.START) == (D("0"), None)

    @pytest.mark.django_db
    def test_a_band_passed_as_none_is_not_resolved_again(self):
        tariff = factories.TariffFactory()
        factories.TariffPeriodFactory(tariff=tariff, price_chf_per_kwh=D("0.21000"))
        assert price_at(tariff, self.START, band=None) == (D("0"), None)
