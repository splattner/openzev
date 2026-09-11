"""``tariff_pricing``'s dynamic branch: the average shown on a printed
document for a tariff whose price has no single figure at all.

See the module docstring in ``tariff_pricing.py`` for why a printed document
needs a static number where the engine resolves a live one, and why the two
must not silently disagree.
"""

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

import pytest

from tariffs.dynamic.models import DynamicPricePoint, DynamicTariffSource
from tariffs.models import BillingMode, EnergyType, PeriodType, Tariff, TariffCategory, TariffPeriod
from testing import factories

from .tariff_pricing import (
    display_grid_base_chf_per_kwh,
    dynamic_average_chf_per_kwh,
    grid_base_is_dynamic,
    grid_base_is_multiband,
)

pytestmark = pytest.mark.django_db

UTC = timezone.utc


def make_source(**overrides) -> DynamicTariffSource:
    defaults = {
        "label": "Groupe E vario — grid", "url": "https://api.tariffs.groupe-e.ch/v2/tariffs",
        "api_version": "v1_0_5", "tariff_type": "grid", "tariff_name": "vario",
    }
    return DynamicTariffSource.objects.create(**{**defaults, **overrides})


def dynamic_tariff(zev, source, **overrides) -> Tariff:
    defaults = {
        "zev": zev, "name": "Grid (dynamic)", "category": TariffCategory.ENERGY,
        "billing_mode": BillingMode.ENERGY, "energy_type": EnergyType.GRID,
        "valid_from": date(2026, 1, 1), "dynamic_source": source,
    }
    return Tariff.objects.create(**{**defaults, **overrides})


def static_tariff(zev, **overrides) -> Tariff:
    defaults = {
        "zev": zev, "name": "Grid", "category": TariffCategory.ENERGY,
        "billing_mode": BillingMode.ENERGY, "energy_type": EnergyType.GRID,
        "valid_from": date(2026, 1, 1),
    }
    return Tariff.objects.create(**{**defaults, **overrides})


def store(source, valid_from: datetime, price: str, *, minutes=15):
    DynamicPricePoint.objects.create(
        source=source, valid_from=valid_from, valid_to=valid_from + timedelta(minutes=minutes),
        price_chf_per_kwh=Decimal(price),
    )


class TestDynamicAverageChfPerKwh:
    def test_none_when_nothing_has_been_fetched(self):
        zev = factories.ZevFactory()
        tariff = dynamic_tariff(zev, make_source())

        assert dynamic_average_chf_per_kwh(tariff) is None

    def test_the_mean_of_every_stored_point(self):
        zev = factories.ZevFactory()
        source = make_source()
        tariff = dynamic_tariff(zev, source)
        store(source, datetime(2026, 1, 1, 10, tzinfo=UTC), "0.10000")
        store(source, datetime(2026, 1, 1, 11, tzinfo=UTC), "0.20000")
        store(source, datetime(2026, 1, 1, 12, tzinfo=UTC), "0.30000")

        assert dynamic_average_chf_per_kwh(tariff) == Decimal("0.2")

    def test_negative_points_pull_the_average_down(self):
        zev = factories.ZevFactory()
        source = make_source()
        tariff = dynamic_tariff(zev, source)
        store(source, datetime(2026, 1, 1, 10, tzinfo=UTC), "0.10000")
        store(source, datetime(2026, 1, 1, 11, tzinfo=UTC), "-0.10000")

        assert dynamic_average_chf_per_kwh(tariff) == Decimal("0.0")


class TestDisplayGridBaseWithDynamicTariffs:
    def test_a_dynamic_tariff_with_no_data_contributes_nothing(self):
        zev = factories.ZevFactory()
        tariff = dynamic_tariff(zev, make_source())

        assert display_grid_base_chf_per_kwh([tariff]) == Decimal("0")

    def test_a_dynamic_tariff_contributes_its_average(self):
        zev = factories.ZevFactory()
        source = make_source()
        tariff = dynamic_tariff(zev, source)
        store(source, datetime(2026, 1, 1, 10, tzinfo=UTC), "0.30000")
        store(source, datetime(2026, 1, 1, 11, tzinfo=UTC), "0.10000")

        assert display_grid_base_chf_per_kwh([tariff]) == Decimal("0.2")

    def test_a_dynamic_and_a_static_grid_tariff_sum_together(self):
        # A community's grid sheet often has more than one active row — the
        # Arbeitspreis on a static tariff, Netznutzung gone dynamic.
        zev = factories.ZevFactory()
        static = static_tariff(zev, name="Arbeitspreis")
        TariffPeriod.objects.create(tariff=static, price_chf_per_kwh=Decimal("0.13600"))
        source = make_source()
        dynamic = dynamic_tariff(zev, source, name="Netznutzung")
        store(source, datetime(2026, 1, 1, 10, tzinfo=UTC), "0.10400")

        assert display_grid_base_chf_per_kwh([static, dynamic]) == Decimal("0.24000")


class TestGridBaseFlags:
    def test_a_dynamic_tariff_is_flagged_dynamic_not_multiband(self):
        # The two need different footnote text — see tariff_overview.py's
        # _price_row_for_percentage_tariff — so they must not be conflated.
        zev = factories.ZevFactory()
        tariff = dynamic_tariff(zev, make_source())

        assert grid_base_is_dynamic([tariff]) is True
        assert grid_base_is_multiband([tariff]) is False

    def test_a_single_band_static_tariff_is_neither(self):
        zev = factories.ZevFactory()
        tariff = static_tariff(zev)
        TariffPeriod.objects.create(tariff=tariff, price_chf_per_kwh=Decimal("0.20000"))

        assert grid_base_is_dynamic([tariff]) is False
        assert grid_base_is_multiband([tariff]) is False

    def test_a_multiband_static_tariff_is_flagged_multiband_not_dynamic(self):
        zev = factories.ZevFactory()
        tariff = static_tariff(zev)
        TariffPeriod.objects.create(
            tariff=tariff, period_type=PeriodType.HIGH, price_chf_per_kwh=Decimal("0.30000"),
            time_from=time(6, 0), time_to=time(22, 0),
        )
        TariffPeriod.objects.create(
            tariff=tariff, period_type=PeriodType.LOW, price_chf_per_kwh=Decimal("0.10000"),
            time_from=time(22, 0), time_to=time(23, 59, 59),
        )

        assert grid_base_is_multiband([tariff]) is True
        assert grid_base_is_dynamic([tariff]) is False
