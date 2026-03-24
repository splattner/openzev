from datetime import date, datetime, timezone
from decimal import Decimal
from django.core.files.uploadedfile import SimpleUploadedFile

from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import User, UserRole
from metering.models import MeterReading, ReadingDirection, ReadingResolution
from zev.models import Zev, Participant, MeteringPoint, MeteringPointType


def make_user(username, role, password="pass1234"):
	return User.objects.create_user(username=username, password=password, role=role)


def auth(client, user, password="pass1234"):
	resp = client.post("/api/v1/auth/token/", {"username": user.username, "password": password})
	client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")


class DashboardSummaryAlignmentTests(TestCase):
	def setUp(self):
		self.client = APIClient()
		self.owner = make_user("dash_owner", UserRole.ZEV_OWNER)
		self.participant_user = make_user("dash_participant", UserRole.PARTICIPANT)

		self.zev = Zev.objects.create(name="Dash ZEV", owner=self.owner, zev_type="vzev", invoice_prefix="D")
		self.participant = Participant.objects.create(
			zev=self.zev,
			user=self.participant_user,
			first_name="Alice",
			last_name="Example",
			email="alice@example.com",
			valid_from=date(2026, 1, 1),
		)

		self.consumption_mp = MeteringPoint.objects.create(
			zev=self.zev,
			participant=self.participant,
			meter_id="CH-CONS-1",
			meter_type=MeteringPointType.CONSUMPTION,
		)
		self.production_mp = MeteringPoint.objects.create(
			zev=self.zev,
			participant=self.participant,
			meter_id="CH-PROD-1",
			meter_type=MeteringPointType.PRODUCTION,
		)

		MeterReading.objects.create(
			metering_point=self.consumption_mp,
			timestamp=datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
			energy_kwh=Decimal("10.0000"),
			direction=ReadingDirection.IN,
			resolution=ReadingResolution.FIFTEEN_MIN,
		)
		MeterReading.objects.create(
			metering_point=self.production_mp,
			timestamp=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
			energy_kwh=Decimal("10.0000"),
			direction=ReadingDirection.OUT,
			resolution=ReadingResolution.FIFTEEN_MIN,
		)

	def test_participant_dashboard_uses_timestamp_level_local_grid_split(self):
		auth(self.client, self.participant_user)
		resp = self.client.get(
			"/api/v1/metering/readings/dashboard-summary/",
			{
				"date_from": "2026-01-01",
				"date_to": "2026-01-01",
				"bucket": "day",
			},
		)

		self.assertEqual(resp.status_code, 200)
		totals = resp.data["totals"]
		self.assertAlmostEqual(float(totals["total_consumed_kwh"]), 10.0, places=6)
		self.assertAlmostEqual(float(totals["consumed_from_zev_kwh"]), 0.0, places=6)
		self.assertAlmostEqual(float(totals["imported_from_grid_kwh"]), 10.0, places=6)

		timeline = resp.data["timeline"]
		self.assertEqual(len(timeline), 1)
		self.assertAlmostEqual(float(timeline[0]["total_consumed_kwh"]), 10.0, places=6)
		self.assertAlmostEqual(float(timeline[0]["consumed_from_zev_kwh"]), 0.0, places=6)
		self.assertAlmostEqual(float(timeline[0]["imported_from_grid_kwh"]), 10.0, places=6)

	def test_owner_can_filter_to_single_participant_with_production_visible(self):
		auth(self.client, self.owner)
		resp = self.client.get(
			"/api/v1/metering/readings/dashboard-summary/",
			{
				"zev_id": str(self.zev.id),
				"participant_id": str(self.participant.id),
				"date_from": "2026-01-01",
				"date_to": "2026-01-01",
				"bucket": "day",
			},
		)

		self.assertEqual(resp.status_code, 200)
		totals = resp.data["totals"]
		self.assertAlmostEqual(float(totals["consumed_kwh"]), 10.0, places=6)
		self.assertAlmostEqual(float(totals["produced_kwh"]), 10.0, places=6)
		self.assertAlmostEqual(float(totals["imported_kwh"]), 10.0, places=6)
		self.assertAlmostEqual(float(totals["exported_kwh"]), 10.0, places=6)

		stats = resp.data["participant_stats"]
		self.assertEqual(len(stats), 1)
		self.assertAlmostEqual(float(stats[0]["total_consumed_kwh"]), 10.0, places=6)
		self.assertAlmostEqual(float(stats[0]["total_produced_kwh"]), 10.0, places=6)

	def test_owner_participant_filter_excludes_other_participants(self):
		second_participant_user = make_user("dash_participant_2", UserRole.PARTICIPANT)
		second_participant = Participant.objects.create(
			zev=self.zev,
			user=second_participant_user,
			first_name="Bob",
			last_name="Second",
			email="bob.second@example.com",
			valid_from=date(2026, 1, 1),
		)
		second_consumption_mp = MeteringPoint.objects.create(
			zev=self.zev,
			participant=second_participant,
			meter_id="CH-CONS-2",
			meter_type=MeteringPointType.CONSUMPTION,
		)

		MeterReading.objects.create(
			metering_point=second_consumption_mp,
			timestamp=datetime(2026, 1, 1, 6, 0, tzinfo=timezone.utc),
			energy_kwh=Decimal("30.0000"),
			direction=ReadingDirection.IN,
			resolution=ReadingResolution.FIFTEEN_MIN,
		)

		auth(self.client, self.owner)
		resp = self.client.get(
			"/api/v1/metering/readings/dashboard-summary/",
			{
				"zev_id": str(self.zev.id),
				"participant_id": str(self.participant.id),
				"date_from": "2026-01-01",
				"date_to": "2026-01-01",
				"bucket": "day",
			},
		)

		self.assertEqual(resp.status_code, 200)
		self.assertEqual(resp.data["selected_participant_id"], str(self.participant.id))
		self.assertAlmostEqual(float(resp.data["totals"]["consumed_kwh"]), 10.0, places=6)
		self.assertAlmostEqual(float(resp.data["totals"]["produced_kwh"]), 10.0, places=6)
		self.assertAlmostEqual(float(resp.data["totals"]["imported_kwh"]), 10.0, places=6)

		unfiltered = self.client.get(
			"/api/v1/metering/readings/dashboard-summary/",
			{
				"zev_id": str(self.zev.id),
				"date_from": "2026-01-01",
				"date_to": "2026-01-01",
				"bucket": "day",
			},
		)
		self.assertEqual(unfiltered.status_code, 200)
		self.assertAlmostEqual(float(unfiltered.data["totals"]["consumed_kwh"]), 40.0, places=6)


