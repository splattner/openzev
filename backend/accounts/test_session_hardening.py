"""Session revocation, the locked-down self-service profile, and the verified
email change.

Spec: docs/specs/2026-03-community-and-access.md §5.6–§5.6b; ADR 0022.
"""

import re
from unittest import mock

from django.core import mail
from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from audit.models import AuditEvent, AuditEventStatus
from testing.helpers import authenticate, make_user

from .jwt_utils import make_jwt_for_user
from .models import User, UserRole
from .session_revocation import revoke_sessions
from .test_api_keys import create_api_key
from .throttling import AuthEmailChangeThrottle

ME = "/api/v1/auth/me/"
REFRESH = "/api/v1/auth/token/refresh/"
CHANGE_PASSWORD = "/api/v1/auth/me/change-password/"
REVOKE_OWN = "/api/v1/auth/me/sessions/revoke/"
EMAIL_CHANGE = "/api/v1/auth/me/email-change/"
EMAIL_CONFIRM = "/api/v1/auth/confirm-email-change/"
NEW_PASSWORD = "Uniquely-Long-9164!"


def _bearer(access: str) -> APIClient:
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    return client


def _session(user) -> dict:
    """A fresh login's tokens, as production issues them."""
    return make_jwt_for_user(user)


class SelfServiceProfileTests(TestCase):
    def setUp(self):
        self.user = make_user("ss_user", UserRole.PARTICIPANT)
        self.user.must_change_password = True
        self.user.save()
        self.client = APIClient()
        authenticate(self.client, self.user)

    def test_changing_a_protected_field_is_rejected_and_nothing_is_applied(self):
        attempts = {
            "email": "attacker@example.com",
            "username": "renamed",
            "role": "admin",
            "must_change_password": False,
            "is_active": False,
        }
        for field, value in attempts.items():
            response = self.client.patch(ME, {field: value, "first_name": "Sneaky"}, format="json")
            self.assertEqual(response.status_code, 400, field)
            self.assertIn(field, response.json())

        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "ss_user@example.com")
        self.assertEqual(self.user.username, "ss_user")
        self.assertEqual(self.user.role, UserRole.PARTICIPANT)
        self.assertTrue(self.user.must_change_password)
        self.assertTrue(self.user.is_active)
        self.assertEqual(self.user.first_name, "")  # the whole request failed, not just the field

    def test_repeating_the_current_values_is_accepted(self):
        response = self.client.patch(
            ME,
            {"email": "SS_USER@example.com", "username": "ss_user", "role": "participant",
             "must_change_password": True, "is_active": True, "first_name": "Ada"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Ada")
        self.assertEqual(self.user.email, "ss_user@example.com")  # untouched, not re-cased

    def test_names_can_still_be_edited(self):
        response = self.client.patch(ME, {"first_name": "Ada", "last_name": "Lovelace"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual((self.user.first_name, self.user.last_name), ("Ada", "Lovelace"))

    def test_owner_can_still_set_a_default_community(self):
        from zev.models import Zev

        owner = make_user("ss_owner", UserRole.ZEV_OWNER)
        zev = Zev.objects.create(name="Mine", owner=owner, zev_type="vzev", invoice_prefix="M")
        client = APIClient()
        authenticate(client, owner)
        response = client.patch(ME, {"preferred_zev": str(zev.pk)}, format="json")
        self.assertEqual(response.status_code, 200)
        owner.refresh_from_db()
        self.assertEqual(owner.preferred_zev_id, zev.pk)

    def test_me_reports_whether_the_account_has_a_password(self):
        self.user.set_unusable_password()
        self.user.save()
        self.assertFalse(self.client.get(ME).json()["has_usable_password"])
        self.user.set_password("pass1234")
        self.user.save()
        self.assertTrue(self.client.get(ME).json()["has_usable_password"])

    def test_admin_can_still_edit_everything_on_the_detail_endpoint(self):
        admin = make_user("ss_admin", UserRole.ADMIN)
        client = APIClient()
        authenticate(client, admin)
        response = client.patch(f"/api/v1/auth/users/{self.user.pk}/", {"email": "new@example.com"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "new@example.com")


class SessionRevocationTests(TestCase):
    def setUp(self):
        self.user = make_user("sr_user", UserRole.PARTICIPANT)

    def test_a_session_works_until_it_is_revoked(self):
        session = _session(self.user)
        self.assertEqual(_bearer(session["access"]).get(ME).status_code, 200)
        revoke_sessions(self.user)
        self.assertEqual(_bearer(session["access"]).get(ME).status_code, 401)

    def test_a_session_started_after_the_revocation_is_valid(self):
        revoke_sessions(self.user)
        self.assertEqual(_bearer(_session(self.user)["access"]).get(ME).status_code, 200)

    def test_tokens_without_the_claim_stay_valid_only_until_the_first_revocation(self):
        legacy = str(RefreshToken.for_user(self.user).access_token)
        self.assertEqual(_bearer(legacy).get(ME).status_code, 200)
        revoke_sessions(self.user)
        self.assertEqual(_bearer(legacy).get(ME).status_code, 401)

    def test_a_refresh_token_from_a_revoked_session_is_refused(self):
        session = _session(self.user)
        revoke_sessions(self.user)
        client = APIClient()
        client.cookies["openzev_refresh"] = session["refresh"]
        response = client.post(REFRESH)
        self.assertEqual(response.status_code, 401)
        # Cookies are cleared so the browser stops presenting it.
        self.assertEqual(response.cookies["openzev_refresh"].value, "")

    def test_a_current_refresh_token_still_refreshes_and_keeps_the_claim(self):
        revoke_sessions(self.user)
        session = _session(self.user)
        client = APIClient()
        client.cookies["openzev_refresh"] = session["refresh"]
        response = client.post(REFRESH)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(_bearer(response.cookies["openzev_access"].value).get(ME).status_code, 200)

    def test_a_deactivated_account_cannot_refresh_and_stays_locked_out_when_reactivated(self):
        session = _session(self.user)
        admin = make_user("sr_admin", UserRole.ADMIN)
        admin_client = APIClient()
        authenticate(admin_client, admin)

        admin_client.patch(f"/api/v1/auth/users/{self.user.pk}/", {"is_active": False}, format="json")
        client = APIClient()
        client.cookies["openzev_refresh"] = session["refresh"]
        self.assertEqual(client.post(REFRESH).status_code, 401)

        admin_client.patch(f"/api/v1/auth/users/{self.user.pk}/", {"is_active": True}, format="json")
        self.assertEqual(_bearer(session["access"]).get(ME).status_code, 401)
        self.assertEqual(client.post(REFRESH).status_code, 401)

    def test_a_model_save_from_a_stale_instance_does_not_revive_revoked_sessions(self):
        session = _session(self.user)
        stale = User.objects.get(pk=self.user.pk)
        revoke_sessions(self.user)
        stale.first_name = "Stale"
        stale.save()  # full save from before the revocation
        self.assertEqual(_bearer(session["access"]).get(ME).status_code, 401)
        self.assertEqual(User.objects.get(pk=self.user.pk).session_version, 1)

    def test_api_keys_are_not_affected(self):
        _, key = create_api_key(self.user)
        revoke_sessions(self.user)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Api-Key {key}")
        self.assertEqual(client.get(ME).status_code, 200)

    def test_an_impersonation_session_ends_with_the_targets_revocation(self):
        admin = make_user("sr_imp_admin", UserRole.ADMIN)
        admin_client = APIClient()
        authenticate(admin_client, admin)
        response = admin_client.post(f"/api/v1/auth/users/{self.user.pk}/impersonate/")
        self.assertEqual(response.status_code, 200)
        access = response.cookies["openzev_access"].value
        self.assertEqual(_bearer(access).get(ME).status_code, 200)
        revoke_sessions(self.user)
        self.assertEqual(_bearer(access).get(ME).status_code, 401)


class PasswordChangeRevokesSessionsTests(TestCase):
    def setUp(self):
        self.user = make_user("pc_user", UserRole.ZEV_OWNER)
        self.this_device = _session(self.user)
        self.other_device = _session(self.user)

    def test_other_sessions_end_and_the_caller_keeps_theirs(self):
        response = _bearer(self.this_device["access"]).post(
            CHANGE_PASSWORD, {"old_password": "pass1234", "new_password": NEW_PASSWORD}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.content)

        self.assertEqual(_bearer(self.other_device["access"]).get(ME).status_code, 401)
        self.assertEqual(_bearer(self.this_device["access"]).get(ME).status_code, 401)  # the old token, too
        fresh = response.cookies["openzev_access"].value
        self.assertEqual(_bearer(fresh).get(ME).status_code, 200)

    def test_a_failed_change_revokes_nothing(self):
        response = _bearer(self.this_device["access"]).post(
            CHANGE_PASSWORD, {"old_password": "wrong", "new_password": NEW_PASSWORD}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(_bearer(self.other_device["access"]).get(ME).status_code, 200)


class RevokeSessionsEndpointTests(TestCase):
    def setUp(self):
        self.user = make_user("rv_user", UserRole.PARTICIPANT)
        self.admin = make_user("rv_admin", UserRole.ADMIN)
        self.this_device = _session(self.user)
        self.other_device = _session(self.user)

    def test_own_revoke_signs_out_the_others_but_not_the_caller(self):
        response = _bearer(self.this_device["access"]).post(REVOKE_OWN)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(_bearer(self.other_device["access"]).get(ME).status_code, 401)
        self.assertEqual(_bearer(response.cookies["openzev_access"].value).get(ME).status_code, 200)
        event = AuditEvent.objects.get(action_type="auth.sessions.revoked")
        self.assertEqual(event.metadata_json["scope"], "others")

    def test_own_revoke_is_refused_while_impersonating(self):
        admin_client = APIClient()
        authenticate(admin_client, self.admin)
        impersonation = admin_client.post(f"/api/v1/auth/users/{self.user.pk}/impersonate/")
        access = impersonation.cookies["openzev_access"].value
        self.assertEqual(_bearer(access).post(REVOKE_OWN).status_code, 403)
        self.assertEqual(_bearer(self.other_device["access"]).get(ME).status_code, 200)

    def test_admin_can_sign_an_account_out_everywhere(self):
        client = APIClient()
        authenticate(client, self.admin)
        response = client.post(f"/api/v1/auth/users/{self.user.pk}/revoke-sessions/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(_bearer(self.this_device["access"]).get(ME).status_code, 401)
        self.assertEqual(_bearer(self.other_device["access"]).get(ME).status_code, 401)
        event = AuditEvent.objects.get(action_type="auth.sessions.revoked")
        self.assertEqual(event.metadata_json["scope"], "all")
        self.assertEqual(event.actor_user_id, self.admin.pk)

    def test_admin_cannot_use_it_on_their_own_account(self):
        client = APIClient()
        authenticate(client, self.admin)
        self.assertEqual(client.post(f"/api/v1/auth/users/{self.admin.pk}/revoke-sessions/").status_code, 400)

    def test_non_admins_cannot_use_the_admin_endpoint(self):
        other = make_user("rv_other", UserRole.ZEV_OWNER)
        client = APIClient()
        authenticate(client, other)
        self.assertEqual(client.post(f"/api/v1/auth/users/{self.user.pk}/revoke-sessions/").status_code, 403)
        self.assertEqual(_bearer(self.this_device["access"]).get(ME).status_code, 200)

    def test_unknown_account_is_a_404(self):
        client = APIClient()
        authenticate(client, self.admin)
        self.assertEqual(client.post("/api/v1/auth/users/999999/revoke-sessions/").status_code, 404)

    def test_an_api_key_cannot_sign_out_its_owner(self):
        _, key = create_api_key(self.admin)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Api-Key {key}")
        self.assertEqual(client.post(f"/api/v1/auth/users/{self.user.pk}/revoke-sessions/").status_code, 403)
        self.assertEqual(client.post(REVOKE_OWN).status_code, 403)

    def test_admin_mfa_reset_signs_the_account_out(self):
        client = APIClient()
        authenticate(client, self.admin)
        self.assertEqual(client.delete(f"/api/v1/auth/users/{self.user.pk}/mfa/").status_code, 200)
        self.assertEqual(_bearer(self.this_device["access"]).get(ME).status_code, 401)


def _confirmation_link() -> str:
    body = mail.outbox[-1].body
    return re.search(r"confirm-email-change\?token=(\S+)", body).group(1)


class EmailChangeTests(TestCase):
    def setUp(self):
        self.user = make_user("ec_user", UserRole.ZEV_OWNER)
        self.session = _session(self.user)
        self.client = _bearer(self.session["access"])

    def _request(self, new="new-address@example.org", password="pass1234", client=None):
        return (client or self.client).post(
            EMAIL_CHANGE, {"new_email": new, "current_password": password}, format="json"
        )

    def test_request_sends_a_link_to_the_new_address_and_changes_nothing_yet(self):
        response = self._request()
        self.assertEqual(response.status_code, 202)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["new-address@example.org"])
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "ec_user@example.com")
        self.assertEqual(self.client.get(ME).status_code, 200)
        self.assertTrue(AuditEvent.objects.filter(action_type="auth.email_change.requested").exists())

    def test_confirming_changes_the_address_signs_everyone_out_and_tells_the_old_mailbox(self):
        self._request()
        token = _confirmation_link()

        response = APIClient().post(EMAIL_CONFIRM, {"token": token}, format="json")
        self.assertEqual(response.status_code, 200, response.content)

        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "new-address@example.org")
        self.assertEqual(self.client.get(ME).status_code, 401)
        # No session is minted by the link.
        self.assertNotIn("openzev_access", response.cookies)

        notice = mail.outbox[-1]
        self.assertEqual(notice.to, ["ec_user@example.com"])
        self.assertIn("n***@example.org", notice.body)
        self.assertNotIn("new-address", notice.body)

        event = AuditEvent.objects.get(action_type="auth.email_change.confirmed")
        self.assertEqual(event.changes_json["email"]["after"], "new-address@example.org")

    def test_wrong_password_is_refused_and_audited(self):
        response = self._request(password="not-it")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(len(mail.outbox), 0)
        event = AuditEvent.objects.get(action_type="auth.email_change.failed")
        self.assertEqual(event.status, AuditEventStatus.FAILED)
        self.assertEqual(event.metadata_json["reason"], "bad_password")

    def test_missing_password_is_refused(self):
        response = self.client.post(EMAIL_CHANGE, {"new_email": "x@example.org"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(len(mail.outbox), 0)

    def test_an_account_without_a_password_cannot_change_its_own_address(self):
        participant = make_user("ec_participant", UserRole.PARTICIPANT)
        participant.set_unusable_password()
        participant.save()
        response = self._request(client=_bearer(_session(participant)["access"]))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "no_password")
        self.assertEqual(len(mail.outbox), 0)

    def test_an_address_held_by_another_account_looks_like_success_but_sends_nothing(self):
        make_user("ec_taken", UserRole.PARTICIPANT)
        taken = self._request(new="EC_TAKEN@example.com")
        free = self._request(new="free@example.org")
        self.assertEqual((taken.status_code, taken.json()), (free.status_code, free.json()))
        self.assertEqual([m.to for m in mail.outbox], [["free@example.org"]])
        event = AuditEvent.objects.get(action_type="auth.email_change.failed")
        self.assertEqual(event.metadata_json["reason"], "address_in_use")

    def test_the_current_address_and_malformed_ones_are_rejected(self):
        self.assertEqual(self._request(new="EC_USER@example.com").status_code, 400)
        self.assertEqual(self._request(new="not-an-email").status_code, 400)
        self.assertEqual(self._request(new="").status_code, 400)
        self.assertEqual(len(mail.outbox), 0)

    def test_a_link_works_once(self):
        self._request()
        token = _confirmation_link()
        self.assertEqual(APIClient().post(EMAIL_CONFIRM, {"token": token}, format="json").status_code, 200)
        self.assertEqual(APIClient().post(EMAIL_CONFIRM, {"token": token}, format="json").status_code, 400)

    def test_a_password_change_invalidates_an_outstanding_link(self):
        self._request()
        token = _confirmation_link()
        self.user.set_password(NEW_PASSWORD)
        self.user.save()
        self.assertEqual(APIClient().post(EMAIL_CONFIRM, {"token": token}, format="json").status_code, 400)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "ec_user@example.com")

    def test_a_link_is_dead_if_someone_else_took_the_address_meanwhile(self):
        self._request()
        token = _confirmation_link()
        make_user("ec_sneaky", UserRole.PARTICIPANT).__class__.objects.filter(username="ec_sneaky").update(
            email="new-address@example.org"
        )
        self.assertEqual(APIClient().post(EMAIL_CONFIRM, {"token": token}, format="json").status_code, 400)

    def test_a_link_is_dead_if_the_address_changed_another_way(self):
        self._request()
        token = _confirmation_link()
        User.objects.filter(pk=self.user.pk).update(email="admin-set@example.com")
        self.assertEqual(APIClient().post(EMAIL_CONFIRM, {"token": token}, format="json").status_code, 400)

    def test_a_link_for_a_deactivated_account_is_dead(self):
        self._request()
        token = _confirmation_link()
        User.objects.filter(pk=self.user.pk).update(is_active=False)
        self.assertEqual(APIClient().post(EMAIL_CONFIRM, {"token": token}, format="json").status_code, 400)

    def test_an_expired_link_is_refused(self):
        self._request()
        token = _confirmation_link()
        with mock.patch("accounts.email_change.LIFETIME_SECONDS", -1):
            self.assertEqual(APIClient().post(EMAIL_CONFIRM, {"token": token}, format="json").status_code, 400)

    def test_garbage_and_tampered_tokens_are_refused_alike(self):
        self._request()
        token = _confirmation_link()
        for bad in ("", "nonsense", token[:-2] + "xx", token + "a"):
            response = APIClient().post(EMAIL_CONFIRM, {"token": bad}, format="json")
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json(), {"detail": "This link is invalid or has expired."})

    def test_a_token_for_another_purpose_is_not_accepted(self):
        from django.core import signing

        forged = signing.dumps({"u": self.user.pk, "n": "x@example.org", "f": "x"}, salt="other")
        self.assertEqual(APIClient().post(EMAIL_CONFIRM, {"token": forged}, format="json").status_code, 400)

    def test_it_is_refused_while_impersonating(self):
        admin = make_user("ec_admin", UserRole.ADMIN)
        admin_client = APIClient()
        authenticate(admin_client, admin)
        access = admin_client.post(f"/api/v1/auth/users/{self.user.pk}/impersonate/").cookies["openzev_access"].value
        self.assertEqual(self._request(client=_bearer(access)).status_code, 403)
        self.assertEqual(len(mail.outbox), 0)

    def test_an_api_key_cannot_request_it(self):
        _, key = create_api_key(self.user)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Api-Key {key}")
        self.assertEqual(self._request(client=client).status_code, 403)

    def test_a_mail_failure_is_reported_and_nothing_is_recorded_as_requested(self):
        with mock.patch("accounts.emails.EmailMessage.send", side_effect=OSError("smtp down")):
            response = self._request()
        self.assertEqual(response.status_code, 503)
        self.assertFalse(AuditEvent.objects.filter(action_type="auth.email_change.requested").exists())

    def test_asking_is_rate_limited_per_account(self):
        cache.clear()
        with mock.patch.object(AuthEmailChangeThrottle, "THROTTLE_RATES", {"auth_email_change": "2/hour"}):
            codes = [self._request(password="wrong").status_code for _ in range(3)]
        self.assertEqual(codes, [400, 400, 429])
        cache.clear()
