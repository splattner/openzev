"""Coverage for TOTP enrolment, the two-step login, and the six other doors.

See docs/specs/2026-09-two-factor-authentication.md §9. The seventh door
(OAuth's require_mfa_claim/amr check) has its own fixtures and lives in
accounts/test_oauth.py's OAuthMfaClaimTests instead of duplicating the
callback-flow scaffolding here; ``test_oauth_does_not_double_challenge``
below covers OAuth's *default* (unaffected) behaviour, which only needs the
token-exchange endpoint, not the full callback.
"""

import secrets
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone as dt_timezone
from unittest import mock
from unittest.mock import patch

import pyotp
from cryptography.fernet import Fernet
from django.core.cache import cache
from django.test import TestCase
from django.test.utils import override_settings
from rest_framework.test import APIClient

from audit.models import AuditEvent, AuditEventStatus
from testing.factories import ParticipantFactory
from testing.helpers import authenticate as auth, make_user

from .models import MfaRecoveryCode, OAuthExchangeCode, TotpDevice, UserRole
from .throttling import AuthMfaThrottle

TOKEN_URL = "/api/v1/auth/token/"
MFA_URL = "/api/v1/auth/token/mfa/"
MFA_STATUS_URL = "/api/v1/auth/me/mfa/"
TOTP_DEVICE_URL = "/api/v1/auth/me/mfa/totp/"
TOTP_CONFIRM_URL = "/api/v1/auth/me/mfa/totp/confirm/"
RECOVERY_CODES_URL = "/api/v1/auth/me/mfa/recovery-codes/"

TEST_KEY = Fernet.generate_key().decode()

# A fixed instant, not real time: pyotp.TOTP(secret).now() is real-clock and
# a fast test suite can easily call it twice inside the same 30-second step,
# which TotpDevice's own replay protection then (correctly) rejects — a test
# bug that looks exactly like a product bug. Stepping through fixed,
# explicitly-numbered TOTP intervals makes every code in this file
# deterministic and lets a genuine replay test reuse a step on purpose.
BASE_TIME = datetime(2026, 1, 1, tzinfo=dt_timezone.utc)


@contextmanager
def totp_step(secret: str, step: int):
    """Patch the clock to TOTP interval ``step`` past BASE_TIME and yield the
    code valid at that instant. ``accounts.models.timezone.now`` is what
    TotpDevice._matching_step actually calls, so patching it here is what
    makes the device agree with the code this yields."""
    when = BASE_TIME + timedelta(seconds=30 * step)
    with patch("accounts.models.timezone.now", return_value=when):
        yield pyotp.TOTP(secret).at(when)


