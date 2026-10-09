"""Push endpoint and CSV upload of SPEC-2026-supplementary-energy-data §5."""

from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from unittest import mock
from zoneinfo import ZoneInfo

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from audit.models import AuditEvent
from metering.models import SupplementaryReading, SupplementarySource
from metering.supplementary.authentication import SupplementaryPushThrottle
from metering.supplementary.testing import (
    INGEST_URL,
    SOURCES_URL,
    SupplementaryApiTestCase,
    client_for,
    enable_feature,
    quarter_hours,
    reading_payload,
)


class IngestTestCase(SupplementaryApiTestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        created = self.create_push_source().json()
        self.token = created["push_token"]
        self.source = SupplementarySource.objects.get(pk=created["id"])

    def push(self, readings, token=None):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token or self.token}")
        return client.post(INGEST_URL, {"readings": readings}, format="json")


class PushIngestTests(IngestTestCase):
    def test_a_valid_batch_is_stored_and_advances_the_coverage(self):
        stamps = quarter_hours(8)
        response = self.push([reading_payload(ts) for ts in stamps])
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json(), {"accepted": 8, "updated": 0, "rejected": [], "dropped_outside_assignment": 0})
        self.assertEqual(SupplementaryReading.objects.count(), 8)

        self.source.refresh_from_db()
        self.assertEqual(self.source.status, "ok")
        self.assertEqual(self.source.covers_from, stamps[0])
        self.assertEqual(self.source.synced_through, stamps[-1] + timedelta(minutes=15))
        self.assertIsNotNone(self.source.last_success_at)
        row = SupplementaryReading.objects.get(timestamp=stamps[0])
        self.assertEqual(
            (row.consumption_kwh, row.production_kwh, row.import_kwh, row.export_kwh),
            (Decimal("0.4"), Decimal("1.2"), Decimal("0.1"), Decimal("0.9")),
        )
        self.assertEqual(row.source_id, self.source.pk)
        self.assertEqual(row.metering_point_id, self.point.pk)

    def test_redelivery_updates_instead_of_duplicating(self):
        stamps = quarter_hours(4)
        self.push([reading_payload(ts) for ts in stamps])
        response = self.push([reading_payload(ts, consumption_kwh="9.5") for ts in stamps[:2]] + [reading_payload(stamps[-1] + timedelta(minutes=15))])
        self.assertEqual(response.json()["accepted"], 3)
        self.assertEqual(response.json()["updated"], 2)
        self.assertEqual(SupplementaryReading.objects.count(), 5)
        self.assertEqual(SupplementaryReading.objects.get(timestamp=stamps[0]).consumption_kwh, Decimal("9.5"))

    def test_coverage_never_shrinks_when_older_data_arrives_later(self):
        late, early = quarter_hours(4)[2:], quarter_hours(4)[:2]
        self.push([reading_payload(ts) for ts in late])
        self.push([reading_payload(ts) for ts in early])
        self.source.refresh_from_db()
        self.assertEqual(self.source.covers_from, early[0])
        self.assertEqual(self.source.synced_through, late[-1] + timedelta(minutes=15))

    def test_values_are_rounded_to_four_decimals(self):
        ts = quarter_hours(1)[0]
        self.push([reading_payload(ts, consumption_kwh="0.0933500001", production_kwh=1.23456, import_kwh="0,5")])
        row = SupplementaryReading.objects.get()
        self.assertEqual(row.consumption_kwh, Decimal("0.0934"))
        self.assertEqual(row.production_kwh, Decimal("1.2346"))
        self.assertEqual(row.import_kwh, Decimal("0.5000"))

    def test_offsets_are_normalised_to_utc(self):
        ts = quarter_hours(1)[0]
        local = ts.astimezone(ZoneInfo("Europe/Zurich")).isoformat()
        self.push([reading_payload(ts, timestamp=local)])
        self.assertEqual(SupplementaryReading.objects.get().timestamp, ts)

    def test_bad_rows_are_rejected_individually_and_the_good_ones_kept(self):
        good = quarter_hours(1)[0]
        now = datetime.now(dt_timezone.utc).replace(minute=0, second=0, microsecond=0)
        rows = [
            reading_payload(good),
            reading_payload(good + timedelta(minutes=15), timestamp="2026-07-01T10:00:00"),  # naive
            reading_payload(good + timedelta(minutes=30), timestamp=(good + timedelta(minutes=37)).isoformat()),  # unaligned
            reading_payload(now + timedelta(days=1), timestamp=(now + timedelta(days=1)).isoformat()),  # future
            reading_payload(now - timedelta(days=800), timestamp=(now - timedelta(days=800)).isoformat()),  # too old
            reading_payload(good - timedelta(minutes=15), consumption_kwh="-1"),
            reading_payload(good - timedelta(minutes=30), production_kwh="abc"),
            reading_payload(good - timedelta(minutes=45), import_kwh="NaN"),
            reading_payload(good - timedelta(minutes=60), export_kwh="1e12"),
            {"timestamp": (good - timedelta(minutes=75)).isoformat(), "consumption_kwh": "1"},  # missing fields
            "not an object",
            reading_payload(good),  # duplicate of row 0
        ]
        response = self.push(rows)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["accepted"], 1)
        reasons = {item["index"]: item["reason"] for item in body["rejected"]}
        self.assertEqual(sorted(reasons), list(range(1, 12)))
        self.assertIn("UTC offset", reasons[1])
        self.assertIn("15 minutes", reasons[2])
        self.assertIn("future", reasons[3])
        self.assertIn("backfill", reasons[4])
        self.assertIn("negative", reasons[5])
        self.assertIn("not a number", reasons[6])
        self.assertIn("not a number", reasons[7])
        self.assertIn("too large", reasons[8])
        self.assertIn("required", reasons[9])
        self.assertIn("not an object", reasons[10])
        self.assertIn("duplicate", reasons[11])
        self.assertEqual(SupplementaryReading.objects.count(), 1)

    def test_more_rows_than_the_limit_is_a_400(self):
        with override_settings(SUPPLEMENTARY_INGEST_MAX_ROWS=3):
            response = self.push([reading_payload(ts) for ts in quarter_hours(4)])
        self.assertEqual(response.status_code, 400)
        self.assertEqual(SupplementaryReading.objects.count(), 0)

    def test_an_empty_or_malformed_body_is_a_400(self):
        self.assertEqual(self.push([]).status_code, 400)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.token}")
        self.assertEqual(client.post(INGEST_URL, {"nope": 1}, format="json").status_code, 400)

    def test_intervals_outside_the_participants_tenancy_are_dropped_and_counted(self):
        today = timezone.localdate()
        self.assignment.valid_from = today - timedelta(days=100)
        self.assignment.save()
        recent = quarter_hours(2)
        old = datetime.now(dt_timezone.utc).replace(minute=0, second=0, microsecond=0) - timedelta(days=150)
        response = self.push([reading_payload(ts) for ts in recent] + [reading_payload(old)])
        self.assertEqual(response.json()["accepted"], 2)
        self.assertEqual(response.json()["dropped_outside_assignment"], 1)
        self.assertEqual(response.json()["rejected"], [])
        self.assertEqual(SupplementaryReading.objects.count(), 2)

    def test_a_community_assignment_drops_everything(self):
        from zev.models import AllocationMode

        self.assignment.allocation_mode = AllocationMode.COMMUNITY
        self.assignment.save()
        response = self.push([reading_payload(ts) for ts in quarter_hours(3)])
        self.assertEqual(response.json()["accepted"], 0)
        self.assertEqual(response.json()["dropped_outside_assignment"], 3)

    def test_pushed_data_never_touches_meter_readings(self):
        from metering.models import MeterReading

        self.push([reading_payload(ts) for ts in quarter_hours(3)])
        self.assertEqual(MeterReading.objects.count(), 0)

    def test_pushes_are_not_audited_one_by_one(self):
        self.push([reading_payload(ts) for ts in quarter_hours(3)])
        self.assertFalse(AuditEvent.objects.filter(action_type__contains="ingest").exists())


