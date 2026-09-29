"""reanchor_readings: legacy offset-less CSV batches move to the real instant (ADR 0026).

Spec: docs/specs/2026-09-swiss-civil-time.md §6.3.
"""

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from audit.models import AuditEvent
from invoices.models import InvoiceStatus
from metering.models import ImportLog, ImportSource, MeterReading
from testing.factories import InvoiceFactory, MeteringPointAssignmentFactory, MeteringPointFactory

pytestmark = pytest.mark.django_db


def _utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


def _batch(meter, timestamps, *, source=ImportSource.CSV, timestamp_timezone="", energy="1"):
    """An import log plus readings stored the legacy way (wall clock labelled UTC)."""
    log = ImportLog.objects.create(
        batch_id=uuid.uuid4(), zev=meter.zev, source=source, filename="legacy.csv",
        timestamp_timezone=timestamp_timezone,
    )
    for ts in timestamps:
        MeterReading.objects.create(
            metering_point=meter, timestamp=ts, direction="in", energy_kwh=Decimal(energy),
            import_source=source, import_batch=log.batch_id,
        )
    return log


def _run(*args):
    out = StringIO()
    call_command("reanchor_readings", *args, stdout=out)
    return out.getvalue()


def _stamps(meter):
    return list(MeterReading.objects.filter(metering_point=meter).order_by("timestamp").values_list("timestamp", flat=True))


@pytest.fixture
def meter():
    return MeteringPointFactory()


def test_list_shows_only_legacy_csv_batches(meter):
    legacy = _batch(meter, [_utc(2026, 1, 15, 12)])
    _batch(meter, [_utc(2026, 1, 16, 12)], source=ImportSource.SDATCH, timestamp_timezone="Europe/Zurich")
    _batch(meter, [_utc(2026, 1, 17, 12)], timestamp_timezone="Europe/Zurich")

    out = _run("--list")

    assert str(legacy.batch_id) in out
    assert out.count("legacy.csv") == 1


def test_dry_run_writes_nothing(meter):
    log = _batch(meter, [_utc(2026, 1, 15, 12)])

    out = _run("--batch", str(log.batch_id))

    assert "Dry run" in out
    assert _stamps(meter) == [_utc(2026, 1, 15, 12)]
    log.refresh_from_db()
    assert log.timestamp_timezone == ""


def test_apply_moves_winter_and_summer_readings(meter):
    # Stored 12:00 "UTC" meant 12:00 Swiss time.
    log = _batch(meter, [_utc(2026, 1, 15, 12), _utc(2026, 7, 15, 12), _utc(2026, 7, 15, 14)])

    _run("--batch", str(log.batch_id), "--apply")

    assert _stamps(meter) == [_utc(2026, 1, 15, 11), _utc(2026, 7, 15, 10), _utc(2026, 7, 15, 12)]


def test_apply_marks_batch_and_second_run_is_refused(meter):
    log = _batch(meter, [_utc(2026, 1, 15, 12)])
    _run("--batch", str(log.batch_id), "--apply")
    log.refresh_from_db()
    assert log.timestamp_timezone == "Europe/Zurich"

    with pytest.raises(CommandError, match="already read as Europe/Zurich"):
        _run("--batch", str(log.batch_id), "--apply")
    assert _stamps(meter) == [_utc(2026, 1, 15, 11)]


def test_sdat_batch_is_refused(meter):
    log = _batch(meter, [_utc(2026, 1, 15, 12)], source=ImportSource.SDATCH)

    with pytest.raises(CommandError, match="carry offsets"):
        _run("--batch", str(log.batch_id), "--apply")


def test_collision_outside_batch_refuses_batch(meter):
    log = _batch(meter, [_utc(2026, 1, 15, 12)])
    MeterReading.objects.create(metering_point=meter, timestamp=_utc(2026, 1, 15, 11), direction="in", energy_kwh=1)

    with pytest.raises(CommandError, match="already taken"):
        _run("--batch", str(log.batch_id), "--apply")
    assert _utc(2026, 1, 15, 12) in _stamps(meter)


def test_zero_energy_spring_gap_reading_is_dropped(meter):
    # 02:00 on 29 March does not exist in Swiss time; 04:00 CEST moves onto its old slot.
    log = _batch(meter, [_utc(2026, 3, 29, 2), _utc(2026, 3, 29, 4)], energy="0")

    out = _run("--batch", str(log.batch_id), "--apply")

    assert "1 zero-energy reading(s) in the spring DST gap to delete" in out
    assert _stamps(meter) == [_utc(2026, 3, 29, 2)]


def test_nonexistent_spring_time_with_energy_refuses_batch(meter):
    log = _batch(meter, [_utc(2026, 3, 29, 2, 30)])

    with pytest.raises(CommandError, match="does not exist in Swiss time"):
        _run("--batch", str(log.batch_id), "--apply")
    assert _stamps(meter) == [_utc(2026, 3, 29, 2, 30)]


def test_invoiced_period_requires_allow_invoiced(meter):
    assignment = MeteringPointAssignmentFactory(metering_point=meter, participant__zev=meter.zev)
    InvoiceFactory(
        zev=meter.zev, participant=assignment.participant, status=InvoiceStatus.SENT,
        period_start=date(2026, 1, 1), period_end=date(2026, 1, 31),
    )
    log = _batch(meter, [_utc(2026, 1, 15, 12)])

    with pytest.raises(CommandError, match="--allow-invoiced"):
        _run("--batch", str(log.batch_id), "--apply")

    _run("--batch", str(log.batch_id), "--apply", "--allow-invoiced")
    assert _stamps(meter) == [_utc(2026, 1, 15, 11)]


def test_apply_records_audit_event(meter):
    log = _batch(meter, [_utc(2026, 1, 15, 12)])

    _run("--batch", str(log.batch_id), "--apply")

    event = AuditEvent.objects.get(action_type="import.readings_reanchored")
    assert event.metadata_json["moved"] == 1
    assert event.metadata_json["batch_id"] == str(log.batch_id)


def test_adjacent_batches_are_planned_together(meter):
    """August's first hours move onto July's last ones, which July vacates in the same run."""
    july = _batch(meter, [_utc(2026, 7, 31, 22), _utc(2026, 7, 31, 23)])
    august = _batch(meter, [_utc(2026, 8, 1, 0), _utc(2026, 8, 1, 1)])

    _run("--batch", str(july.batch_id), "--batch", str(august.batch_id), "--apply")

    assert _stamps(meter) == [
        _utc(2026, 7, 31, 20), _utc(2026, 7, 31, 21), _utc(2026, 7, 31, 22), _utc(2026, 7, 31, 23),
    ]


def test_selecting_only_the_later_batch_collides_with_the_earlier_one(meter):
    _batch(meter, [_utc(2026, 7, 31, 22)])
    august = _batch(meter, [_utc(2026, 8, 1, 0)])

    with pytest.raises(CommandError, match="outside the selection"):
        _run("--batch", str(august.batch_id), "--apply")
