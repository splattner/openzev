"""Coverage for admin impersonation.

``accounts/tests.py`` already had four tests here, all driving the endpoint with
an ``Authorization: Bearer`` header — despite the helper being named
``_cookie_auth``. That mattered: the whole point of the feature is that the
admin's own tokens are parked in backup cookies and restored afterwards, and
``request.COOKIES`` is empty under Bearer auth, so **the backup-and-restore path
was never executed by any test**. ``stop-impersonation`` had no tests at all.

These tests drive the real cookie flow through ``/auth/token/``, and pin the
audit events, which are the part most at risk from moving the admin check from
a hand-written ``if`` to a permission class.
"""

from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from audit.models import AuditActionCategory, AuditEvent, AuditEventStatus
from testing.helpers import authenticate as auth, make_user

from .cookies import ACCESS_COOKIE, ADMIN_ACCESS_COOKIE, ADMIN_REFRESH_COOKIE, REFRESH_COOKIE
from .models import UserRole

TOKEN = "/api/v1/auth/token/"
STOP = "/api/v1/auth/users/stop-impersonation/"


def impersonate_url(user_id) -> str:
    return f"/api/v1/auth/users/{user_id}/impersonate/"


class ImpersonationPermissionTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = make_user("imp_admin", UserRole.ADMIN)
        self.target = make_user("imp_target", UserRole.PARTICIPANT)

    def test_admin_may_impersonate_a_participant(self):
        auth(self.client, self.admin)

        resp = self.client.post(impersonate_url(self.target.pk))

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["impersonated_user"]["id"], self.target.pk)
        self.assertEqual(resp.data["impersonator"]["id"], self.admin.pk)

    def test_admin_may_impersonate_a_zev_owner(self):
        auth(self.client, self.admin)
        owner = make_user("imp_owner_target", UserRole.ZEV_OWNER)

        self.assertEqual(self.client.post(impersonate_url(owner.pk)).status_code, 200)

    def test_admins_and_guests_may_not_be_impersonated(self):
        """The role guard is what stops an admin minting a token for another
        admin, which would transfer privilege with no record of the human."""
        auth(self.client, self.admin)
        for role in (UserRole.ADMIN, UserRole.GUEST):
            with self.subTest(role=role):
                victim = make_user(f"imp_victim_{role}", role)
                resp = self.client.post(impersonate_url(victim.pk))
                self.assertEqual(resp.status_code, 400)

    def test_non_admins_are_refused(self):
        for role in (UserRole.ZEV_OWNER, UserRole.PARTICIPANT, UserRole.GUEST):
            with self.subTest(role=role):
                auth(self.client, make_user(f"imp_actor_{role}", role))
                resp = self.client.post(impersonate_url(self.target.pk))
                self.assertEqual(resp.status_code, 403)

    def test_anonymous_is_refused(self):
        self.client.credentials()

        self.assertEqual(self.client.post(impersonate_url(self.target.pk)).status_code, 401)

    def test_unknown_target_is_404(self):
        auth(self.client, self.admin)

        self.assertEqual(self.client.post(impersonate_url(999999)).status_code, 404)


class ImpersonationAuditTests(TestCase):
    """The audit trail is the reason this endpoint is safe to have at all."""

    def setUp(self):
        self.client = APIClient()
        self.admin = make_user("aud_admin", UserRole.ADMIN)
        self.target = make_user("aud_target", UserRole.PARTICIPANT)

    def _event(self):
        event = AuditEvent.objects.get()
        self.assertEqual(event.action_category, AuditActionCategory.AUTH)
        self.assertEqual(event.action_type, "impersonation.issue_token")
        return event

    def test_success_records_who_impersonated_whom(self):
        auth(self.client, self.admin)

        self.client.post(impersonate_url(self.target.pk))

        event = self._event()
        self.assertEqual(event.status, AuditEventStatus.SUCCESS)
        self.assertEqual(event.target_id, str(self.target.pk))
        self.assertEqual(event.target_display, self.target.email)
        self.assertEqual(event.summary, f"Issued impersonation token for {self.target.email}.")
        self.assertEqual(event.metadata_json["impersonated_by"], self.admin.pk)

    def test_non_admin_denial_is_recorded(self):
        """Pins the event that used to be written by a hand-rolled admin check
        and is now emitted from permission_denied()."""
        auth(self.client, make_user("aud_owner", UserRole.ZEV_OWNER))

        self.client.post(impersonate_url(self.target.pk))

        event = self._event()
        self.assertEqual(event.status, AuditEventStatus.DENIED)
        self.assertEqual(event.summary, "Denied impersonation token issuance by non-admin.")
        self.assertEqual(event.target_id, str(self.target.pk))

    def test_role_guard_denial_is_recorded(self):
        auth(self.client, self.admin)
        other_admin = make_user("aud_other_admin", UserRole.ADMIN)

        self.client.post(impersonate_url(other_admin.pk))

        event = self._event()
        self.assertEqual(event.status, AuditEventStatus.DENIED)
        self.assertIn("due to role guard", event.summary)
        self.assertEqual(event.metadata_json["role"], UserRole.ADMIN)

    def test_unknown_target_is_recorded_as_failed(self):
        auth(self.client, self.admin)

        self.client.post(impersonate_url(999999))

        event = self._event()
        self.assertEqual(event.status, AuditEventStatus.FAILED)
        self.assertEqual(event.summary, "Impersonation target user 999999 not found.")

    def test_anonymous_attempt_is_not_audited(self):
        """A 401 is not a governance event; only an authenticated non-admin is."""
        self.client.credentials()

        self.client.post(impersonate_url(self.target.pk))

        self.assertFalse(AuditEvent.objects.exists())


