"""Metering import log deletion tests."""

import threading
import uuid
from importlib import import_module
from types import SimpleNamespace
from unittest import skipUnless
from unittest.mock import patch
from datetime import date, datetime, timezone
from decimal import Decimal

from django.test import TestCase, TransactionTestCase
from django.apps import apps
from django.db import connection, OperationalError, transaction
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from accounts.models import UserRole
from audit.models import AuditEvent
from invoices.models import Invoice, InvoiceReadingImpact, InvoiceStatus
from metering.importers import csv_importer
from metering.deletion import collect_deleted_slots
from metering.models import ImportLog, ImportSource, MeterReading, QuarantinedReading, ReadingDirection, ReadingResolution
from metering.testing import upload_csv
from metering.importers.csv_importer import ImportFileError, import_csv, _upsert_reading
from testing.sdat import build_block, build_e66, quarter_block
from testing.helpers import authenticate as auth, make_user, create_managed_zev
from zev.models import MeteringPoint, MeteringPointAssignment, MeteringPointType, Participant, ZevAccessGrant, ZevAccessRole


class ImportLogDeletionTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = make_user("import_delete_owner", UserRole.USER)
        self.other_owner = make_user("import_delete_other", UserRole.USER)

        self.zev = create_managed_zev(name="Delete Imports ZEV", owner=self.owner, zev_type="vzev", invoice_prefix="D")
        auth(self.client, self.owner)
        self.other_zev = create_managed_zev(name="Other Imports ZEV", owner=self.other_owner, zev_type="vzev", invoice_prefix="O")
        self.participant = Participant.objects.create(
            zev=self.zev,
            first_name="Delete",
            last_name="Case",
            email="delete.case@example.com",
            valid_from=date(2026, 1, 1),
        )
        self.metering_point = MeteringPoint.objects.create(
            zev=self.zev,
            meter_id="CH-DELETE-1",
            meter_type=MeteringPointType.CONSUMPTION,
        )
        self.other_metering_point = MeteringPoint.objects.create(
            zev=self.other_zev,
            meter_id="CH-DELETE-OTHER",
            meter_type=MeteringPointType.CONSUMPTION,
        )

    def _create_import_log_with_reading(self, *, zev, metering_point, created_at, imported_by=None):
        batch_id = uuid.uuid4()
        log = ImportLog.objects.create(
            batch_id=batch_id,
            zev=zev,
            imported_by=imported_by or self.owner,
            source=ImportSource.CSV,
            filename=f"{batch_id}.csv",
            rows_total=1,
            rows_imported=1,
            rows_skipped=0,
        )
        ImportLog.objects.filter(pk=log.pk).update(created_at=created_at)
        log.refresh_from_db()
        MeterReading.objects.create(
            metering_point=metering_point,
            timestamp=created_at,
            energy_kwh=Decimal("1.0000"),
            direction=ReadingDirection.IN,
            resolution=ReadingResolution.FIFTEEN_MIN,
            import_source=ImportSource.CSV,
            import_batch=batch_id,
        )
        return log

    def _create_correction_log(self):
        log = self._create_import_log_with_reading(
            zev=self.zev, metering_point=self.metering_point,
            created_at=datetime(2026, 2, 10, tzinfo=timezone.utc),
        )
        log.reading_changes = [{"kind": "value", "timestamp": "2026-02-10T00:00:00Z"}]
        log.save(update_fields=["reading_changes"])
        return log

    def test_list_omits_reading_evidence_but_detail_keeps_it(self):
        log = self._create_correction_log()
        listed = self.client.get("/api/v1/metering/import-logs/")
        self.assertNotIn("reading_changes", listed.data["results"][0])
        detail = self.client.get(f"/api/v1/metering/import-logs/{log.id}/")
        self.assertEqual(detail.data["reading_changes"], log.reading_changes)

    def test_viewer_can_read_correction_history(self):
        log = self._create_correction_log()
        viewer = make_user("correction_viewer", UserRole.USER)
        ZevAccessGrant.objects.create(zev=self.zev, user=viewer, role=ZevAccessRole.VIEWER)
        auth(self.client, viewer)
        detail = self.client.get(f"/api/v1/metering/import-logs/{log.id}/")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.data["reading_changes"], log.reading_changes)

    def test_other_community_manager_cannot_read_correction_history(self):
        log = self._create_correction_log()
        auth(self.client, self.other_owner)
        detail = self.client.get(f"/api/v1/metering/import-logs/{log.id}/")
        self.assertEqual(detail.status_code, 404)

    def test_participant_cannot_read_correction_history(self):
        log = self._create_correction_log()
        tenant = make_user("correction_tenant", UserRole.USER)
        self.participant.user = tenant
        self.participant.save(update_fields=["user"])
        auth(self.client, tenant)
        detail = self.client.get(f"/api/v1/metering/import-logs/{log.id}/")
        self.assertEqual(detail.status_code, 403)

    def test_delete_single_import_log_removes_log_and_imported_readings(self):
        created_at = datetime(2026, 2, 10, 8, 0, tzinfo=timezone.utc)
        log = self._create_import_log_with_reading(zev=self.zev, metering_point=self.metering_point, created_at=created_at)

        resp = self.client.delete(f"/api/v1/metering/import-logs/{log.id}/")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["deleted_logs"], 1)
        self.assertEqual(resp.data["deleted_readings"], 1)
        self.assertFalse(ImportLog.objects.filter(pk=log.id).exists())
        self.assertEqual(MeterReading.objects.filter(import_batch=log.batch_id).count(), 0)

    def test_deletion_flags_readings_zev_when_log_has_none(self):
        # A legacy log without a ZEV must not lose its invoice flag: deletion
        # flags follow the deleted readings' ZEV, not the log's.
        MeteringPointAssignment.objects.create(
            metering_point=self.metering_point,
            participant=self.participant,
            valid_from=date(2026, 1, 1),
        )
        invoice = Invoice.objects.create(
            invoice_number="D-LEGACY-1",
            zev=self.zev,
            participant=self.participant,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            status=InvoiceStatus.DRAFT,
            total_chf=Decimal("42.00"),
        )
        batch_id = uuid.uuid4()
        log = ImportLog.objects.create(
            batch_id=batch_id,
            zev=None,
            imported_by=self.owner,
            source=ImportSource.CSV,
            filename="legacy.csv",
            rows_total=1,
            rows_imported=1,
            rows_skipped=0,
        )
        MeterReading.objects.create(
            metering_point=self.metering_point,
            timestamp=datetime(2026, 1, 10, 8, 0, tzinfo=timezone.utc),
            energy_kwh=Decimal("1.0000"),
            direction=ReadingDirection.IN,
            resolution=ReadingResolution.FIFTEEN_MIN,
            import_source=ImportSource.CSV,
            import_batch=batch_id,
        )

        resp = self.client.delete(f"/api/v1/metering/import-logs/{log.id}/")

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(
            InvoiceReadingImpact.objects.filter(invoice=invoice, resolved_at__isnull=True).exists()
        )

    def _overwrite_import(self, profile):
        original = self._create_import_log_with_reading(
            zev=self.zev, metering_point=self.metering_point,
            created_at=datetime(2026, 2, 10, tzinfo=timezone.utc),
        )
        if profile == "standard":
            content = b"meter_id,timestamp,energy_kwh\nCH-DELETE-1,2026-02-10T00:00:00Z,2.0\nCH-DELETE-1,2026-02-10T00:15:00Z,3.0\n"
            options = {}
        else:
            content = b"meter_id,timestamp,v1,v2\nCH-DELETE-1,2026-02-10,2.0,3.0\n"
            # The seeded reading sits at UTC midnight; a UTC file lands on it.
            options = {"col_energy_start": "v1", "values_count": 2, "timestamp_timezone": "UTC"}
        response = upload_csv(
            self.client, "overwrite.csv", content, zev_id=str(self.zev.pk),
            format_profile=profile, overwrite_existing="true", **options,
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["rows_overwritten"], 1)
        self.assertEqual(response.data["rows_imported"], 2)
        return original, ImportLog.objects.get(pk=response.data["id"])

    def test_overwrite_import_cannot_be_deleted_in_either_profile(self):
        for profile in ("standard", "daily_15min"):
            with self.subTest(profile=profile):
                original, overwritten = self._overwrite_import(profile)
                response = self.client.delete(f"/api/v1/metering/import-logs/{overwritten.pk}/")
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.data["code"], "overwrite_import_protected")
                self.assertTrue(ImportLog.objects.filter(pk=overwritten.pk).exists())
                self.assertTrue(ImportLog.objects.filter(pk=original.pk).exists())
                self.assertEqual(list(MeterReading.objects.order_by("timestamp").values_list("energy_kwh", flat=True)), [Decimal("2"), Decimal("3")])
                # Removing the predecessor must not remove the replacement.
                response = self.client.delete(f"/api/v1/metering/import-logs/{original.pk}/")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data["deleted_readings"], 0)
                MeterReading.objects.all().delete()
                ImportLog.objects.all().delete()

    def test_bulk_delete_with_overwrite_import_is_all_or_nothing(self):
        original, overwritten = self._overwrite_import("standard")
        ImportLog.objects.filter(pk=overwritten.pk).update(created_at=original.created_at)
        for payload in ({"mode": "all"}, {"mode": "period", "date_from": "2026-02-10", "date_to": "2026-02-10"}):
            with self.subTest(payload=payload):
                response = self.client.post("/api/v1/metering/import-logs/bulk-delete/", payload, format="json")
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.data["code"], "overwrite_import_protected")
                self.assertEqual(ImportLog.objects.count(), 2)
                self.assertEqual(MeterReading.objects.count(), 2)
                self.assertEqual(MeterReading.objects.order_by("timestamp").first().energy_kwh, Decimal("2"))

    def test_overwrite_option_without_replacements_remains_deletable(self):
        response = upload_csv(
            self.client, "new.csv", b"meter_id,timestamp,energy_kwh\nCH-DELETE-1,2026-02-10,1\n",
            zev_id=str(self.zev.pk), overwrite_existing="true",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["rows_overwritten"], 0)
        deleted = self.client.delete(f"/api/v1/metering/import-logs/{response.data['id']}/")
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(deleted.data["deleted_readings"], 1)

    def test_unexpected_import_failure_records_durable_failed_log(self):
        # The import transaction rolls back readings and its own log save,
        # but the failed attempt is recorded durably on the pre-created log
        # and reported as an actionable error instead of an untraced 500.
        original = self._create_import_log_with_reading(
            zev=self.zev, metering_point=self.metering_point,
            created_at=datetime(2026, 2, 10, tzinfo=timezone.utc),
        )
        file = SimpleUploadedFile("interrupted.csv", b"meter_id,timestamp,energy_kwh\nCH-DELETE-1,2026-02-10,2\nCH-DELETE-1,2026-02-11,3\n")
        calls = 0

        def interrupted_write(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("Interrupted import")
            return _upsert_reading(*args, **kwargs)

        with patch("metering.importers.csv_importer._upsert_reading", side_effect=interrupted_write):
            with self.assertRaisesRegex(ImportFileError, "Interrupted import"):
                import_csv(file, self.owner, zev=self.zev, overwrite_existing=True)
        self.assertEqual(ImportLog.objects.count(), 2)
        failed = ImportLog.objects.exclude(pk=original.pk).get()
        self.assertEqual(failed.rows_imported, 0)
        self.assertEqual(failed.rows_overwritten, 0)
        self.assertEqual(failed.rows_skipped, 2)
        self.assertTrue(any("Interrupted import" in err["error"] for err in failed.errors))
        reading = MeterReading.objects.get()
        self.assertEqual(reading.energy_kwh, Decimal("1"))
        self.assertEqual(reading.import_batch, original.batch_id)

    def test_import_log_admin_is_read_only(self):
        # Overwrite protection lives in the application's deletion workflow;
        # the admin must not offer an unprotected delete (which would also
        # orphan readings by skipping the batch cleanup).
        from django.contrib import admin

        from metering.models import ImportLog as ImportLogModel

        model_admin = admin.site._registry[ImportLogModel]
        self.assertFalse(model_admin.has_add_permission(None))
        self.assertFalse(model_admin.has_delete_permission(None))

    def test_legacy_overwrite_notes_are_backfilled_and_protected(self):
        migration = import_module("metering.migrations.0005_importlog_rows_overwritten")
        for field, key in (("errors", "error"), ("warnings", "warning")):
            with self.subTest(field=field):
                log = ImportLog.objects.create(
                    zev=self.zev, imported_by=self.owner, source=ImportSource.CSV,
                    **{field: [{"row": None, key: "Overwrote 3 existing readings."}]},
                )
                migration.backfill_overwrites(apps, SimpleNamespace(connection=connection))
                log.refresh_from_db()
                self.assertEqual(log.rows_overwritten, 3)
                response = self.client.delete(f"/api/v1/metering/import-logs/{log.pk}/")
                self.assertEqual(response.status_code, 400)

    def test_bulk_delete_rejects_impossible_and_unbounded_dates(self):
        for value in ("2026-02-30", "9999-12-31", 123):
            with self.subTest(value=value):
                response = self.client.post(
                    "/api/v1/metering/import-logs/bulk-delete/",
                    {"mode": "period", "date_from": "2026-01-01", "date_to": value}, format="json",
                )
                self.assertEqual(response.status_code, 400)

    def test_bulk_delete_period_only_removes_logs_in_selected_created_at_range(self):
        log_in_range = self._create_import_log_with_reading(
            zev=self.zev,
            metering_point=self.metering_point,
            created_at=datetime(2026, 3, 10, 9, 0, tzinfo=timezone.utc),
        )
        log_out_of_range = self._create_import_log_with_reading(
            zev=self.zev,
            metering_point=self.metering_point,
            created_at=datetime(2026, 4, 2, 9, 0, tzinfo=timezone.utc),
        )

        resp = self.client.post(
            "/api/v1/metering/import-logs/bulk-delete/",
            {
                "mode": "period",
                "date_from": "2026-03-01",
                "date_to": "2026-03-31",
            },
            format="json",
        )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["deleted_logs"], 1)
        self.assertEqual(resp.data["deleted_readings"], 1)
        self.assertFalse(ImportLog.objects.filter(pk=log_in_range.id).exists())
        self.assertTrue(ImportLog.objects.filter(pk=log_out_of_range.id).exists())

    def test_bulk_delete_all_without_zev_covers_all_visible_zevs(self):
        second_zev = create_managed_zev(name="Second Imports ZEV", owner=self.owner, zev_type="vzev", invoice_prefix="S")
        second_meter = MeteringPoint.objects.create(
            zev=second_zev,
            meter_id="CH-DELETE-SECOND",
            meter_type=MeteringPointType.CONSUMPTION,
        )
        own_log = self._create_import_log_with_reading(
            zev=self.zev,
            metering_point=self.metering_point,
            created_at=datetime(2026, 5, 1, 10, 0, tzinfo=timezone.utc),
        )
        second_log = self._create_import_log_with_reading(
            zev=second_zev,
            metering_point=second_meter,
            created_at=datetime(2026, 5, 2, 10, 0, tzinfo=timezone.utc),
        )
        foreign_log = self._create_import_log_with_reading(
            zev=self.other_zev,
            metering_point=self.other_metering_point,
            created_at=datetime(2026, 5, 3, 10, 0, tzinfo=timezone.utc),
            imported_by=self.other_owner,
        )

        resp = self.client.post(
            "/api/v1/metering/import-logs/bulk-delete/",
            {"mode": "all"},
            format="json",
        )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["deleted_logs"], 2)
        self.assertFalse(ImportLog.objects.filter(pk=own_log.id).exists())
        self.assertFalse(ImportLog.objects.filter(pk=second_log.id).exists())
        self.assertTrue(ImportLog.objects.filter(pk=foreign_log.id).exists())

    def test_bulk_delete_all_can_be_scoped_to_selected_zev(self):
        own_log = self._create_import_log_with_reading(
            zev=self.zev,
            metering_point=self.metering_point,
            created_at=datetime(2026, 5, 1, 10, 0, tzinfo=timezone.utc),
        )
        other_log = self._create_import_log_with_reading(
            zev=self.other_zev,
            metering_point=self.other_metering_point,
            created_at=datetime(2026, 5, 2, 10, 0, tzinfo=timezone.utc),
        )

        resp = self.client.post(
            "/api/v1/metering/import-logs/bulk-delete/",
            {
                "mode": "all",
                "zev_id": str(self.zev.id),
            },
            format="json",
        )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["deleted_logs"], 1)
        self.assertEqual(resp.data["deleted_readings"], 1)
        self.assertFalse(ImportLog.objects.filter(pk=own_log.id).exists())
        self.assertTrue(ImportLog.objects.filter(pk=other_log.id).exists())

    def test_single_delete_audit_event_is_scoped_to_the_zev(self):
        log = self._create_import_log_with_reading(
            zev=self.zev,
            metering_point=self.metering_point,
            created_at=datetime(2026, 2, 10, 8, 0, tzinfo=timezone.utc),
        )

        self.client.delete(f"/api/v1/metering/import-logs/{log.id}/")

        event = AuditEvent.objects.get(action_type="import_log.delete")
        self.assertEqual(event.zev_id, self.zev.id)
        listed = self.client.get("/api/v1/audit/events/?action_type=import_log.delete")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.data["count"], 1)

    def test_bulk_delete_records_one_scoped_audit_event_per_zev(self):
        second_zev = create_managed_zev(name="Second Audit ZEV", owner=self.owner, zev_type="vzev", invoice_prefix="A")
        second_meter = MeteringPoint.objects.create(
            zev=second_zev, meter_id="CH-DELETE-AUDIT", meter_type=MeteringPointType.CONSUMPTION
        )
        self._create_import_log_with_reading(
            zev=self.zev,
            metering_point=self.metering_point,
            created_at=datetime(2026, 5, 1, 10, 0, tzinfo=timezone.utc),
        )
        self._create_import_log_with_reading(
            zev=second_zev,
            metering_point=second_meter,
            created_at=datetime(2026, 5, 2, 10, 0, tzinfo=timezone.utc),
        )
        self._create_import_log_with_reading(
            zev=second_zev,
            metering_point=second_meter,
            created_at=datetime(2026, 5, 3, 10, 0, tzinfo=timezone.utc),
        )

        resp = self.client.post("/api/v1/metering/import-logs/bulk-delete/", {"mode": "all"}, format="json")

        self.assertEqual(resp.data["deleted_logs"], 3)
        self.assertEqual(resp.data["deleted_readings"], 3)
        events = {e.zev_id: e for e in AuditEvent.objects.filter(action_type="import_log.bulk_delete")}
        self.assertEqual(set(events), {self.zev.id, second_zev.id})
        self.assertEqual(events[self.zev.id].metadata_json["deleted_logs"], 1)
        self.assertEqual(events[second_zev.id].metadata_json["deleted_logs"], 2)
        self.assertEqual(events[second_zev.id].metadata_json["deleted_readings"], 2)

    def test_bulk_delete_audit_event_hidden_from_other_zev_owner(self):
        self._create_import_log_with_reading(
            zev=self.zev,
            metering_point=self.metering_point,
            created_at=datetime(2026, 5, 1, 10, 0, tzinfo=timezone.utc),
        )
        self.client.post("/api/v1/metering/import-logs/bulk-delete/", {"mode": "all"}, format="json")

        other_client = APIClient()
        auth(other_client, self.other_owner)
        listed = other_client.get("/api/v1/audit/events/?action_type=import_log.bulk_delete")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.data["count"], 0)

    def test_bulk_delete_does_not_scope_audit_event_to_unowned_zev_id(self):
        self._create_import_log_with_reading(
            zev=self.zev,
            metering_point=self.metering_point,
            created_at=datetime(2026, 5, 1, 10, 0, tzinfo=timezone.utc),
        )

        self.client.post(
            "/api/v1/metering/import-logs/bulk-delete/",
            {"mode": "all", "zev_id": str(self.other_zev.id)},
            format="json",
        )

        event = AuditEvent.objects.get(action_type="import_log.bulk_delete")
        self.assertIsNone(event.zev_id)
        self.assertEqual(event.metadata_json["deleted_logs"], 0)

    def test_bulk_delete_rejects_malformed_zev_id(self):
        resp = self.client.post(
            "/api/v1/metering/import-logs/bulk-delete/",
            {"mode": "all", "zev_id": "not-a-uuid"},
            format="json",
        )

        self.assertEqual(resp.status_code, 400)

    def test_bulk_delete_period_uses_utc_boundaries(self):
        log_before = self._create_import_log_with_reading(
            zev=self.zev,
            metering_point=self.metering_point,
            created_at=datetime(2026, 3, 1, 23, 30, tzinfo=timezone.utc),
        )
        log_after = self._create_import_log_with_reading(
            zev=self.zev,
            metering_point=self.metering_point,
            created_at=datetime(2026, 4, 1, 0, 0, tzinfo=timezone.utc),
        )

        resp = self.client.post(
            "/api/v1/metering/import-logs/bulk-delete/",
            {
                "mode": "period",
                "date_from": "2026-03-01",
                "date_to": "2026-03-31",
            },
            format="json",
        )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["deleted_logs"], 1)
        self.assertFalse(ImportLog.objects.filter(pk=log_before.id).exists())
        self.assertTrue(ImportLog.objects.filter(pk=log_after.id).exists())

    def test_bulk_delete_rejects_invalid_period_payload(self):
        resp = self.client.post(
            "/api/v1/metering/import-logs/bulk-delete/",
            {
                "mode": "period",
                "date_from": "2026-06-10",
                "date_to": "2026-06-01",
            },
            format="json",
        )

        self.assertEqual(resp.status_code, 400)

    def test_import_log_list_exposes_human_readable_identity(self):
        log = self._create_import_log_with_reading(
            zev=self.zev,
            metering_point=self.metering_point,
            created_at=datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc),
        )

        resp = self.client.get("/api/v1/metering/import-logs/")

        self.assertEqual(resp.status_code, 200)
        entry = next(item for item in resp.data["results"] if str(item["id"]) == str(log.id))
        self.assertEqual(entry["zev_name"], "Delete Imports ZEV")
        self.assertEqual(entry["imported_by_display"], self.owner.username)
        self.assertEqual(entry["batch_id"], str(log.batch_id))