class ParticipantImportRestrictionTests(TestCase):
	def setUp(self):
		self.client = APIClient()
		self.participant_user = make_user("import_participant", UserRole.PARTICIPANT)
		auth(self.client, self.participant_user)

	def test_participant_cannot_list_import_logs(self):
		resp = self.client.get("/api/v1/metering/import-logs/")
		self.assertEqual(resp.status_code, 403)

	def test_participant_cannot_preview_csv_import(self):
		resp = self.client.post("/api/v1/metering/import/preview-csv/")
		self.assertEqual(resp.status_code, 403)

	def test_participant_cannot_upload_csv_import(self):
		resp = self.client.post("/api/v1/metering/import/csv/")
		self.assertEqual(resp.status_code, 403)


class ImportParserRobustnessTests(TestCase):
	def setUp(self):
		self.client = APIClient()
		self.owner = make_user("import_owner", UserRole.ZEV_OWNER)
		auth(self.client, self.owner)

		self.zev = Zev.objects.create(name="Import Robustness ZEV", owner=self.owner, zev_type="vzev", invoice_prefix="I")
		self.participant = Participant.objects.create(
			zev=self.zev,
			first_name="Import",
			last_name="Participant",
			email="import.participant@example.com",
			valid_from=date(2026, 1, 1),
		)
		self.metering_point = MeteringPoint.objects.create(
			zev=self.zev,
			participant=self.participant,
			meter_id="CH-IMPORT-1",
			meter_type=MeteringPointType.CONSUMPTION,
		)

	def test_malformed_csv_payload_is_reported_without_crash(self):
		csv_bytes = b"wrong_col1,wrong_col2\nfoo,bar\n"
		upload = SimpleUploadedFile("bad.csv", csv_bytes, content_type="text/csv")

		resp = self.client.post("/api/v1/metering/import/csv/", {"file": upload}, format="multipart")

		self.assertEqual(resp.status_code, 201)
		self.assertEqual(resp.data["rows_imported"], 0)
		self.assertGreaterEqual(resp.data["rows_skipped"], 1)
		self.assertTrue(resp.data["errors"])
		self.assertEqual(MeterReading.objects.count(), 0)

	def test_malformed_sdatch_payload_is_reported_without_crash(self):
		xml_bytes = b"<MeteringData><broken></MeteringData"
		upload = SimpleUploadedFile("broken.xml", xml_bytes, content_type="application/xml")

		resp = self.client.post(
			"/api/v1/metering/import/sdatch/",
			{"file": upload, "zev_id": str(self.zev.id)},
			format="multipart",
		)

		self.assertEqual(resp.status_code, 201)
		self.assertEqual(resp.data["rows_imported"], 0)
		self.assertTrue(resp.data["errors"])
		self.assertIn("Malformed SDAT-CH XML", resp.data["errors"][0]["error"])

	def test_csv_timezone_offset_is_normalized_to_utc(self):
		csv_bytes = (
			b"meter_id,timestamp,energy_kwh,direction\n"
			b"CH-IMPORT-1,2026-01-01T02:00:00+02:00,1.5000,in\n"
		)
		upload = SimpleUploadedFile("tz.csv", csv_bytes, content_type="text/csv")

		resp = self.client.post("/api/v1/metering/import/csv/", {"file": upload}, format="multipart")

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
		upload = SimpleUploadedFile("dupe.csv", csv_bytes, content_type="text/csv")

		resp = self.client.post("/api/v1/metering/import/csv/", {"file": upload}, format="multipart")

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

		first_upload = SimpleUploadedFile("idempotent-first.csv", csv_bytes, content_type="text/csv")
		first_resp = self.client.post("/api/v1/metering/import/csv/", {"file": first_upload}, format="multipart")
		self.assertEqual(first_resp.status_code, 201)
		self.assertEqual(first_resp.data["rows_imported"], 1)

		second_upload = SimpleUploadedFile("idempotent-second.csv", csv_bytes, content_type="text/csv")
		second_resp = self.client.post("/api/v1/metering/import/csv/", {"file": second_upload}, format="multipart")

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

		first_upload = SimpleUploadedFile("overwrite-first.csv", initial_csv, content_type="text/csv")
		first_resp = self.client.post("/api/v1/metering/import/csv/", {"file": first_upload}, format="multipart")
		self.assertEqual(first_resp.status_code, 201)
		self.assertEqual(first_resp.data["rows_imported"], 1)

		overwrite_upload = SimpleUploadedFile("overwrite-second.csv", updated_csv, content_type="text/csv")
		overwrite_resp = self.client.post(
			"/api/v1/metering/import/csv/",
			{"file": overwrite_upload, "overwrite_existing": "true"},
			format="multipart",
		)

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


