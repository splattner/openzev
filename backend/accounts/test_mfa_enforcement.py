"""Server-side enforcement of the MFA enrolment policy on interactive
sessions — the gap left by ``MfaEnrolmentGate``, which only withholds the
browser UI and stops nothing at the API. See
``accounts.authentication.enforce_mfa_enrolment`` and
docs/specs/2026-09-two-factor-authentication.md §7.3a.
"""

from datetime import timedelta

from cryptography.fernet import Fernet
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from audit.models import AuditEvent, AuditEventStatus
from testing.helpers import authenticate as auth, make_user

from .jwt_utils import make_jwt_for_user
from .models import AppSettings, UserRole
from .test_api_keys import create_api_key

ME = "/api/v1/auth/me/"
CHANGE_PASSWORD = "/api/v1/auth/me/change-password/"
TOTP_DEVICE = "/api/v1/auth/me/mfa/totp/"
API_KEYS = "/api/v1/auth/me/api-keys/"
TOTP_KEY = Fernet.generate_key().decode()


def _unsafe_write(client):
    """A representative unsafe, non-exempt, any-role-reachable request: creating
    an API key. ('/auth/me/' itself is deliberately exempt — see
    ExemptSelfServiceRoutesTests — so it cannot stand in for "some ordinary
    write" here.)"""
    return client.post(API_KEYS, {"name": "probe"}, format="json")


def _set_policy(*, roles, grace_days=1, changed_days_ago=None):
    AppSettings.load()  # the row must exist before .update() can touch it
    AppSettings.objects.update(mfa_required_roles=roles, mfa_grace_period_days=grace_days)
    if changed_days_ago is not None:
        AppSettings.objects.update(mfa_policy_changed_at=timezone.now() - timedelta(days=changed_days_ago))


def _overdue_user(username, role=UserRole.PARTICIPANT):
    """A freshly created account, backdated so a 1-day grace period from
    policy-change time has already passed."""
    user = make_user(username, role)
    type(user).objects.filter(pk=user.pk).update(date_joined=timezone.now() - timedelta(days=30))
    return user


class MfaEnrolmentEnforcementTests(TestCase):
    def setUp(self):
        AppSettings.load()  # pre-create the singleton; see test_admin_users_list.py

    def test_a_write_is_refused_once_overdue_with_no_factor(self):
        user = _overdue_user("mee_overdue")
        _set_policy(roles=["participant"], grace_days=1, changed_days_ago=30)
        client = APIClient()
        auth(client, user)

        response = _unsafe_write(client)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "mfa_enrolment_required")
        event = AuditEvent.objects.get(action_type="auth.mfa.enrolment_required")
        self.assertEqual(event.status, AuditEventStatus.DENIED)
        self.assertEqual(event.target_id, str(user.pk))

    def test_reads_are_never_blocked(self):
        user = _overdue_user("mee_read")
        _set_policy(roles=["participant"], grace_days=1, changed_days_ago=30)
        client = APIClient()
        auth(client, user)

        self.assertEqual(client.get(ME).status_code, 200)

    def test_within_the_grace_period_writes_still_work(self):
        user = make_user("mee_grace", UserRole.PARTICIPANT)  # joined "now"
        _set_policy(roles=["participant"], grace_days=30)
        client = APIClient()
        auth(client, user)

        self.assertEqual(_unsafe_write(client).status_code, 201)

    def test_an_enrolled_account_is_never_blocked_even_past_the_deadline(self):
        from .models import TotpDevice

        user = _overdue_user("mee_enrolled")
        _set_policy(roles=["participant"], grace_days=1, changed_days_ago=30)
        device = TotpDevice(user=user, confirmed_at=timezone.now())
        with self.settings(MFA_ENCRYPTION_KEYS=[TOTP_KEY]):
            device.set_secret("JBSWY3DPEHPK3PXP")
            device.save()

        client = APIClient()
        auth(client, user)
        response = _unsafe_write(client)
        self.assertEqual(response.status_code, 201, response.content)

    def test_a_role_the_policy_does_not_name_is_never_blocked(self):
        user = _overdue_user("mee_other_role", UserRole.ZEV_OWNER)
        _set_policy(roles=["participant"], grace_days=1, changed_days_ago=30)
        client = APIClient()
        auth(client, user)

        self.assertEqual(_unsafe_write(client).status_code, 201)

    def test_with_no_policy_at_all_nothing_is_ever_blocked(self):
        user = _overdue_user("mee_no_policy")
        client = APIClient()
        auth(client, user)

        self.assertEqual(_unsafe_write(client).status_code, 201)


