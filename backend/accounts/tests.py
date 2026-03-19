from django.test import TestCase
from rest_framework.test import APIClient

from .models import AppSettings, User, UserRole, VatRate
from invoices.models import Invoice, InvoiceStatus
from zev.models import MeteringPoint, MeteringPointType, Participant, Zev
from datetime import date


class UserModelTests(TestCase):
	def test_user_role_helpers(self):
		admin = User.objects.create_user(username="admin", password="x", role=UserRole.ADMIN)
		owner = User.objects.create_user(username="owner", password="x", role=UserRole.ZEV_OWNER)
		participant = User.objects.create_user(
			username="participant", password="x", role=UserRole.PARTICIPANT
		)

		self.assertTrue(admin.is_admin)
		self.assertTrue(owner.is_zev_owner)
		self.assertFalse(participant.is_admin)


class PasswordChangeFlagTests(TestCase):
	def test_change_password_clears_must_change_password_flag(self):
		client = APIClient()
		user = User.objects.create_user(
			username="mustchange",
			password="old-pass-123",
			role=UserRole.PARTICIPANT,
			must_change_password=True,
		)

		resp = client.post("/api/v1/auth/token/", {"username": user.username, "password": "old-pass-123"})
		client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")

		change_resp = client.post(
			"/api/v1/auth/me/change-password/",
			{"old_password": "old-pass-123", "new_password": "new-pass-1234"},
		)

		self.assertEqual(change_resp.status_code, 200)
		user.refresh_from_db()
		self.assertFalse(user.must_change_password)


class ImpersonationTests(TestCase):
	def _auth(self, client, user, password="pass1234"):
		resp = client.post("/api/v1/auth/token/", {"username": user.username, "password": password})
		client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")

	def test_admin_can_impersonate_participant(self):
		client = APIClient()
		admin = User.objects.create_user(username="admin_imp", password="pass1234", role=UserRole.ADMIN)
		participant = User.objects.create_user(username="part_imp", password="pass1234", role=UserRole.PARTICIPANT)
		self._auth(client, admin)

		resp = client.post(f"/api/v1/auth/users/{participant.id}/impersonate/")

		self.assertEqual(resp.status_code, 200)
		self.assertIn("access", resp.data)
		self.assertIn("refresh", resp.data)
		self.assertEqual(resp.data["impersonated_user"]["id"], participant.id)

	def test_non_admin_cannot_impersonate(self):
		client = APIClient()
		owner = User.objects.create_user(username="owner_imp", password="pass1234", role=UserRole.ZEV_OWNER)
		participant = User.objects.create_user(username="part_imp_2", password="pass1234", role=UserRole.PARTICIPANT)
		self._auth(client, owner)

		resp = client.post(f"/api/v1/auth/users/{participant.id}/impersonate/")

		self.assertEqual(resp.status_code, 403)

	def test_admin_cannot_impersonate_non_participant(self):
		client = APIClient()
		admin = User.objects.create_user(username="admin_imp_2", password="pass1234", role=UserRole.ADMIN)
		owner = User.objects.create_user(username="owner_imp_2", password="pass1234", role=UserRole.ZEV_OWNER)
		self._auth(client, admin)

		resp = client.post(f"/api/v1/auth/users/{owner.id}/impersonate/")

		self.assertEqual(resp.status_code, 200)
		self.assertEqual(resp.data["impersonated_user"]["id"], owner.id)

	def test_admin_cannot_impersonate_admin(self):
		client = APIClient()
		admin = User.objects.create_user(username="admin_imp_3", password="pass1234", role=UserRole.ADMIN)
		other_admin = User.objects.create_user(username="admin_imp_4", password="pass1234", role=UserRole.ADMIN)
		self._auth(client, admin)

		resp = client.post(f"/api/v1/auth/users/{other_admin.id}/impersonate/")

		self.assertEqual(resp.status_code, 400)


