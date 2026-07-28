"""CSV/Excel metering import tests."""

from datetime import date, datetime, timezone
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import User, UserRole
from metering.models import ImportLog, MeterReading, ReadingDirection
from testing.helpers import authenticate as auth
from zev.models import MeteringPoint, MeteringPointAssignment, MeteringPointType, Participant, Zev


def make_user(username, role, password="pass1234"):
    return User.objects.create_user(username=username, password=password, role=role)


class CsvImportTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = make_user("csv_import_owner", UserRole.ZEV_OWNER)
        self.other_owner = make_user("csv_import_other_owner", UserRole.ZEV_OWNER)
        auth(self.client, self.owner)

        self.zev = Zev.objects.create(name="CSV Import ZEV", owner=self.owner, zev_type="vzev", invoice_prefix="C")
        self.other_zev = Zev.objects.create(name="Other CSV ZEV", owner=self.other_owner, zev_type="vzev", invoice_prefix="O")
        self.participant = Participant.objects.create(
            zev=self.zev,
            first_name="CSV",
            last_name="Participant",
            email="csv.participant@example.com",
            valid_from=date(2026, 1, 1),
        )
        self.metering_point = MeteringPoint.objects.create(
            zev=self.zev,
            meter_id="CH-IMPORT-1",
            meter_type=MeteringPointType.CONSUMPTION,
        )
        MeteringPointAssignment.objects.create(
            metering_point=self.metering_point,
            participant=self.participant,
            valid_from=date(2026, 1, 1),
        )
        self.other_metering_point = MeteringPoint.objects.create(
            zev=self.other_zev,
            meter_id="CH-IMPORT-OTHER",
            meter_type=MeteringPointType.CONSUMPTION,
        )

    def _upload(self, name, content, **fields):
        upload = SimpleUploadedFile(name, content, content_type="text/csv")
        return self.client.post("/api/v1/metering/import/csv/", {"file": upload, **fields}, format="multipart")

    def _preview(self, name, content, **fields):
        upload = SimpleUploadedFile(name, content, content_type="text/csv")
        return self.client.post("/api/v1/metering/import/preview-csv/", {"file": upload, **fields}, format="multipart")

    def test_malformed_csv_payload_is_reported_without_crash(self):
        resp = self._upload("bad.csv", b"wrong_col1,wrong_col2\nfoo,bar\n")

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["rows_imported"], 0)
        self.assertGreaterEqual(resp.data["rows_skipped"], 1)
        self.assertTrue(resp.data["errors"])
        self.assertEqual(MeterReading.objects.count(), 0)

    def test_csv_timezone_offset_is_normalized_to_utc(self):
        csv_bytes = (
            b"meter_id,timestamp,energy_kwh,direction\n"
            b"CH-IMPORT-1,2026-01-01T02:00:00+02:00,1.5000,in\n"
        )

        resp = self._upload("tz.csv", csv_bytes)

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["rows_imported"], 1)
        reading = MeterReading.objects.get(metering_point=self.metering_point)
        self.assertEqual(reading.timestamp, datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc))

    def test_duplicate_rows_are_skipped_and_reported(self):
        csv_bytes = (
            b"meter_id,timestamp,energy_kwh,direction\n"
            b"CH-IMPORT-1,2026-01-02T00:00:00Z,2.0000,in\n"
            b"CH-IMPORT-1,2026-01-02T00:00:00Z,2.0000,in\n"
        )

        resp = self._upload("dupe.csv", csv_bytes)

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["rows_imported"], 1)
        self.assertEqual(resp.data["rows_skipped"], 1)
        self.assertTrue(any("Duplicate reading" in err["error"] for err in resp.data["errors"]))
        self.assertEqual(MeterReading.objects.filter(metering_point=self.metering_point).count(), 1)

    def test_csv_import_is_idempotent_for_repeated_payload(self):
        csv_bytes = (
            b"meter_id,timestamp,energy_kwh,direction\n"
            b"CH-IMPORT-1,2026-01-03T00:00:00Z,3.0000,in\n"
        )

        first_resp = self._upload("idempotent-first.csv", csv_bytes)
        self.assertEqual(first_resp.status_code, 201)
        self.assertEqual(first_resp.data["rows_imported"], 1)

        second_resp = self._upload("idempotent-second.csv", csv_bytes)

        self.assertEqual(second_resp.status_code, 201)
        self.assertEqual(second_resp.data["rows_imported"], 0)
        self.assertGreaterEqual(second_resp.data["rows_skipped"], 1)
        self.assertEqual(MeterReading.objects.filter(metering_point=self.metering_point).count(), 1)

    def test_csv_import_with_overwrite_existing_updates_value_without_new_row(self):
        initial_csv = (
            b"meter_id,timestamp,energy_kwh,direction\n"
            b"CH-IMPORT-1,2026-01-04T00:00:00Z,1.0000,in\n"
        )
        updated_csv = (
            b"meter_id,timestamp,energy_kwh,direction\n"
            b"CH-IMPORT-1,2026-01-04T00:00:00Z,4.5000,in\n"
        )

        first_resp = self._upload("overwrite-first.csv", initial_csv)
        self.assertEqual(first_resp.status_code, 201)
        self.assertEqual(first_resp.data["rows_imported"], 1)

        overwrite_resp = self._upload("overwrite-second.csv", updated_csv, overwrite_existing="true")

        self.assertEqual(overwrite_resp.status_code, 201)
        self.assertEqual(overwrite_resp.data["rows_imported"], 1)
        self.assertTrue(any("Overwrote 1 existing readings." in err["error"] for err in overwrite_resp.data["errors"]))
        self.assertEqual(MeterReading.objects.filter(metering_point=self.metering_point).count(), 1)

        reading = MeterReading.objects.get(
            metering_point=self.metering_point,
            timestamp=datetime(2026, 1, 4, 0, 0, tzinfo=timezone.utc),
            direction=ReadingDirection.IN,
        )
        self.assertEqual(reading.energy_kwh, Decimal("4.5000"))

    def test_preview_csv_reports_accessible_and_missing_meters_without_writing(self):
        csv_bytes = (
            b"meter_id,timestamp,energy_kwh,direction\n"
            b"CH-IMPORT-1,2026-01-05T00:00:00Z,1.0000,in\n"
            b"CH-MISSING,2026-01-05T00:15:00Z,2.0000,in\n"
        )

        resp = self._preview("preview.csv", csv_bytes)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["rows_total"], 2)
        self.assertEqual(resp.data["summary"]["existing_metering_points"], 1)
        self.assertEqual(resp.data["summary"]["missing_metering_points"], 1)
        self.assertEqual(len(resp.data["preview_rows"]), 2)
        self.assertEqual(MeterReading.objects.count(), 0)
        self.assertEqual(ImportLog.objects.count(), 0)

    def test_headerless_csv_uses_index_column_mapping(self):
        csv_bytes = b"CH-IMPORT-1;2026-01-06T00:00:00Z;6,2500;in\n"

        resp = self._upload(
            "headerless.csv",
            csv_bytes,
            has_header="false",
            delimiter=";",
            col_meter_id="0",
            col_timestamp="1",
            col_energy_kwh="2",
            col_direction="3",
        )

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["rows_imported"], 1)
        reading = MeterReading.objects.get(metering_point=self.metering_point)
        self.assertEqual(reading.energy_kwh, Decimal("6.2500"))

    def test_daily_15min_profile_imports_configured_slots(self):
        csv_bytes = b"meter_id,date,v1,v2\nCH-IMPORT-1,2026-01-07,1.0000,2.0000\n"

        resp = self._upload(
            "daily.csv",
            csv_bytes,
            format_profile="daily_15min",
            col_timestamp="date",
            col_energy_start="2",
            values_count="2",
        )

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["rows_imported"], 2)
        readings = list(MeterReading.objects.filter(metering_point=self.metering_point).order_by("timestamp"))
        self.assertEqual([reading.timestamp for reading in readings], [
            datetime(2026, 1, 7, 0, 0, tzinfo=timezone.utc),
            datetime(2026, 1, 7, 0, 15, tzinfo=timezone.utc),
        ])
        self.assertEqual([reading.energy_kwh for reading in readings], [Decimal("1.0000"), Decimal("2.0000")])

    def test_invalid_direction_is_skipped_and_reported(self):
        csv_bytes = (
            b"meter_id,timestamp,energy_kwh,direction\n"
            b"CH-IMPORT-1,2026-01-08T00:00:00Z,1.0000,sideways\n"
        )

        resp = self._upload("invalid-direction.csv", csv_bytes)

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["rows_imported"], 0)
        self.assertEqual(resp.data["rows_skipped"], 1)
        self.assertTrue(any("Invalid direction" in err["error"] for err in resp.data["errors"]))
        self.assertEqual(MeterReading.objects.count(), 0)

    def test_missing_timestamp_and_energy_are_skipped_and_reported(self):
        csv_bytes = (
            b"meter_id,timestamp,energy_kwh,direction\n"
            b"CH-IMPORT-1,,1.0000,in\n"
            b"CH-IMPORT-1,2026-01-09T00:00:00Z,,in\n"
        )

        resp = self._upload("missing-values.csv", csv_bytes)

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["rows_imported"], 0)
        self.assertEqual(resp.data["rows_skipped"], 2)
        self.assertTrue(any("Missing timestamp value" in err["error"] for err in resp.data["errors"]))
        self.assertTrue(any("Missing numeric value" in err["error"] for err in resp.data["errors"]))
        self.assertEqual(MeterReading.objects.count(), 0)

    def test_owner_cannot_import_meter_from_other_zev(self):
        csv_bytes = (
            b"meter_id,timestamp,energy_kwh,direction\n"
            b"CH-IMPORT-OTHER,2026-01-10T00:00:00Z,1.0000,in\n"
        )

        resp = self._upload("other-zev.csv", csv_bytes)

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["rows_imported"], 0)
        self.assertEqual(resp.data["rows_skipped"], 1)
        self.assertTrue(any("not found or not accessible" in err["error"] for err in resp.data["errors"]))
        self.assertEqual(MeterReading.objects.count(), 0)

    def test_direction_is_inferred_for_production_and_bidirectional_meters(self):
        production_mp = MeteringPoint.objects.create(
            zev=self.zev,
            meter_id="CH-PROD",
            meter_type=MeteringPointType.PRODUCTION,
        )
        bidirectional_mp = MeteringPoint.objects.create(
            zev=self.zev,
            meter_id="CH-BIDI",
            meter_type=MeteringPointType.BIDIRECTIONAL,
        )
        csv_bytes = (
            b"meter_id,timestamp,energy_kwh\n"
            b"CH-PROD,2026-01-11T00:00:00Z,2.0000\n"
            b"CH-BIDI,2026-01-11T00:15:00Z,-3.0000\n"
            b"CH-BIDI,2026-01-11T00:30:00Z,4.0000\n"
        )

        resp = self._upload("inferred-direction.csv", csv_bytes)

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["rows_imported"], 3)
        production_reading = MeterReading.objects.get(metering_point=production_mp)
        self.assertEqual(production_reading.direction, ReadingDirection.OUT)
        self.assertEqual(production_reading.energy_kwh, Decimal("2.0000"))

        bidirectional_readings = list(MeterReading.objects.filter(metering_point=bidirectional_mp).order_by("timestamp"))
        self.assertEqual([reading.direction for reading in bidirectional_readings], [ReadingDirection.OUT, ReadingDirection.IN])
        self.assertEqual([reading.energy_kwh for reading in bidirectional_readings], [Decimal("3.0000"), Decimal("4.0000")])

    def test_import_log_zev_is_inferred_for_single_touched_zev(self):
        csv_bytes = (
            b"meter_id,timestamp,energy_kwh,direction\n"
            b"CH-IMPORT-1,2026-01-12T00:00:00Z,1.0000,in\n"
        )

        resp = self._upload("infer-zev.csv", csv_bytes)

        self.assertEqual(resp.status_code, 201)
        log = ImportLog.objects.get(id=resp.data["id"])
        self.assertEqual(log.zev, self.zev)
        self.assertEqual(str(resp.data["zev"]), str(self.zev.id))
