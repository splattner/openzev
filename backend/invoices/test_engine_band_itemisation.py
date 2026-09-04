"""Tests for ``Zev.itemize_tariff_bands`` (issue #546).

A tariff with several price bands normally bills as one line at the blended
average of whichever bands the participant's consumption fell into. With the
setting on, each band that was actually used gets its own line at its own
rate. These tests pin both shapes, and the rule that joins them: whichever
way a tariff is presented, it costs the same.
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

from .band_labels import band_description, translations_for
from .engine import _round_to_group_total, generate_invoice

pytestmark = pytest.mark.django_db


def _banded_tariff(zev, *, name="Netznutzung"):
    """A three-band grid tariff: peak, off-peak and a labelled weekend band."""
    tariff = Tariff.objects.create(
        zev=zev,
        name=name,
        category=TariffCategory.ENERGY,
        billing_mode=BillingMode.ENERGY,
        energy_type=EnergyType.GRID,
        valid_from=date(2026, 1, 1),
    )
    TariffPeriod.objects.create(
        tariff=tariff, period_type=PeriodType.HIGH,
        price_chf_per_kwh=Decimal("0.30000"),
        time_from=time(6, 0), time_to=time(22, 0),
    )
    TariffPeriod.objects.create(
        tariff=tariff, period_type=PeriodType.LOW,
        price_chf_per_kwh=Decimal("0.10000"),
        time_from=time(22, 0), time_to=time(23, 59, 59),
    )
    return tariff


def _flat_tariff(zev, price="0.20000"):
    tariff = Tariff.objects.create(
        zev=zev, name="Einheitstarif", category=TariffCategory.ENERGY,
        billing_mode=BillingMode.ENERGY, energy_type=EnergyType.GRID,
        valid_from=date(2026, 1, 1),
    )
    TariffPeriod.objects.create(
        tariff=tariff, period_type=PeriodType.FLAT, price_chf_per_kwh=Decimal(price),
    )
    return tariff


def _participant_with_meter(**zev_kwargs):
    participant = factories.ParticipantFactory(valid_from=date(2026, 1, 1))
    zev = participant.zev
    for field, value in zev_kwargs.items():
        setattr(zev, field, value)
    if zev_kwargs:
        zev.save(update_fields=list(zev_kwargs))
    mp = factories.MeteringPointFactory(zev=zev)
    factories.MeteringPointAssignmentFactory(
        metering_point=mp, participant=participant, valid_from=date(2026, 1, 1),
    )
    return participant, mp


def _read(mp, hour, kwh):
    MeterReading.objects.create(
        metering_point=mp,
        timestamp=datetime(2026, 1, 15, hour, 0, tzinfo=timezone.utc),
        energy_kwh=Decimal(kwh),
        direction=ReadingDirection.IN,
    )


class TestDefaultIsUnchanged:
    def test_multi_band_tariff_stays_one_blended_line(self):
        participant, mp = _participant_with_meter()
        _banded_tariff(participant.zev)
        _read(mp, 10, "10.0")   # peak   @ 0.30
        _read(mp, 23, "30.0")   # off-peak @ 0.10

        invoice = generate_invoice(participant, date(2026, 1, 1), date(2026, 1, 31))
        items = list(invoice.items.all())

        assert len(items) == 1
        # 10*0.30 + 30*0.10 = 6.00 over 40 kWh -> a rate that is neither band's.
        assert items[0].total_chf == Decimal("6.00")
        assert items[0].unit_price_chf == Decimal("0.15000")

    def test_setting_is_off_for_a_new_zev(self):
        assert factories.ZevFactory().itemize_tariff_bands is False


class TestItemisedBands:
    def test_each_used_band_gets_its_own_line_at_its_own_rate(self):
        participant, mp = _participant_with_meter(itemize_tariff_bands=True)
        _banded_tariff(participant.zev)
        _read(mp, 10, "10.0")
        _read(mp, 23, "30.0")

        invoice = generate_invoice(participant, date(2026, 1, 1), date(2026, 1, 31))
        items = list(invoice.items.all())

        assert len(items) == 2
        by_rate = {item.unit_price_chf: item for item in items}
        assert set(by_rate) == {Decimal("0.30000"), Decimal("0.10000")}
        assert by_rate[Decimal("0.30000")].quantity_kwh == Decimal("10.0000")
        assert by_rate[Decimal("0.30000")].total_chf == Decimal("3.00")
        assert by_rate[Decimal("0.10000")].quantity_kwh == Decimal("30.0000")
        assert by_rate[Decimal("0.10000")].total_chf == Decimal("3.00")

    def test_a_band_that_was_never_used_gets_no_line(self):
        participant, mp = _participant_with_meter(itemize_tariff_bands=True)
        _banded_tariff(participant.zev)
        _read(mp, 10, "10.0")  # peak only

        invoice = generate_invoice(participant, date(2026, 1, 1), date(2026, 1, 31))
        assert len(list(invoice.items.all())) == 1

    def test_line_names_the_band_the_way_the_contract_does(self):
        participant, mp = _participant_with_meter(itemize_tariff_bands=True)
        tariff = _banded_tariff(participant.zev)
        _read(mp, 10, "10.0")
        _read(mp, 23, "30.0")

        invoice = generate_invoice(participant, date(2026, 1, 1), date(2026, 1, 31))
        descriptions = {item.description for item in invoice.items.all()}

        tr = translations_for(participant.zev.invoice_language or "de")
        expected = {
            f"{tariff.name} – {band_description(period, tr)}"
            for period in tariff.periods.all()
        }
        assert descriptions == expected

    def test_single_band_tariff_is_untouched_by_the_setting(self):
        participant, mp = _participant_with_meter(itemize_tariff_bands=True)
        tariff = _flat_tariff(participant.zev)
        _read(mp, 10, "10.0")

        invoice = generate_invoice(participant, date(2026, 1, 1), date(2026, 1, 31))
        items = list(invoice.items.all())

        assert len(items) == 1
        # No band qualifier: one band has nothing to distinguish it from.
        assert items[0].description == tariff.name


class TestGroupRounding:
    def test_itemising_does_not_change_what_the_tariff_costs(self):
        """The same readings bill the same total either way (the #546 rule)."""
        totals = {}
        for itemise in (False, True):
            participant, mp = _participant_with_meter(itemize_tariff_bands=itemise)
            _banded_tariff(participant.zev)
            # Quantities chosen so both bands round away from the centime.
            _read(mp, 10, "3.335")
            _read(mp, 23, "7.775")
            invoice = generate_invoice(participant, date(2026, 1, 1), date(2026, 1, 31))
            totals[itemise] = invoice.subtotal_chf
            assert sum(i.total_chf for i in invoice.items.all()) == invoice.subtotal_chf

        assert totals[False] == totals[True]

    def test_band_lines_sum_to_the_tariff_total(self):
        participant, mp = _participant_with_meter(itemize_tariff_bands=True)
        _banded_tariff(participant.zev)
        _read(mp, 10, "1.111")
        _read(mp, 23, "2.222")

        invoice = generate_invoice(participant, date(2026, 1, 1), date(2026, 1, 31))
        items = list(invoice.items.all())
        assert len(items) == 2
        assert sum(i.total_chf for i in items) == invoice.subtotal_chf


class TestRoundToGroupTotal:
    """The distribution rule on its own, where the drift is easy to construct."""

    def test_lines_that_already_sum_are_left_alone(self):
        raw = [Decimal("1.00"), Decimal("2.00")]
        assert _round_to_group_total(raw, Decimal("3.00")) == [
            Decimal("1.00"), Decimal("2.00"),
        ]

    def test_two_lines_rounding_up_are_pulled_back_to_the_group_total(self):
        # Each line rounds up (1.01 + 2.01 = 3.02) but the tariff itself is
        # 3.010 -> 3.01. The group total wins and a centime comes back off.
        raw = [Decimal("1.005"), Decimal("2.005")]
        result = _round_to_group_total(raw, Decimal("3.01"))
        assert sum(result) == Decimal("3.01")

    def test_positive_drift_goes_to_the_worst_rounded_line(self):
        # 0.334 + 0.333 = 0.667 -> group 0.67, but the lines round to 0.33+0.33.
        result = _round_to_group_total(
            [Decimal("0.334"), Decimal("0.333")], Decimal("0.67")
        )
        assert sum(result) == Decimal("0.67")
        assert result == [Decimal("0.34"), Decimal("0.33")]

    def test_negative_drift_is_taken_off_a_line(self):
        # 0.336 + 0.335 = 0.671 -> group 0.67, lines round up to 0.34+0.34.
        result = _round_to_group_total(
            [Decimal("0.336"), Decimal("0.335")], Decimal("0.67")
        )
        assert sum(result) == Decimal("0.67")

    def test_drift_larger_than_the_line_count_is_still_absorbed(self):
        raw = [Decimal("0.004"), Decimal("0.004")]
        result = _round_to_group_total(raw, Decimal("0.03"))
        assert sum(result) == Decimal("0.03")
