"""Emailed password reset (#1006): who gets a link, what the link can and cannot do.

Spec: docs/specs/2026-03-community-and-access.md §5.6d.
"""

import re
from datetime import timedelta
from unittest import mock

import pyotp
from django.core import mail
from django.core.cache import cache
from django.test import TestCase
from django.test.utils import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from audit.models import AuditEvent
from testing.helpers import authenticate as auth, make_user

from . import password_reset
from .models import OAuthExchangeCode, TotpDevice, User, UserRole
from .session_revocation import revoke_sessions
from .test_mfa import TEST_KEY, TOKEN_URL, TOTP_CONFIRM_URL, TOTP_DEVICE_URL

REQUEST_URL = "/api/v1/auth/password-reset/"
CONFIRM_URL = "/api/v1/auth/password-reset/confirm/"
NEW_PASSWORD = "a-Much-better-passw0rd"


def _token_from_mail(message) -> str:
    return re.search(r"token=(\S+)", message.body).group(1)


class PasswordResetBase(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.client = APIClient()
        self.user = make_user("reset_user", UserRole.USER)
        self.user.must_change_password = True
        self.user.save(update_fields=["must_change_password"])

    def request_reset(self, email=None):
        return self.client.post(REQUEST_URL, {"email": email or self.user.email}, format="json")

    def issue(self, user=None):
        return password_reset.issue_token(user or self.user)

    def confirm(self, token, password=NEW_PASSWORD):
        return self.client.post(CONFIRM_URL, {"token": token, "new_password": password}, format="json")


class PasswordResetRequestTests(PasswordResetBase):
    def test_sends_a_link_to_an_account_with_a_password(self):
        response = self.request_reset()

        self.assertEqual(response.status_code, 202)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.user.email])
        self.assertEqual(password_reset.resolve_token(_token_from_mail(mail.outbox[0])), self.user)
        self.assertTrue(AuditEvent.objects.filter(action_type="password.reset_requested").exists())

    def test_address_is_matched_case_insensitively(self):
        self.request_reset(self.user.email.upper())

        self.assertEqual(len(mail.outbox), 1)

    def test_response_is_identical_for_every_kind_of_address(self):
        participant_only = User.objects.create_user(username="participant", email="p@example.com")
        oauth_only = User.objects.create_user(username="oauth", email="o@example.com")
        oauth_only.set_unusable_password()
        oauth_only.save()
        pending = make_user("pending")
        pending.is_active = False
        pending.save(update_fields=["is_active"])

        bodies = []
        for email in (self.user.email, "nobody@example.com", participant_only.email, oauth_only.email, pending.email):
            response = self.request_reset(email)
            bodies.append((response.status_code, response.json()))

        self.assertEqual(len(set(map(str, bodies))), 1)
        self.assertEqual(len(mail.outbox), 1)

    def test_malformed_address_is_a_validation_error(self):
        self.assertEqual(self.request_reset("not-an-address").status_code, 400)
        self.assertEqual(len(mail.outbox), 0)

    def test_a_second_request_inside_the_cooldown_sends_nothing(self):
        self.request_reset()
        again = self.request_reset()

        self.assertEqual(again.status_code, 202)
        self.assertEqual(len(mail.outbox), 1)

    def test_delivery_failure_is_not_revealed_and_frees_the_cooldown(self):
        with mock.patch("accounts.emails.send_password_reset_link", side_effect=OSError("smtp down")):
            failed = self.request_reset()
        ok = self.request_reset()

        self.assertEqual(failed.status_code, 202)
        self.assertEqual(failed.json(), ok.json())
        self.assertEqual(len(mail.outbox), 1)

    def test_unreachable_cache_gives_the_neutral_response_and_no_mail(self):
        from redis.exceptions import ConnectionError as RedisConnectionError

        with mock.patch("accounts.views_security._reserve_mail_slot", side_effect=RedisConnectionError("down")):
            response = self.request_reset()

        self.assertEqual(response.status_code, 202)
        self.assertEqual(len(mail.outbox), 0)


