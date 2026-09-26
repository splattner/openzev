"""Engine tests for time-of-use bands on percentage-of-energy tariffs.

See ``docs/specs/2026-09-percentage-tariff-bands.md`` §5.2, §6. A percentage
band is resolved and itemised exactly as an energy band is; these tests pin
the numbers the spec's worked examples give.
"""
from datetime import date, datetime, time, timezone

from decimal import Decimal

import pytest

from metering.models import MeterReading, ReadingDirection
from tariffs.dynamic.models import DynamicTariffSource
from tariffs.models import BillingMode, EnergyType, PeriodType, Tariff, TariffCategory, TariffPeriod
from testing import factories

from .band_labels import band_description, translations_for
from .engine import DynamicPriceGapError, generate_invoice, preflight_dynamic_prices

pytestmark = pytest.mark.django_db


def _grid_tariff(zev, price="0.20000"):
    tariff = Tariff.objects.create(
        zev=zev, name="Grid", category=TariffCategory.ENERGY,
        billing_mode=BillingMode.ENERGY, energy_type=EnergyType.GRID,
        valid_from=date(2026, 1, 1),
    )
    TariffPeriod.objects.create(tariff=tariff, period_type=PeriodType.FLAT, price_chf_per_kwh=Decimal(price))
    return tariff


def _percentage_tariff(zev, *, name="Local Surcharge", energy_type=EnergyType.LOCAL):
    """60% for 10:00-16:00, 90% otherwise (two non-wrapping bands, §5.1)."""
    tariff = Tariff.objects.create(
        zev=zev, name=name, category=TariffCategory.LEVIES,
        billing_mode=BillingMode.PERCENTAGE_OF_ENERGY, energy_type=energy_type,
        valid_from=date(2026, 1, 1),
    )
    TariffPeriod.objects.create(
        tariff=tariff, period_type=PeriodType.LOW, percentage=Decimal("90.00"),
        time_from=time(0, 0), time_to=time(10, 0),
    )
    TariffPeriod.objects.create(
        tariff=tariff, period_type=PeriodType.HIGH, percentage=Decimal("60.00"),
        time_from=time(10, 0), time_to=time(16, 0),
    )
    TariffPeriod.objects.create(
        tariff=tariff, period_type=PeriodType.BAND, percentage=Decimal("90.00"),
        time_from=time(16, 0), time_to=time(23, 59, 59),
    )
    return tariff


def _flat_percentage_tariff(zev, *, percentage="50.00", energy_type=EnergyType.LOCAL):
    tariff = Tariff.objects.create(
        zev=zev, name="Surcharge", category=TariffCategory.LEVIES,
        billing_mode=BillingMode.PERCENTAGE_OF_ENERGY, energy_type=energy_type,
        valid_from=date(2026, 1, 1),
    )
    TariffPeriod.objects.create(tariff=tariff, period_type=PeriodType.FLAT, percentage=Decimal(percentage))
    return tariff


def _participant_with_meters(**zev_kwargs):
    participant = factories.ParticipantFactory(valid_from=date(2026, 1, 1))
    zev = participant.zev
    for field, value in zev_kwargs.items():
        setattr(zev, field, value)
    if zev_kwargs:
        zev.save(update_fields=list(zev_kwargs))
    consumption = factories.MeteringPointFactory(zev=zev)
    factories.MeteringPointAssignmentFactory(
        metering_point=consumption, participant=participant, valid_from=date(2026, 1, 1),
    )
    production = factories.MeteringPointFactory(
        zev=zev, meter_type=factories.MeteringPointType.PRODUCTION,
    )
    factories.MeteringPointAssignmentFactory(
        metering_point=production, participant=participant, valid_from=date(2026, 1, 1),
    )
    return participant, consumption, production


def _read(mp, hour, kwh, *, direction=ReadingDirection.IN):
    MeterReading.objects.create(
        metering_point=mp,
        timestamp=datetime(2026, 1, 15, hour, 0, tzinfo=timezone.utc),
        energy_kwh=Decimal(kwh),
        direction=direction,
    )


