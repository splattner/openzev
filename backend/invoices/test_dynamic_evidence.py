"""Frozen provenance and PostgreSQL serialization of billing with maintenance."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from importlib import import_module
from threading import Event
from time import monotonic, sleep
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from django.apps import apps
from django.db import connection, connections
from django.db.models.deletion import ProtectedError

from metering.models import MeterReading
from tariffs.dynamic.fetch import BilledPriceChanged, PriceSeriesConflict, store_points
from tariffs.dynamic.models import DynamicTariffSource
from tariffs.dynamic.services import clear_source_points
from tariffs.dynamic.vse_v1 import PricePoint
from tariffs.models import EnergyType, Tariff, TariffCategory
from testing import factories

from .engine import (
    DynamicPriceGapError,
    DynamicTariffError,
    _DynamicSeries,
    generate_invoice,
    preflight_dynamic_prices,
)


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
    with pytest.raises(DynamicTariffError, match="storage-qualified") as error:
        generate_invoice(participant, date(2026, 1, 1), date(2026, 1, 31))
    assert error.value.as_dict()["code"] == "invalid_dynamic_tariff"
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
    migration = import_module("invoices.migrations.0018_dynamic_source_evidence")
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


def test_source_identity_migration_names_invalid_exact_url_capabilities():
    migration = import_module("tariffs.migrations.0015_source_version_identity")
    source_id = "253925c0-b87c-4767-a6c6-bba3634be90f"
    queryset = Mock()
    queryset.using.return_value = queryset
    queryset.filter.return_value = queryset
    queryset.values_list.return_value = [(source_id, "https://example.test/current")]
    historical_apps = SimpleNamespace(
        get_model=Mock(return_value=SimpleNamespace(objects=queryset)),
    )
    editor = SimpleNamespace(connection=SimpleNamespace(alias="migration"))

    with pytest.raises(RuntimeError, match=rf"{source_id} .*example\.test/current"):
        migration.reject_invalid_source_capabilities(historical_apps, editor)

    queryset.values_list.return_value = []
    migration.reject_invalid_source_capabilities(historical_apps, editor)
    queryset.using.assert_called_with("migration")
    queryset.filter.assert_called_with(request_mode="exact_url", supports_range=True)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("operation", ["replace", "clear"])
@pytest.mark.parametrize("rollback", [False, True])
def test_invoice_price_read_blocks_concurrent_maintenance_until_evidence_commits(operation, rollback):
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
        if rollback:
            raise ValueError("Simulated pricing failure")
        return result

    def bill():
        try:
            with patch.object(_DynamicSeries, "load", side_effect=paused_load):
                if rollback:
                    with pytest.raises(ValueError, match="Simulated pricing failure"):
                        generate_invoice(participant, date(2026, 1, 1), date(2026, 1, 31))
                    return None
                return generate_invoice(participant, date(2026, 1, 1), date(2026, 1, 31)).pk
        finally:
            connections.close_all()

    def mutate():
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                writer_pid.append(cursor.fetchone()[0])
            writer_connected.set()
            with nullcontext() if rollback else pytest.raises(PriceSeriesConflict):
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
    if rollback and operation == "clear":
        assert not source.points.exists()
    else:
        assert source.points.get().price_chf_per_kwh == Decimal("0.3" if rollback else "0.2")
    assert source.invoice_evidence.count() == (0 if rollback else 1)


@pytest.mark.django_db
@pytest.mark.parametrize("merge", [False, True])
def test_identical_billed_resolution_changes_preserve_original_rows(merge):
    participant, _tariff, source, point = setup_billing()
    midpoint = point.valid_from + (point.valid_to - point.valid_from) / 2
    split = [
        PricePoint(point.valid_from, midpoint, point.price_chf_per_kwh),
        PricePoint(midpoint, point.valid_to, point.price_chf_per_kwh),
    ]
    if merge:
        source.points.all().delete()
        store_points(source, split)
    generate_invoice(participant, date(2026, 1, 1), date(2026, 1, 31))
    before = list(source.points.values_list("pk", "valid_from", "valid_to", "price_chf_per_kwh"))
    assert store_points(source, [point] if merge else split) == 0
    assert (
        list(source.points.values_list("pk", "valid_from", "valid_to", "price_chf_per_kwh"))
        == before
    )


@pytest.mark.django_db
def test_billed_ranges_merge_duplicates_without_protecting_gaps():
    from tariffs.dynamic.evidence import billed_ranges
    from tariffs.dynamic.storage import _overlaps_billed

    participant, _tariff, source, _point = setup_billing()
    invoice = generate_invoice(participant, date(2026, 1, 1), date(2026, 1, 31))
    evidence = invoice.dynamic_evidence.get()
    from uuid import uuid4

    evidence.pk = None
    evidence.tariff_id_snapshot = uuid4()
    evidence.evidence_from = datetime(2026, 1, 15, tzinfo=timezone.utc)
    evidence.evidence_to = datetime(2026, 2, 15, tzinfo=timezone.utc)
    evidence.save()
    ranges = billed_ranges(source)
    assert ranges == [(datetime(2026, 1, 1, tzinfo=timezone.utc), evidence.evidence_to)]
    assert _overlaps_billed(evidence.evidence_from, evidence.evidence_to, ranges)
    assert not _overlaps_billed(
        evidence.evidence_to, evidence.evidence_to + timedelta(days=1), ranges
    )


@pytest.mark.django_db
def test_bulk_preflight_checks_price_use_timestamps_not_the_full_tariff_window(owner_client, owner_user):
    participant, _tariff, source, _point = setup_billing()
    participant.zev.owner = owner_user
    participant.zev.save()
    payload = {
        "zev_id": str(participant.zev_id),
        "period_start": "2026-01-01",
        "period_end": "2026-01-31",
    }
    with patch("invoices.views.generate_zev_invoices_task.delay") as queue:
        response = owner_client.post("/api/v1/invoices/invoices/generate-all/", payload)
        assert response.status_code == 202
        queue.assert_called_once()

        source.points.all().delete()
        response = owner_client.post("/api/v1/invoices/invoices/generate-all/", payload)
        assert response.status_code == 409
        assert response.json()["code"] == "dynamic_price_gap"
        assert response.json()["source_id"] == str(source.pk)
        queue.assert_called_once()


@pytest.mark.django_db
def test_bulk_preflight_skips_reading_scan_without_dynamic_tariffs():
    participant = factories.ParticipantFactory(valid_from=date(2026, 1, 1))
    factories.TariffFactory(
        zev=participant.zev, energy_type=EnergyType.GRID,
        valid_from=date(2026, 1, 1),
    )

    with patch("invoices.engine._billable_energy_types_by_timestamp") as requirements:
        preflight_dynamic_prices(
            participant.zev, date(2026, 1, 1), date(2026, 1, 31),
        )

    requirements.assert_not_called()


@pytest.mark.django_db
def test_bulk_preflight_ignores_a_dynamic_type_no_reading_will_price(owner_client, owner_user):
    participant, _tariff, _source, _point = setup_billing()
    participant.zev.owner = owner_user
    participant.zev.save()
    unused_source = DynamicTariffSource.objects.create(
        label="Feed-in", url="https://example.test/feed-in", tariff_type="feed_in",
    )
    factories.TariffFactory(
        zev=participant.zev, dynamic_source=unused_source,
        energy_type="feed_in", valid_from=date(2026, 1, 1),
    )

    with patch("invoices.views.generate_zev_invoices_task.delay") as queue:
        response = owner_client.post(
            "/api/v1/invoices/invoices/generate-all/",
            {
                "zev_id": str(participant.zev_id),
                "period_start": "2026-01-01",
                "period_end": "2026-01-31",
            },
        )

    assert response.status_code == 202
    queue.assert_called_once()


@pytest.mark.django_db
def test_bulk_preflight_checks_dynamic_grid_price_used_by_a_percentage_tariff():
    participant = factories.ParticipantFactory(valid_from=date(2026, 1, 1))
    consumption = factories.assignment_for(participant).metering_point
    production = factories.assignment_for(
        participant, meter_type=factories.MeteringPointType.PRODUCTION,
    ).metering_point
    source = DynamicTariffSource.objects.create(
        label="Grid", url="https://example.test/grid", tariff_type="grid",
    )
    factories.TariffFactory(
        zev=participant.zev, dynamic_source=source,
        energy_type=EnergyType.GRID, valid_from=date(2026, 1, 1),
    )
    factories.percentage_tariff(
        participant.zev,
        category=TariffCategory.ENERGY,
        energy_type=EnergyType.LOCAL,
        percentage="10",
        valid_from=date(2026, 1, 1),
    )
    timestamp = datetime(2026, 1, 15, 10, tzinfo=timezone.utc)
    MeterReading.objects.create(
        metering_point=consumption, timestamp=timestamp,
        energy_kwh=Decimal("10"), direction="in",
    )
    MeterReading.objects.create(
        metering_point=production, timestamp=timestamp,
        energy_kwh=Decimal("10"), direction="out",
    )

    with pytest.raises(DynamicPriceGapError) as error:
        preflight_dynamic_prices(
            participant.zev, date(2026, 1, 1), date(2026, 1, 31),
        )

    assert error.value.missing_at == timestamp
    assert error.value.source_id == source.pk


@pytest.mark.django_db
def test_bulk_preflight_ignores_dynamic_grid_base_for_zero_percentage_tariff():
    participant = factories.ParticipantFactory(valid_from=date(2026, 1, 1))
    consumption = factories.assignment_for(participant).metering_point
    production = factories.assignment_for(
        participant, meter_type=factories.MeteringPointType.PRODUCTION,
    ).metering_point
    source = DynamicTariffSource.objects.create(
        label="Grid", url="https://example.test/grid", tariff_type="grid",
    )
    factories.TariffFactory(
        zev=participant.zev, dynamic_source=source,
        energy_type=EnergyType.GRID, valid_from=date(2026, 1, 1),
    )
    factories.percentage_tariff(
        participant.zev,
        category=TariffCategory.ENERGY,
        energy_type=EnergyType.LOCAL,
        percentage="0",
        valid_from=date(2026, 1, 1),
    )
    timestamp = datetime(2026, 1, 15, 10, tzinfo=timezone.utc)
    MeterReading.objects.create(
        metering_point=consumption, timestamp=timestamp,
        energy_kwh=Decimal("10"), direction="in",
    )
    MeterReading.objects.create(
        metering_point=production, timestamp=timestamp,
        energy_kwh=Decimal("10"), direction="out",
    )

    preflight_dynamic_prices(
        participant.zev, date(2026, 1, 1), date(2026, 1, 31),
    )


@pytest.mark.django_db
def test_bulk_preflight_does_not_disclose_other_owners_sources(owner_client):
    participant, _tariff, _source, _point = setup_billing()
    with patch("invoices.views.preflight_dynamic_prices") as preflight:
        response = owner_client.post(
            "/api/v1/invoices/invoices/generate-all/",
            {
                "zev_id": str(participant.zev_id),
                "period_start": "2026-01-01",
                "period_end": "2026-01-31",
            },
        )
    assert response.status_code == 403
    preflight.assert_not_called()


@pytest.mark.django_db
def test_migration_flushes_full_and_final_evidence_batches():
    from .models import Invoice

    participant, _tariff, source, _point = setup_billing()
    Invoice.objects.bulk_create(
        [
            Invoice(
                zev=participant.zev,
                participant=participant,
                invoice_number=f"MIG-{i}",
                period_start=date(2026, 1, 1),
                period_end=date(2026, 1, 31),
            )
            for i in range(1001)
        ]
    )
    migration = import_module("invoices.migrations.0018_dynamic_source_evidence")
    migration.backfill_evidence(apps, SimpleNamespace(connection=connection))
    assert source.invoice_evidence.count() == 1001


@pytest.mark.django_db
def test_tariff_evidence_guard_uses_utc_billing_days_not_local_history_days():
    from tariffs.dynamic.services import tariff_has_dynamic_billing_evidence

    participant, _tariff, source, _point = setup_billing()
    invoice = generate_invoice(participant, date(2026, 1, 1), date(2026, 1, 31))
    invoice.dynamic_evidence.update(
        evidence_from=datetime(2026, 1, 15, tzinfo=timezone.utc),
        evidence_to=datetime(2026, 1, 16, tzinfo=timezone.utc),
    )
    for day, protected in [(15, True), (16, False)]:
        assert tariff_has_dynamic_billing_evidence(
            zev_id=participant.zev_id,
            valid_from=date(2026, 1, day),
            valid_to=date(2026, 1, day),
            dynamic_source_id=source.pk,
        ) is protected