@override_settings(MFA_ENCRYPTION_KEYS=[TEST_KEY])
class TotpEnrolmentTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = make_user("totp_enrol_user", UserRole.PARTICIPANT)
        auth(self.client, self.user)

    def test_begin_enrolment_creates_unconfirmed_device(self):
        resp = self.client.post(TOTP_DEVICE_URL)

        self.assertEqual(resp.status_code, 200)
        self.assertIn("provisioning_uri", resp.data)
        self.assertIn("secret", resp.data)
        self.assertIn("qr_svg", resp.data)
        device = TotpDevice.objects.get(user=self.user)
        self.assertIsNone(device.confirmed_at)

    def test_unconfirmed_device_does_not_gate_login(self):
        self.client.post(TOTP_DEVICE_URL)

        resp = self.client.post(TOKEN_URL, {"username": self.user.username, "password": "pass1234"})

        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("mfa_required", resp.data)

    def test_confirm_with_valid_code_activates_and_issues_recovery_codes(self):
        begin = self.client.post(TOTP_DEVICE_URL)
        code = pyotp.TOTP(begin.data["secret"]).now()

        resp = self.client.post(TOTP_CONFIRM_URL, {"code": code})

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data["recovery_codes"]), 10)
        device = TotpDevice.objects.get(user=self.user)
        self.assertIsNotNone(device.confirmed_at)
        self.assertEqual(MfaRecoveryCode.objects.filter(user=self.user).count(), 10)

    def test_confirm_with_invalid_code_is_refused(self):
        self.client.post(TOTP_DEVICE_URL)

        resp = self.client.post(TOTP_CONFIRM_URL, {"code": "000000"})

        self.assertEqual(resp.status_code, 400)
        device = TotpDevice.objects.get(user=self.user)
        self.assertIsNone(device.confirmed_at)

    def test_begin_replaces_an_existing_unconfirmed_device(self):
        self.client.post(TOTP_DEVICE_URL)
        self.client.post(TOTP_DEVICE_URL)

        self.assertEqual(TotpDevice.objects.filter(user=self.user).count(), 1)

    def test_begin_refused_once_a_device_is_active(self):
        begin = self.client.post(TOTP_DEVICE_URL)
        code = pyotp.TOTP(begin.data["secret"]).now()
        self.client.post(TOTP_CONFIRM_URL, {"code": code})

        resp = self.client.post(TOTP_DEVICE_URL)

        self.assertEqual(resp.status_code, 409)

    def test_secret_is_never_serialized_after_enrolment(self):
        begin = self.client.post(TOTP_DEVICE_URL)
        code = pyotp.TOTP(begin.data["secret"]).now()
        self.client.post(TOTP_CONFIRM_URL, {"code": code})

        resp = self.client.get(MFA_STATUS_URL)

        self.assertNotIn("secret", resp.data["totp"])
        self.assertEqual(set(resp.data["totp"]), {"id", "confirmed_at", "created_at"})

    @override_settings(MFA_ENCRYPTION_KEYS=[])
    def test_enrolment_refused_when_encryption_key_unset(self):
        resp = self.client.post(TOTP_DEVICE_URL)

        self.assertEqual(resp.status_code, 503)
        self.assertIn("MFA_ENCRYPTION_KEYS", resp.data["detail"])
        self.assertFalse(TotpDevice.objects.filter(user=self.user).exists())

    def test_delete_removes_the_device_and_recovery_codes(self):
        begin = self.client.post(TOTP_DEVICE_URL)
        code = pyotp.TOTP(begin.data["secret"]).now()
        self.client.post(TOTP_CONFIRM_URL, {"code": code})

        resp = self.client.delete(TOTP_DEVICE_URL)

        self.assertEqual(resp.status_code, 204)
        self.assertFalse(TotpDevice.objects.filter(user=self.user).exists())
        self.assertFalse(MfaRecoveryCode.objects.filter(user=self.user).exists())

    def test_delete_without_a_device_is_404(self):
        resp = self.client.delete(TOTP_DEVICE_URL)

        self.assertEqual(resp.status_code, 404)

    def test_regenerate_recovery_codes_invalidates_the_old_set(self):
        begin = self.client.post(TOTP_DEVICE_URL)
        code = pyotp.TOTP(begin.data["secret"]).now()
        first = self.client.post(TOTP_CONFIRM_URL, {"code": code}).data["recovery_codes"]

        resp = self.client.post(RECOVERY_CODES_URL)

        self.assertEqual(resp.status_code, 200)
        second = resp.data["recovery_codes"]
        self.assertEqual(len(second), 10)
        self.assertNotEqual(set(first), set(second))
        self.assertEqual(MfaRecoveryCode.objects.filter(user=self.user).count(), 10)

    def test_regenerate_refused_without_an_active_device(self):
        resp = self.client.post(RECOVERY_CODES_URL)

        self.assertEqual(resp.status_code, 400)

    def test_status_reports_no_device_as_null(self):
        resp = self.client.get(MFA_STATUS_URL)

        self.assertIsNone(resp.data["totp"])
        self.assertEqual(resp.data["passkeys"], [])
        self.assertEqual(resp.data["recovery_codes_remaining"], 0)
        self.assertFalse(resp.data["required"])
        self.assertIsNone(resp.data["grace_until"])

    def test_an_api_key_cannot_reach_any_mfa_endpoint(self):
        """ACCOUNTS_API_KEY_ALLOWLIST is default-deny; these routes were
        never added to it. A key must not be able to manage or bypass its
        owner's own second factor."""
        from .api_keys import generate_key
        from .models import ApiKey

        full_key, prefix, hashed = generate_key()
        ApiKey.objects.create(user=self.user, name="k", prefix=prefix, hashed_key=hashed)
        key_client = APIClient()
        key_client.credentials(HTTP_AUTHORIZATION=f"Api-Key {full_key}")

        self.assertEqual(key_client.get(MFA_STATUS_URL).status_code, 403)
        self.assertEqual(key_client.post(TOTP_DEVICE_URL).status_code, 403)