class LinkedAccountSafetyTests(TestCase):
	def _auth(self, client, user, password="pass1234"):
		resp = client.post("/api/v1/auth/token/", {"username": user.username, "password": password})
		client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")

	def setUp(self):
		self.client = APIClient()
		self.admin = User.objects.create_user(username="admin_safety", password="pass1234", role=UserRole.ADMIN)
		self.owner = User.objects.create_user(username="owner_safety", password="pass1234", role=UserRole.ZEV_OWNER)
		self.linked_account = User.objects.create_user(username="linked_account", password="pass1234", role=UserRole.PARTICIPANT)
		self.unlinked_account = User.objects.create_user(username="unlinked_account", password="pass1234", role=UserRole.PARTICIPANT)

		zev = Zev.objects.create(name="Safety ZEV", owner=self.owner, zev_type="vzev", invoice_prefix="S")
		Participant.objects.create(
			zev=zev,
			user=self.linked_account,
			first_name="Linked",
			last_name="Person",
			email="linked@example.com",
			valid_from=date(2026, 1, 1),
		)

		self._auth(self.client, self.admin)

	def test_admin_cannot_edit_linked_account(self):
		resp = self.client.patch(
			f"/api/v1/auth/users/{self.linked_account.id}/",
			{"first_name": "Blocked"},
			format="json",
		)
		self.assertEqual(resp.status_code, 403)

	def test_admin_cannot_delete_linked_account(self):
		resp = self.client.delete(f"/api/v1/auth/users/{self.linked_account.id}/")
		self.assertEqual(resp.status_code, 403)

	def test_admin_can_edit_and_delete_unlinked_account(self):
		update_resp = self.client.patch(
			f"/api/v1/auth/users/{self.unlinked_account.id}/",
			{"first_name": "Allowed"},
			format="json",
		)
		delete_resp = self.client.delete(f"/api/v1/auth/users/{self.unlinked_account.id}/")

		self.assertEqual(update_resp.status_code, 200)
		self.assertEqual(delete_resp.status_code, 204)

	def test_admin_cannot_change_own_role_via_user_detail(self):
		resp = self.client.patch(
			f"/api/v1/auth/users/{self.admin.id}/",
			{"role": UserRole.PARTICIPANT},
			format="json",
		)
		self.assertEqual(resp.status_code, 400)

	def test_admin_cannot_change_own_role_via_me(self):
		resp = self.client.patch(
			"/api/v1/auth/me/",
			{"role": UserRole.PARTICIPANT},
			format="json",
		)
		self.assertEqual(resp.status_code, 400)


class AppSettingsTests(TestCase):
	def _auth(self, client, user, password="pass1234"):
		resp = client.post("/api/v1/auth/token/", {"username": user.username, "password": password})
		client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")

	def setUp(self):
		self.client = APIClient()
		self.admin = User.objects.create_user(username="admin_settings", password="pass1234", role=UserRole.ADMIN)
		self.owner = User.objects.create_user(username="owner_settings", password="pass1234", role=UserRole.ZEV_OWNER)

	def test_authenticated_user_can_read_settings(self):
		self._auth(self.client, self.owner)

		resp = self.client.get("/api/v1/auth/app-settings/")

		self.assertEqual(resp.status_code, 200)
		self.assertEqual(resp.data["date_format_short"], AppSettings.SHORT_DATE_DD_MM_YYYY)
		self.assertEqual(resp.data["date_format_long"], AppSettings.LONG_DATE_D_MMMM_YYYY)
		self.assertEqual(resp.data["date_time_format"], AppSettings.DATETIME_DD_MM_YYYY_HH_MM)

	def test_admin_can_update_settings(self):
		self._auth(self.client, self.admin)

		resp = self.client.patch(
			"/api/v1/auth/app-settings/",
			{
				"date_format_short": AppSettings.SHORT_DATE_YYYY_MM_DD,
				"date_format_long": AppSettings.LONG_DATE_MMMM_D_YYYY,
				"date_time_format": AppSettings.DATETIME_YYYY_MM_DD_HH_MM,
			},
			format="json",
		)

		self.assertEqual(resp.status_code, 200)
		settings_obj = AppSettings.load()
		self.assertEqual(settings_obj.date_format_short, AppSettings.SHORT_DATE_YYYY_MM_DD)
		self.assertEqual(settings_obj.date_format_long, AppSettings.LONG_DATE_MMMM_D_YYYY)
		self.assertEqual(settings_obj.date_time_format, AppSettings.DATETIME_YYYY_MM_DD_HH_MM)

	def test_non_admin_cannot_update_settings(self):
		self._auth(self.client, self.owner)

		resp = self.client.patch(
			"/api/v1/auth/app-settings/",
			{"date_format_short": AppSettings.SHORT_DATE_YYYY_MM_DD},
			format="json",
		)

		self.assertEqual(resp.status_code, 403)