class PushAuthenticationTests(IngestTestCase):
    def test_no_token_is_401(self):
        response = APIClient().post(INGEST_URL, {"readings": [reading_payload(quarter_hours(1)[0])]}, format="json")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response["WWW-Authenticate"], "Bearer")

    def test_a_wrong_secret_a_wrong_prefix_and_garbage_are_all_the_same_401(self):
        prefix = self.source.push_token_prefix
        for token in (f"ozs_{prefix}_not-the-secret", "ozs_ffffffffffff_x", "ozv_{prefix}_x", "garbage", "ozs__"):
            response = self.push([reading_payload(quarter_hours(1)[0])], token=token)
            self.assertEqual(response.status_code, 401, token)
            self.assertEqual(response.json()["detail"], "Invalid or revoked push token.")

    def test_a_rotated_token_stops_working_at_once(self):
        old = self.token
        rotated = client_for(self.holder_user).post(f"{SOURCES_URL}{self.source.pk}/rotate-push-token/").json()
        self.assertEqual(self.push([reading_payload(quarter_hours(1)[0])], token=old).status_code, 401)
        self.assertEqual(self.push([reading_payload(quarter_hours(1)[0])], token=rotated["push_token"]).status_code, 200)

    def test_a_disabled_source_answers_403(self):
        client_for(self.manager).patch(f"{SOURCES_URL}{self.source.pk}/", {"enabled": False}, format="json")
        response = self.push([reading_payload(quarter_hours(1)[0])])
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "Source is disabled.")
        self.assertEqual(SupplementaryReading.objects.count(), 0)

    def test_a_disabled_zev_accepts_nothing(self):
        from django.utils import timezone

        self.zev.disabled_at = timezone.now()
        self.zev.save()
        response = self.push([reading_payload(quarter_hours(1)[0])])
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "This ZEV is disabled.")
        self.assertEqual(SupplementaryReading.objects.count(), 0)

    def test_a_disconnected_source_no_longer_accepts_its_token(self):
        client_for(self.holder_user).post(f"{SOURCES_URL}{self.source.pk}/disconnect/")
        self.assertEqual(self.push([reading_payload(quarter_hours(1)[0])]).status_code, 401)

    def test_a_user_session_cannot_use_the_ingest_endpoint(self):
        response = client_for(self.holder_user).post(
            INGEST_URL, {"readings": [reading_payload(quarter_hours(1)[0])]}, format="json"
        )
        self.assertEqual(response.status_code, 401)

    def test_a_push_token_cannot_reach_any_other_endpoint(self):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.token}")
        for url in (SOURCES_URL, f"{SOURCES_URL}{self.source.pk}/", "/api/v1/auth/me/", "/api/v1/zev/zevs/"):
            self.assertIn(client.get(url).status_code, (401, 403, 404), url)

    def test_the_flag_off_is_404(self):
        enable_feature(False)
        self.assertEqual(self.push([reading_payload(quarter_hours(1)[0])]).status_code, 404)

    def test_the_throttle_is_per_token(self):
        with mock.patch.object(SupplementaryPushThrottle, "THROTTLE_RATES", {"supplementary_push": "2/hour"}):
            row = [reading_payload(quarter_hours(1)[0])]
            self.assertEqual(self.push(row).status_code, 200)
            self.assertEqual(self.push(row).status_code, 200)
            self.assertEqual(self.push(row).status_code, 429)