@override_settings(MFA_ENCRYPTION_KEYS=[TEST_KEY])
class TotpLoginTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = make_user("totp_login_user", UserRole.PARTICIPANT)
        auth(self.client, self.user)
        begin = self.client.post(TOTP_DEVICE_URL)
        self.secret = begin.data["secret"]
        with totp_step(self.secret, 0) as code:
            confirm = self.client.post(TOTP_CONFIRM_URL, {"code": code})
        self.recovery_codes = confirm.data["recovery_codes"]
        self.client.credentials()  # drop the bearer header; log in for real below

    def test_password_login_returns_a_challenge_not_a_session(self):
        resp = self.client.post(TOKEN_URL, {"username": self.user.username, "password": "pass1234"})

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data["mfa_required"])
        self.assertEqual(resp.data["methods"], ["totp", "recovery_code"])
        self.assertNotIn("openzev_access", resp.cookies)
        self.assertNotIn("openzev_refresh", resp.cookies)

    def test_challenge_exchange_sets_cookies_and_audits(self):
        challenge = self.client.post(TOKEN_URL, {"username": self.user.username, "password": "pass1234"})
        mfa_token = challenge.data["mfa_token"]

        with totp_step(self.secret, 1) as code:
            resp = self.client.post(MFA_URL, {"mfa_token": mfa_token, "code": code})

        self.assertEqual(resp.status_code, 200)
        self.assertIn("openzev_access", resp.cookies)
        self.assertIn("openzev_refresh", resp.cookies)
        event = AuditEvent.objects.get(action_type="auth.login")
        self.assertEqual(event.metadata_json["method"], "password+totp")
        self.assertEqual(event.actor_user_id, self.user.pk)

    def test_expired_challenge_is_refused(self):
        challenge = self.client.post(TOKEN_URL, {"username": self.user.username, "password": "pass1234"})
        mfa_token = challenge.data["mfa_token"]

        with patch("accounts.mfa.MFA_CHALLENGE_TTL", timedelta(seconds=-1)), totp_step(self.secret, 2) as code:
            resp = self.client.post(MFA_URL, {"mfa_token": mfa_token, "code": code})

        self.assertEqual(resp.status_code, 400)
        event = AuditEvent.objects.get(action_type="auth.mfa.challenge_failed")
        self.assertEqual(event.status, AuditEventStatus.FAILED)
        self.assertEqual(event.metadata_json["reason"], "expired_challenge")

    def test_replayed_code_is_refused(self):
        challenge = self.client.post(TOKEN_URL, {"username": self.user.username, "password": "pass1234"})
        mfa_token = challenge.data["mfa_token"]
        with totp_step(self.secret, 3) as code:
            self.assertEqual(self.client.post(MFA_URL, {"mfa_token": mfa_token, "code": code}).status_code, 200)

            # A fresh challenge (the first is not single-use — §5.1), same
            # step deliberately reused: this is what makes it a replay.
            challenge2 = self.client.post(TOKEN_URL, {"username": self.user.username, "password": "pass1234"})
            resp = self.client.post(MFA_URL, {"mfa_token": challenge2.data["mfa_token"], "code": code})

        self.assertEqual(resp.status_code, 400)
        event = AuditEvent.objects.filter(action_type="auth.mfa.challenge_failed").latest("created_at")
        self.assertEqual(event.metadata_json["reason"], "replayed_code")

    def test_recovery_code_completes_the_challenge_once(self):
        challenge = self.client.post(TOKEN_URL, {"username": self.user.username, "password": "pass1234"})
        recovery_code = self.recovery_codes[0]

        first = self.client.post(MFA_URL, {"mfa_token": challenge.data["mfa_token"], "code": recovery_code})
        self.assertEqual(first.status_code, 200)
        used_event = AuditEvent.objects.get(action_type="auth.mfa.recovery_used")
        self.assertEqual(used_event.metadata_json["remaining"], 9)

        challenge2 = self.client.post(TOKEN_URL, {"username": self.user.username, "password": "pass1234"})
        second = self.client.post(MFA_URL, {"mfa_token": challenge2.data["mfa_token"], "code": recovery_code})
        self.assertEqual(second.status_code, 400)

    def test_account_without_a_factor_is_unaffected(self):
        plain_user = make_user("totp_login_plain", UserRole.PARTICIPANT)

        resp = self.client.post(TOKEN_URL, {"username": plain_user.username, "password": "pass1234"})

        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("mfa_required", resp.data)
        self.assertIn("openzev_access", resp.cookies)

    def test_challenge_token_cannot_authenticate_a_request(self):
        challenge = self.client.post(TOKEN_URL, {"username": self.user.username, "password": "pass1234"})
        mfa_token = challenge.data["mfa_token"]

        bare_client = APIClient()
        bare_client.credentials(HTTP_AUTHORIZATION=f"Bearer {mfa_token}")
        resp = bare_client.get(MFA_STATUS_URL)

        self.assertEqual(resp.status_code, 401)