class TestBandsPriceByTimestamp:
    def test_consumer_readings_are_priced_at_the_resolved_bands_percentage(self):
        # energy_type=GRID: the reading needs no matching production, since
        # unmatched consumption draws straight from the grid.
        participant, consumption, _production = _participant_with_meters()
        _grid_tariff(participant.zev, "0.20000")
        _percentage_tariff(participant.zev, energy_type=EnergyType.GRID)
        _read(consumption, 12, "10.0")  # 60% band -> 0.20 * 0.60 = 0.12/kWh
        _read(consumption, 20, "10.0")  # 90% band -> 0.20 * 0.90 = 0.18/kWh

        invoice = generate_invoice(participant, date(2026, 1, 1), date(2026, 1, 31))

        items = list(invoice.items.filter(description__startswith="Local Surcharge"))
        assert len(items) == 1  # blended, itemisation off by default
        assert items[0].total_chf == Decimal("3.00")  # 10*0.12 + 10*0.18

    def test_producer_local_credit_at_noon_uses_the_noon_band(self):
        participant, consumption, production = _participant_with_meters()
        _grid_tariff(participant.zev, "0.20000")
        _percentage_tariff(participant.zev)
        _read(consumption, 12, "6.0")
        _read(production, 12, "6.0", direction=ReadingDirection.OUT)

        invoice = generate_invoice(participant, date(2026, 1, 1), date(2026, 1, 31))

        credits = invoice.items.filter(
            description__startswith="Local Surcharge", total_chf__lt=0,
        )
        assert credits.count() == 1
        # local_sold = 6.0 kWh at 60% of 0.20 = 0.12/kWh -> -0.72
        assert credits.first().total_chf == Decimal("-0.72")

    def test_single_flat_band_description_matches_the_pre_band_format(self):
        participant, consumption, _production = _participant_with_meters()
        _grid_tariff(participant.zev, "0.32000")
        tariff = _flat_percentage_tariff(participant.zev, percentage="50.00", energy_type=EnergyType.GRID)
        _read(consumption, 12, "6.0")

        invoice = generate_invoice(participant, date(2026, 1, 1), date(2026, 1, 31))

        item = invoice.items.get(description__startswith=tariff.name)
        assert item.description == "Surcharge (50% von CHF 0.32/kWh)"


class TestZeroPercentBand:
    def test_a_zero_percent_band_produces_no_line_and_needs_no_grid_base(self):
        # energy_type=LOCAL with production matching consumption: the grid
        # quantity is 0, so the (gapped) dynamic GRID tariff is never asked to
        # price anything directly — only the percentage tariff's own base
        # lookup could reach it, and a 0% band must not make that lookup.
        participant, consumption, production = _participant_with_meters()
        source = DynamicTariffSource.objects.create(
            label="Grid", url="https://example.test/grid", tariff_type="grid",
        )
        Tariff.objects.create(
            zev=participant.zev, name="Grid (dynamic)", category=TariffCategory.ENERGY,
            billing_mode=BillingMode.ENERGY, energy_type=EnergyType.GRID,
            valid_from=date(2026, 1, 1), dynamic_source=source,
        )
        # No DynamicPricePoint stored at all: the grid series has a gap
        # everywhere. A 0% percentage band must not need it.
        _flat_percentage_tariff(participant.zev, percentage="0.00", energy_type=EnergyType.LOCAL)
        _read(consumption, 12, "10.0")
        _read(production, 12, "10.0", direction=ReadingDirection.OUT)

        invoice = generate_invoice(participant, date(2026, 1, 1), date(2026, 1, 31))

        assert not invoice.items.filter(description__startswith="Surcharge").exists()

    def test_preflight_does_not_require_the_grid_base_when_every_band_is_zero(self):
        participant, consumption, production = _participant_with_meters()
        source = DynamicTariffSource.objects.create(
            label="Grid", url="https://example.test/grid2", tariff_type="grid",
        )
        Tariff.objects.create(
            zev=participant.zev, name="Grid (dynamic)", category=TariffCategory.ENERGY,
            billing_mode=BillingMode.ENERGY, energy_type=EnergyType.GRID,
            valid_from=date(2026, 1, 1), dynamic_source=source,
        )
        _flat_percentage_tariff(participant.zev, percentage="0.00", energy_type=EnergyType.LOCAL)
        _read(consumption, 12, "10.0")
        _read(production, 12, "10.0", direction=ReadingDirection.OUT)

        # Would raise DynamicPriceGapError if the (unpriced) grid base were
        # required at this timestamp.
        preflight_dynamic_prices(participant.zev, date(2026, 1, 1), date(2026, 1, 31))

    def test_preflight_still_requires_the_grid_base_for_a_nonzero_band(self):
        participant, consumption, production = _participant_with_meters()
        source = DynamicTariffSource.objects.create(
            label="Grid", url="https://example.test/grid3", tariff_type="grid",
        )
        Tariff.objects.create(
            zev=participant.zev, name="Grid (dynamic)", category=TariffCategory.ENERGY,
            billing_mode=BillingMode.ENERGY, energy_type=EnergyType.GRID,
            valid_from=date(2026, 1, 1), dynamic_source=source,
        )
        _flat_percentage_tariff(participant.zev, percentage="10.00", energy_type=EnergyType.LOCAL)
        _read(consumption, 12, "10.0")
        _read(production, 12, "10.0", direction=ReadingDirection.OUT)

        with pytest.raises(DynamicPriceGapError):
            preflight_dynamic_prices(participant.zev, date(2026, 1, 1), date(2026, 1, 31))


