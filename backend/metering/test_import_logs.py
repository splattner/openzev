"""Metering import log deletion tests."""

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import UserRole
from metering.models import ImportLog, ImportSource, MeterReading, ReadingDirection, ReadingResolution
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

    def _create_import_log_with_reading(self, *, zev, metering_point, created_at):
        batch_id = uuid.uuid4()
        log = ImportLog.objects.create(
            batch_id=batch_id,
            zev=zev,
            imported_by=self.owner,
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
