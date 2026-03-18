from datetime import date, datetime, timezone
from decimal import Decimal

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
			valid_from=date(2026, 1, 1),
		)
		self.production_mp = MeteringPoint.objects.create(
			zev=self.zev,
			participant=self.participant,
			meter_id="CH-PROD-1",
			meter_type=MeteringPointType.PRODUCTION,
			valid_from=date(2026, 1, 1),
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
			valid_from=date(2026, 1, 1),
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
