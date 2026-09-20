"""``User.last_login`` is stamped at every door that actually mints a new
session, and left alone by everything that only reissues tokens under an
existing one. Spec: docs/specs/2026-03-community-and-access.md §5.1a.

Passkey login, OAuth token exchange, and onboarding/magic-link consume each
have their own fixtures already and are covered by one added test apiece,
next to the rest of that door's coverage:
- ``test_passkeys.py::PasskeyLoginTests::test_successful_login_stamps_last_login``
- ``test_cookie_oauth.py::test_oauth_token_exchange_stamps_last_login``
- ``invoices/test_public_invoice_access.py::MagicLinkTests::test_consume_stamps_last_login``
- ``zev/test_onboarding.py::OnboardingConsumeViewTests::test_stamps_last_login``
"""

from cryptography.fernet import Fernet
from django.test import TestCase
from rest_framework.test import APIClient

from testing.helpers import authenticate as auth, make_user

from .models import EmailVerificationToken, UserRole

TOKEN_URL = "/api/v1/auth/token/"
MFA_URL = "/api/v1/auth/token/mfa/"
TOTP_DEVICE_URL = "/api/v1/auth/me/mfa/totp/"
TOTP_CONFIRM_URL = "/api/v1/auth/me/mfa/totp/confirm/"
CHANGE_PASSWORD_URL = "/api/v1/auth/me/change-password/"
SET_INITIAL_PASSWORD_URL = "/api/v1/auth/me/set-initial-password/"
VERIFY_EMAIL_URL = "/api/v1/auth/verify-email/"
TOTP_KEY = Fernet.generate_key().decode()


class PasswordLoginStampsLastLoginTests(TestCase):
    def test_a_plain_password_login_stamps_it(self):
        user = make_user("ll_plain", UserRole.PARTICIPANT)
        self.assertIsNone(user.last_login)

        APIClient().post(TOKEN_URL, {"username": user.username, "password": "pass1234"})

        user.refresh_from_db()
        self.assertIsNotNone(user.last_login)

    def test_a_failed_login_does_not_stamp_it(self):
        user = make_user("ll_failed", UserRole.PARTICIPANT)

        APIClient().post(TOKEN_URL, {"username": user.username, "password": "wrong"})

        user.refresh_from_db()
        self.assertIsNone(user.last_login)

    def test_the_password_step_of_a_two_step_login_does_not_stamp_it_yet(self):
        """A second factor is still outstanding — no session exists until
        /token/mfa/ completes it, so nothing has logged in yet."""
        from .test_mfa import totp_step

        user = make_user("ll_pending_mfa", UserRole.PARTICIPANT)
        client = APIClient()
        auth(client, user)
        with self.settings(MFA_ENCRYPTION_KEYS=[TOTP_KEY]):
            secret = client.post(TOTP_DEVICE_URL).data["secret"]
            with totp_step(secret, 0) as code:
                client.post(TOTP_CONFIRM_URL, {"code": code})
        client.credentials()

        challenge = client.post(TOKEN_URL, {"username": user.username, "password": "pass1234"})
        self.assertTrue(challenge.data["mfa_required"])
        user.refresh_from_db()
        self.assertIsNone(user.last_login)

        with self.settings(MFA_ENCRYPTION_KEYS=[TOTP_KEY]), totp_step(secret, 1) as code:
            client.post(MFA_URL, {"mfa_token": challenge.data["mfa_token"], "code": code})
        user.refresh_from_db()
        self.assertIsNotNone(user.last_login)


class VerifyEmailStampsLastLoginTests(TestCase):
    def test_the_auto_login_after_verifying_stamps_it(self):
        from .models import User

        pending = User.objects.create_user(
            username="ll_verify", email="ll_verify@example.com", password="pass1234",
            role=UserRole.PARTICIPANT, is_active=False,
        )
        token = EmailVerificationToken.objects.create(user=pending, token="ll-verify-token")

        APIClient().post(VERIFY_EMAIL_URL, {"token": token.token})

        pending.refresh_from_db()
        self.assertIsNotNone(pending.last_login)


class ReissuesAreNotLoginsTests(TestCase):
    """Getting a fresh token pair under the *same* session — after a
    password change, or completing a first-time password set moments after
    verifying — is not a new sign-in and must not restamp last_login."""

    def _stamp_via_login(self, user):
        client = APIClient()
        client.post(TOKEN_URL, {"username": user.username, "password": "pass1234"})
        user.refresh_from_db()
        return user.last_login

    def test_changing_your_password_does_not_restamp_it(self):
        user = make_user("ll_pwchange", UserRole.ZEV_OWNER)
        first_login = self._stamp_via_login(user)
        client = APIClient()
        auth(client, user)

        client.post(CHANGE_PASSWORD_URL, {"old_password": "pass1234", "new_password": "Uniquely-Long-9164!"}, format="json")

        user.refresh_from_db()
        self.assertEqual(user.last_login, first_login)

    def test_setting_your_initial_password_does_not_restamp_it(self):
        from .models import EmailVerificationToken, User

        pending = User.objects.create_user(
            username="ll_initial", email="ll_initial@example.com", password="pass1234",
            role=UserRole.PARTICIPANT, is_active=False,
        )
        pending.set_unusable_password()
        pending.save()
        token = EmailVerificationToken.objects.create(user=pending, token="ll-initial-token")
        client = APIClient()
        client.post(VERIFY_EMAIL_URL, {"token": token.token})
        pending.refresh_from_db()
        stamped_at_verification = pending.last_login

        client.post(SET_INITIAL_PASSWORD_URL, {"new_password": "Uniquely-Long-9164!"}, format="json")

        pending.refresh_from_db()
        self.assertEqual(pending.last_login, stamped_at_verification)


class ImpersonationDoesNotTouchLastLoginTests(TestCase):
    def test_neither_account_is_restamped_by_impersonation(self):
        admin = make_user("ll_admin", UserRole.ADMIN)
        target = make_user("ll_target", UserRole.PARTICIPANT)
        admin_client = APIClient()
        admin_client.post(TOKEN_URL, {"username": admin.username, "password": "pass1234"})
        admin.refresh_from_db()
        admin_login = admin.last_login
        self.assertIsNotNone(admin_login)
        self.assertIsNone(target.last_login)
        auth(admin_client, admin)

        admin_client.post(f"/api/v1/auth/users/{target.pk}/impersonate/")

        admin.refresh_from_db()
        target.refresh_from_db()
        self.assertEqual(admin.last_login, admin_login)
        self.assertIsNone(target.last_login)