class ImpersonationCookieRoundTripTests(TestCase):
    """The backup-and-restore cookie dance, driven the way a browser drives it.

    Every pre-existing test authenticated with a Bearer header, which leaves
    ``request.COOKIES`` empty and silently skips the backup branch entirely.
    """

    def setUp(self):
        self.client = APIClient()
        self.admin = make_user("ck_admin", UserRole.ADMIN)
        self.target = make_user("ck_target", UserRole.PARTICIPANT)

    def _login_as_admin(self):
        resp = self.client.post(TOKEN, {"username": self.admin.username, "password": "pass1234"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn(ACCESS_COOKIE, resp.cookies)
        return resp.cookies[ACCESS_COOKIE].value, resp.cookies[REFRESH_COOKIE].value

    def test_impersonating_parks_the_admin_tokens_and_swaps_in_the_targets(self):
        admin_access, admin_refresh = self._login_as_admin()

        resp = self.client.post(impersonate_url(self.target.pk))

        self.assertEqual(resp.status_code, 200)
        # The admin's own pair is preserved untouched under the backup names...
        self.assertEqual(resp.cookies[ADMIN_ACCESS_COOKIE].value, admin_access)
        self.assertEqual(resp.cookies[ADMIN_REFRESH_COOKIE].value, admin_refresh)
        # ...and the main pair now belongs to the impersonated user.
        self.assertNotEqual(resp.cookies[ACCESS_COOKIE].value, admin_access)
        claims = AccessToken(resp.cookies[ACCESS_COOKIE].value)
        self.assertEqual(claims["user_id"], str(self.target.pk))
        self.assertEqual(claims["impersonated_by"], self.admin.pk)

    def test_auth_cookies_are_httponly(self):
        self._login_as_admin()

        resp = self.client.post(impersonate_url(self.target.pk))

        for name in (ACCESS_COOKIE, REFRESH_COOKIE, ADMIN_ACCESS_COOKIE, ADMIN_REFRESH_COOKIE):
            with self.subTest(cookie=name):
                self.assertTrue(resp.cookies[name]["httponly"])

    def test_stopping_restores_the_admin_tokens_and_clears_the_backup(self):
        admin_access, admin_refresh = self._login_as_admin()
        self.client.post(impersonate_url(self.target.pk))

        resp = self.client.post(STOP)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.cookies[ACCESS_COOKIE].value, admin_access)
        self.assertEqual(resp.cookies[REFRESH_COOKIE].value, admin_refresh)
        # The backup pair is expired rather than left lying around.
        self.assertEqual(resp.cookies[ADMIN_ACCESS_COOKIE].value, "")
        self.assertEqual(resp.cookies[ADMIN_REFRESH_COOKIE].value, "")

    def test_the_restored_session_is_the_admin_again(self):
        self._login_as_admin()
        self.client.post(impersonate_url(self.target.pk))
        self.client.post(STOP)

        me = self.client.get("/api/v1/auth/me/")

        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.data["id"], self.admin.pk)


class StopImpersonationTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_without_a_backup_pair_it_is_400(self):
        auth(self.client, make_user("stop_admin", UserRole.ADMIN))

        resp = self.client.post(STOP)

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["detail"], "No active impersonation session.")

    def test_half_a_backup_pair_is_not_enough(self):
        auth(self.client, make_user("stop_half", UserRole.ADMIN))
        self.client.cookies[ADMIN_ACCESS_COOKIE] = "access-only"

        self.assertEqual(self.client.post(STOP).status_code, 400)

    def test_anonymous_is_refused(self):
        self.client.credentials()

        self.assertEqual(self.client.post(STOP).status_code, 401)

    def test_a_no_op_stop_is_not_audited(self):
        """Nothing changed, so there is nothing to record — keeps the AUTH
        trail free of noise from double-clicks and stale tabs."""
        auth(self.client, make_user("stop_noop", UserRole.ADMIN))

        self.client.post(STOP)

        self.assertFalse(AuditEvent.objects.filter(action_type="impersonation.end").exists())


class StopImpersonationAuditTests(TestCase):
    """Starting an impersonation was audited three ways; ending one was not
    recorded at all, so the trail showed a session opening and never closing."""

    def setUp(self):
        self.client = APIClient()
        self.admin = make_user("end_admin", UserRole.ADMIN)
        self.target = make_user("end_target", UserRole.PARTICIPANT)

    def test_ending_a_session_is_recorded_against_the_impersonated_user(self):
        self.client.post(TOKEN, {"username": self.admin.username, "password": "pass1234"})
        self.client.post(impersonate_url(self.target.pk))
        AuditEvent.objects.all().delete()

        resp = self.client.post(STOP)

        self.assertEqual(resp.status_code, 200)
        event = AuditEvent.objects.get()
        self.assertEqual(event.action_category, AuditActionCategory.AUTH)
        self.assertEqual(event.action_type, "impersonation.end")
        self.assertEqual(event.status, AuditEventStatus.SUCCESS)
        self.assertEqual(event.target_id, str(self.target.pk))
        self.assertEqual(event.summary, f"Ended impersonation of {self.target.email}.")

    def test_the_admin_behind_the_session_is_recoverable(self):
        """request.user is the impersonated user by this point, so the only
        record of who was driving is the claim stamped on the token."""
        self.client.post(TOKEN, {"username": self.admin.username, "password": "pass1234"})
        self.client.post(impersonate_url(self.target.pk))
        AuditEvent.objects.all().delete()

        self.client.post(STOP)

        self.assertEqual(AuditEvent.objects.get().metadata_json["impersonated_by"], self.admin.pk)