def csv_upload(rows, header="timestamp,consumption_kwh,production_kwh,import_kwh,export_kwh", sep=","):
    lines = [header.replace(",", sep)] + [sep.join(str(cell) for cell in row) for row in rows]
    return SimpleUploadedFile("energy.csv", "\n".join(lines).encode("utf-8"), content_type="text/csv")


class CsvImportTests(IngestTestCase):
    def url(self, dry_run=False):
        return f"{SOURCES_URL}{self.source.pk}/import-csv/" + ("?dry_run=true" if dry_run else "")

    def rows(self, count=4):
        return [(ts.isoformat(), "0.4", "1.2", "0.1", "0.9") for ts in quarter_hours(count)]

    def test_a_valid_file_is_imported_and_audited(self):
        response = client_for(self.holder_user).post(self.url(), {"file": csv_upload(self.rows())}, format="multipart")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["accepted"], 4)
        self.assertEqual(SupplementaryReading.objects.count(), 4)
        event = AuditEvent.objects.get(action_type="supplementary_source.import_csv")
        self.assertEqual(event.metadata_json["accepted"], 4)

    def test_a_semicolon_file_with_a_bom_and_decimal_commas(self):
        rows = [(ts.isoformat(), "0,4", "1,2", "0,1", "0,9") for ts in quarter_hours(2)]
        upload = csv_upload(rows, sep=";")
        upload = SimpleUploadedFile("e.csv", b"\xef\xbb\xbf" + upload.read(), content_type="text/csv")
        response = client_for(self.holder_user).post(self.url(), {"file": upload}, format="multipart")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(SupplementaryReading.objects.first().consumption_kwh, Decimal("0.4"))

    def test_dry_run_validates_without_writing(self):
        response = client_for(self.holder_user).post(
            self.url(dry_run=True), {"file": csv_upload(self.rows())}, format="multipart"
        )
        self.assertEqual(response.json()["accepted"], 4)
        self.assertEqual(SupplementaryReading.objects.count(), 0)
        self.assertFalse(AuditEvent.objects.filter(action_type="supplementary_source.import_csv").exists())

    def test_one_bad_row_rejects_the_whole_file(self):
        rows = self.rows()
        rows[2] = (rows[2][0], "-1", "1", "1", "1")
        response = client_for(self.holder_user).post(self.url(), {"file": csv_upload(rows)}, format="multipart")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["rejected"][0]["index"], 2)
        self.assertEqual(response.json()["accepted"], 0)
        self.assertEqual(SupplementaryReading.objects.count(), 0)

    def test_missing_columns_empty_and_oversized_files(self):
        client = client_for(self.holder_user)
        missing = client.post(self.url(), {"file": csv_upload([("a", "b")], header="timestamp,consumption_kwh")}, format="multipart")
        self.assertEqual(missing.status_code, 400)
        self.assertIn("production_kwh", str(missing.json()))
        self.assertEqual(client.post(self.url(), {"file": csv_upload([])}, format="multipart").status_code, 400)
        with override_settings(SUPPLEMENTARY_CSV_MAX_ROWS=2):
            too_many = client.post(self.url(), {"file": csv_upload(self.rows(3))}, format="multipart")
        self.assertEqual(too_many.status_code, 400)

    def test_not_utf8_is_refused(self):
        upload = SimpleUploadedFile("e.csv", b"\xff\xfe\x00bad", content_type="text/csv")
        response = client_for(self.holder_user).post(self.url(), {"file": upload}, format="multipart")
        self.assertEqual(response.status_code, 400)

    def test_only_the_owner_or_an_admin_may_import(self):
        for user, expected in ((self.manager, 403), (self.viewer, 403), (self.admin, 200)):
            response = client_for(user).post(self.url(), {"file": csv_upload(self.rows())}, format="multipart")
            self.assertEqual(response.status_code, expected, user.username)
        self.assertEqual(
            client_for(self.other_user).post(self.url(), {"file": csv_upload(self.rows())}, format="multipart").status_code,
            404,
        )

    def test_a_disabled_source_refuses_files(self):
        client_for(self.manager).patch(f"{SOURCES_URL}{self.source.pk}/", {"enabled": False}, format="json")
        response = client_for(self.holder_user).post(self.url(), {"file": csv_upload(self.rows())}, format="multipart")
        self.assertEqual(response.status_code, 403)