class PasswordResetConfirmTests(PasswordResetBase):
    def test_mailbox_recovery_establishes_an_independent_password(self):
        self.user.password_from_participant_link = True
        self.user.save(update_fields=["password_from_participant_link"])
        self.request_reset()
        token = _token_from_mail(mail.outbox[0])

        self.assertEqual(self.confirm(token).status_code, 200)
        self.user.refresh_from_db()
        self.assertFalse(self.user.password_from_participant_link)
        login = self.client.post(TOKEN_URL, {"username": self.user.username, "password": NEW_PASSWORD})
        self.assertEqual(login.status_code, 200)
        from .jwt_utils import is_participant_link_session
        from rest_framework_simplejwt.tokens import AccessToken

        self.assertFalse(is_participant_link_session(AccessToken(login.cookies["openzev_access"].value)))

    def test_recovery_discards_pending_oauth_exchange_codes(self):
        code = OAuthExchangeCode.objects.create(user=self.user, code="before-mailbox-recovery")
        self.assertEqual(self.confirm(self.issue()).status_code, 200)
        self.assertFalse(OAuthExchangeCode.objects.filter(pk=code.pk).exists())
        response = self.client.post("/api/v1/auth/oauth/token-exchange/", {"code": code.code}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.cookies)

    def test_session_revocation_invalidates_an_outstanding_reset_link(self):
        token = self.issue()
        revoke_sessions(self.user)
        self.assertEqual(self.confirm(token).status_code, 400)

    def test_confirmation_rechecks_revocation_after_token_resolution(self):
        token = self.issue()
        resolve = password_reset.resolve_token

        def revoke_after_read(value, **kwargs):
            user = resolve(value, **kwargs)
            revoke_sessions(User.objects.get(pk=user.pk))
            return user

        with mock.patch("accounts.views_security.password_reset.resolve_token", side_effect=revoke_after_read):
            self.assertEqual(self.confirm(token).status_code, 400)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("pass1234"))

    def test_sets_the_password_and_clears_the_forced_change(self):
        response = self.confirm(self.issue())

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(NEW_PASSWORD))
        self.assertFalse(self.user.must_change_password)
        self.assertTrue(AuditEvent.objects.filter(action_type="password.reset", actor_user=self.user).exists())

    def test_signs_every_session_out_and_mints_none(self):
        auth(self.client, self.user)
        stale_session = self.client._credentials.copy()
        self.client.credentials()
        old_version = self.user.session_version

        response = self.confirm(self.issue())

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.cookies)
        self.user.refresh_from_db()
        self.assertEqual(self.user.session_version, old_version + 1)
        self.client.credentials(**stale_session)
        self.assertEqual(self.client.get("/api/v1/auth/me/").status_code, 401)

    def test_the_link_works_once(self):
        token = self.issue()

        self.assertEqual(self.confirm(token).status_code, 200)
        self.assertEqual(self.confirm(token, "yet-another-Passw0rd!").status_code, 400)

    def test_a_weak_password_is_refused_and_the_link_stays_usable(self):
        token = self.issue()

        weak = self.confirm(token, "12345678")
        self.assertEqual(weak.status_code, 400)
        self.assertIsInstance(weak.json()["detail"], str)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("pass1234"))

        self.assertEqual(self.confirm(token).status_code, 200)

    def test_a_missing_password_is_refused(self):
        response = self.client.post(CONFIRM_URL, {"token": self.issue()}, format="json")

        self.assertEqual(response.status_code, 400)

    def test_garbage_and_foreign_tokens_are_refused(self):
        from . import email_change

        for token in ("", "garbage", email_change.issue_token(self.user, "new@example.com")):
            self.assertEqual(self.confirm(token).status_code, 400)

    def test_an_expired_link_is_refused(self):
        token = self.issue()
        later = timezone.now() + timedelta(seconds=password_reset.LIFETIME_SECONDS + 5)

        with mock.patch("django.core.signing.time.time", return_value=later.timestamp()):
            self.assertEqual(self.confirm(token).status_code, 400)

    def test_a_password_change_since_issue_kills_the_link(self):
        token = self.issue()
        self.user.set_password("changed-meanwhile-1")
        self.user.save()

        self.assertEqual(self.confirm(token).status_code, 400)

    def test_an_address_change_since_issue_kills_the_link(self):
        token = self.issue()
        self.user.email = "moved@example.com"
        self.user.save(update_fields=["email"])

        self.assertEqual(self.confirm(token).status_code, 400)

    def test_a_deactivated_account_or_one_without_a_password_is_refused(self):
        token = self.issue()
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        self.assertEqual(self.confirm(token).status_code, 400)

        self.user.is_active = True
        self.user.set_unusable_password()
        self.user.save()
        self.assertEqual(self.confirm(self.issue()).status_code, 400)

    def test_sends_a_security_notice(self):
        with mock.patch(
            "accounts.tasks.send_security_notification.delay"
        ) as queued, self.captureOnCommitCallbacks(execute=True):
            self.confirm(self.issue())

        self.assertEqual(queued.call_args.args[:2], (self.user.pk, "password_reset"))

    def test_revokes_onboarding_links(self):
        with mock.patch("accounts.views_security.zev_onboarding.revoke_active_for_user", return_value=2) as revoke:
            self.confirm(self.issue())

        revoke.assert_called_once()
        event = AuditEvent.objects.get(action_type="password.reset")
        self.assertEqual(event.metadata_json["onboarding_links_revoked"], 2)

    def test_revokes_magic_links_so_an_old_link_cannot_undo_recovery(self):
        from testing.factories import ParticipantFactory
        from . import magic_links

        participant = ParticipantFactory(user=self.user, email=self.user.email)
        account = magic_links.account_for_participant(participant)
        link = magic_links.issue(account)
        self.user.refresh_from_db()

        response = self.confirm(self.issue())

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.cookies)
        old_link = APIClient().post("/api/v1/public/magic-link/consume/", {"token": link.token})
        self.assertEqual(old_link.status_code, 400)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(NEW_PASSWORD))
        event = AuditEvent.objects.get(action_type="password.reset")
        self.assertEqual(event.metadata_json["magic_links_revoked"], 1)

    def test_audit_failure_rolls_back_password_sessions_and_links(self):
        from . import magic_links

        link = magic_links.issue(self.user)
        version = self.user.session_version
        with mock.patch("accounts.views_security._audit", side_effect=RuntimeError("audit unavailable")), \
                mock.patch("accounts.views_security.notifications.notify") as notify:
            with self.assertRaises(RuntimeError):
                self.confirm(self.issue())
        self.user.refresh_from_db()
        link.refresh_from_db()
        self.assertTrue(self.user.check_password("pass1234"))
        self.assertTrue(self.user.must_change_password)
        self.assertEqual(self.user.session_version, version)
        self.assertIsNone(link.consumed_at)
        notify.assert_not_called()

    def test_expiry_is_rechecked_after_waiting_for_the_account_lock(self):
        token = self.issue()
        locked_users = User.objects.locked()
        original_get = locked_users.get
        later = timezone.now() + timedelta(seconds=password_reset.LIFETIME_SECONDS + 5)
        expired_clock = mock.patch("django.core.signing.time.time", return_value=later.timestamp())

        def waited_for_user(*args, **kwargs):
            user = original_get(*args, **kwargs)
            expired_clock.start()
            return user

        try:
            with mock.patch("accounts.views_security.User.objects.locked", return_value=locked_users), \
                    mock.patch.object(locked_users, "get", side_effect=waited_for_user):
                response = self.confirm(token)
        finally:
            expired_clock.stop()
        self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("pass1234"))


@override_settings(MFA_ENCRYPTION_KEYS=[TEST_KEY])
class PasswordResetKeepsMfaTests(PasswordResetBase):
    def test_reset_does_not_bypass_or_remove_the_second_factor(self):
        auth(self.client, self.user)
        secret = self.client.post(TOTP_DEVICE_URL).data["secret"]
        self.assertEqual(self.client.post(TOTP_CONFIRM_URL, {"code": pyotp.TOTP(secret).now()}).status_code, 200)
        self.client.credentials()

        self.assertEqual(self.confirm(self.issue()).status_code, 200)

        self.assertTrue(TotpDevice.objects.filter(user=self.user, confirmed_at__isnull=False).exists())
        login = self.client.post(TOKEN_URL, {"username": self.user.username, "password": NEW_PASSWORD})
        self.assertEqual(login.status_code, 200)
        self.assertTrue(login.json().get("mfa_required"))
        self.assertNotIn("openzev_access", login.cookies)
