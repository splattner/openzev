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
from tariffs.dynamic.pricing import summarize_dynamic_tariff, summarize_requests
from tariffs.serializers import TariffSerializer
from tariffs.models import BillingMode, EnergyType, PeriodType, Tariff, TariffCategory, TariffPeriod
from testing import factories

from .tariff_pricing import (
    display_grid_base_summary,
    grid_base_is_multiband,
    prepare_tariff_display_summaries,
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

        assert summarize_dynamic_tariff(tariff, as_of=date(2026, 1, 1)).average_chf_per_kwh is None

    def test_the_average_is_weighted_by_interval_duration(self):
        zev = factories.ZevFactory()
        source = make_source()
        tariff = dynamic_tariff(zev, source)
        store(source, datetime(2026, 1, 1, 10, tzinfo=UTC), "0.10000", minutes=15)
        store(source, datetime(2026, 1, 1, 11, tzinfo=UTC), "0.30000", minutes=45)

        assert summarize_dynamic_tariff(
            tariff, as_of=date(2026, 1, 1)
        ).average_chf_per_kwh == Decimal("0.25000")

    def test_negative_points_pull_the_average_down(self):
        zev = factories.ZevFactory()
        source = make_source()
        tariff = dynamic_tariff(zev, source)
        store(source, datetime(2026, 1, 1, 10, tzinfo=UTC), "0.10000")
        store(source, datetime(2026, 1, 1, 11, tzinfo=UTC), "-0.10000")

        assert summarize_dynamic_tariff(
            tariff, as_of=date(2026, 1, 1)
        ).average_chf_per_kwh == Decimal("0.00000")

    def test_points_older_than_the_display_window_do_not_affect_the_average(self):
        zev = factories.ZevFactory()
        source = make_source()
        tariff = dynamic_tariff(zev, source)
        store(source, datetime(2026, 1, 1, 10, tzinfo=UTC), "9.00000")
        store(source, datetime(2026, 2, 1, 10, tzinfo=UTC), "0.20000")

        assert summarize_dynamic_tariff(
            tariff, as_of=date(2026, 2, 1)
        ).average_chf_per_kwh == Decimal("0.20000")

    def test_summary_distinguishes_complete_partial_and_unavailable(self):
        zev = factories.ZevFactory()
        source = make_source()
        tariff = dynamic_tariff(zev, source)
        assert summarize_dynamic_tariff(
            tariff, as_of=date(2026, 1, 1), days=1
        ).status == "unavailable"

        store(source, datetime(2026, 1, 1, 0, tzinfo=UTC), "0.20000", minutes=60)
        assert summarize_dynamic_tariff(
            tariff, as_of=date(2026, 1, 1), days=1
        ).status == "partial"

        source.points.all().delete()
        store(source, datetime(2026, 1, 1, 0, tzinfo=UTC), "0.20000", minutes=24 * 60)
        assert summarize_dynamic_tariff(
            tariff, as_of=date(2026, 1, 1), days=1
        ).status == "complete"


class TestDisplayGridBaseWithDynamicTariffs:
    @pytest.mark.parametrize("types,expected", [
        (["band", "low", "high", "flat"], "0.4"),
        (["band", "low", "high"], "0.3"),
        (["band", "low"], "0.2"),
        (["band"], "0.1"),
    ])
    def test_static_fallback_is_flat_then_ht_then_nt_then_band(self, types, expected):
        tariff = static_tariff(factories.ZevFactory())
        for index, kind in enumerate(types, start=1):
            TariffPeriod.objects.create(tariff=tariff, period_type=kind, price_chf_per_kwh=Decimal(index) / 10)
        assert display_grid_base_summary([tariff]).price_chf_per_kwh == Decimal(expected)

    @pytest.mark.parametrize("reverse", [False, True])
    def test_unavailable_wins_over_partial_in_either_order(self, reverse):
        zev = factories.ZevFactory()
        partial = dynamic_tariff(zev, make_source(), name="Partial")
        missing = dynamic_tariff(zev, make_source(tariff_name="missing"), name="Missing")
        store(partial.dynamic_source, datetime(2026, 1, 1, tzinfo=UTC), "0.1")
        components = [partial, missing] if reverse else [missing, partial]
        base = display_grid_base_summary(components, as_of=date(2026, 1, 1))
        assert base.price_chf_per_kwh is None
        assert base.dynamic_status == "unavailable"

    def test_percentage_bases_share_one_source_query_but_not_a_reference_date(self, django_assert_num_queries):
        zev = factories.ZevFactory()
        source = make_source()
        grid = dynamic_tariff(zev, source)
        past = static_tariff(zev, name="Local", energy_type="local", billing_mode="percentage_of_energy",
                             percentage=50, valid_to=date(2026, 6, 30))
        current = static_tariff(zev, name="Local", energy_type="local", billing_mode="percentage_of_energy",
                                percentage=50, valid_from=date(2026, 7, 1))
        store(source, datetime(2026, 6, 30, tzinfo=UTC), "0.1")
        store(source, datetime(2026, 9, 12, tzinfo=UTC), "0.9")
        tariffs = list(zev.tariffs.prefetch_related("periods"))
        with django_assert_num_queries(1):
            prepare_tariff_display_summaries(tariffs, as_of=date(2026, 9, 12))
            payload = {row["id"]: row for row in TariffSerializer(tariffs, many=True).data}
        assert payload[str(past.pk)]["percentage_base_summary"] == {
            "price_chf_per_kwh": "0.10000", "dynamic_status": "partial", "reference_date": "2026-06-30",
        }
        assert payload[str(current.pk)]["percentage_base_summary"]["price_chf_per_kwh"] == "0.90000"
        assert payload[str(grid.pk)]["dynamic_price_summary"]["average_chf_per_kwh"] == "0.90000"

    def test_batch_summaries_are_keyed_by_persistent_tariff_id(self, django_assert_num_queries):
        zev = factories.ZevFactory()
        source = make_source()
        old = dynamic_tariff(zev, source, valid_to=date(2026, 1, 31))
        current = dynamic_tariff(zev, source, valid_from=date(2026, 9, 1))
        store(source, datetime(2026, 1, 31, tzinfo=UTC), "0.1")
        store(source, datetime(2026, 5, 1, tzinfo=UTC), "9.0")
        store(source, datetime(2026, 9, 12, tzinfo=UTC), "0.3")
        with django_assert_num_queries(1):
            summaries = summarize_requests({
                tariff.pk: (tariff, date(2026, 9, 12)) for tariff in [old, current]
            })
        assert summaries[Tariff.objects.get(pk=old.pk).pk].average_chf_per_kwh == Decimal("0.1")
        assert summaries[current.pk].average_chf_per_kwh == Decimal("0.3")

    def test_a_dynamic_tariff_with_no_data_makes_the_base_unavailable(self):
        zev = factories.ZevFactory()
        tariff = dynamic_tariff(zev, make_source())

        assert display_grid_base_summary(
            [tariff], as_of=date(2026, 1, 1)
        ).price_chf_per_kwh is None

    def test_a_dynamic_tariff_contributes_its_average(self):
        zev = factories.ZevFactory()
        source = make_source()
        tariff = dynamic_tariff(zev, source)
        store(source, datetime(2026, 1, 1, 10, tzinfo=UTC), "0.30000")
        store(source, datetime(2026, 1, 1, 11, tzinfo=UTC), "0.10000")

        assert display_grid_base_summary(
            [tariff], as_of=date(2026, 1, 1)
        ).price_chf_per_kwh == Decimal("0.20000")

    def test_a_dynamic_and_a_static_grid_tariff_sum_together(self):
        # A community's grid sheet often has more than one active row — the
        # Arbeitspreis on a static tariff, Netznutzung gone dynamic.
        zev = factories.ZevFactory()
        static = static_tariff(zev, name="Arbeitspreis")
        TariffPeriod.objects.create(tariff=static, price_chf_per_kwh=Decimal("0.13600"))
        source = make_source()
        dynamic = dynamic_tariff(zev, source, name="Netznutzung")
        store(source, datetime(2026, 1, 1, 10, tzinfo=UTC), "0.10400")

        assert display_grid_base_summary(
            [static, dynamic], as_of=date(2026, 1, 1)
        ).price_chf_per_kwh == Decimal("0.24000")


class TestGridBaseFlags:
    def test_a_dynamic_tariff_is_flagged_dynamic_not_multiband(self):
        # The two need different footnote text — see tariff_overview.py's
        # _price_row_for_percentage_tariff — so they must not be conflated.
        zev = factories.ZevFactory()
        tariff = dynamic_tariff(zev, make_source())

        assert grid_base_is_multiband([tariff]) is False

    def test_a_single_band_static_tariff_is_neither(self):
        zev = factories.ZevFactory()
        tariff = static_tariff(zev)
        TariffPeriod.objects.create(tariff=tariff, price_chf_per_kwh=Decimal("0.20000"))

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