class VatRateSettingsTests(TestCase):
	def _auth(self, client, user, password="pass1234"):
		resp = client.post("/api/v1/auth/token/", {"username": user.username, "password": password})
		client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")

	def setUp(self):
		self.client = APIClient()
		self.admin = User.objects.create_user(username="admin_vat", password="pass1234", role=UserRole.ADMIN)
		self.owner = User.objects.create_user(username="owner_vat", password="pass1234", role=UserRole.ZEV_OWNER)

	def test_admin_can_crud_vat_rates(self):
		self._auth(self.client, self.admin)

		create_resp = self.client.post(
			"/api/v1/auth/vat-rates/",
			{"rate": "0.0810", "valid_from": "2026-01-01", "valid_to": None},
			format="json",
		)
		self.assertEqual(create_resp.status_code, 201)
		rate_id = create_resp.data["id"]

		list_resp = self.client.get("/api/v1/auth/vat-rates/")
		self.assertEqual(list_resp.status_code, 200)
		self.assertEqual(len(list_resp.data["results"]), 1)

		patch_resp = self.client.patch(
			f"/api/v1/auth/vat-rates/{rate_id}/",
			{"rate": "0.0820"},
			format="json",
		)
		self.assertEqual(patch_resp.status_code, 200)
		self.assertEqual(patch_resp.data["rate"], "0.0820")

		delete_resp = self.client.delete(f"/api/v1/auth/vat-rates/{rate_id}/")
		self.assertEqual(delete_resp.status_code, 204)
		self.assertFalse(VatRate.objects.filter(pk=rate_id).exists())

	def test_non_admin_cannot_manage_vat_rates(self):
		self._auth(self.client, self.owner)

		list_resp = self.client.get("/api/v1/auth/vat-rates/")
		self.assertEqual(list_resp.status_code, 403)

		create_resp = self.client.post(
			"/api/v1/auth/vat-rates/",
			{"rate": "0.0810", "valid_from": "2026-01-01", "valid_to": None},
			format="json",
		)
		self.assertEqual(create_resp.status_code, 403)

	def test_vat_rate_ranges_cannot_overlap(self):
		self._auth(self.client, self.admin)
		VatRate.objects.create(rate="0.0770", valid_from=date(2024, 1, 1), valid_to=date(2025, 12, 31))

		resp = self.client.post(
			"/api/v1/auth/vat-rates/",
			{"rate": "0.0810", "valid_from": "2025-12-01", "valid_to": "2026-12-31"},
			format="json",
		)

		self.assertEqual(resp.status_code, 400)
		self.assertIn("overlap", str(resp.data).lower())

	def test_vat_rate_valid_to_must_be_after_valid_from(self):
		self._auth(self.client, self.admin)

		resp = self.client.post(
			"/api/v1/auth/vat-rates/",
			{"rate": "0.0810", "valid_from": "2026-02-01", "valid_to": "2026-01-01"},
			format="json",
		)

		self.assertEqual(resp.status_code, 400)
		self.assertIn("valid_to", resp.data)


