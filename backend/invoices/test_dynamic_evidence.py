"""Frozen provenance and PostgreSQL serialization of billing with maintenance."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from importlib import import_module
from threading import Event
from time import monotonic, sleep
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.apps import apps
from django.db import connection, connections
from django.db.models.deletion import ProtectedError

from metering.models import MeterReading
from tariffs.dynamic.fetch import BilledPriceChanged, PriceSeriesConflict, store_points
from tariffs.dynamic.models import DynamicTariffSource
from tariffs.dynamic.services import clear_source_points
from tariffs.dynamic.vse_v1 import PricePoint
from tariffs.models import Tariff
from testing import factories

from .engine import _DynamicSeries, generate_invoice


def setup_billing():
    participant = factories.ParticipantFactory(valid_from=date(2026, 1, 1))
    meter = factories.assignment_for(participant).metering_point
    source = DynamicTariffSource.objects.create(
        label="Grid", url="https://example.test/prices", tariff_type="grid",
    )
    tariff = factories.TariffFactory(
        zev=participant.zev, dynamic_source=source, energy_type="grid", valid_from=date(2026, 1, 1),
    )
    start = datetime(2026, 1, 15, 10, tzinfo=timezone.utc)
    point = PricePoint(start, start + timedelta(minutes=15), Decimal("0.2"))
    store_points(source, [point])
    MeterReading.objects.create(metering_point=meter, timestamp=start, energy_kwh=10, direction="in")
    return participant, tariff, source, point


@pytest.mark.django_db
def test_legacy_refund_links_cannot_price_general_exports():
    participant, _tariff, source, _point = setup_billing()
    DynamicTariffSource.objects.filter(pk=source.pk).update(tariff_type="refund")
    with pytest.raises(ValueError, match="storage-qualified"):
        generate_invoice(participant, date(2026, 1, 1), date(2026, 1, 31))
    assert not participant.invoices.exists()


@pytest.mark.django_db
def test_evidence_survives_validity_community_source_changes_and_tariff_deletion():
    participant, tariff, source, point = setup_billing()
    invoice = generate_invoice(participant, date(2026, 1, 1), date(2026, 1, 31))
    evidence = invoice.dynamic_evidence.get()
    assert evidence.tariff_id_snapshot == tariff.pk
    # Even bypassing tariff validation cannot erase the frozen provenance.
    Tariff.objects.filter(pk=tariff.pk).update(
        valid_from=date(2027, 1, 1), zev=factories.ZevFactory(), dynamic_source=None,
    )
    Tariff.objects.filter(pk=tariff.pk).delete()
    with pytest.raises(BilledPriceChanged):
        store_points(source, [PricePoint(point.valid_from, point.valid_to, Decimal("0.3"))])
    with pytest.raises(PriceSeriesConflict):
        clear_source_points(source)
    with pytest.raises(ProtectedError):
        source.delete()
    assert source.points.get().price_chf_per_kwh == Decimal("0.2")


@pytest.mark.django_db
def test_migration_backfills_existing_invoice_source_windows():
    participant, tariff, source, _point = setup_billing()
    invoice = generate_invoice(participant, date(2026, 1, 1), date(2026, 1, 31))
    invoice.dynamic_evidence.all().delete()
    migration = import_module("invoices.migrations.0017_dynamic_source_evidence")
    migration.backfill_evidence(apps, SimpleNamespace(connection=connection))
    evidence = invoice.dynamic_evidence.get()
    assert evidence.source_id == source.pk
    assert evidence.tariff_id_snapshot == tariff.pk
    assert evidence.evidence_from == datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert evidence.evidence_to == datetime(2026, 2, 1, tzinfo=timezone.utc)


@pytest.mark.django_db
def test_migration_refuses_legacy_overlaps_without_repairing_evidence():
    _participant, _tariff, source, point = setup_billing()
    overlap = source.points.create(
        valid_from=point.valid_from + timedelta(minutes=5), valid_to=point.valid_to,
        price_chf_per_kwh=point.price_chf_per_kwh,
    )
    migration = import_module("tariffs.migrations.0014_remove_dynamicpricepoint_dyn_price_source_from_idx_and_more")
    editor = SimpleNamespace(connection=connection)
    with pytest.raises(RuntimeError, match=f"row {overlap.pk}, source {source.pk}"):
        migration.reject_invalid_intervals(apps, editor)
    overlap.delete()
    migration.reject_invalid_intervals(apps, editor)
    assert source.points.count() == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("operation", ["replace", "clear"])
def test_invoice_price_read_blocks_concurrent_maintenance_until_evidence_commits(operation):
    if connection.vendor != "postgresql":
        pytest.skip("Requires PostgreSQL row locks and pg_blocking_pids")
    participant, _tariff, source, point = setup_billing()
    read, release, writer_connected = Event(), Event(), Event()
    writer_pid = []
    load = _DynamicSeries.load

    def paused_load(*args, **kwargs):
        result = load(*args, **kwargs)
        read.set()
        assert release.wait(10), "Test did not release the invoice transaction"
        return result

    def bill():
        try:
            with patch.object(_DynamicSeries, "load", side_effect=paused_load):
                return generate_invoice(participant, date(2026, 1, 1), date(2026, 1, 31)).pk
        finally:
            connections.close_all()

    def mutate():
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                writer_pid.append(cursor.fetchone()[0])
            writer_connected.set()
            with pytest.raises(PriceSeriesConflict):
                if operation == "clear":
                    clear_source_points(source)
                else:
                    store_points(source, [PricePoint(point.valid_from, point.valid_to, Decimal("0.3"))])
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        invoice_future = pool.submit(bill)
        try:
            assert read.wait(10)
            writer_future = pool.submit(mutate)
            assert writer_connected.wait(10)
            deadline = monotonic() + 5
            blocked = False
            while monotonic() < deadline:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT cardinality(pg_blocking_pids(%s))", [writer_pid[0]])
                    blocked = cursor.fetchone()[0] > 0
                if blocked:
                    break
                sleep(0.01)
            assert blocked, "Maintenance did not wait for the invoice's source lock"
        finally:
            release.set()
        invoice_future.result(timeout=10)
        writer_future.result(timeout=10)
    assert source.points.get().price_chf_per_kwh == Decimal("0.2")
    assert source.invoice_evidence.count() == 1