class TestBandItemisation:
    def test_itemisation_on_gives_one_line_per_band_summing_to_the_group_total(self):
        participant, consumption, _production = _participant_with_meters(itemize_tariff_bands=True)
        _grid_tariff(participant.zev, "0.20000")
        tariff = _percentage_tariff(participant.zev, energy_type=EnergyType.GRID)
        _read(consumption, 12, "10.0")  # 60% band
        _read(consumption, 20, "10.0")  # 90% band (evening BAND period)

        invoice = generate_invoice(participant, date(2026, 1, 1), date(2026, 1, 31))
        items = list(invoice.items.filter(description__startswith=tariff.name))

        assert len(items) == 2
        tr = translations_for(participant.zev.invoice_language or "de")
        used_periods = [
            p for p in tariff.periods.all()
            if p.percentage in (Decimal("60.00"), Decimal("90.00")) and p.period_type != PeriodType.LOW
        ]
        by_band = {
            f"{tariff.name} – {band_description(period, tr)}": period
            for period in used_periods
        }
        descriptions = {item.description for item in items}
        # Each line names its own band (dash-joined) and carries that band's
        # own percentage, not a blend.
        for prefix, period in by_band.items():
            matching = [d for d in descriptions if d.startswith(prefix)]
            assert len(matching) == 1, descriptions
            pct_str = f"{period.percentage:f}".rstrip("0").rstrip(".")
            assert f"{pct_str}%" in matching[0]
        assert sum((item.total_chf for item in items), Decimal("0")) == Decimal("3.00")

    def test_itemisation_off_with_differing_bands_shows_the_blended_average(self):
        participant, consumption, _production = _participant_with_meters(itemize_tariff_bands=False)
        _grid_tariff(participant.zev, "0.20000")
        tariff = _percentage_tariff(participant.zev, energy_type=EnergyType.GRID)
        _read(consumption, 12, "10.0")  # 60% band
        _read(consumption, 20, "10.0")  # 90% band

        invoice = generate_invoice(participant, date(2026, 1, 1), date(2026, 1, 31))
        items = list(invoice.items.filter(description__startswith=tariff.name))

        assert len(items) == 1
        # blended: (10*0.12 + 10*0.18) / 20 base of 0.20*20=4.00 -> effective 75.00%
        assert "Ø" in items[0].description
        assert "75%" in items[0].description

    def test_itemisation_off_ignores_zero_bands_when_naming_the_percentage(self):
        participant, consumption, _production = _participant_with_meters(itemize_tariff_bands=False)
        _grid_tariff(participant.zev, "0.20000")
        tariff = Tariff.objects.create(
            zev=participant.zev, name="Midday Free", category=TariffCategory.LEVIES,
            billing_mode=BillingMode.PERCENTAGE_OF_ENERGY, energy_type=EnergyType.GRID,
            valid_from=date(2026, 1, 1),
        )
        TariffPeriod.objects.create(
            tariff=tariff, period_type=PeriodType.BAND, percentage=Decimal("90.00"),
            time_from=time(0, 0), time_to=time(10, 0),
        )
        TariffPeriod.objects.create(
            tariff=tariff, period_type=PeriodType.BAND, percentage=Decimal("0.00"),
            time_from=time(10, 0), time_to=time(16, 0),
        )
        TariffPeriod.objects.create(
            tariff=tariff, period_type=PeriodType.BAND, percentage=Decimal("90.00"),
            time_from=time(16, 0), time_to=time(23, 59, 59),
        )
        _read(consumption, 12, "10.0")  # 0% band: no quantity on the line
        _read(consumption, 20, "10.0")  # 90% band

        invoice = generate_invoice(participant, date(2026, 1, 1), date(2026, 1, 31))
        items = list(invoice.items.filter(description__startswith=tariff.name))

        # Only the 90% hours reach the line, so it is billed at exactly 90%
        # and must not read as an average.
        assert len(items) == 1
        assert "Ø" not in items[0].description
        assert "90%" in items[0].description