class RbacEndpointMatrixTests(TestCase):
	def _auth(self, client, user, password="pass1234"):
		resp = client.post("/api/v1/auth/token/", {"username": user.username, "password": password})
		client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")

	def setUp(self):
		self.clients = {}

		self.admin = User.objects.create_user(username="rbac_matrix_admin", password="pass1234", role=UserRole.ADMIN)
		self.owner = User.objects.create_user(username="rbac_matrix_owner", password="pass1234", role=UserRole.ZEV_OWNER)
		self.participant_user = User.objects.create_user(username="rbac_matrix_participant", password="pass1234", role=UserRole.PARTICIPANT)
		self.guest = User.objects.create_user(username="rbac_matrix_guest", password="pass1234", role=UserRole.GUEST)

		self.zev = Zev.objects.create(name="RBAC Matrix ZEV", owner=self.owner, zev_type="vzev", invoice_prefix="R")
		self.participant = Participant.objects.create(
			zev=self.zev,
			user=self.participant_user,
			first_name="Role",
			last_name="Participant",
			email="role.participant@example.com",
			valid_from=date(2026, 1, 1),
		)
		self.metering_point = MeteringPoint.objects.create(
			zev=self.zev,
			participant=self.participant,
			meter_id="RBAC-MP-1",
			meter_type=MeteringPointType.CONSUMPTION,
			valid_from=date(2026, 1, 1),
		)

		for role, user in {
			"admin": self.admin,
			"owner": self.owner,
			"participant": self.participant_user,
			"guest": self.guest,
		}.items():
			client = APIClient()
			self._auth(client, user)
			self.clients[role] = client

	def test_list_endpoint_role_matrix(self):
		matrix = [
			{
				"url": "/api/v1/zev/zevs/",
				"expected": {"admin": 200, "owner": 200, "participant": 403, "guest": 403},
			},
			{
				"url": "/api/v1/zev/participants/",
				"expected": {"admin": 200, "owner": 200, "participant": 403, "guest": 403},
			},
			{
				"url": "/api/v1/zev/metering-points/",
				"expected": {"admin": 200, "owner": 200, "participant": 200, "guest": 200},
			},
			{
				"url": "/api/v1/zev/metering-point-assignments/",
				"expected": {"admin": 200, "owner": 200, "participant": 403, "guest": 403},
			},
			{
				"url": "/api/v1/tariffs/tariffs/",
				"expected": {"admin": 200, "owner": 200, "participant": 403, "guest": 403},
			},
			{
				"url": "/api/v1/metering/readings/",
				"expected": {"admin": 200, "owner": 200, "participant": 403, "guest": 403},
			},
			{
				"url": "/api/v1/invoices/invoices/",
				"expected": {"admin": 200, "owner": 200, "participant": 200, "guest": 200},
			},
		]

		for case in matrix:
			for role, client in self.clients.items():
				with self.subTest(url=case["url"], role=role):
					resp = client.get(case["url"])
					self.assertEqual(resp.status_code, case["expected"][role])

	def test_invoice_dashboard_is_admin_only(self):
		expected = {
			"admin": 200,
			"owner": 403,
			"participant": 403,
			"guest": 403,
		}

		for role, client in self.clients.items():
			with self.subTest(role=role):
				resp = client.get("/api/v1/invoices/invoices/dashboard/")
				self.assertEqual(resp.status_code, expected[role])

	def test_create_endpoint_role_matrix(self):
		create_cases = [
			{
				"url": "/api/v1/zev/zevs/",
				"payload": {
					"name": "RBAC Created ZEV",
					"start_date": "2026-01-01",
					"zev_type": "vzev",
					"billing_interval": "monthly",
					"owner": self.owner.id,
				},
				"expected": {"admin": 201, "owner": 403, "participant": 403, "guest": 403},
			},
			{
				"url": "/api/v1/zev/metering-points/",
				"payload": {
					"zev": str(self.zev.id),
					"participant": str(self.participant.id),
					"meter_id": "RBAC-MP-CREATE",
					"meter_type": MeteringPointType.CONSUMPTION,
					"valid_from": "2026-01-01",
				},
				"expected": {"admin": 201, "owner": 201, "participant": 403, "guest": 403},
			},
			{
				"url": "/api/v1/tariffs/tariffs/",
				"payload": {
					"zev": str(self.zev.id),
					"name": "RBAC Tariff",
					"category": "grid_fees",
					"billing_mode": "monthly_fee",
					"fixed_price_chf": "10.00",
					"valid_from": "2026-01-01",
				},
				"expected": {"admin": 201, "owner": 201, "participant": 403, "guest": 403},
			},
		]

		for case in create_cases:
			for role, client in self.clients.items():
				with self.subTest(url=case["url"], role=role):
					payload = dict(case["payload"])
					if case["url"] == "/api/v1/zev/zevs/" and role == "admin":
						payload["name"] = f"RBAC Created ZEV {role}"
					if case["url"] == "/api/v1/zev/metering-points/":
						payload["meter_id"] = f"RBAC-MP-{role}"
					if case["url"] == "/api/v1/tariffs/tariffs/" and role in ("admin", "owner"):
						payload["name"] = f"RBAC Tariff {role}"
					resp = client.post(case["url"], payload, format="json")
					self.assertEqual(resp.status_code, case["expected"][role])

	def test_update_endpoint_role_matrix(self):
		expected = {"admin": 200, "owner": 200, "participant": 403, "guest": 403}

		for role, client in self.clients.items():
			with self.subTest(role=role):
				resp = client.patch(
					f"/api/v1/zev/participants/{self.participant.id}/",
					{"phone": f"+41 79 000 0{len(role)} 00"},
					format="json",
				)
				self.assertEqual(resp.status_code, expected[role])

	def test_action_and_delete_role_matrix(self):
		action_expected = {"admin": 200, "owner": 200, "participant": 403, "guest": 403}
		delete_expected = {"admin": 204, "owner": 204, "participant": 403, "guest": 404}

		for role, client in self.clients.items():
			with self.subTest(role=role, operation="approve"):
				invoice = Invoice.objects.create(
					invoice_number=f"R-{role}-A",
					zev=self.zev,
					participant=self.participant,
					period_start=date(2026, 1, 1),
					period_end=date(2026, 1, 31),
					status=InvoiceStatus.DRAFT,
					total_chf="12.00",
				)
				resp = client.post(f"/api/v1/invoices/invoices/{invoice.id}/approve/")
				self.assertEqual(resp.status_code, action_expected[role])

			with self.subTest(role=role, operation="delete"):
				invoice = Invoice.objects.create(
					invoice_number=f"R-{role}-D",
					zev=self.zev,
					participant=self.participant,
					period_start=date(2026, 2, 1),
					period_end=date(2026, 2, 28),
					status=InvoiceStatus.DRAFT,
					total_chf="15.00",
				)
				resp = client.delete(f"/api/v1/invoices/invoices/{invoice.id}/")
				self.assertEqual(resp.status_code, delete_expected[role])

	def test_unauthenticated_matrix_returns_401(self):
		client = APIClient()

		invoice = Invoice.objects.create(
			invoice_number="R-unauth-1",
			zev=self.zev,
			participant=self.participant,
			period_start=date(2026, 3, 1),
			period_end=date(2026, 3, 31),
			status=InvoiceStatus.DRAFT,
			total_chf="20.00",
		)

		cases = [
			("GET", "/api/v1/zev/zevs/", None),
			("GET", "/api/v1/zev/participants/", None),
			("GET", "/api/v1/zev/metering-points/", None),
			("GET", "/api/v1/tariffs/tariffs/", None),
			("GET", "/api/v1/metering/readings/", None),
			("GET", "/api/v1/invoices/invoices/", None),
			("GET", "/api/v1/invoices/invoices/dashboard/", None),
			(
				"POST",
				"/api/v1/zev/metering-points/",
				{
					"zev": str(self.zev.id),
					"participant": str(self.participant.id),
					"meter_id": "RBAC-MP-unauth",
					"meter_type": MeteringPointType.CONSUMPTION,
					"valid_from": "2026-01-01",
				},
			),
			("PATCH", f"/api/v1/zev/participants/{self.participant.id}/", {"phone": "+41 79 999 99 99"}),
			("POST", f"/api/v1/invoices/invoices/{invoice.id}/approve/", None),
			("DELETE", f"/api/v1/invoices/invoices/{invoice.id}/", None),
		]

		for method, url, payload in cases:
			with self.subTest(method=method, url=url):
				if method == "GET":
					resp = client.get(url)
				elif method == "POST":
					if payload is None:
						resp = client.post(url)
					else:
						resp = client.post(url, payload, format="json")
				elif method == "PATCH":
					resp = client.patch(url, payload, format="json")
				else:
					resp = client.delete(url)

				self.assertEqual(resp.status_code, 401)
