from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import User, UserRole
from tariffs.models import BillingMode, Tariff, TariffCategory, TariffPeriod
from zev.models import Zev


def auth(client, user, password="pass1234"):
	resp = client.post("/api/v1/auth/token/", {"username": user.username, "password": password})
	client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")


class TariffPermissionTests(TestCase):
	def test_participant_cannot_access_tariffs(self):
		client = APIClient()
		participant = User.objects.create_user(
			username="tariff_participant",
			password="pass1234",
			role=UserRole.PARTICIPANT,
		)
		auth(client, participant)

		resp = client.get("/api/v1/tariffs/tariffs/")
		self.assertEqual(resp.status_code, 403)

	def test_owner_can_create_monthly_fee_tariff(self):
		client = APIClient()
		owner = User.objects.create_user(
			username="tariff_owner",
			password="pass1234",
			role=UserRole.ZEV_OWNER,
		)
		zev = Zev.objects.create(name="Tariff ZEV", owner=owner, zev_type="vzev")
		auth(client, owner)

		resp = client.post("/api/v1/tariffs/tariffs/", {
			"zev": str(zev.id),
			"name": "Monthly metering fee",
			"category": TariffCategory.GRID_FEES,
			"billing_mode": BillingMode.MONTHLY_FEE,
			"fixed_price_chf": "15.00",
			"valid_from": "2026-01-01",
		}, format="json")
		self.assertEqual(resp.status_code, 201)
		self.assertEqual(Tariff.objects.get(name="Monthly metering fee").energy_type, None)

	def test_owner_can_create_per_metering_point_monthly_fee_tariff(self):
		client = APIClient()
		owner = User.objects.create_user(
			username="tariff_owner_3",
			password="pass1234",
			role=UserRole.ZEV_OWNER,
		)
		zev = Zev.objects.create(name="Tariff ZEV 3", owner=owner, zev_type="vzev")
		auth(client, owner)

		resp = client.post("/api/v1/tariffs/tariffs/", {
			"zev": str(zev.id),
			"name": "Per MP monthly",
			"category": TariffCategory.GRID_FEES,
			"billing_mode": BillingMode.PER_METERING_POINT_MONTHLY_FEE,
			"fixed_price_chf": "4.50",
			"valid_from": "2026-01-01",
		}, format="json")
		self.assertEqual(resp.status_code, 201)

	def test_cannot_add_period_to_fixed_fee_tariff(self):
		client = APIClient()
		owner = User.objects.create_user(
			username="tariff_owner_2",
			password="pass1234",
			role=UserRole.ZEV_OWNER,
		)
		zev = Zev.objects.create(name="Tariff ZEV 2", owner=owner, zev_type="vzev")
		tariff = Tariff.objects.create(
			zev=zev,
			name="Annual fee",
			category=TariffCategory.LEVIES,
			billing_mode=BillingMode.YEARLY_FEE,
			fixed_price_chf="120.00",
			valid_from="2026-01-01",
		)
		auth(client, owner)

		resp = client.post("/api/v1/tariffs/periods/", {
			"tariff": str(tariff.id),
			"period_type": "flat",
			"price_chf_per_kwh": "0.10",
		}, format="json")
		self.assertEqual(resp.status_code, 400)

	def test_owner_can_export_tariffs_as_json(self):
		client = APIClient()
		owner = User.objects.create_user(
			username="tariff_owner_export",
			password="pass1234",
			role=UserRole.ZEV_OWNER,
		)
		zev = Zev.objects.create(name="Tariff Export ZEV", owner=owner, zev_type="vzev")
		tariff = Tariff.objects.create(
			zev=zev,
			name="Energy Local",
			category=TariffCategory.ENERGY,
			billing_mode=BillingMode.ENERGY,
			energy_type="local",
			valid_from="2026-01-01",
		)
		TariffPeriod.objects.create(
			tariff=tariff,
			period_type="flat",
			price_chf_per_kwh="0.22",
		)
		auth(client, owner)

		resp = client.get(f"/api/v1/tariffs/tariffs/export/?zev_id={zev.id}")

		self.assertEqual(resp.status_code, 200)
		self.assertEqual(len(resp.data), 1)
		self.assertEqual(resp.data[0]["name"], "Energy Local")
		self.assertNotIn("zev", resp.data[0])
		self.assertNotIn("id", resp.data[0])
		self.assertEqual(len(resp.data[0]["periods"]), 1)
		self.assertNotIn("tariff", resp.data[0]["periods"][0])

	def test_owner_can_export_percentage_of_energy_tariff_with_percentage(self):
		client = APIClient()
		owner = User.objects.create_user(
			username="tariff_owner_export_percentage",
			password="pass1234",
			role=UserRole.ZEV_OWNER,
		)
		zev = Zev.objects.create(name="Tariff Export Percentage ZEV", owner=owner, zev_type="vzev")
		Tariff.objects.create(
			zev=zev,
			name="Grid Surcharge %",
			category=TariffCategory.GRID_FEES,
			billing_mode=BillingMode.PERCENTAGE_OF_ENERGY,
			energy_type="grid",
			percentage="12.50",
			valid_from="2026-01-01",
		)
		auth(client, owner)

		resp = client.get(f"/api/v1/tariffs/tariffs/export/?zev_id={zev.id}")

		self.assertEqual(resp.status_code, 200)
		self.assertEqual(len(resp.data), 1)
		self.assertEqual(resp.data[0]["billing_mode"], BillingMode.PERCENTAGE_OF_ENERGY)
		self.assertEqual(resp.data[0]["percentage"], "12.50")

	def test_owner_can_import_tariffs_from_json(self):
		client = APIClient()
		owner = User.objects.create_user(
			username="tariff_owner_import",
			password="pass1234",
			role=UserRole.ZEV_OWNER,
		)
		zev = Zev.objects.create(name="Tariff Import ZEV", owner=owner, zev_type="vzev")
		auth(client, owner)

		payload = {
			"zev_id": str(zev.id),
			"tariffs": [
				{
					"name": "Imported Energy",
					"category": "energy",
					"billing_mode": "energy",
					"energy_type": "grid",
					"valid_from": "2026-01-01",
					"valid_to": None,
					"notes": "Imported preset",
					"periods": [
						{
							"period_type": "flat",
							"price_chf_per_kwh": "0.31",
							"time_from": None,
							"time_to": None,
							"weekdays": "",
						}
					],
				}
			],
		}

		resp = client.post("/api/v1/tariffs/tariffs/import/", payload, format="json")

		self.assertEqual(resp.status_code, 201)
		self.assertEqual(resp.data["created"], 1)
		imported_tariff = Tariff.objects.get(name="Imported Energy")
		self.assertEqual(str(imported_tariff.zev_id), str(zev.id))
		self.assertEqual(imported_tariff.periods.count(), 1)

	def test_owner_can_roundtrip_percentage_of_energy_tariff(self):
		client = APIClient()
		owner = User.objects.create_user(
			username="tariff_owner_roundtrip_percentage",
			password="pass1234",
			role=UserRole.ZEV_OWNER,
		)
		source_zev = Zev.objects.create(name="Tariff Source ZEV", owner=owner, zev_type="vzev")
		target_zev = Zev.objects.create(name="Tariff Target ZEV", owner=owner, zev_type="vzev")
		Tariff.objects.create(
			zev=source_zev,
			name="Imported Percentage Tariff",
			category=TariffCategory.GRID_FEES,
			billing_mode=BillingMode.PERCENTAGE_OF_ENERGY,
			energy_type="grid",
			percentage="7.25",
			valid_from="2026-01-01",
			notes="Roundtrip check",
		)
		auth(client, owner)

		export_resp = client.get(f"/api/v1/tariffs/tariffs/export/?zev_id={source_zev.id}")
		self.assertEqual(export_resp.status_code, 200)
		self.assertEqual(len(export_resp.data), 1)
		self.assertEqual(export_resp.data[0]["percentage"], "7.25")

		import_resp = client.post(
			"/api/v1/tariffs/tariffs/import/",
			{"zev_id": str(target_zev.id), "tariffs": export_resp.data},
			format="json",
		)
		self.assertEqual(import_resp.status_code, 201)

		roundtripped = Tariff.objects.get(zev=target_zev, name="Imported Percentage Tariff")
		self.assertEqual(roundtripped.billing_mode, BillingMode.PERCENTAGE_OF_ENERGY)
		self.assertEqual(roundtripped.energy_type, "grid")
		self.assertEqual(str(roundtripped.percentage), "7.25")
		self.assertIsNone(roundtripped.fixed_price_chf)