class ExemptSelfServiceRoutesTests(TestCase):
    """The account's own security actions stay reachable regardless — the
    only way out (enrolling) must not itself be blocked."""

    def setUp(self):
        self.user = _overdue_user("mee_exempt")
        _set_policy(roles=["participant"], grace_days=1, changed_days_ago=30)
        self.client = APIClient()
        auth(self.client, self.user)

    def test_editing_your_own_profile_still_works(self):
        self.assertEqual(self.client.patch(ME, {"first_name": "Ada"}, format="json").status_code, 200)

    def test_changing_your_password_still_works(self):
        response = self.client.post(
            CHANGE_PASSWORD, {"old_password": "pass1234", "new_password": "Uniquely-Long-9164!"}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.content)

    def test_beginning_totp_enrolment_still_works(self):
        with self.settings(MFA_ENCRYPTION_KEYS=[TOTP_KEY]):
            response = self.client.post(TOTP_DEVICE)
        self.assertEqual(response.status_code, 200, response.content)

    def test_signing_out_other_devices_still_works(self):
        self.assertEqual(self.client.post("/api/v1/auth/me/sessions/revoke/").status_code, 200)

    def test_revoking_your_own_api_key_still_works(self):
        _, _ = create_api_key(self.user)
        key_id = self.user.api_keys.get().pk
        self.assertEqual(self.client.delete(f"{API_KEYS}{key_id}/").status_code, 204)

    def test_minting_a_new_api_key_is_blocked(self):
        # The one loophole that would defeat the whole feature: API keys are
        # themselves exempt from this check, so minting a fresh one would be
        # a standing way around it.
        response = self.client.post(API_KEYS, {"name": "workaround"}, format="json")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "mfa_enrolment_required")

    def test_editing_the_policy_itself_is_blocked(self):
        # No escaping the block by turning the policy off.
        response = self.client.patch("/api/v1/auth/app-settings/", {"mfa_required_roles": []}, format="json")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(AppSettings.load().mfa_required_roles, ["participant"])


class AdminActionsOnOthersAreBlockedTests(TestCase):
    """The calling admin's own compliance state gates admin actions taken on
    *someone else* — those are not this account protecting itself."""

    def setUp(self):
        self.admin = _overdue_user("mee_admin", UserRole.ADMIN)
        _set_policy(roles=["admin"], grace_days=1, changed_days_ago=30)
        self.client = APIClient()
        auth(self.client, self.admin)
        self.other = make_user("mee_other", UserRole.PARTICIPANT)

    def test_editing_someone_elses_account_is_blocked(self):
        response = self.client.patch(f"/api/v1/auth/users/{self.other.pk}/", {"first_name": "X"}, format="json")
        self.assertEqual(response.status_code, 403)

    def test_resetting_someone_elses_mfa_is_blocked(self):
        self.assertEqual(self.client.delete(f"/api/v1/auth/users/{self.other.pk}/mfa/").status_code, 403)

    def test_signing_someone_else_out_everywhere_is_blocked(self):
        self.assertEqual(self.client.post(f"/api/v1/auth/users/{self.other.pk}/revoke-sessions/").status_code, 403)

    def test_impersonating_is_blocked(self):
        response = self.client.post(f"/api/v1/auth/users/{self.other.pk}/impersonate/")
        self.assertEqual(response.status_code, 403)

    def test_creating_a_new_account_is_blocked(self):
        response = self.client.post(
            "/api/v1/auth/users/",
            {"username": "mee_new", "email": "mee_new@example.com", "first_name": "N", "last_name": "N", "role": "participant"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_admin_reads_still_work(self):
        self.assertEqual(self.client.get("/api/v1/auth/users/").status_code, 200)


class ImpersonationIsExemptTests(TestCase):
    def test_an_active_impersonation_session_is_not_gated_by_the_targets_compliance(self):
        admin = make_user("mee_imp_admin", UserRole.ADMIN)
        target = _overdue_user("mee_imp_target", UserRole.PARTICIPANT)
        _set_policy(roles=["participant"], grace_days=1, changed_days_ago=30)

        admin_client = APIClient()
        auth(admin_client, admin)
        response = admin_client.post(f"/api/v1/auth/users/{target.pk}/impersonate/")
        self.assertEqual(response.status_code, 200, response.content)

        impersonated = APIClient()
        impersonated.credentials(HTTP_AUTHORIZATION=f"Bearer {response.cookies['openzev_access'].value}")
        # An ordinary write, unrelated to the exemption list — it only passes
        # because the token carries impersonated_by.
        result = impersonated.patch("/api/v1/auth/me/", {"first_name": "Puppeted"}, format="json")
        self.assertEqual(result.status_code, 200, result.content)


class ApiKeysAreExemptTests(TestCase):
    def test_an_overdue_accounts_api_key_keeps_working(self):
        user = _overdue_user("mee_key_user", UserRole.ZEV_OWNER)
        _set_policy(roles=["zev_owner"], grace_days=1, changed_days_ago=30)
        _, plaintext = create_api_key(user)

        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Api-Key {plaintext}")
        response = client.get("/api/v1/auth/me/")

        self.assertEqual(response.status_code, 200)


class CookieAndRefreshPathTests(TestCase):
    """The check must fire on the httpOnly-cookie path too, not only the
    Authorization-header path the rest of this module's tests exercise —
    and a token refresh must never be caught by it."""

    def setUp(self):
        self.user = _overdue_user("mee_cookie")
        _set_policy(roles=["participant"], grace_days=1, changed_days_ago=30)

    def test_a_write_via_the_cookie_is_refused_too(self):
        tokens = make_jwt_for_user(self.user)
        client = APIClient()
        client.cookies["openzev_access"] = tokens["access"]
        client.cookies["openzev_refresh"] = tokens["refresh"]
        response = _unsafe_write(client)
        self.assertEqual(response.status_code, 403)

    def test_refreshing_a_still_live_session_is_unaffected(self):
        tokens = make_jwt_for_user(self.user)
        client = APIClient()
        client.cookies["openzev_access"] = tokens["access"]
        client.cookies["openzev_refresh"] = tokens["refresh"]
        response = client.post("/api/v1/auth/token/refresh/")
        self.assertEqual(response.status_code, 200, response.content)