class ImportLogCommitVisibilityTests(TransactionTestCase):
    """The successful import log must not exist before the import commits.

    Two-connection regression test: pause the importer inside its
    transaction and assert a second connection sees (and therefore cannot
    delete) no log row yet. Deleting an unfinished import and having it
    reappear on commit must be impossible by construction.
    """

    def setUp(self):
        self.owner = make_user("import_visibility_owner", UserRole.USER)
        self.zev = create_managed_zev(
            name="Visibility ZEV", owner=self.owner, zev_type="vzev", invoice_prefix="V"
        )
        self.metering_point = MeteringPoint.objects.create(
            zev=self.zev, meter_id="CH-VIS-1", meter_type=MeteringPointType.CONSUMPTION
        )

    @skipUnless(connection.vendor == "postgresql", "requires cross-connection visibility")
    def test_sdat_log_is_not_deletable_before_readings_commit(self):
        from metering.importers import sdatch_importer
        from testing.sdat import build_e66, quarter_block
        meter_id = "CH9999901234500000000000000000001"
        self.metering_point.meter_id = meter_id
        self.metering_point.save(update_fields=["meter_id"])
        entered = threading.Event()
        release = threading.Event()
        outcome = {}
        original = sdatch_importer._apply_plan

        def pause(**kwargs):
            entered.set()
            self.assertTrue(release.wait(10))
            return original(**kwargs)

        def upload():
            try:
                content = build_e66([quarter_block(meter_id, "2025-06-10T00:00:00Z", 4)])
                outcome["log"] = sdatch_importer.import_sdatch(SimpleUploadedFile("pending.xml", content), self.zev, self.owner)
            except Exception as exc:
                outcome["error"] = exc
            finally:
                connection.close()

        with patch.object(sdatch_importer, "_apply_plan", side_effect=pause):
            worker = threading.Thread(target=upload)
            worker.start()
            try:
                self.assertTrue(entered.wait(10))
                self.assertEqual(ImportLog.objects.count(), 0)
                self.assertEqual(MeterReading.objects.count(), 0)
            finally:
                release.set()
                worker.join(15)
        self.assertFalse(worker.is_alive())
        self.assertNotIn("error", outcome)
        self.assertEqual(ImportLog.objects.count(), 1)
        self.assertEqual(MeterReading.objects.count(), 4)

    @skipUnless(connection.vendor == "postgresql", "requires cross-connection transaction isolation")
    def test_successful_log_invisible_until_commit(self):
        from django.db import connection as default_connection

        entered = threading.Event()
        release = threading.Event()
        real_rows = csv_importer._import_table_rows

        def paused_rows(*args, **kwargs):
            entered.set()
            self.assertTrue(release.wait(timeout=30), "importer did not pause inside its transaction")
            return real_rows(*args, **kwargs)

        outcome = {}

        def run_import():
            try:
                file = SimpleUploadedFile(
                    "visibility.csv",
                    b"meter_id,timestamp,energy_kwh\nCH-VIS-1,2026-02-10T00:00:00Z,2.5\n",
                )
                outcome["log"] = csv_importer.import_csv(file, self.owner, zev=self.zev)
            except Exception as exc:
                outcome["error"] = exc
            finally:
                default_connection.close()

        with patch.object(csv_importer, "_import_table_rows", side_effect=paused_rows):
            worker = threading.Thread(target=run_import)
            worker.start()
            try:
                self.assertTrue(entered.wait(timeout=30), "importer did not reach its transaction")
                # Second connection: nothing committed yet, so there is
                # nothing to delete.
                self.assertEqual(ImportLog.objects.count(), 0)
                self.assertEqual(MeterReading.objects.count(), 0)
            finally:
                release.set()
            worker.join(timeout=60)
            self.assertFalse(worker.is_alive(), "importer thread hung")

        self.assertNotIn("error", outcome)
        self.assertEqual(ImportLog.objects.count(), 1)
        self.assertEqual(MeterReading.objects.count(), 1)
        self.assertEqual(outcome["log"].rows_imported, 1)

    @skipUnless(connection.vendor == "postgresql", "requires row locks across connections")
    def test_captured_deletion_evidence_stays_locked_until_commit(self):
        batch_id = uuid.uuid4()
        models = (MeterReading, QuarantinedReading)
        for model in models:
            model.objects.create(
                metering_point=self.metering_point, import_batch=batch_id,
                timestamp=datetime(2026, 2, 10, tzinfo=timezone.utc), energy_kwh=Decimal("1"),
            )
        errors = []

        def overwrite():
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '100ms'")
                for model in models:
                    try:
                        model.objects.filter(import_batch=batch_id).update(energy_kwh=Decimal("2"))
                    except OperationalError as exc:
                        errors.append(str(exc))
            finally:
                connection.close()

        with transaction.atomic():
            slots, truncated = collect_deleted_slots([batch_id])
            self.assertEqual(len(slots), 2)
            self.assertFalse(truncated)
            worker = threading.Thread(target=overwrite)
            worker.start()
            worker.join(timeout=10)
            self.assertFalse(worker.is_alive(), "concurrent writer did not finish")
            self.assertEqual(len(errors), 2)
            self.assertTrue(all("lock timeout" in error for error in errors), errors)
        for model in models:
            self.assertEqual(model.objects.get(import_batch=batch_id).energy_kwh, Decimal("1"))


