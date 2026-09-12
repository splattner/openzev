"""Linking a tariff to a price series.

A dynamic tariff is an ordinary energy tariff that happens to get its price from
a fetched series rather than from bands. These cover the constraints that keeps
that honest: the series bills per kWh, it bills one specific component, and the
points behind an issued invoice cannot be deleted out from under it.
"""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db.models import ProtectedError

from testing import factories

from tariffs.dynamic.models import DynamicPricePoint, DynamicTariffSource
from tariffs.models import BillingMode, EnergyType, Tariff, TariffCategory, TariffPeriod

pytestmark = pytest.mark.django_db

UTC = timezone.utc


def make_source(**overrides) -> DynamicTariffSource:
    defaults = {
        "label": "Groupe E vario — grid",
        "url": "https://api.tariffs.groupe-e.ch/v2/tariffs",
        "api_version": "v1_0_5",
        "tariff_type": "grid",
        "tariff_name": "vario",
    }
    return DynamicTariffSource.objects.create(**{**defaults, **overrides})


def make_tariff(zev, source, **overrides) -> Tariff:
    defaults = {
        "zev": zev,
        "name": "Grid usage (dynamic)",
        "category": TariffCategory.GRID_FEES,
        "billing_mode": BillingMode.ENERGY,
        "energy_type": EnergyType.GRID,
        "valid_from": date(2026, 1, 1),
        "dynamic_source": source,
    }
    return Tariff.objects.create(**{**defaults, **overrides})


class TestValidation:
    def test_a_dynamic_grid_tariff_is_accepted(self):
        zev = factories.ZevFactory()
        tariff = make_tariff(zev, make_source())

        assert tariff.dynamic_source is not None
        assert list(tariff.periods.all()) == []

    def test_a_series_cannot_price_a_tariff_that_is_not_billed_per_kwh(self):
        # The series carries CHF/kWh and nothing else, so a monthly fee has
        # nothing to read from it.
        zev = factories.ZevFactory()

        with pytest.raises(ValidationError) as caught:
            make_tariff(
                zev, make_source(), billing_mode=BillingMode.MONTHLY_FEE,
                energy_type=None, fixed_price_chf=Decimal("5.00"),
            )

        assert "dynamic_source" in caught.value.message_dict

    def test_a_feed_in_series_cannot_price_grid_consumption(self):
        # Getting this backwards would credit a consumer or bill a producer.
        zev = factories.ZevFactory()
        source = make_source(tariff_type="feed_in", tariff_name="", label="BKW feed-in",
                             url="https://prices.example.test/current", api_version="v1_0_5",
                             request_mode="exact_url", supports_range=False)

        with pytest.raises(ValidationError) as caught:
            make_tariff(zev, source, energy_type=EnergyType.GRID)

        assert "energy_type" in caught.value.message_dict

    def test_a_feed_in_series_prices_a_feed_in_tariff(self):
        zev = factories.ZevFactory()
        source = make_source(tariff_type="feed_in", tariff_name="", label="BKW feed-in",
                             url="https://prices.example.test/current", api_version="v1_0_5",
                             request_mode="exact_url", supports_range=False)

        tariff = make_tariff(
            zev, source, name="Feed-in (dynamic)",
            category=TariffCategory.ENERGY, energy_type=EnergyType.FEED_IN,
        )

        assert tariff.energy_type == EnergyType.FEED_IN

    def test_an_electricity_series_prices_grid_energy(self):
        # The DSO's supply is *grid* energy from the community's point of view:
        # it is bought through the connection, not produced on the roof.
        zev = factories.ZevFactory()
        source = make_source(tariff_type="electricity", label="Supply")

        tariff = make_tariff(
            zev, source, name="Supply (dynamic)",
            category=TariffCategory.ENERGY, energy_type=EnergyType.GRID,
        )

        assert tariff.energy_type == EnergyType.GRID

    def test_a_dynamic_series_cannot_price_local_solar(self):
        zev = factories.ZevFactory()

        with pytest.raises(ValidationError):
            make_tariff(zev, make_source(), energy_type=EnergyType.LOCAL)


class TestSeriesVersioning:
    def test_a_tariff_series_may_go_static_then_dynamic_across_versions(self):
        # Exactly what happens when an operator switches to dynamic pricing on
        # 1 January. Because the link is a field rather than one of the series
        # fields, the two versions stay one series instead of forking.
        zev = factories.ZevFactory()
        static = Tariff.objects.create(
            zev=zev, name="Grid usage", category=TariffCategory.GRID_FEES,
            billing_mode=BillingMode.ENERGY, energy_type=EnergyType.GRID,
            valid_from=date(2026, 1, 1), valid_to=date(2026, 12, 31),
        )

        dynamic = make_tariff(zev, make_source(), name="Grid usage", valid_from=date(2027, 1, 1))

        assert static.name == dynamic.name
        assert Tariff.objects.filter(zev=zev, name="Grid usage").count() == 2


class TestDynamicPeriods:
    def test_the_model_refuses_price_bands_on_a_dynamic_tariff(self):
        zev = factories.ZevFactory()
        tariff = make_tariff(zev, make_source())
        period = TariffPeriod(tariff=tariff, period_type="flat", price_chf_per_kwh="0.99")

        with pytest.raises(ValidationError):
            period.full_clean(exclude=["tariff"])

    def test_price_bands_are_rejected_on_a_dynamic_tariff(self):
        from tariffs.serializers import TariffPeriodSerializer

        zev = factories.ZevFactory()
        tariff = make_tariff(zev, make_source())
        serializer = TariffPeriodSerializer(
            data={"tariff": str(tariff.pk), "period_type": "flat", "price_chf_per_kwh": "0.99"}
        )
        assert not serializer.is_valid()

    def test_source_capabilities_cannot_claim_ranges_for_an_exact_url(self):
        with pytest.raises(ValidationError) as caught:
            make_source(request_mode="exact_url", supports_range=True)

        assert "supports_range" in caught.value.message_dict


class TestRetention:
    def test_api_version_is_part_of_source_identity(self):
        v1 = make_source(api_version="v1_0_5")
        v2 = make_source(api_version="v2_0_0")
        assert v1.pk != v2.pk
        v1.api_version = "v2_0_0"
        with pytest.raises(ValidationError, match="immutable"):
            v1.save()

    def test_a_source_still_referenced_by_a_tariff_cannot_be_deleted(self):
        # The points behind an issued invoice are its audit trail, and neither
        # operator can re-supply them: Groupe E drops history after ~9 months
        # and BKW keeps none at all.
        zev = factories.ZevFactory()
        source = make_source()
        make_tariff(zev, source)

        with pytest.raises(ProtectedError):
            source.delete()

    def test_points_are_reachable_for_as_long_as_the_source_is(self):
        source = make_source()
        start = datetime(2026, 3, 1, 10, tzinfo=UTC)
        DynamicPricePoint.objects.create(
            source=source, valid_from=start, valid_to=start + timedelta(minutes=15),
            price_chf_per_kwh=Decimal("-0.05430"),
        )

        stored = DynamicPricePoint.objects.get(source=source, valid_from=start)
        assert stored.price_chf_per_kwh == Decimal("-0.05430")
