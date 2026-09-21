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
from django.db import connection
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from accounts.models import UserRole
from metering.importers import csv_importer
from metering.models import ImportLog, ImportSource, MeterReading, ReadingDirection, ReadingResolution
from metering.testing import upload_csv
from metering.importers.csv_importer import ImportFileError, import_csv, _upsert_reading
from testing.helpers import authenticate as auth, make_user
from zev.models import MeteringPoint, MeteringPointType, Participant, Zev


class ImportLogDeletionTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = make_user("import_delete_owner", UserRole.ZEV_OWNER)
        self.other_owner = make_user("import_delete_other", UserRole.ZEV_OWNER)
        auth(self.client, self.owner)

        self.zev = Zev.objects.create(name="Delete Imports ZEV", owner=self.owner, zev_type="vzev", invoice_prefix="D")
        self.other_zev = Zev.objects.create(name="Other Imports ZEV", owner=self.other_owner, zev_type="vzev", invoice_prefix="O")
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

    def test_delete_single_import_log_removes_log_and_imported_readings(self):
        created_at = datetime(2026, 2, 10, 8, 0, tzinfo=timezone.utc)
        log = self._create_import_log_with_reading(zev=self.zev, metering_point=self.metering_point, created_at=created_at)

        resp = self.client.delete(f"/api/v1/metering/import-logs/{log.id}/")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["deleted_logs"], 1)
        self.assertEqual(resp.data["deleted_readings"], 1)
        self.assertFalse(ImportLog.objects.filter(pk=log.id).exists())
        self.assertEqual(MeterReading.objects.filter(import_batch=log.batch_id).count(), 0)

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
            options = {"col_energy_start": "v1", "values_count": 2}
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
        second_zev = Zev.objects.create(name="Second Imports ZEV", owner=self.owner, zev_type="vzev", invoice_prefix="S")
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
        self.owner = make_user("import_visibility_owner", UserRole.ZEV_OWNER)
        self.zev = Zev.objects.create(
            name="Visibility ZEV", owner=self.owner, zev_type="vzev", invoice_prefix="V"
        )
        self.metering_point = MeteringPoint.objects.create(
            zev=self.zev, meter_id="CH-VIS-1", meter_type=MeteringPointType.CONSUMPTION
        )

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
