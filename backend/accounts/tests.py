from django.test import TestCase
from rest_framework.test import APIClient

from .models import AppSettings, User, UserRole
from zev.models import Zev, Participant
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
