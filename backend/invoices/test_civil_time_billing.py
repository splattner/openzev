"""Billing on Swiss civil time, end to end (ADR 0026).

Readings are UTC instants; periods, assignment days and tariff bands are Swiss
civil time, whatever source the readings came from.

Spec: docs/specs/2026-09-swiss-civil-time.md §9.
"""

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from io import BytesIO

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from allocation.validity import period_window
from invoices.engine import generate_invoice
from metering.importers.csv_importer import import_csv
from metering.importers.sdatch_importer import import_sdatch
from metering.models import MeterReading
from tariffs.dynamic.models import DynamicTariffSource
from tariffs.dynamic.storage import store_points
from tariffs.dynamic.vse_v1 import PricePoint
from tariffs.models import BillingMode, EnergyType, PeriodType, Tariff, TariffCategory, TariffPeriod
from testing import factories
from zev.models import MeteringPointType

pytestmark = pytest.mark.django_db


def _utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


def _grid_tariff(zev, bands):
    tariff = Tariff.objects.create(
        zev=zev, name="Grid", category=TariffCategory.ENERGY, billing_mode=BillingMode.ENERGY,
        energy_type=EnergyType.GRID, valid_from=date(2026, 1, 1),
    )
    for period_type, start, end, price in bands:
        TariffPeriod.objects.create(
            tariff=tariff, period_type=period_type, time_from=start, time_to=end,
            price_chf_per_kwh=Decimal(price),
        )
    return tariff


def _flat_grid_tariff(zev):
    return _grid_tariff(zev, [(PeriodType.FLAT, None, None, "0.20000")])


def _reading(meter, ts, kwh="1", direction="in"):
    return MeterReading.objects.create(metering_point=meter, timestamp=ts, energy_kwh=Decimal(kwh), direction=direction)


def _csv(name, text):
    return SimpleUploadedFile(name, text.encode(), content_type="text/csv")


def test_reading_before_local_midnight_bills_in_previous_month():
    participant = factories.ParticipantFactory(valid_from=date(2026, 1, 1))
    meter = factories.assignment_for(participant).metering_point
    _flat_grid_tariff(participant.zev)
    _reading(meter, _utc(2026, 1, 31, 22, 45))  # 23:45 CET, 31 January
    _reading(meter, _utc(2026, 1, 31, 23, 0), kwh="2")  # 00:00 CET, 1 February

    january = generate_invoice(participant, date(2026, 1, 1), date(2026, 1, 31))
    february = generate_invoice(participant, date(2026, 2, 1), date(2026, 2, 28))

    assert january.total_grid_kwh == Decimal("1.0000")
    assert february.total_grid_kwh == Decimal("2.0000")


def test_ht_nt_split_for_sdat_day():
    """A full Swiss summer day of hourly SDAT-style instants: 16 h HT, 8 h NT."""
    participant = factories.ParticipantFactory(valid_from=date(2026, 1, 1))
    meter = factories.assignment_for(participant).metering_point
    _grid_tariff(participant.zev, [
        (PeriodType.HIGH, time(6), time(22), "0.30000"),
        (PeriodType.LOW, time(22), time(6), "0.10000"),
    ])
    start, end = period_window(date(2026, 7, 1), date(2026, 7, 1))
    ts = start
    while ts < end:
        _reading(meter, ts)
        ts += timedelta(hours=1)

    invoice = generate_invoice(participant, date(2026, 7, 1), date(2026, 7, 31))

    assert invoice.total_grid_kwh == Decimal("24.0000")
    assert invoice.subtotal_chf == Decimal("5.60")  # 16 × 0.30 + 8 × 0.10


def test_move_out_applies_at_local_midnight():
    leaving = factories.ParticipantFactory(valid_from=date(2026, 1, 1))
    arriving = factories.ParticipantFactory(zev=leaving.zev, valid_from=date(2026, 1, 1))
    meter = factories.assignment_for(leaving, valid_to=date(2026, 6, 30)).metering_point
    factories.MeteringPointAssignmentFactory(metering_point=meter, participant=arriving, valid_from=date(2026, 7, 1))
    _flat_grid_tariff(leaving.zev)
    _reading(meter, _utc(2026, 6, 30, 21, 45))  # 23:45 CEST, 30 June
    _reading(meter, _utc(2026, 6, 30, 22, 15), kwh="2")  # 00:15 CEST, 1 July

    june = generate_invoice(leaving, date(2026, 6, 1), date(2026, 6, 30))
    july = generate_invoice(arriving, date(2026, 7, 1), date(2026, 7, 31))

    assert june.total_grid_kwh == Decimal("1.0000")
    assert july.total_grid_kwh == Decimal("2.0000")


def test_dynamic_price_matches_offsetless_csv_reading():
    participant = factories.ParticipantFactory(valid_from=date(2026, 1, 1))
    meter = factories.assignment_for(participant).metering_point
    source = DynamicTariffSource.objects.create(label="Grid", url="https://example.test/prices", tariff_type="grid")
    factories.TariffFactory(zev=participant.zev, dynamic_source=source, energy_type="grid", valid_from=date(2026, 1, 1))
    quarter = timedelta(minutes=15)
    store_points(source, [
        PricePoint(_utc(2026, 7, 1, 10), _utc(2026, 7, 1, 10) + quarter, Decimal("0.2")),  # 12:00 CEST
        PricePoint(_utc(2026, 7, 1, 12), _utc(2026, 7, 1, 12) + quarter, Decimal("0.9")),  # 14:00 CEST
    ])

    import_csv(
        _csv("swiss.csv", f"meter_id,timestamp,energy_kwh\n{meter.meter_id},2026-07-01 12:00,10\n"),
        participant.zev.owner, zev=participant.zev,
    )
    invoice = generate_invoice(participant, date(2026, 7, 1), date(2026, 7, 31))

    assert MeterReading.objects.get(metering_point=meter).timestamp == _utc(2026, 7, 1, 10)
    assert invoice.subtotal_chf == Decimal("2.00")


def test_mixed_sdat_and_csv_allocate_on_same_instant():
    """SDAT production and Swiss-time CSV consumption for the same quarter-hour
    share one timestamp, so the consumption is covered locally."""
    participant = factories.ParticipantFactory(valid_from=date(2026, 1, 1))
    consumption = factories.assignment_for(participant).metering_point
    production = factories.assignment_for(participant, meter_type=MeteringPointType.PRODUCTION).metering_point
    _flat_grid_tariff(participant.zev)
    sdat = (
        "<MeteringData><MeteringPoint>"
        f"<MeteringPointID>{production.meter_id}</MeteringPointID>"
        "<Interval><StartDateTime>2026-07-01T12:00:00+02:00</StartDateTime><Resolution>PT15M</Resolution>"
        "<Observation><Volume>5</Volume><Direction>OUT</Direction></Observation>"
        "</Interval></MeteringPoint></MeteringData>"
    ).encode()
    sdat_file = BytesIO(sdat)
    sdat_file.name = "production.xml"
    import_sdatch(sdat_file, participant.zev, participant.zev.owner)
    import_csv(
        _csv("consumption.csv", f"meter_id,timestamp,energy_kwh\n{consumption.meter_id},2026-07-01 12:00,3\n"),
        participant.zev.owner, zev=participant.zev,
    )

    stamps = set(MeterReading.objects.values_list("timestamp", flat=True))
    invoice = generate_invoice(participant, date(2026, 7, 1), date(2026, 7, 31))

    assert stamps == {_utc(2026, 7, 1, 10)}
    assert invoice.total_local_kwh == Decimal("3.0000")
    assert invoice.total_grid_kwh == Decimal("0.0000")