@override_settings(MFA_ENCRYPTION_KEYS=[TEST_KEY])
class MfaDoorTests(TestCase):
    """One test per door in spec §5.4, except door 4 (OAuth's opt-in amr
    check), which lives in test_oauth.py's OAuthMfaClaimTests alongside the
    fixtures it needs. ``test_oauth_does_not_double_challenge`` here covers
    door 4's *default*."""

    def setUp(self):
        self.client = APIClient()
        self.user = make_user("door_user", UserRole.PARTICIPANT)
        auth(self.client, self.user)
        begin = self.client.post(TOTP_DEVICE_URL)
        self.secret = begin.data["secret"]
        self.client.post(TOTP_CONFIRM_URL, {"code": pyotp.TOTP(self.secret).now()})
        self.client.credentials()

    def test_magic_link_challenges_an_account_with_a_factor(self):
        from accounts import magic_links

        token = magic_links.issue(self.user)

        resp = self.client.post("/api/v1/public/magic-link/consume/", {"token": token.token})

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data["mfa_required"])
        self.assertNotIn("openzev_access", resp.cookies)

    def test_onboarding_link_challenges_an_account_with_a_factor(self):
        from zev import onboarding

        participant = ParticipantFactory(user=self.user)
        link = onboarding.get_or_create_for_participant(participant)

        resp = self.client.post(
            "/api/v1/public/onboarding/consume/",
            {"prefix": link.prefix, "s": link.secret},
        )

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data["mfa_required"])
        self.assertNotIn("openzev_access", resp.cookies)

    def test_oauth_does_not_double_challenge(self):
        """Door 4's default: the IdP owns authentication, so a session mints
        directly even though the account has a local TOTP factor."""
        exchange = OAuthExchangeCode.objects.create(user=self.user, code=secrets.token_urlsafe(32))

        resp = self.client.post("/api/v1/auth/oauth/token-exchange/", {"code": exchange.code})

        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("mfa_required", resp.data)
        self.assertIn("openzev_access", resp.cookies)

    def test_impersonation_does_not_challenge_the_target(self):
        admin = make_user("door_admin", UserRole.ADMIN)
        admin_client = APIClient()
        auth(admin_client, admin)

        resp = admin_client.post(f"/api/v1/auth/users/{self.user.pk}/impersonate/")

        self.assertEqual(resp.status_code, 200)
        self.assertIn("openzev_access", resp.cookies)

    def test_email_verification_is_unaffected_in_practice(self):
        """An inactive account being verified for the first time cannot yet
        have a factor, but the code path runs the same requires_challenge
        check regardless — this pins that it does not misfire."""
        from .models import EmailVerificationToken, User

        pending = User.objects.create_user(
            username="door_verify", email="verify@example.com", password="pass1234",
            role=UserRole.PARTICIPANT, is_active=False,
        )
        token = EmailVerificationToken.objects.create(user=pending, token="verify-token-123")

        resp = self.client.post("/api/v1/auth/verify-email/", {"token": token.token})

        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("mfa_required", resp.data)
        self.assertIn("openzev_access", resp.cookies)


