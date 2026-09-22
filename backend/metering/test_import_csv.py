"""CSV/Excel metering import tests."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest import mock

from django.db import IntegrityError, connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone as django_timezone
from rest_framework.test import APIClient

from accounts.models import UserRole
from audit.models import AuditEvent
from metering.models import ImportLog, MeterReading, ReadingDirection
from metering.testing import preview_csv, upload_csv
from testing.helpers import authenticate as auth, make_user
from zev.models import MeteringPoint, MeteringPointAssignment, MeteringPointType, Participant, Zev


class CsvImportTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = make_user("csv_import_owner", UserRole.ZEV_OWNER)
        self.other_owner = make_user("csv_import_other_owner", UserRole.ZEV_OWNER)
        auth(self.client, self.owner)

        self.zev = Zev.objects.create(name="CSV Import ZEV", owner=self.owner, zev_type="vzev", invoice_prefix="C")
        self.zev_id = str(self.zev.id)
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

    def test_malformed_csv_payload_is_reported_without_crash(self):
        resp = upload_csv(self.client, "bad.csv", b"wrong_col1,wrong_col2\nfoo,bar\n", zev_id=self.zev_id)

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

        resp = upload_csv(self.client, "tz.csv", csv_bytes, zev_id=self.zev_id)

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["rows_imported"], 1)
        reading = MeterReading.objects.get(metering_point=self.metering_point)
        self.assertEqual(reading.timestamp, datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc))

    def test_offset_timestamp_format_is_converted_to_utc(self):
        csv_bytes = (
            b"meter_id,timestamp,energy_kwh,direction\n"
            b"CH-IMPORT-1,2026-01-01T02:00:00+0200,1.5000,in\n"
        )

        resp = upload_csv(
            self.client,
            "tz-format.csv",
            csv_bytes,
            timestamp_format="%Y-%m-%dT%H:%M:%S%z",
            zev_id=self.zev_id,
        )

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["rows_imported"], 1)
        reading = MeterReading.objects.get(metering_point=self.metering_point)
        self.assertEqual(reading.timestamp, datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc))

    def test_direct_upload_without_preview_is_valid(self):
        # Preview is advisory UI aid: the API validates direct uploads itself.
        csv_bytes = (
            b"meter_id,timestamp,energy_kwh,direction\n"
            b"CH-IMPORT-1,2026-01-05T00:00:00Z,1.0000,in\n"
        )

        resp = upload_csv(self.client, "direct.csv", csv_bytes, zev_id=self.zev_id)

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["rows_imported"], 1)
        self.assertEqual(MeterReading.objects.filter(metering_point=self.metering_point).count(), 1)

    def test_daily_late_collision_preserves_surviving_slots(self):
        # A concurrent import winning one slot after the prefetch must not
        # roll back the row's other new slots: the per-slot retry commits
        # survivors, and the rolled-back fast path leaks no counter.
        csv_bytes = b"meter_id,date,v1,v2\nCH-IMPORT-1,2026-01-20,1.0000,2.0000\n"
        real_create = MeterReading.objects.create
        colliding_ts = datetime(2026, 1, 20, tzinfo=timezone.utc) + timedelta(minutes=15)

        def flaky_create(*args, **kwargs):
            if kwargs.get("timestamp") == colliding_ts:
                raise IntegrityError("simulated race")
            return real_create(*args, **kwargs)

        with mock.patch.object(MeterReading.objects, "create", side_effect=flaky_create):
            resp = upload_csv(
                self.client,
                "race.csv",
                csv_bytes,
                format_profile="daily_15min",
                col_timestamp="date",
                col_energy_start="2",
                values_count="2",
                interval_minutes="15",
                zev_id=self.zev_id,
            )

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["rows_imported"], 1)
        self.assertEqual(resp.data["rows_skipped"], 0)
        self.assertEqual(
            list(MeterReading.objects.order_by("timestamp").values_list("energy_kwh", flat=True)),
            [Decimal("1")],
        )

    def test_preview_standard_existing_data_flags_overwrites(self):
        MeterReading.objects.create(
            metering_point=self.metering_point,
            timestamp=datetime(2026, 1, 20, 0, 0, tzinfo=timezone.utc),
            energy_kwh=Decimal("1.0000"),
            direction="in",
        )
        csv_bytes = (
            b"meter_id,timestamp,energy_kwh\n"
            b"CH-IMPORT-1,2026-01-20T00:00:00Z,2.0000\n"
            b"CH-IMPORT-1,2026-01-21T00:00:00Z,3.0000\n"
        )

        resp = preview_csv(self.client, "std-preview.csv", csv_bytes, zev_id=self.zev_id)

        self.assertEqual(resp.status_code, 200)
        rows = resp.data["preview_rows"]
        self.assertTrue(rows[0]["existing_data"])
        self.assertFalse(rows[1]["existing_data"])
        self.assertEqual(resp.data["summary"]["readings_existing"], 1)
        self.assertEqual(resp.data["summary"]["rows_skipped_existing"], 1)

    def test_preview_standard_intra_file_duplicate_flags_existing(self):
        csv_bytes = (
            b"meter_id,timestamp,energy_kwh\n"
            b"CH-IMPORT-1,2026-01-20T00:00:00Z,2.0000\n"
            b"CH-IMPORT-1,2026-01-20T00:00:00Z,2.0000\n"
        )

        resp = preview_csv(self.client, "std-dupe.csv", csv_bytes, zev_id=self.zev_id)

        self.assertEqual(resp.status_code, 200)
        rows = resp.data["preview_rows"]
        self.assertFalse(rows[0]["existing_data"])
        self.assertTrue(rows[1]["existing_data"])
        self.assertEqual(resp.data["summary"]["rows_skipped_existing"], 1)

    def test_preview_daily_existing_counts_readings_not_rows(self):
        # One daily row of 96 existing slots reports 96 existing readings
        # (not 1 row), matching the rows_overwritten an overwrite import
        # reports for the same file.
        day_start = datetime(2026, 1, 20, 0, 0, tzinfo=timezone.utc)
        for slot in range(96):
            MeterReading.objects.create(
                metering_point=self.metering_point,
                timestamp=day_start + timedelta(minutes=15 * slot),
                energy_kwh=Decimal("1.0000"),
                direction="in",
            )
        values = ",".join(["2.0000"] * 96)
        csv_bytes = f"meter_id,date,{','.join(f'v{i}' for i in range(1, 97))}\nCH-IMPORT-1,2026-01-20,{values}\n".encode()

        resp = preview_csv(
            self.client,
            "daily-preview.csv",
            csv_bytes,
            format_profile="daily_15min",
            col_timestamp="date",
            col_energy_start="2",
            values_count="96",
            zev_id=self.zev_id,
        )

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data["preview_rows"][0]["existing_data"])
        self.assertEqual(resp.data["summary"]["readings_existing"], 96)

        uploaded = upload_csv(
            self.client,
            "daily-overwrite.csv",
            csv_bytes,
            format_profile="daily_15min",
            col_timestamp="date",
            col_energy_start="2",
            values_count="96",
            overwrite_existing="true",
            zev_id=self.zev_id,
        )
        self.assertEqual(uploaded.status_code, 201)
        self.assertEqual(uploaded.data["rows_overwritten"], 96)

    def test_preview_and_upload_reject_energy_overflow(self):
        # 123456789012.3456 parses as a Decimal but exceeds
        # DecimalField(max_digits=12, decimal_places=4): both paths must
        # report an actionable error instead of a database DataError.
        csv_bytes = b"meter_id,timestamp,energy_kwh\nCH-IMPORT-1,2026-01-24T00:00:00Z,123456789012.3456\n"

        preview = preview_csv(self.client, "overflow.csv", csv_bytes, zev_id=self.zev_id)
        self.assertEqual(preview.status_code, 200)
        self.assertTrue(any("exceeds the maximum" in err["error"] for err in preview.data["errors"]))

        resp = upload_csv(self.client, "overflow.csv", csv_bytes, zev_id=self.zev_id)
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["rows_imported"], 0)
        self.assertEqual(resp.data["rows_skipped"], 1)
        self.assertTrue(any("exceeds the maximum" in err["error"] for err in resp.data["errors"]))
        self.assertEqual(MeterReading.objects.count(), 0)

    def test_daily_row_without_values_is_skipped_with_error(self):
        csv_bytes = b"meter_id,date,v1\nCH-IMPORT-1,2026-01-21,\n"

        resp = upload_csv(
            self.client,
            "empty-row.csv",
            csv_bytes,
            format_profile="daily_15min",
            col_timestamp="date",
            col_energy_start="2",
            values_count="1",
            zev_id=self.zev_id,
        )

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["rows_imported"], 0)
        self.assertEqual(resp.data["rows_skipped"], 1)
        self.assertTrue(any("no interval values" in err["error"] for err in resp.data["errors"]))
        self.assertEqual(MeterReading.objects.filter(metering_point=self.metering_point).count(), 0)

    def test_daily_import_batches_existence_checks(self):
        rows = b"".join(f"CH-IMPORT-1,2026-02-{day:02d},1.0000\n".encode() for day in range(1, 11))
        csv_bytes = b"meter_id,date,v1\n" + rows

        with CaptureQueriesContext(connection) as ctx:
            resp = upload_csv(
                self.client,
                "batched.csv",
                csv_bytes,
                format_profile="daily_15min",
                col_timestamp="date",
                col_energy_start="2",
                values_count="1",
                zev_id=self.zev_id,
            )

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["rows_imported"], 10)
        selects = [
            q
            for q in ctx.captured_queries
            if "meterreading" in q["sql"].lower() and q["sql"].lstrip().lower().startswith("select")
        ]
        self.assertLessEqual(len(selects), 2)

    def test_duplicate_rows_are_skipped_and_reported(self):
        csv_bytes = (
            b"meter_id,timestamp,energy_kwh,direction\n"
            b"CH-IMPORT-1,2026-01-02T00:00:00Z,2.0000,in\n"
            b"CH-IMPORT-1,2026-01-02T00:00:00Z,2.0000,in\n"
        )

        resp = upload_csv(self.client, "dupe.csv", csv_bytes, zev_id=self.zev_id)

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

        first_resp = upload_csv(self.client, "idempotent-first.csv", csv_bytes, zev_id=self.zev_id)
        self.assertEqual(first_resp.status_code, 201)
        self.assertEqual(first_resp.data["rows_imported"], 1)

        second_resp = upload_csv(self.client, "idempotent-second.csv", csv_bytes, zev_id=self.zev_id)

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

        first_resp = upload_csv(self.client, "overwrite-first.csv", initial_csv, zev_id=self.zev_id)
        self.assertEqual(first_resp.status_code, 201)
        self.assertEqual(first_resp.data["rows_imported"], 1)

        overwrite_resp = upload_csv(self.client, "overwrite-second.csv", updated_csv, overwrite_existing="true", zev_id=self.zev_id)

        self.assertEqual(overwrite_resp.status_code, 201)
        self.assertEqual(overwrite_resp.data["rows_imported"], 1)
        self.assertEqual(overwrite_resp.data["errors"], [])
        self.assertTrue(any("Overwrote 1 existing readings." in entry.get("warning", "") for entry in overwrite_resp.data["warnings"]))
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

        resp = preview_csv(self.client, "preview.csv", csv_bytes, zev_id=self.zev_id)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["rows_total"], 2)
        self.assertEqual(resp.data["summary"]["existing_metering_points"], 1)
        self.assertEqual(resp.data["summary"]["missing_metering_points"], 1)
        self.assertEqual(len(resp.data["preview_rows"]), 2)
        self.assertEqual(MeterReading.objects.count(), 0)
        self.assertEqual(ImportLog.objects.count(), 0)

    def test_headerless_csv_uses_index_column_mapping(self):
        csv_bytes = b"CH-IMPORT-1;2026-01-06T00:00:00Z;6,2500;in\n"

        resp = upload_csv(self.client,
            "headerless.csv",
            csv_bytes,
            has_header="false",
            delimiter=";",
            col_meter_id="0",
            col_timestamp="1",
            col_energy_kwh="2",
            col_direction="3", zev_id=self.zev_id)

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["rows_imported"], 1)
        reading = MeterReading.objects.get(metering_point=self.metering_point)
        self.assertEqual(reading.energy_kwh, Decimal("6.2500"))

    def test_daily_15min_profile_imports_configured_slots(self):
        csv_bytes = b"meter_id,date,v1,v2\nCH-IMPORT-1,2026-01-07,1.0000,2.0000\n"

        resp = upload_csv(self.client,
            "daily.csv",
            csv_bytes,
            format_profile="daily_15min",
            col_timestamp="date",
            col_energy_start="2",
            values_count="2", zev_id=self.zev_id)

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

        resp = upload_csv(self.client, "invalid-direction.csv", csv_bytes, zev_id=self.zev_id)

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

        resp = upload_csv(self.client, "missing-values.csv", csv_bytes, zev_id=self.zev_id)

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

        resp = upload_csv(self.client, "other-zev.csv", csv_bytes, zev_id=self.zev_id)

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

        resp = upload_csv(self.client, "inferred-direction.csv", csv_bytes, zev_id=self.zev_id)

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["rows_imported"], 3)
        production_reading = MeterReading.objects.get(metering_point=production_mp)
        self.assertEqual(production_reading.direction, ReadingDirection.OUT)
        self.assertEqual(production_reading.energy_kwh, Decimal("2.0000"))

        bidirectional_readings = list(MeterReading.objects.filter(metering_point=bidirectional_mp).order_by("timestamp"))
        self.assertEqual([reading.direction for reading in bidirectional_readings], [ReadingDirection.OUT, ReadingDirection.IN])
        self.assertEqual([reading.energy_kwh for reading in bidirectional_readings], [Decimal("3.0000"), Decimal("4.0000")])

    def test_import_log_zev_is_the_requested_target(self):
        csv_bytes = (
            b"meter_id,timestamp,energy_kwh,direction\n"
            b"CH-IMPORT-1,2026-01-12T00:00:00Z,1.0000,in\n"
        )

        resp = upload_csv(self.client, "target-zev.csv", csv_bytes, zev_id=self.zev_id)

        self.assertEqual(resp.status_code, 201)
        log = ImportLog.objects.get(id=resp.data["id"])
        self.assertEqual(log.zev, self.zev)
        self.assertEqual(str(resp.data["zev"]), str(self.zev.id))

    def test_import_without_zev_id_is_rejected(self):
        csv_bytes = (
            b"meter_id,timestamp,energy_kwh,direction\n"
            b"CH-IMPORT-1,2026-01-13T00:00:00Z,1.0000,in\n"
        )

        resp = upload_csv(self.client, "no-zev.csv", csv_bytes)

        self.assertEqual(resp.status_code, 400)
        self.assertIn("zev_id", resp.data["error"])
        self.assertEqual(MeterReading.objects.count(), 0)

    def test_import_with_invalid_zev_id_is_rejected(self):
        csv_bytes = (
            b"meter_id,timestamp,energy_kwh,direction\n"
            b"CH-IMPORT-1,2026-01-13T00:00:00Z,1.0000,in\n"
        )

        resp = upload_csv(self.client, "bad-zev.csv", csv_bytes, zev_id="not-a-uuid")

        self.assertEqual(resp.status_code, 400)
        self.assertIn("valid UUID", resp.data["error"])
        self.assertEqual(MeterReading.objects.count(), 0)

    def test_import_with_unknown_zev_id_returns_404(self):
        csv_bytes = (
            b"meter_id,timestamp,energy_kwh,direction\n"
            b"CH-IMPORT-1,2026-01-13T00:00:00Z,1.0000,in\n"
        )

        resp = upload_csv(self.client, "unknown-zev.csv", csv_bytes, zev_id="00000000-0000-0000-0000-000000000000")

        self.assertEqual(resp.status_code, 404)
        self.assertEqual(MeterReading.objects.count(), 0)

    def test_import_into_foreign_zev_is_forbidden(self):
        csv_bytes = (
            b"meter_id,timestamp,energy_kwh,direction\n"
            b"CH-IMPORT-OTHER,2026-01-13T00:00:00Z,1.0000,in\n"
        )

        resp = upload_csv(self.client, "foreign-zev.csv", csv_bytes, zev_id=str(self.other_zev.id))

        self.assertEqual(resp.status_code, 403)
        self.assertEqual(MeterReading.objects.count(), 0)

    def test_import_scopes_mixed_zev_file_to_target(self):
        csv_bytes = (
            b"meter_id,timestamp,energy_kwh,direction\n"
            b"CH-IMPORT-1,2026-01-14T00:00:00Z,1.0000,in\n"
            b"CH-IMPORT-OTHER,2026-01-14T00:00:00Z,2.0000,in\n"
        )

        resp = upload_csv(self.client, "mixed-zev.csv", csv_bytes, zev_id=self.zev_id)

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["rows_imported"], 1)
        self.assertEqual(resp.data["rows_skipped"], 1)
        log = ImportLog.objects.get(id=resp.data["id"])
        self.assertEqual(log.zev, self.zev)
        self.assertEqual(MeterReading.objects.filter(metering_point=self.metering_point).count(), 1)
        self.assertEqual(MeterReading.objects.filter(metering_point=self.other_metering_point).count(), 0)

    def test_import_scopes_mixed_file_between_own_zevs(self):
        second_zev = Zev.objects.create(name="Second CSV ZEV", owner=self.owner, zev_type="vzev", invoice_prefix="S")
        second_meter = MeteringPoint.objects.create(
            zev=second_zev,
            meter_id="CH-IMPORT-SECOND",
            meter_type=MeteringPointType.CONSUMPTION,
        )
        csv_bytes = (
            b"meter_id,timestamp,energy_kwh,direction\n"
            b"CH-IMPORT-1,2026-01-14T01:00:00Z,1.0000,in\n"
            b"CH-IMPORT-SECOND,2026-01-14T01:00:00Z,2.0000,in\n"
        )

        resp = upload_csv(self.client, "mixed-own-zevs.csv", csv_bytes, zev_id=self.zev_id)

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["rows_imported"], 1)
        self.assertEqual(resp.data["rows_skipped"], 1)
        self.assertEqual(MeterReading.objects.filter(metering_point=self.metering_point).count(), 1)
        self.assertEqual(MeterReading.objects.filter(metering_point=second_meter).count(), 0)

    def test_preview_scopes_mixed_file_between_own_zevs(self):
        second_zev = Zev.objects.create(name="Second Preview ZEV", owner=self.owner, zev_type="vzev", invoice_prefix="P")
        MeteringPoint.objects.create(
            zev=second_zev,
            meter_id="CH-PREVIEW-SECOND",
            meter_type=MeteringPointType.CONSUMPTION,
        )
        csv_bytes = (
            b"meter_id,timestamp,energy_kwh,direction\n"
            b"CH-IMPORT-1,2026-01-14T02:00:00Z,1.0000,in\n"
            b"CH-PREVIEW-SECOND,2026-01-14T02:00:00Z,2.0000,in\n"
        )

        resp = preview_csv(self.client, "mixed-own-zevs.csv", csv_bytes, zev_id=self.zev_id)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["summary"]["existing_metering_points"], 1)
        self.assertEqual(resp.data["summary"]["missing_metering_points"], 1)
        self.assertEqual(resp.data["missing_meter_ids"], ["CH-PREVIEW-SECOND"])

    def test_preview_column_error_returns_empty_preview_with_error(self):
        csv_bytes = b"meter_id,timestamp,energy_kwh\nCH-IMPORT-1,2026-01-24T00:00:00Z,1.0000\n"

        resp = preview_csv(self.client, "bad-columns.csv", csv_bytes, col_meter_id="nope", zev_id=self.zev_id)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["preview_rows"], [])
        self.assertEqual(resp.data["summary"]["missing_metering_points"], 0)
        self.assertEqual(len(resp.data["errors"]), 1)
        self.assertIsNone(resp.data["errors"][0]["row"])

    def test_preview_rejects_invalid_timestamp_format(self):
        csv_bytes = b"meter_id,timestamp,energy_kwh\nCH-IMPORT-1,2026-01-24T00:00:00Z,1.0000\n"

        resp = preview_csv(self.client, "bad-format.csv", csv_bytes, timestamp_format="not-a-format", zev_id=self.zev_id)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["preview_rows"], [])
        self.assertTrue(any("Invalid timestamp format" in err["error"] for err in resp.data["errors"]))

    def test_import_rejects_invalid_timestamp_format(self):
        csv_bytes = b"meter_id,timestamp,energy_kwh\nCH-IMPORT-1,2026-01-24T00:00:00Z,1.0000\n"

        resp = upload_csv(self.client, "bad-format.csv", csv_bytes, timestamp_format="not-a-format", zev_id=self.zev_id)

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["rows_imported"], 0)
        self.assertTrue(any("Invalid timestamp format" in err["error"] for err in resp.data["errors"]))
        self.assertEqual(MeterReading.objects.count(), 0)

    def test_preview_reports_row_level_field_errors(self):
        csv_bytes = (
            b"meter_id,timestamp,energy_kwh,direction\n"
            b"CH-IMPORT-1,not-a-date,1.0000,in\n"
            b"CH-IMPORT-1,2026-01-25T00:00:00Z,not-a-number,in\n"
            b"CH-IMPORT-1,2026-01-25T01:00:00Z,1.0000,sideways\n"
            b",2026-01-25T02:00:00Z,1.0000,in\n"
            b"CH-IMPORT-1,,1.0000,in\n"
            b"CH-IMPORT-1,2026-01-25T03:00:00Z,,in\n"
        )

        resp = preview_csv(self.client, "row-errors.csv", csv_bytes, zev_id=self.zev_id)

        self.assertEqual(resp.status_code, 200)
        messages = [err["error"] for err in resp.data["errors"]]
        self.assertTrue(any("not-a-date" in message or "date" in message.lower() for message in messages))
        self.assertTrue(any("Invalid numeric value" in message for message in messages))
        self.assertTrue(any("Invalid direction" in message for message in messages))
        self.assertTrue(any("meter_id" in message for message in messages))
        self.assertTrue(any("timestamp" in message.lower() for message in messages))

    def test_preview_reports_exactly_50_missing_without_overflow(self):
        rows = b"".join(
            f"CH-EXACT-{i:03d},2026-01-26T00:00:00Z,1.0000\n".encode() for i in range(50)
        )
        csv_bytes = b"meter_id,timestamp,energy_kwh\n" + rows

        resp = preview_csv(self.client, "exactly-50.csv", csv_bytes, zev_id=self.zev_id)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["summary"]["missing_metering_points"], 50)
        self.assertEqual(len(resp.data["missing_meter_ids"]), 50)

    def test_foreign_zev_preview_and_import_record_audit_events(self):
        csv_bytes = (
            b"meter_id,timestamp,energy_kwh,direction\n"
            b"CH-IMPORT-OTHER,2026-01-27T00:00:00Z,1.0000,in\n"
        )
        other_zev_id = str(self.other_zev.id)

        preview_resp = preview_csv(self.client, "audit-preview.csv", csv_bytes, zev_id=other_zev_id)
        import_resp = upload_csv(self.client, "audit-import.csv", csv_bytes, zev_id=other_zev_id)

        self.assertEqual(preview_resp.status_code, 403)
        self.assertEqual(import_resp.status_code, 403)
        preview_event = AuditEvent.objects.filter(action_type="import.preview_csv", status="denied").latest("created_at")
        import_event = AuditEvent.objects.filter(action_type="import.upload", status="denied").latest("created_at")
        # Denied attempts keep the resolved target for internal attribution.
        self.assertEqual(preview_event.target_id, other_zev_id)
        self.assertEqual(import_event.target_id, other_zev_id)
        self.assertEqual(str(preview_event.zev_id), other_zev_id)
        self.assertEqual(str(import_event.zev_id), other_zev_id)

    def test_admin_import_into_any_zev_sets_log_zev(self):
        admin_client = APIClient()
        auth(admin_client, make_user("csv_import_admin", UserRole.ADMIN))
        csv_bytes = (
            b"meter_id,timestamp,energy_kwh,direction\n"
            b"CH-IMPORT-OTHER,2026-01-15T00:00:00Z,1.0000,in\n"
        )

        resp = upload_csv(admin_client, "admin-zev.csv", csv_bytes, zev_id=str(self.other_zev.id))

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["rows_imported"], 1)
        log = ImportLog.objects.get(id=resp.data["id"])
        self.assertEqual(log.zev, self.other_zev)

    def test_owner_cannot_import_into_disabled_zev(self):
        self.zev.disabled_at = django_timezone.now()
        self.zev.save(update_fields=["disabled_at"])
        csv_bytes = (
            b"meter_id,timestamp,energy_kwh,direction\n"
            b"CH-IMPORT-1,2026-01-15T00:00:00Z,1.0000,in\n"
        )

        resp = upload_csv(self.client, "disabled-zev.csv", csv_bytes, zev_id=self.zev_id)

        self.assertEqual(resp.status_code, 400)
        self.assertIn("This ZEV is disabled", resp.data["error"])
        self.assertFalse(MeterReading.objects.exists())
        self.assertFalse(ImportLog.objects.exists())

    def test_admin_can_import_into_disabled_zev(self):
        self.other_zev.disabled_at = django_timezone.now()
        self.other_zev.save(update_fields=["disabled_at"])
        admin_client = APIClient()
        auth(admin_client, make_user("csv_disabled_zev_admin", UserRole.ADMIN))
        csv_bytes = (
            b"meter_id,timestamp,energy_kwh,direction\n"
            b"CH-IMPORT-OTHER,2026-01-15T00:00:00Z,1.0000,in\n"
        )

        resp = upload_csv(
            admin_client,
            "admin-disabled-zev.csv",
            csv_bytes,
            zev_id=str(self.other_zev.id),
        )

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["rows_imported"], 1)
        self.assertTrue(MeterReading.objects.filter(metering_point=self.other_metering_point).exists())

    def test_owner_can_preview_for_disabled_zev(self):
        self.zev.disabled_at = django_timezone.now()
        self.zev.save(update_fields=["disabled_at"])
        csv_bytes = (
            b"meter_id,timestamp,energy_kwh,direction\n"
            b"CH-IMPORT-1,2026-01-15T00:00:00Z,1.0000,in\n"
        )

        resp = preview_csv(self.client, "disabled-zev.csv", csv_bytes, zev_id=self.zev_id)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["summary"]["existing_metering_points"], 1)
        self.assertFalse(MeterReading.objects.exists())

    def test_preview_without_zev_id_is_rejected(self):
        csv_bytes = (
            b"meter_id,timestamp,energy_kwh,direction\n"
            b"CH-IMPORT-1,2026-01-16T00:00:00Z,1.0000,in\n"
        )

        resp = preview_csv(self.client, "preview-no-zev.csv", csv_bytes)

        self.assertEqual(resp.status_code, 400)
        self.assertIn("zev_id", resp.data["error"])

    def test_preview_with_invalid_zev_id_is_rejected(self):
        csv_bytes = (
            b"meter_id,timestamp,energy_kwh,direction\n"
            b"CH-IMPORT-1,2026-01-16T00:00:00Z,1.0000,in\n"
        )

        resp = preview_csv(self.client, "preview-bad-zev.csv", csv_bytes, zev_id="not-a-uuid")

        self.assertEqual(resp.status_code, 400)
        self.assertIn("valid UUID", resp.data["error"])

    def test_preview_with_unknown_zev_id_returns_404(self):
        csv_bytes = (
            b"meter_id,timestamp,energy_kwh,direction\n"
            b"CH-IMPORT-1,2026-01-16T00:00:00Z,1.0000,in\n"
        )

        resp = preview_csv(self.client, "preview-unknown-zev.csv", csv_bytes, zev_id="00000000-0000-0000-0000-000000000000")

        self.assertEqual(resp.status_code, 404)

    def test_preview_for_foreign_zev_is_forbidden(self):
        csv_bytes = (
            b"meter_id,timestamp,energy_kwh,direction\n"
            b"CH-IMPORT-1,2026-01-16T00:00:00Z,1.0000,in\n"
        )

        resp = preview_csv(self.client, "preview-foreign-zev.csv", csv_bytes, zev_id=str(self.other_zev.id))

        self.assertEqual(resp.status_code, 403)

    def test_preview_counts_unique_meters_over_whole_file(self):
        rows = b"".join(
            f"CH-IMPORT-1,2026-01-17T00:{i:02d}:00Z,1.0000,in\n".encode() for i in range(10)
        ) + b"CH-MISSING,2026-01-17T01:00:00Z,1.0000,in\n" * 30
        csv_bytes = b"meter_id,timestamp,energy_kwh,direction\n" + rows

        resp = preview_csv(self.client, "preview-unique.csv", csv_bytes, zev_id=self.zev_id)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["rows_total"], 40)
        self.assertEqual(resp.data["summary"]["existing_metering_points"], 1)
        self.assertEqual(resp.data["summary"]["missing_metering_points"], 1)
        self.assertEqual(resp.data["missing_meter_ids"], ["CH-MISSING"])
        self.assertLessEqual(len(resp.data["preview_rows"]), 30)

    def test_preview_reports_missing_meter_beyond_display_cap(self):
        rows = b"".join(
            f"CH-IMPORT-1,2026-01-18T00:{i:02d}:00Z,1.0000,in\n".encode() for i in range(30)
        ) + b"CH-LATE-MISSING,2026-01-18T01:00:00Z,1.0000,in\n"
        csv_bytes = b"meter_id,timestamp,energy_kwh,direction\n" + rows

        resp = preview_csv(self.client, "preview-late.csv", csv_bytes, zev_id=self.zev_id)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["summary"]["missing_metering_points"], 1)
        self.assertEqual(resp.data["missing_meter_ids"], ["CH-LATE-MISSING"])

    def test_preview_validates_fields_on_missing_meter_rows(self):
        csv_bytes = (
            b"meter_id,timestamp,energy_kwh\n"
            b"CH-MISSING,2026-01-19T00:00:00Z,not-a-number\n"
        )

        resp = preview_csv(self.client, "missing-meter-fields.csv", csv_bytes, zev_id=self.zev_id)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["summary"]["missing_metering_points"], 1)
        self.assertTrue(any("Invalid numeric value" in err["error"] for err in resp.data["errors"]))

    def test_preview_reports_invalid_timestamp_with_clean_message(self):
        csv_bytes = (
            b"meter_id,timestamp,energy_kwh\n"
            b"CH-IMPORT-1,definitely-not-a-date,1.0000\n"
        )

        resp = preview_csv(self.client, "bad-ts.csv", csv_bytes, zev_id=self.zev_id)

        self.assertEqual(resp.status_code, 200)
        row_errors = [err for err in resp.data["errors"] if err.get("row") == 2]
        self.assertTrue(row_errors)
        for err in row_errors:
            if "timestamp" in err["error"].lower() or "date" in err["error"].lower():
                self.assertIn("Invalid timestamp value", err["error"])
                self.assertNotIn("<class", err["error"])
                self.assertNotIn("ConversionSyntax", err["error"])
                self.assertNotIn("Unknown string format", err["error"])

    def test_preview_daily_existing_data_is_direction_aware(self):
        bidi = MeteringPoint.objects.create(
            zev=self.zev,
            meter_id="CH-BIDI-PREVIEW",
            meter_type=MeteringPointType.BIDIRECTIONAL,
        )
        # Only an "out" reading exists for the day.
        MeterReading.objects.create(
            metering_point=bidi,
            timestamp=datetime(2026, 1, 20, 0, 0, tzinfo=timezone.utc),
            energy_kwh=Decimal("1.0000"),
            direction="out",
        )
        # Row imports a positive (=> "in") slot: no conflict on "in".
        csv_bytes = b"meter_id,date,v1\nCH-BIDI-PREVIEW,2026-01-20,1.0000\n"

        resp = preview_csv(
            self.client,
            "bidi-preview.csv",
            csv_bytes,
            format_profile="daily_15min",
            col_timestamp="date",
            col_energy_start="2",
            values_count="1",
            zev_id=self.zev_id,
        )

        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.data["preview_rows"][0]["existing_data"])

    def test_preview_rejects_yearless_timestamp_format(self):
        csv_bytes = b"meter_id,timestamp,energy_kwh\nCH-IMPORT-1,2026-01-24T00:00:00Z,1.0000\n"

        resp = preview_csv(self.client, "yearless.csv", csv_bytes, timestamp_format="%d.%m", zev_id=self.zev_id)

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(any("Invalid timestamp format" in err["error"] for err in resp.data["errors"]))

    def test_upload_rejects_yearless_timestamp_format(self):
        csv_bytes = b"meter_id,timestamp,energy_kwh\nCH-IMPORT-1,2026-01-24T00:00:00Z,1.0000\n"

        resp = upload_csv(self.client, "yearless.csv", csv_bytes, timestamp_format="%d.%m", zev_id=self.zev_id)

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["rows_imported"], 0)
        self.assertTrue(any("Invalid timestamp format" in err["error"] for err in resp.data["errors"]))
        self.assertEqual(MeterReading.objects.count(), 0)

    def test_preview_daily_truncated_row_reports_one_error(self):
        csv_bytes = b"meter_id,date,v1\nCH-IMPORT-1,2026-01-20,1.0000\n"

        resp = preview_csv(self.client,
            "preview-truncated.csv",
            csv_bytes,
            format_profile="daily_15min",
            col_timestamp="date",
            col_energy_start="2",
            values_count="4", zev_id=self.zev_id)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            len([err for err in resp.data["errors"] if "Missing interval column" in err["error"]]),
            1,
        )

    def test_preview_daily_row_reports_one_error_per_row(self):
        csv_bytes = b"meter_id,date,v1,v2\nCH-IMPORT-1,2026-01-20,not-a-number,also-bad\n"

        resp = preview_csv(self.client,
            "preview-daily-errors.csv",
            csv_bytes,
            format_profile="daily_15min",
            col_timestamp="date",
            col_energy_start="2",
            values_count="2", zev_id=self.zev_id)

        self.assertEqual(resp.status_code, 200)
        row_errors = [err for err in resp.data["errors"] if err["row"] == 2]
        self.assertEqual(len(row_errors), 1)

    def test_preview_stops_validating_past_the_error_cap(self):
        rows = b"".join(
            f"CH-IMPORT-1,2026-01-21T00:{i:02d}:00Z,not-a-number\n".encode() for i in range(60)
        )
        csv_bytes = b"meter_id,timestamp,energy_kwh\n" + rows

        resp = preview_csv(self.client, "cap.csv", csv_bytes, zev_id=self.zev_id)

        self.assertEqual(resp.status_code, 200)
        errors = resp.data["errors"]
        self.assertEqual(len(errors), 51)
        self.assertIn("Too many errors", errors[-1]["error"])
        # Whole-file meter coverage survives the validation short-circuit.
        self.assertEqual(resp.data["summary"]["existing_metering_points"], 1)

    def test_preview_caps_missing_meter_ids_at_50(self):
        rows = b"".join(
            f"CH-MISSING-{i:03d},2026-01-22T00:00:00Z,1.0000\n".encode() for i in range(51)
        )
        csv_bytes = b"meter_id,timestamp,energy_kwh\n" + rows

        resp = preview_csv(self.client, "many-missing.csv", csv_bytes, zev_id=self.zev_id)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["summary"]["missing_metering_points"], 51)
        self.assertEqual(len(resp.data["missing_meter_ids"]), 50)

    def test_import_daily_truncated_row_counts_one_skip(self):
        csv_bytes = b"meter_id,date,v1\nCH-IMPORT-1,2026-01-23,1.0000\n"

        resp = upload_csv(self.client,
            "short-daily.csv",
            csv_bytes,
            format_profile="daily_15min",
            col_timestamp="date",
            col_energy_start="2",
            values_count="4", zev_id=self.zev_id)

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["rows_imported"], 0)
        self.assertEqual(resp.data["rows_skipped"], 1)
        self.assertEqual(
            len([err for err in resp.data["errors"] if "Missing interval column" in err["error"]]),
            1,
        )
        # A truncated daily row writes nothing — no partial day.
        self.assertEqual(MeterReading.objects.count(), 0)

    def test_daily_partial_duplicate_gap_fills_missing_slots(self):
        # One existing reading plus one new reading in the same row imports
        # the missing slot instead of skipping the entire row.
        MeterReading.objects.create(
            metering_point=self.metering_point,
            timestamp=datetime(2026, 1, 7, 0, 0, tzinfo=timezone.utc),
            energy_kwh=Decimal("9.0000"),
            direction="in",
        )
        csv_bytes = b"meter_id,date,v1,v2\nCH-IMPORT-1,2026-01-07,9.0000,2.0000\n"

        resp = upload_csv(
            self.client,
            "gap-fill.csv",
            csv_bytes,
            format_profile="daily_15min",
            col_timestamp="date",
            col_energy_start="2",
            values_count="2",
            zev_id=self.zev_id,
        )

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["rows_imported"], 1)
        self.assertEqual(resp.data["rows_skipped"], 0)
        self.assertEqual(resp.data["errors"], [])
        readings = list(
            MeterReading.objects.filter(metering_point=self.metering_point).order_by("timestamp")
        )
        self.assertEqual(len(readings), 2)
        self.assertEqual(readings[1].energy_kwh, Decimal("2.0000"))

    def test_daily_fully_duplicate_row_is_skipped_with_error(self):
        MeterReading.objects.create(
            metering_point=self.metering_point,
            timestamp=datetime(2026, 1, 7, 0, 0, tzinfo=timezone.utc),
            energy_kwh=Decimal("1.0000"),
            direction="in",
        )
        csv_bytes = b"meter_id,date,v1\nCH-IMPORT-1,2026-01-07,1.0000\n"

        resp = upload_csv(
            self.client,
            "full-dupe.csv",
            csv_bytes,
            format_profile="daily_15min",
            col_timestamp="date",
            col_energy_start="2",
            values_count="1",
            zev_id=self.zev_id,
        )

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["rows_imported"], 0)
        self.assertEqual(resp.data["rows_skipped"], 1)
        self.assertTrue(any("Duplicate reading" in err["error"] for err in resp.data["errors"]))

    def test_daily_intra_file_duplicate_second_row_is_skipped(self):
        csv_bytes = (
            b"meter_id,date,v1\n"
            b"CH-IMPORT-1,2026-01-07,1.0000\n"
            b"CH-IMPORT-1,2026-01-07,1.0000\n"
        )

        resp = upload_csv(
            self.client,
            "intra-dupe.csv",
            csv_bytes,
            format_profile="daily_15min",
            col_timestamp="date",
            col_energy_start="2",
            values_count="1",
            zev_id=self.zev_id,
        )

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["rows_imported"], 1)
        self.assertEqual(resp.data["rows_skipped"], 1)
        self.assertTrue(any("Duplicate reading" in err["error"] for err in resp.data["errors"]))
        self.assertEqual(MeterReading.objects.filter(metering_point=self.metering_point).count(), 1)

    def test_daily_empty_row_preview_and_import_agree(self):
        csv_bytes = b"meter_id,date,v1\nCH-IMPORT-1,2026-01-21,\n"
        kwargs = {
            "format_profile": "daily_15min",
            "col_timestamp": "date",
            "col_energy_start": "2",
            "values_count": "1",
            "zev_id": self.zev_id,
        }

        preview_resp = preview_csv(self.client, "empty-preview.csv", csv_bytes, **kwargs)
        self.assertEqual(preview_resp.status_code, 200)
        self.assertTrue(
            any("no interval values" in err["error"] for err in preview_resp.data["errors"])
        )

        import_resp = upload_csv(self.client, "empty-import.csv", csv_bytes, **kwargs)
        self.assertEqual(import_resp.status_code, 201)
        self.assertEqual(import_resp.data["rows_skipped"], 1)
        self.assertTrue(
            any("no interval values" in err["error"] for err in import_resp.data["errors"])
        )

    def test_daily_preview_partial_duplicate_has_no_error_but_flags_existing(self):
        MeterReading.objects.create(
            metering_point=self.metering_point,
            timestamp=datetime(2026, 1, 7, 0, 0, tzinfo=timezone.utc),
            energy_kwh=Decimal("9.0000"),
            direction="in",
        )
        csv_bytes = b"meter_id,date,v1,v2\nCH-IMPORT-1,2026-01-07,9.0000,2.0000\n"

        resp = preview_csv(
            self.client,
            "partial-preview.csv",
            csv_bytes,
            format_profile="daily_15min",
            col_timestamp="date",
            col_energy_start="2",
            values_count="2",
            zev_id=self.zev_id,
        )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["errors"], [])
        self.assertTrue(resp.data["preview_rows"][0]["existing_data"])

    def test_daily_preview_merge_reimport_skips_existing_days_and_imports_new_days(self):
        kwargs = dict(format_profile="daily_15min", col_timestamp="date", col_energy_start="2", values_count="2", zev_id=self.zev_id)
        original = b"meter_id,date,v1,v2\nCH-IMPORT-1,2026-01-07,,1.0000\n"
        upload_csv(self.client, "first.csv", original, **kwargs)
        # Only the second slot is populated in the duplicate row. The notice
        # counts rows rather than reporting a misleading slot 1 position.
        combined = original + b"CH-IMPORT-1,2026-01-08,2.0000,3.0000\n"
        preview = preview_csv(self.client, "combined.csv", combined, **kwargs)
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.data["errors"], [])
        self.assertEqual(preview.data["summary"]["rows_skipped_existing"], 1)
        self.assertEqual(MeterReading.objects.count(), 1)
        result = upload_csv(self.client, "combined.csv", combined, **kwargs)
        self.assertEqual(result.status_code, 201)
        self.assertEqual(result.data["rows_imported"], 2)
        self.assertEqual(result.data["rows_skipped"], 1)
        self.assertEqual(result.data["rows_overwritten"], 0)
        self.assertEqual(MeterReading.objects.count(), 3)

    def test_daily_preview_fully_duplicate_row_reports_skip_notice(self):
        MeterReading.objects.create(
            metering_point=self.metering_point,
            timestamp=datetime(2026, 1, 7, 0, 0, tzinfo=timezone.utc),
            energy_kwh=Decimal("1.0000"),
            direction="in",
        )
        csv_bytes = b"meter_id,date,v1\nCH-IMPORT-1,2026-01-07,1.0000\n"

        resp = preview_csv(
            self.client,
            "full-dupe-preview.csv",
            csv_bytes,
            format_profile="daily_15min",
            col_timestamp="date",
            col_energy_start="2",
            values_count="1",
            zev_id=self.zev_id,
        )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["errors"], [])
        self.assertEqual(resp.data["summary"]["rows_skipped_existing"], 1)
        self.assertTrue(resp.data["preview_rows"][0]["existing_data"])

    def test_daily_overwrite_preview_allows_duplicates_without_writing(self):
        reading = MeterReading.objects.create(
            metering_point=self.metering_point,
            timestamp=datetime(2026, 1, 7, tzinfo=timezone.utc),
            energy_kwh=Decimal("1.0000"),
            direction="in",
        )
        csv_bytes = b"meter_id,date,v1\nCH-IMPORT-1,2026-01-07,2.0000\nCH-IMPORT-1,2026-01-07,3.0000\n"
        kwargs = dict(
            format_profile="daily_15min", col_timestamp="date",
            col_energy_start="2", values_count="1", zev_id=self.zev_id,
        )
        for overwrite in ("false", "true"):
            with self.subTest(overwrite=overwrite):
                response = preview_csv(self.client, "overwrite.csv", csv_bytes, overwrite_existing=overwrite, **kwargs)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data["errors"], [])
                self.assertEqual(response.data["summary"]["rows_skipped_existing"], 2 if overwrite == "false" else 0)
                self.assertTrue(all(row["existing_data"] for row in response.data["preview_rows"]))
                reading.refresh_from_db()
                self.assertEqual(reading.energy_kwh, Decimal("1.0000"))
                self.assertFalse(ImportLog.objects.exists())
        invalid = preview_csv(self.client, "invalid.csv", csv_bytes.replace(b"2.0000", b"oops"), overwrite_existing="true", **kwargs)
        self.assertTrue(any("Invalid numeric" in error["error"] for error in invalid.data["errors"]))
        result = upload_csv(self.client, "overwrite.csv", csv_bytes, overwrite_existing="true", **kwargs)
        self.assertEqual(result.status_code, 201)
        self.assertEqual(result.data["errors"], [])
        reading.refresh_from_db()
        self.assertEqual(reading.energy_kwh, Decimal("3.0000"))

    def test_daily_preview_sparse_dates_use_bounded_reads(self):
        csv_bytes = (
            b"meter_id,date,v1\n"
            b"CH-IMPORT-1,2024-01-01,1.0000\n"
            b"CH-IMPORT-1,2026-01-01,2.0000\n"
        )
        kwargs = {
            "format_profile": "daily_15min",
            "col_timestamp": "date",
            "col_energy_start": "2",
            "values_count": "1",
            "zev_id": self.zev_id,
        }

        with CaptureQueriesContext(connection) as ctx:
            resp = preview_csv(self.client, "sparse-preview.csv", csv_bytes, **kwargs)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["errors"], [])
        selects = [
            q
            for q in ctx.captured_queries
            if "meterreading" in q["sql"].lower() and q["sql"].lstrip().lower().startswith("select")
        ]
        # Two isolated days → two bounded day-window queries, never a
        # single two-year range scan.
        self.assertLessEqual(len(selects), 3)