SDAT_CONS_ID = "CH9999901234500000000000000000001"
C38_REASON = '<rsm:VSENationalCode>C38</rsm:VSENationalCode>'


class SdatHeldDeletionTests(TestCase):
    """Single/period/all deletion over billable and held (quarantine) streams."""

    def setUp(self):
        self.client = APIClient()
        self.owner = make_user("sdat_delete_owner", UserRole.USER)
        self.zev = create_managed_zev(name="SDAT Delete ZEV", owner=self.owner, zev_type="vzev", invoice_prefix="SD")
        # After the grant: promoting the account retires tokens minted before it.
        auth(self.client, self.owner)
        self.metering_point = MeteringPoint.objects.create(
            zev=self.zev, meter_id=SDAT_CONS_ID, meter_type=MeteringPointType.CONSUMPTION,
        )

    def _sdat_log(self, *, rows_overwritten=0, quarantine_overwritten=0, filename="sdat.xml"):
        batch_id = uuid.uuid4()
        return ImportLog.objects.create(
            batch_id=batch_id,
            zev=self.zev,
            imported_by=self.owner,
            source=ImportSource.SDATCH,
            filename=filename,
            rows_total=4,
            rows_imported=4,
            rows_overwritten=rows_overwritten,
            rows_skipped=0,
            result_status="accepted",
            result_counts={"created": 4, "overwritten": rows_overwritten, "quarantine_overwritten": quarantine_overwritten},
        )

    def _add_rows(self, batch_id, *, billable=0, held=0, day=10):
        for index in range(billable):
            MeterReading.objects.create(
                metering_point=self.metering_point,
                timestamp=datetime(2026, 2, day, index, tzinfo=timezone.utc),
                energy_kwh=Decimal("1.0000"),
                direction=ReadingDirection.IN,
                resolution=ReadingResolution.FIFTEEN_MIN,
                import_source=ImportSource.SDATCH,
                import_batch=batch_id,
            )
        for index in range(held):
            QuarantinedReading.objects.create(
                metering_point=self.metering_point,
                timestamp=datetime(2026, 3, day, index, tzinfo=timezone.utc),
                energy_kwh=Decimal("2.0000"),
                direction=ReadingDirection.IN,
                resolution=ReadingResolution.FIFTEEN_MIN,
                import_batch=batch_id,
                business_reason="C38",
                condition="21",
            )

    def _import(self, content):
        upload = SimpleUploadedFile("derived.xml", content, content_type="application/xml")
        return self.client.post(
            "/api/v1/metering/import/sdatch/",
            {"file": upload, "zev_id": str(self.zev.id)},
            format="multipart",
        )

    def test_mixed_billable_and_held_delete_removes_both_streams(self):
        log = self._sdat_log()
        self._add_rows(log.batch_id, billable=2, held=2)
        other = self._sdat_log(filename="other.xml")
        self._add_rows(other.batch_id, billable=1, held=1, day=12)

        resp = self.client.delete(f"/api/v1/metering/import-logs/{log.id}/")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["deleted_logs"], 1)
        self.assertEqual(resp.data["deleted_readings"], 2)
        self.assertEqual(resp.data["deleted_quarantined_readings"], 2)
        self.assertFalse(ImportLog.objects.filter(pk=log.id).exists())
        self.assertEqual(MeterReading.objects.filter(import_batch=log.batch_id).count(), 0)
        self.assertEqual(QuarantinedReading.objects.filter(import_batch=log.batch_id).count(), 0)
        self.assertEqual(MeterReading.objects.filter(import_batch=other.batch_id).count(), 1)
        self.assertEqual(QuarantinedReading.objects.filter(import_batch=other.batch_id).count(), 1)

    def test_disabled_community_blocks_single_and_bulk_deletion(self):
        log = self._sdat_log()
        self._add_rows(log.batch_id, billable=1, held=1)
        self.zev.disabled_at = datetime(2026, 10, 1, tzinfo=timezone.utc)
        self.zev.save(update_fields=["disabled_at"])
        for bulk in (False, True):
            with self.subTest(bulk=bulk):
                response = (
                    self.client.post("/api/v1/metering/import-logs/bulk-delete/", {"mode": "all"}, format="json")
                    if bulk else self.client.delete(f"/api/v1/metering/import-logs/{log.id}/")
                )
                self.assertEqual(response.status_code, 400)
                self.assertTrue(ImportLog.objects.filter(pk=log.pk).exists())
                self.assertEqual(MeterReading.objects.count(), 1)
                self.assertEqual(QuarantinedReading.objects.count(), 1)

        auth(self.client, make_user("disabled_delete_admin", UserRole.ADMIN))
        response = self.client.delete(f"/api/v1/metering/import-logs/{log.id}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["deleted_quarantined_readings"], 1)

    def test_audit_failure_rolls_back_single_and_bulk_deletion(self):
        log = self._sdat_log()
        self._add_rows(log.batch_id, billable=1, held=1)
        for bulk in (False, True):
            with self.subTest(bulk=bulk), patch("metering.views.record_audit_event", side_effect=RuntimeError("audit failed")):
                with self.assertRaisesRegex(RuntimeError, "audit failed"):
                    if bulk:
                        self.client.post("/api/v1/metering/import-logs/bulk-delete/", {"mode": "all"}, format="json")
                    else:
                        self.client.delete(f"/api/v1/metering/import-logs/{log.id}/")
                self.assertTrue(ImportLog.objects.filter(pk=log.pk).exists())
                self.assertEqual(MeterReading.objects.count(), 1)
                self.assertEqual(QuarantinedReading.objects.count(), 1)

    def test_held_only_delete_leaves_no_orphans_and_frees_selection(self):
        held = self._import(build_e66(
            [quarter_block(SDAT_CONS_ID, "2025-06-02T22:00:00Z", 4)],
            reason_xml=C38_REASON, creation="2025-06-04T10:00:00Z", delivery_id="HELD-ONLY",
        ))
        self.assertEqual(held.status_code, 201)
        self.assertEqual(held.data["result_status"], "held")
        log_id = held.data["id"]

        resp = self.client.delete(f"/api/v1/metering/import-logs/{log_id}/")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["deleted_quarantined_readings"], 4)
        self.assertEqual(QuarantinedReading.objects.count(), 0)
        replay = self._import(build_e66(
            [quarter_block(SDAT_CONS_ID, "2025-06-02T22:00:00Z", 4)],
            reason_xml=C38_REASON, creation="2025-06-04T10:00:00Z", delivery_id="HELD-ONLY",
        ))
        self.assertEqual(replay.data["result_status"], "held")
        self.assertEqual(replay.data["result_counts"]["held"], 4)

    def test_held_replacement_without_billable_overwrites_is_protected(self):
        log = self._sdat_log(quarantine_overwritten=2)
        self._add_rows(log.batch_id, held=2)

        resp = self.client.delete(f"/api/v1/metering/import-logs/{log.id}/")

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["code"], "quarantine_replace_protected")
        self.assertTrue(ImportLog.objects.filter(pk=log.id).exists())
        self.assertEqual(QuarantinedReading.objects.filter(import_batch=log.batch_id).count(), 2)

    def test_mixed_bulk_with_held_protected_rolls_back_entirely(self):
        additive = self._sdat_log(filename="additive.xml")
        self._add_rows(additive.batch_id, billable=1, held=1)
        protected = self._sdat_log(filename="replacer.xml", quarantine_overwritten=1)
        self._add_rows(protected.batch_id, held=1, day=12)

        resp = self.client.post("/api/v1/metering/import-logs/bulk-delete/", {"mode": "all"}, format="json")

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["code"], "quarantine_replace_protected")
        self.assertEqual(ImportLog.objects.count(), 2)
        self.assertEqual(MeterReading.objects.count(), 1)
        self.assertEqual(QuarantinedReading.objects.count(), 2)

    def test_billable_overwrite_reports_overwrite_code(self):
        log = self._sdat_log(rows_overwritten=3)
        self._add_rows(log.batch_id, billable=3)

        resp = self.client.delete(f"/api/v1/metering/import-logs/{log.id}/")

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["code"], "overwrite_import_protected")

    def test_quarantine_update_replacer_is_protected_and_predecessor_frees_nothing(self):
        first = self._import(build_e66(
            [quarter_block(SDAT_CONS_ID, "2025-06-02T22:00:00Z", 4)],
            reason_xml=C38_REASON, creation="2025-06-04T10:00:00Z", delivery_id="HELD-V1",
        ))
        second = self._import(build_e66(
            [quarter_block(SDAT_CONS_ID, "2025-06-02T22:00:00Z", 4, doc="HELD-V2-BLK")],
            reason_xml=C38_REASON, status="5", creation="2025-06-05T10:00:00Z", delivery_id="HELD-V2",
        ))
        self.assertEqual(second.data["result_counts"]["quarantine_overwritten"], 4)

        blocked = self.client.delete(f"/api/v1/metering/import-logs/{second.data['id']}/")
        self.assertEqual(blocked.status_code, 400)
        self.assertEqual(blocked.data["code"], "quarantine_replace_protected")

        freed = self.client.delete(f"/api/v1/metering/import-logs/{first.data['id']}/")
        self.assertEqual(freed.status_code, 200)
        self.assertEqual(freed.data["deleted_quarantined_readings"], 0)
        self.assertEqual(QuarantinedReading.objects.count(), 4)

    def test_promotion_keeps_association_and_neither_log_is_protected(self):
        held = self._import(build_e66(
            [quarter_block(SDAT_CONS_ID, "2025-06-02T22:00:00Z", 4)],
            reason_xml=C38_REASON, creation="2025-06-04T10:00:00Z", delivery_id="PROM-HELD",
        ))
        billed = self._import(build_e66(
            [quarter_block(SDAT_CONS_ID, "2025-06-02T22:00:00Z", 4, doc="PROM-BILL")],
            creation="2025-06-05T10:00:00Z", delivery_id="PROM-BILL",
        ))
        self.assertEqual(billed.data["result_status"], "accepted")
        self.assertEqual(billed.data["result_counts"]["promoted"], 4)
        self.assertEqual(QuarantinedReading.objects.count(), 0)

        listed = self.client.get("/api/v1/metering/import-logs/")
        by_id = {entry["id"]: entry for entry in listed.data["results"]}
        self.assertTrue(by_id[str(held.data["id"])]["deletable"])
        self.assertIsNone(by_id[str(held.data["id"])]["deletion_protection_code"])
        self.assertTrue(by_id[str(billed.data["id"])]["deletable"])

        drop_held = self.client.delete(f"/api/v1/metering/import-logs/{held.data['id']}/")
        self.assertEqual(drop_held.status_code, 200)
        self.assertEqual(drop_held.data["deleted_quarantined_readings"], 0)
        self.assertEqual(MeterReading.objects.count(), 4)
        drop_billed = self.client.delete(f"/api/v1/metering/import-logs/{billed.data['id']}/")
        self.assertEqual(drop_billed.status_code, 200)
        self.assertEqual(drop_billed.data["deleted_readings"], 4)
        self.assertEqual(MeterReading.objects.count(), 0)
        self.assertEqual(QuarantinedReading.objects.count(), 0)

    def test_billable_replace_replacer_is_protected_and_predecessor_keeps_new_values(self):
        original = self._import(build_e66([quarter_block(SDAT_CONS_ID, "2025-06-02T22:00:00Z", 4)]))
        obs = "".join(
            f"<rsm:Observation><rsm:Position><rsm:Sequence>{seq}</rsm:Sequence></rsm:Position>"
            f"<rsm:Volume>{200 + seq}</rsm:Volume></rsm:Observation>"
            for seq in range(1, 5)
        )

        replacer = self._import(build_e66(
            [build_block(SDAT_CONS_ID, obs, doc="REPL-BLK")],
            status="5", creation="2025-06-06T10:00:00Z", delivery_id="REPL-1",
        ))
        self.assertEqual(replacer.data["rows_overwritten"], 4)

        blocked = self.client.delete(f"/api/v1/metering/import-logs/{replacer.data['id']}/")
        self.assertEqual(blocked.status_code, 400)
        self.assertEqual(blocked.data["code"], "overwrite_import_protected")

        freed = self.client.delete(f"/api/v1/metering/import-logs/{original.data['id']}/")
        self.assertEqual(freed.status_code, 200)
        self.assertEqual(freed.data["deleted_readings"], 0)
        kept = list(MeterReading.objects.order_by("timestamp").values_list("energy_kwh", flat=True))
        self.assertEqual(kept, [Decimal("201"), Decimal("202"), Decimal("203"), Decimal("204")])

    def test_deletion_audit_carries_held_counts_and_slot_evidence(self):
        log = self._sdat_log()
        self._add_rows(log.batch_id, billable=1, held=1)

        self.client.delete(f"/api/v1/metering/import-logs/{log.id}/")

        event = AuditEvent.objects.get(action_type="import_log.delete")
        self.assertEqual(event.metadata_json["deleted_quarantined_readings"], 1)
        streams = sorted(slot["stream"] for slot in event.metadata_json["deleted_slots"])
        self.assertEqual(streams, ["billable", "held"])
        self.assertFalse(event.metadata_json["deleted_slots_truncated"])

    def test_bulk_audit_marks_evidence_limited_by_audit_redaction(self):
        log = self._sdat_log()
        self._add_rows(log.batch_id, held=21)
        response = self.client.post("/api/v1/metering/import-logs/bulk-delete/", {"mode": "all"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["deleted_slots_truncated"])
        event = AuditEvent.objects.get(action_type="import_log.bulk_delete")
        self.assertTrue(event.metadata_json["deleted_slots_truncated"])
        self.assertEqual(len(event.metadata_json["deleted_slots"]), 20)

    def test_malformed_replacement_evidence_does_not_allow_deletion(self):
        log = self._sdat_log()
        self._add_rows(log.batch_id, held=1)
        for counts in ({"quarantine_overwritten": "bad"}, {"quarantine_overwritten": -1}, []):
            with self.subTest(counts=counts):
                ImportLog.objects.filter(pk=log.pk).update(result_counts=counts)
                response = self.client.delete(f"/api/v1/metering/import-logs/{log.id}/")
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.data["code"], "quarantine_replace_protected")
                self.assertEqual(QuarantinedReading.objects.count(), 1)

    def test_legacy_log_cannot_delete_readings_in_a_community_no_longer_managed(self):
        log = self._sdat_log()
        log.zev = None
        log.save(update_fields=["zev"])
        self._add_rows(log.batch_id, billable=1, held=1)
        other_owner = make_user("legacy_delete_other", UserRole.USER)
        other_zev = create_managed_zev(name="Legacy foreign community", owner=other_owner)
        # Reproduce legacy moved history, which current model writes now prohibit.
        MeteringPoint.objects.filter(pk=self.metering_point.pk).update(zev=other_zev)
        from unittest.mock import patch

        with patch("metering.views.lock_billing_inputs") as lock:
            response = self.client.delete(f"/api/v1/metering/import-logs/{log.id}/")
        lock.assert_not_called()
        self.assertEqual(response.status_code, 403)
        self.assertTrue(ImportLog.objects.filter(pk=log.pk).exists())
        self.assertEqual(MeterReading.objects.count(), 1)
        self.assertEqual(QuarantinedReading.objects.count(), 1)


    def test_moved_reading_evidence_is_audited_only_in_its_current_community(self):
        log = self._sdat_log()
        self._add_rows(log.batch_id, billable=1, held=1)
        other = create_managed_zev(name="Moved reading history", owner=self.owner)
        MeteringPoint.objects.filter(pk=self.metering_point.pk).update(zev=other)
        response = self.client.delete(f"/api/v1/metering/import-logs/{log.id}/")
        self.assertEqual(response.status_code, 200, response.content)
        old_event = AuditEvent.objects.get(action_type="import_log.delete", zev=self.zev)
        new_event = AuditEvent.objects.get(action_type="import_log.delete", zev=other)
        self.assertEqual(old_event.metadata_json["deleted_slots"], [])
        self.assertEqual(old_event.metadata_json["deleted_readings"], 0)
        self.assertEqual(new_event.metadata_json["deleted_logs"], 0)
        self.assertEqual(len(new_event.metadata_json["deleted_slots"]), 2)
