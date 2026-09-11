"""Pricing an energy tariff from a fetched dynamic series.

Three layers: ``_DynamicSeries`` (a bisectable view over stored points, no
Django test client involved), ``TariffResolver.price_at`` (the one funnel
every engine call site reads from, static or dynamic), and an end-to-end
``generate_invoice`` run — the same integration shape
``test_engine_pricing.py`` uses for HT/NT, but with a fetched series standing
in for the bands.

The one behaviour worth stating up front: a static tariff with no matching
band bills zero, silently — that is existing, unrelated behaviour and stays.
A *dynamic* tariff with no price for a reading raises instead. The two must
never be confused, because "no price" means something different for each:
for a static tariff it is normal (an operator's bands need not cover every
hour); for a dynamic one it means the fetched series has a hole.
"""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from metering.models import MeterReading, ReadingDirection
from tariffs.dynamic.models import DynamicPricePoint, DynamicTariffSource
from tariffs.models import BillingMode, EnergyType, Tariff, TariffCategory
from testing import factories

from .engine import (
    DynamicPriceGapError,
    InvoiceGenerationContext,
    TariffResolver,
    _DynamicSeries,
    generate_invoice,
)

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


def store(source, valid_from, price, *, minutes=15):
    DynamicPricePoint.objects.create(
        source=source, valid_from=valid_from, valid_to=valid_from + timedelta(minutes=minutes),
        price_chf_per_kwh=Decimal(price),
    )


def dynamic_tariff(zev, source, **overrides) -> Tariff:
    defaults = {
        "zev": zev, "name": "Grid usage (dynamic)", "category": TariffCategory.GRID_FEES,
        "billing_mode": BillingMode.ENERGY, "energy_type": EnergyType.GRID,
        "valid_from": date(2026, 1, 1), "dynamic_source": source,
    }
    return Tariff.objects.create(**{**defaults, **overrides})


# ---------------------------------------------------------------------------
# _DynamicSeries
# ---------------------------------------------------------------------------

class TestDynamicSeries:
    def test_a_timestamp_inside_an_interval_resolves_to_its_price(self):
        source = make_source()
        store(source, datetime(2026, 2, 1, 10, tzinfo=UTC), "0.11300")

        series = _DynamicSeries.load(source.pk)

        assert series.price_at(datetime(2026, 2, 1, 10, 0, tzinfo=UTC)) == Decimal("0.11300")
        assert series.price_at(datetime(2026, 2, 1, 10, 14, tzinfo=UTC)) == Decimal("0.11300")

    def test_the_interval_end_is_exclusive(self):
        source = make_source()
        store(source, datetime(2026, 2, 1, 10, tzinfo=UTC), "0.11300")
        store(source, datetime(2026, 2, 1, 10, 15, tzinfo=UTC), "0.22200")

        series = _DynamicSeries.load(source.pk)

        assert series.price_at(datetime(2026, 2, 1, 10, 15, tzinfo=UTC)) == Decimal("0.22200")

    def test_a_gap_resolves_to_none(self):
        source = make_source()
        store(source, datetime(2026, 2, 1, 10, tzinfo=UTC), "0.1")
        store(source, datetime(2026, 2, 1, 12, tzinfo=UTC), "0.1")

        series = _DynamicSeries.load(source.pk)

        assert series.price_at(datetime(2026, 2, 1, 11, tzinfo=UTC)) is None

    def test_before_the_first_point_or_after_the_last_resolves_to_none(self):
        source = make_source()
        store(source, datetime(2026, 2, 1, 10, tzinfo=UTC), "0.1")

        series = _DynamicSeries.load(source.pk)

        assert series.price_at(datetime(2026, 2, 1, 9, tzinfo=UTC)) is None
        assert series.price_at(datetime(2026, 2, 1, 11, tzinfo=UTC)) is None

    def test_an_empty_series_resolves_everything_to_none(self):
        source = make_source()

        series = _DynamicSeries.load(source.pk)

        assert series.price_at(datetime(2026, 2, 1, 10, tzinfo=UTC)) is None

    def test_a_negative_price_resolves_correctly(self):
        # 22 of 96 intervals were negative on the Groupe E day recorded in
        # testdata — this is the mechanism, not an edge case.
        source = make_source()
        store(source, datetime(2026, 2, 1, 12, tzinfo=UTC), "-0.05430")

        series = _DynamicSeries.load(source.pk)

        assert series.price_at(datetime(2026, 2, 1, 12, 0, tzinfo=UTC)) == Decimal("-0.05430")


# ---------------------------------------------------------------------------
# TariffResolver.price_at
# ---------------------------------------------------------------------------