@override_settings(MFA_ENCRYPTION_KEYS=[TEST_KEY])
class MfaThrottleTests(TestCase):
    """DRF snapshots THROTTLE_RATES from settings onto the class at import
    time, so override_settings cannot reach it — same reasoning
    test_throttling.py's module docstring already documents for the other
    auth throttles."""

    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.user = make_user("throttle_user", UserRole.PARTICIPANT)
        auth(self.client, self.user)
        begin = self.client.post(TOTP_DEVICE_URL)
        self.secret = begin.data["secret"]
        with totp_step(self.secret, 0) as code:
            self.client.post(TOTP_CONFIRM_URL, {"code": code})
        self.client.credentials()

    def tearDown(self):
        cache.clear()

    @mock.patch.object(AuthMfaThrottle, "THROTTLE_RATES", {"auth_mfa": "2/hour"})
    def test_budget_is_per_account_not_per_ip(self):
        # Exhaust the budget for THIS account with wrong codes.
        for _ in range(2):
            challenge = self.client.post(TOKEN_URL, {"username": self.user.username, "password": "pass1234"})
            self.client.post(MFA_URL, {"mfa_token": challenge.data["mfa_token"], "code": "000000"})

        challenge = self.client.post(TOKEN_URL, {"username": self.user.username, "password": "pass1234"})
        throttled = self.client.post(MFA_URL, {"mfa_token": challenge.data["mfa_token"], "code": "000000"})
        self.assertEqual(throttled.status_code, 429)

        # A DIFFERENT account, same IP (the same test client), is unaffected —
        # this is the property a per-IP budget would not give us.
        other = make_user("throttle_other", UserRole.PARTICIPANT)
        other_client = APIClient()
        auth(other_client, other)
        other_secret = other_client.post(TOTP_DEVICE_URL).data["secret"]
        with totp_step(other_secret, 0) as code:
            other_client.post(TOTP_CONFIRM_URL, {"code": code})
        other_client.credentials()

        other_challenge = other_client.post(TOKEN_URL, {"username": other.username, "password": "pass1234"})
        with totp_step(other_secret, 1) as code:
            resp = other_client.post(MFA_URL, {"mfa_token": other_challenge.data["mfa_token"], "code": code})
        self.assertEqual(resp.status_code, 200)

    def test_malformed_token_falls_back_to_per_ip_throttling(self):
        throttle = AuthMfaThrottle()

        class _FakeRequest:
            data = {"mfa_token": "not-a-real-token"}
            META = {"REMOTE_ADDR": "203.0.113.5"}

        key = throttle.get_cache_key(_FakeRequest(), None)
        self.assertIn("203.0.113.5", key)
