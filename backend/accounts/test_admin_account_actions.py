"""Admin console actions on accounts: creating one and deactivating one.

Spec: docs/specs/2026-03-community-and-access.md §6.2, §6.3a.
"""

from django.test import TestCase

from audit.models import AuditEvent
from testing.helpers import authenticate, make_user

from .models import User, UserRole
from rest_framework.test import APIClient

USERS_URL = "/api/v1/auth/users/"


def _detail(pk):
    return f"/api/v1/auth/users/{pk}/"


class AccountCreationTests(TestCase):
    def setUp(self):
        self.admin = make_user("aa_admin", UserRole.ADMIN)
        self.client = APIClient()
        authenticate(self.client, self.admin)

    def _create(self, **overrides):
        payload = {
            "username": "aa_new", "email": "aa_new@example.com",
            "first_name": "New", "last_name": "Account", "role": "participant",
            **overrides,
        }
        return self.client.post(USERS_URL, payload, format="json")

    def test_omitting_a_password_generates_one_and_returns_it_once(self):
        response = self._create()

        self.assertEqual(response.status_code, 201, response.content)
        password = response.data["generated_password"]
        self.assertGreaterEqual(len(password), 16)
        user = User.objects.get(username="aa_new")
        self.assertTrue(user.check_password(password))
        self.assertTrue(user.must_change_password)
        # Never persisted anywhere else, and never in the plain user list either.
        self.assertNotIn("generated_password", self.client.get(USERS_URL).json()["results"][0])

    def test_two_created_accounts_get_different_passwords(self):
        first = self._create(username="aa_one", email="aa_one@example.com").data["generated_password"]
        second = self._create(username="aa_two", email="aa_two@example.com").data["generated_password"]
        self.assertNotEqual(first, second)

    def test_a_supplied_password_is_still_accepted_and_still_forces_a_change(self):
        response = self._create(password="Uniquely-Long-9164!", password2="Uniquely-Long-9164!")

        self.assertEqual(response.status_code, 201, response.content)
        self.assertNotIn("generated_password", response.data)
        user = User.objects.get(username="aa_new")
        self.assertTrue(user.check_password("Uniquely-Long-9164!"))
        self.assertTrue(user.must_change_password)

    def test_mismatched_supplied_passwords_are_rejected(self):
        response = self._create(password="Uniquely-Long-9164!", password2="something-else-9164!")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(User.objects.filter(username="aa_new").exists())

    def test_a_weak_supplied_password_is_rejected_by_the_validators(self):
        response = self._create(password="password", password2="password")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(User.objects.filter(username="aa_new").exists())

    def test_generated_password_skips_validation_but_is_long_enough_to_pass_it(self):
        # It never goes through validate_password (there is nothing for a
        # human to judge as weak), but it must still actually satisfy Django's
        # validators — nothing here should mint a password that would itself
        # be rejected on the next change.
        from django.contrib.auth.password_validation import validate_password

        response = self._create()
        validate_password(response.data["generated_password"])  # raises on failure

    def test_response_carries_the_new_accounts_id(self):
        response = self._create()
        self.assertEqual(response.data["id"], User.objects.get(username="aa_new").pk)

    def test_non_admin_cannot_create_an_account(self):
        client = APIClient()
        authenticate(client, make_user("aa_owner", UserRole.ZEV_OWNER))
        response = client.post(USERS_URL, {"username": "aa_blocked", "email": "x@example.com",
                                            "first_name": "x", "last_name": "y", "role": "participant"}, format="json")
        self.assertEqual(response.status_code, 403)


class SelfDeactivationGuardTests(TestCase):
    def setUp(self):
        self.admin = make_user("sd_admin", UserRole.ADMIN)
        self.client = APIClient()
        authenticate(self.client, self.admin)

    def test_an_admin_cannot_deactivate_their_own_account(self):
        response = self.client.patch(_detail(self.admin.pk), {"is_active": False}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("is_active", response.json())
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_an_admin_can_deactivate_someone_else(self):
        other = make_user("sd_other", UserRole.PARTICIPANT)
        response = self.client.patch(_detail(other.pk), {"is_active": False}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        other.refresh_from_db()
        self.assertFalse(other.is_active)
        self.assertTrue(AuditEvent.objects.filter(action_type="user.update", target_id=str(other.pk)).exists())

    def test_reactivating_the_admins_own_account_is_unaffected_by_the_guard(self):
        # The guard only concerns turning it off; a payload that leaves it (or
        # sets it) true must not be blocked by the same-account check.
        response = self.client.patch(_detail(self.admin.pk), {"is_active": True}, format="json")
        self.assertEqual(response.status_code, 200)

    def test_deactivating_someone_else_still_revokes_their_sessions(self):
        from .jwt_utils import make_jwt_for_user

        other = make_user("sd_sessions", UserRole.PARTICIPANT)
        tokens = make_jwt_for_user(other)
        other_client = APIClient()
        other_client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
        self.assertEqual(other_client.get("/api/v1/auth/me/").status_code, 200)

        self.client.patch(_detail(other.pk), {"is_active": False}, format="json")

        self.assertEqual(other_client.get("/api/v1/auth/me/").status_code, 401)