class TestPriceAt:
    def _context(self, zev):
        return InvoiceGenerationContext.build(zev, date(2026, 1, 1), date(2026, 1, 31))

    def test_a_static_tariff_resolves_as_before_and_reports_its_band(self):
        zev = factories.ZevFactory()
        tariff = factories.flat_tariff(zev, energy_type=EnergyType.GRID, price="0.20000")
        resolver = TariffResolver([tariff], self._context(zev))

        price, period = resolver.price_at(tariff, datetime(2026, 1, 5, 10, tzinfo=UTC))

        assert price == Decimal("0.20000")
        assert period is not None

    def test_a_static_tariff_with_no_bands_bills_zero_without_raising(self):
        # Unrelated, existing behaviour — must survive the dynamic branch
        # being added beside it.
        zev = factories.ZevFactory()
        tariff = factories.TariffFactory(
            zev=zev, category=TariffCategory.ENERGY, billing_mode=BillingMode.ENERGY,
            energy_type=EnergyType.GRID, valid_from=date(2026, 1, 1),
        )
        resolver = TariffResolver([tariff], self._context(zev))

        price, period = resolver.price_at(tariff, datetime(2026, 1, 5, 10, tzinfo=UTC))

        assert price == Decimal("0")
        assert period is None

    def test_a_dynamic_tariff_resolves_from_its_series_and_reports_no_band(self):
        zev = factories.ZevFactory()
        source = make_source()
        store(source, datetime(2026, 1, 5, 10, tzinfo=UTC), "-0.05430")
        tariff = dynamic_tariff(zev, source)
        resolver = TariffResolver([tariff], self._context(zev))

        price, period = resolver.price_at(tariff, datetime(2026, 1, 5, 10, tzinfo=UTC))

        assert price == Decimal("-0.05430")
        assert period is None

    def test_a_dynamic_tariff_with_a_gap_raises_instead_of_billing_zero(self):
        zev = factories.ZevFactory()
        source = make_source()
        # Nothing stored at all: the series is empty.
        tariff = dynamic_tariff(zev, source)
        resolver = TariffResolver([tariff], self._context(zev))

        with pytest.raises(DynamicPriceGapError) as caught:
            resolver.price_at(tariff, datetime(2026, 1, 5, 10, tzinfo=UTC))

        assert tariff.name in str(caught.value)
        assert "2026-01-05T10:00:00" in str(caught.value)

    def test_the_series_is_loaded_once_per_context_not_per_lookup(self):
        # The point of caching on InvoiceGenerationContext: a batch shares one
        # context across every participant in the ZEV-period.
        zev = factories.ZevFactory()
        source = make_source()
        store(source, datetime(2026, 1, 5, 10, tzinfo=UTC), "0.1")
        tariff = dynamic_tariff(zev, source)
        context = self._context(zev)
        resolver = TariffResolver([tariff], context)

        resolver.price_at(tariff, datetime(2026, 1, 5, 10, tzinfo=UTC))
        first = context.dynamic_series(source.pk)
        resolver.price_at(tariff, datetime(2026, 1, 5, 10, 5, tzinfo=UTC))
        second = context.dynamic_series(source.pk)

        assert first is second

    def test_pricing_a_dynamic_tariff_without_a_context_is_refused_clearly(self):
        zev = factories.ZevFactory()
        tariff = dynamic_tariff(zev, make_source())
        resolver = TariffResolver([tariff])  # no generation_context

        with pytest.raises(ValueError, match="generation_context"):
            resolver.price_at(tariff, datetime(2026, 1, 5, 10, tzinfo=UTC))


# ---------------------------------------------------------------------------
# generate_invoice — end-to-end
# ---------------------------------------------------------------------------