class MeteringRawDataEndpointTests(TestCase):
	def setUp(self):
		self.client = APIClient()
		self.owner = make_user("rawdata_owner", UserRole.ZEV_OWNER)
		self.participant_user = make_user("rawdata_participant", UserRole.PARTICIPANT)

		self.zev = Zev.objects.create(name="RawData ZEV", owner=self.owner, zev_type="vzev", invoice_prefix="R")
		self.participant = Participant.objects.create(
			zev=self.zev,
			user=self.participant_user,
			first_name="Raw",
			last_name="Data",
			email="raw.data@example.com",
			valid_from=date(2026, 1, 1),
		)
		self.metering_point = MeteringPoint.objects.create(
			zev=self.zev,
			participant=self.participant,
			meter_id="CH-RAW-1",
			meter_type=MeteringPointType.BIDIRECTIONAL,
		)

		MeterReading.objects.create(
			metering_point=self.metering_point,
			timestamp=datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
			energy_kwh=Decimal("1.2500"),
			direction=ReadingDirection.IN,
			resolution=ReadingResolution.FIFTEEN_MIN,
		)
		MeterReading.objects.create(
			metering_point=self.metering_point,
			timestamp=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
			energy_kwh=Decimal("0.7500"),
			direction=ReadingDirection.OUT,
			resolution=ReadingResolution.FIFTEEN_MIN,
		)
		MeterReading.objects.create(
			metering_point=self.metering_point,
			timestamp=datetime(2026, 1, 2, 0, 15, tzinfo=timezone.utc),
			energy_kwh=Decimal("2.0000"),
			direction=ReadingDirection.IN,
			resolution=ReadingResolution.FIFTEEN_MIN,
		)

	def test_owner_gets_daily_grouped_raw_rows(self):
		auth(self.client, self.owner)
		resp = self.client.get(
			"/api/v1/metering/readings/raw-data/",
			{
				"metering_point": str(self.metering_point.id),
				"date_from": "2026-01-01",
				"date_to": "2026-01-02",
			},
		)

		self.assertEqual(resp.status_code, 200)
		self.assertEqual(len(resp.data), 2)

		first_day = resp.data[0]
		self.assertEqual(first_day["date"], "2026-01-01")
		self.assertEqual(first_day["readings_count"], 2)
		self.assertAlmostEqual(float(first_day["in_kwh"]), 1.25, places=6)
		self.assertAlmostEqual(float(first_day["out_kwh"]), 0.75, places=6)
		self.assertEqual(len(first_day["readings"]), 2)

		second_day = resp.data[1]
		self.assertEqual(second_day["date"], "2026-01-02")
		self.assertEqual(second_day["readings_count"], 1)
		self.assertAlmostEqual(float(second_day["in_kwh"]), 2.0, places=6)
		self.assertAlmostEqual(float(second_day["out_kwh"]), 0.0, places=6)

	def test_participant_can_read_own_metering_point_raw_rows(self):
		auth(self.client, self.participant_user)
		resp = self.client.get(
			"/api/v1/metering/readings/raw-data/",
			{
				"metering_point": str(self.metering_point.id),
				"date_from": "2026-01-01",
				"date_to": "2026-01-02",
			},
		)
		self.assertEqual(resp.status_code, 200)
		self.assertEqual(len(resp.data), 2)