class TestDynamicInvoiceGeneration:
    def _billed_participant(self, source_prices):
        """A participant with one grid consumption reading per price given."""
        participant = factories.ParticipantFactory(valid_from=date(2026, 1, 1))
        zev = participant.zev
        mp = factories.MeteringPointFactory(zev=zev)
        factories.MeteringPointAssignmentFactory(
            metering_point=mp, participant=participant, valid_from=date(2026, 1, 1),
        )
        source = make_source()
        for ts, price in source_prices:
            store(source, ts, price)
        dynamic_tariff(zev, source)
        return participant, mp, source

    def test_grid_consumption_is_billed_at_the_fetched_price(self):
        participant, mp, _source = self._billed_participant([
            (datetime(2026, 1, 15, 10, 0, tzinfo=UTC), "0.30000"),
            (datetime(2026, 1, 15, 10, 15, tzinfo=UTC), "0.10000"),
        ])
        MeterReading.objects.create(
            metering_point=mp, timestamp=datetime(2026, 1, 15, 10, 0, tzinfo=UTC),
            energy_kwh=Decimal("10.0"), direction=ReadingDirection.IN,
        )
        MeterReading.objects.create(
            metering_point=mp, timestamp=datetime(2026, 1, 15, 10, 15, tzinfo=UTC),
            energy_kwh=Decimal("10.0"), direction=ReadingDirection.IN,
        )

        invoice = generate_invoice(participant, date(2026, 1, 1), date(2026, 1, 31))

        assert invoice.total_grid_kwh == Decimal("20.0000")
        # 10 * 0.30 + 10 * 0.10 = 4.00 CHF — same arithmetic as the HT/NT test,
        # with a fetched price standing in for a band.
        assert invoice.subtotal_chf == Decimal("4.00")

    def test_a_negative_fetched_price_credits_the_participant(self):
        participant, mp, _source = self._billed_participant([
            (datetime(2026, 1, 15, 12, 0, tzinfo=UTC), "-0.05430"),
        ])
        MeterReading.objects.create(
            metering_point=mp, timestamp=datetime(2026, 1, 15, 12, 0, tzinfo=UTC),
            energy_kwh=Decimal("10.0"), direction=ReadingDirection.IN,
        )

        invoice = generate_invoice(participant, date(2026, 1, 1), date(2026, 1, 31))

        assert invoice.subtotal_chf == Decimal("-0.54")

    def test_a_gap_in_the_series_refuses_the_whole_invoice(self):
        # One unpriced reading is enough: billing the rest at the right price
        # and this one at zero would still be a wrong invoice.
        participant, mp, _source = self._billed_participant([
            (datetime(2026, 1, 15, 10, 0, tzinfo=UTC), "0.20000"),
        ])
        MeterReading.objects.create(
            metering_point=mp, timestamp=datetime(2026, 1, 15, 10, 0, tzinfo=UTC),
            energy_kwh=Decimal("10.0"), direction=ReadingDirection.IN,
        )
        # This reading falls outside the one interval stored above.
        MeterReading.objects.create(
            metering_point=mp, timestamp=datetime(2026, 1, 20, 8, 0, tzinfo=UTC),
            energy_kwh=Decimal("5.0"), direction=ReadingDirection.IN,
        )

        with pytest.raises(DynamicPriceGapError):
            generate_invoice(participant, date(2026, 1, 1), date(2026, 1, 31))

        assert not participant.invoices.exists()

    def test_a_percentage_tariff_on_a_dynamic_grid_rate_follows_the_series(self):
        # The percentage base sums every active GRID energy tariff at the
        # timestamp — a dynamic one has to flow into that sum for free.
        participant, mp, source = self._billed_participant([
            (datetime(2026, 1, 15, 10, 0, tzinfo=UTC), "0.20000"),
        ])
        zev = participant.zev
        levy = factories.TariffFactory(
            zev=zev, category=TariffCategory.LEVIES,
            billing_mode=BillingMode.PERCENTAGE_OF_ENERGY, energy_type=EnergyType.GRID,
            valid_from=date(2026, 1, 1),
        )
        levy.percentage = Decimal("50")
        levy.save()
        MeterReading.objects.create(
            metering_point=mp, timestamp=datetime(2026, 1, 15, 10, 0, tzinfo=UTC),
            energy_kwh=Decimal("10.0"), direction=ReadingDirection.IN,
        )

        invoice = generate_invoice(participant, date(2026, 1, 1), date(2026, 1, 31))

        # Grid: 10 * 0.20 = 2.00. Levy: 50% of 0.20 * 10 = 1.00. Total 3.00.
        assert invoice.subtotal_chf == Decimal("3.00")

    def test_feed_in_export_is_credited_at_the_fetched_price(self):
        participant = factories.ParticipantFactory(valid_from=date(2026, 1, 1))
        zev = participant.zev
        consumption_mp = factories.MeteringPointFactory(zev=zev)
        production_mp = factories.MeteringPointFactory(
            zev=zev, meter_type=factories.MeteringPointType.PRODUCTION,
        )
        factories.MeteringPointAssignmentFactory(
            metering_point=consumption_mp, participant=participant, valid_from=date(2026, 1, 1),
        )
        factories.MeteringPointAssignmentFactory(
            metering_point=production_mp, participant=participant, valid_from=date(2026, 1, 1),
        )
        source = make_source(
            tariff_type="feed_in", tariff_name="", label="Example feed-in", api_version="v1_0_5",
            request_mode="exact_url", supports_range=False,
            url="https://api.bkw.ch/api/dyntariffs/v1/Tariffs/energyreturn",
        )
        store(source, datetime(2026, 1, 15, 12, 0, tzinfo=UTC), "0.17700")
        dynamic_tariff(
            zev, source, name="Feed-in (dynamic)", category=TariffCategory.ENERGY,
            energy_type=EnergyType.FEED_IN,
        )
        # All production exported: no consumption at the same instant.
        MeterReading.objects.create(
            metering_point=production_mp, timestamp=datetime(2026, 1, 15, 12, 0, tzinfo=UTC),
            energy_kwh=Decimal("8.0"), direction=ReadingDirection.OUT,
        )

        invoice = generate_invoice(participant, date(2026, 1, 1), date(2026, 1, 31))

        # A credit: 8 kWh exported at 0.177 CHF/kWh.
        assert invoice.subtotal_chf == Decimal("-1.42")