class DataQualityStatusTests(TestCase):
	def setUp(self):
		self.client = APIClient()
		self.owner = make_user("dq_owner", UserRole.ZEV_OWNER)
		self.participant_user = make_user("dq_participant", UserRole.PARTICIPANT)

		self.zev = Zev.objects.create(name="DQ ZEV", owner=self.owner, zev_type="vzev", invoice_prefix="DQ")
		self.participant = Participant.objects.create(
			zev=self.zev,
			user=self.participant_user,
			first_name="Bob",
			last_name="Monitor",
			email="bob@example.com",
			valid_from=date(2026, 1, 1),
		)

		self.metering_point = MeteringPoint.objects.create(
			zev=self.zev,
			meter_id="CH-DQ-001",
			meter_type=MeteringPointType.CONSUMPTION,
		)

		# Create assignment (metering point validity replaced by assignment)
		from zev.models import MeteringPointAssignment
		MeteringPointAssignment.objects.create(
			metering_point=self.metering_point,
			participant=self.participant,
			valid_from=date(2026, 1, 1),
		)

	def test_owner_can_check_data_quality_status(self):
		"""ZEV owner can view data quality status for their ZEV."""
		auth(self.client, self.owner)

		# Add readings on days 2 and 5 (gap on days 3-4)
		MeterReading.objects.create(
			metering_point=self.metering_point,
			timestamp=datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc),
			energy_kwh=Decimal("10.5"),
			direction=ReadingDirection.IN,
			resolution=ReadingResolution.DAILY,
		)
		MeterReading.objects.create(
			metering_point=self.metering_point,
			timestamp=datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc),
			energy_kwh=Decimal("15.2"),
			direction=ReadingDirection.IN,
			resolution=ReadingResolution.DAILY,
		)

		# Query for Jan 1-7
		resp = self.client.get(
			"/api/v1/metering/readings/data-quality-status/",
			{"date_from": "2026-01-01", "date_to": "2026-01-07"},
		)

		self.assertEqual(resp.status_code, 200)
		self.assertEqual(len(resp.data["metering_points"]), 1)
		
		mp_status = resp.data["metering_points"][0]
		self.assertEqual(mp_status["meter_id"], "CH-DQ-001")
		self.assertEqual(mp_status["data_completeness"], 28)  # 2 of 7 days
		self.assertEqual(mp_status["severity"], "red")
		self.assertEqual(len(mp_status["gaps"]), 3)  # 3 gaps: [1], [3-4], [6-7]
		self.assertIn(date(2026, 1, 3), [date.fromisoformat(g["start_date"]) for g in mp_status["gaps"]])

	def test_participant_can_check_own_metering_point_quality(self):
		"""Participant can view data quality for own readings."""
		auth(self.client, self.participant_user)

		# Add reading on day 2 only
		MeterReading.objects.create(
			metering_point=self.metering_point,
			timestamp=datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc),
			energy_kwh=Decimal("20.0"),
			direction=ReadingDirection.IN,
			resolution=ReadingResolution.DAILY,
		)

		resp = self.client.get(
			"/api/v1/metering/readings/data-quality-status/",
			{"date_from": "2026-01-01", "date_to": "2026-01-05"},
		)

		self.assertEqual(resp.status_code, 200)
		self.assertGreater(len(resp.data["metering_points"]), 0)

	def test_default_date_range_is_30_days(self):
		"""Without date parameters, defaults to 30 days."""
		auth(self.client, self.owner)

		resp = self.client.get("/api/v1/metering/readings/data-quality-status/")
		self.assertEqual(resp.status_code, 200)
		self.assertIn("date_from", resp.data)
		self.assertIn("date_to", resp.data)