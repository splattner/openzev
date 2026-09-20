"""Coverage for passkey registration and passwordless sign-in, plus the MFA
policy fields, the removal guard and the admin reset.

See docs/specs/2026-09-two-factor-authentication.md §9.

WebAuthn ceremonies are exercised end to end against a small software
authenticator (``SoftAuthenticator``) that produces real ``none``-format
attestations and ES256 assertions, so the verification code under test is
py_webauthn's own — nothing about the library is mocked.
"""

import hashlib
import json
import os
import struct
from datetime import timedelta
from unittest import mock

import cbor2
import pyotp
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.test.utils import override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url

from audit.models import AuditEvent, AuditEventStatus
from testing.helpers import authenticate as auth, make_user

from .models import AppSettings, MfaRecoveryCode, TotpDevice, UserRole, WebAuthnCredential
from .throttling import AuthPasskeyThrottle

REGISTER_BEGIN_URL = "/api/v1/auth/me/passkeys/register/begin/"
REGISTER_COMPLETE_URL = "/api/v1/auth/me/passkeys/register/complete/"
PASSKEYS_URL = "/api/v1/auth/me/passkeys/"
AUTH_BEGIN_URL = "/api/v1/auth/passkeys/authenticate/begin/"
AUTH_COMPLETE_URL = "/api/v1/auth/passkeys/authenticate/complete/"
MFA_STATUS_URL = "/api/v1/auth/me/mfa/"
APP_SETTINGS_URL = "/api/v1/auth/app-settings/"
RP_ID = "localhost"
ORIGIN = "http://localhost:5173"
TEST_KEY = Fernet.generate_key().decode()

FLAG_UP = 0x01
FLAG_UV = 0x04
FLAG_AT = 0x40


class SoftAuthenticator:
    """A minimal ES256 platform authenticator.

    ``user_verified`` and ``sign_count`` are attributes so a test can make it
    misbehave in exactly the ways real hardware can.
    """

    def __init__(self, *, user_verified=True):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = os.urandom(32)
        self.user_verified = user_verified
        self.sign_count = 0

    def _cose_public_key(self) -> bytes:
        numbers = self.key.public_key().public_numbers()
        return cbor2.dumps({
            1: 2, 3: -7, -1: 1,
            -2: numbers.x.to_bytes(32, "big"),
            -3: numbers.y.to_bytes(32, "big"),
        })

    def _flags(self, *, attested=False) -> int:
        return FLAG_UP | (FLAG_UV if self.user_verified else 0) | (FLAG_AT if attested else 0)

    def _client_data(self, kind, challenge_b64, origin=ORIGIN) -> bytes:
        return json.dumps({"type": kind, "challenge": challenge_b64, "origin": origin, "crossOrigin": False}).encode()

    def register(self, options) -> dict:
        client_data = self._client_data("webauthn.create", options["challenge"])
        auth_data = (
            hashlib.sha256(RP_ID.encode()).digest()
            + bytes([self._flags(attested=True)])
            + struct.pack(">I", self.sign_count)
            + bytes(16)  # AAGUID: all zeros, "unknown authenticator"
            + struct.pack(">H", len(self.credential_id))
            + self.credential_id
            + self._cose_public_key()
        )
        attestation = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth_data})
        return {
            "id": bytes_to_base64url(self.credential_id),
            "rawId": bytes_to_base64url(self.credential_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": bytes_to_base64url(client_data),
                "attestationObject": bytes_to_base64url(attestation),
                "transports": ["internal"],
            },
            "clientExtensionResults": {},
        }

    def assert_(self, options, *, origin=ORIGIN) -> dict:
        self.sign_count += 1
        client_data = self._client_data("webauthn.get", options["challenge"], origin)
        auth_data = (
            hashlib.sha256(RP_ID.encode()).digest()
            + bytes([self._flags()])
            + struct.pack(">I", self.sign_count)
        )
        signature = self.key.sign(auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256()))
        return {
            "id": bytes_to_base64url(self.credential_id),
            "rawId": bytes_to_base64url(self.credential_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": bytes_to_base64url(client_data),
                "authenticatorData": bytes_to_base64url(auth_data),
                "signature": bytes_to_base64url(signature),
            },
            "clientExtensionResults": {},
        }


def register_passkey(client, authenticator, name="Test key"):
    options = client.post(REGISTER_BEGIN_URL).data
    return client.post(
        REGISTER_COMPLETE_URL,
        {"credential": authenticator.register(options), "name": name},
        format="json",
    )


def sign_in_with(client, authenticator, **kwargs):
    options = client.post(AUTH_BEGIN_URL, {}, format="json").data
    return client.post(
        AUTH_COMPLETE_URL,
        {"credential": authenticator.assert_(options, **kwargs)},
        format="json",
    )


@override_settings(WEBAUTHN_RP_ID=RP_ID, WEBAUTHN_ORIGIN=ORIGIN)
class PasskeyRegistrationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.user = make_user("passkey_reg_user", UserRole.PARTICIPANT)
        auth(self.client, self.user)
        self.authenticator = SoftAuthenticator()

    def test_begin_demands_user_verification_and_excludes_existing_credentials(self):
        register_passkey(self.client, self.authenticator)

        options = self.client.post(REGISTER_BEGIN_URL).data

        self.assertEqual(options["authenticatorSelection"]["userVerification"], "required")
        self.assertEqual(options["authenticatorSelection"]["residentKey"], "preferred")
        self.assertEqual(options["rp"]["id"], RP_ID)
        excluded = [c["id"] for c in options["excludeCredentials"]]
        self.assertEqual(excluded, [bytes_to_base64url(self.authenticator.credential_id)])

    def test_registration_stores_credential_and_audits(self):
        resp = register_passkey(self.client, self.authenticator, name="MacBook Touch ID")

        self.assertEqual(resp.status_code, 201)
        stored = WebAuthnCredential.objects.get(user=self.user)
        self.assertEqual(bytes(stored.credential_id), self.authenticator.credential_id)
        self.assertEqual(stored.name, "MacBook Touch ID")
        self.assertEqual(stored.transports, ["internal"])
        registered = AuditEvent.objects.get(action_type="auth.passkey.registered")
        self.assertEqual(registered.metadata_json["name"], "MacBook Touch ID")
        enrolled = AuditEvent.objects.get(action_type="auth.mfa.enrolled")
        self.assertEqual(enrolled.metadata_json["method"], "passkey")

    def test_first_factor_issues_recovery_codes_once(self):
        first = register_passkey(self.client, SoftAuthenticator())
        second = register_passkey(self.client, SoftAuthenticator(), name="Second")

        self.assertEqual(len(first.data["recovery_codes"]), 10)
        self.assertEqual(second.data["recovery_codes"], [])
        self.assertEqual(MfaRecoveryCode.objects.filter(user=self.user).count(), 10)

    def test_response_never_exposes_credential_id_or_public_key(self):
        resp = register_passkey(self.client, self.authenticator)

        listed = self.client.get(PASSKEYS_URL).data
        for payload in (resp.data["passkey"], listed[0]):
            self.assertNotIn("credential_id", payload)
            self.assertNotIn("public_key", payload)

    def test_multiple_credentials_per_user_are_allowed(self):
        register_passkey(self.client, SoftAuthenticator(), name="One")
        register_passkey(self.client, SoftAuthenticator(), name="Two")

        self.assertEqual(WebAuthnCredential.objects.filter(user=self.user).count(), 2)

    def test_authenticator_that_skips_user_verification_is_refused(self):
        resp = register_passkey(self.client, SoftAuthenticator(user_verified=False))

        self.assertEqual(resp.status_code, 400)
        self.assertFalse(WebAuthnCredential.objects.exists())

    def test_completion_without_a_begun_ceremony_is_refused(self):
        resp = self.client.post(
            REGISTER_COMPLETE_URL,
            {"credential": self.authenticator.register({"challenge": bytes_to_base64url(os.urandom(32))})},
            format="json",
        )

        self.assertEqual(resp.status_code, 400)
        self.assertFalse(WebAuthnCredential.objects.exists())

    def test_a_ceremony_cannot_be_completed_twice(self):
        options = self.client.post(REGISTER_BEGIN_URL).data
        credential = self.authenticator.register(options)
        body = {"credential": credential, "name": "Once"}

        first = self.client.post(REGISTER_COMPLETE_URL, body, format="json")
        replay = self.client.post(REGISTER_COMPLETE_URL, body, format="json")

        self.assertEqual(first.status_code, 201)
        self.assertEqual(replay.status_code, 400)

    def test_credential_id_is_globally_unique(self):
        register_passkey(self.client, self.authenticator)
        other = make_user("passkey_other_user", UserRole.PARTICIPANT)
        other_client = APIClient()
        auth(other_client, other)

        resp = register_passkey(other_client, self.authenticator)

        self.assertEqual(resp.status_code, 409)
        self.assertEqual(WebAuthnCredential.objects.count(), 1)

    def test_rename_and_remove_are_limited_to_the_owner(self):
        register_passkey(self.client, self.authenticator)
        stored = WebAuthnCredential.objects.get()
        stranger = APIClient()
        auth(stranger, make_user("passkey_stranger", UserRole.ADMIN))

        self.assertEqual(stranger.patch(f"{PASSKEYS_URL}{stored.pk}/", {"name": "x"}, format="json").status_code, 404)
        self.assertEqual(stranger.delete(f"{PASSKEYS_URL}{stored.pk}/").status_code, 404)

        renamed = self.client.patch(f"{PASSKEYS_URL}{stored.pk}/", {"name": "Work laptop"}, format="json")
        self.assertEqual(renamed.data["name"], "Work laptop")
        self.assertEqual(self.client.delete(f"{PASSKEYS_URL}{stored.pk}/").status_code, 204)
        self.assertTrue(AuditEvent.objects.filter(action_type="auth.passkey.removed").exists())

    def test_rename_cannot_change_read_only_fields(self):
        register_passkey(self.client, self.authenticator)
        stored = WebAuthnCredential.objects.get()

        self.client.patch(f"{PASSKEYS_URL}{stored.pk}/", {"name": "n", "aaguid": "evil", "transports": ["usb"]}, format="json")

        stored.refresh_from_db()
        self.assertEqual(stored.transports, ["internal"])
        self.assertNotEqual(stored.aaguid, "evil")

    def test_removing_the_last_factor_drops_the_recovery_codes(self):
        register_passkey(self.client, self.authenticator)
        stored = WebAuthnCredential.objects.get()
        self.assertEqual(MfaRecoveryCode.objects.filter(user=self.user).count(), 10)

        self.client.delete(f"{PASSKEYS_URL}{stored.pk}/")

        self.assertFalse(MfaRecoveryCode.objects.filter(user=self.user).exists())

    def test_removing_one_of_two_keeps_the_recovery_codes(self):
        register_passkey(self.client, SoftAuthenticator())
        register_passkey(self.client, SoftAuthenticator(), name="Second")

        self.client.delete(f"{PASSKEYS_URL}{WebAuthnCredential.objects.first().pk}/")

        self.assertEqual(MfaRecoveryCode.objects.filter(user=self.user).count(), 10)


@override_settings(WEBAUTHN_RP_ID=RP_ID, WEBAUTHN_ORIGIN=ORIGIN)
class PasskeyLoginTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_user("passkey_login_user", UserRole.ZEV_OWNER)
        self.authenticator = SoftAuthenticator()
        owner = APIClient()
        auth(owner, self.user)
        register_passkey(owner, self.authenticator)
        self.client = APIClient()  # unauthenticated: this is a sign-in

    def test_begin_demands_user_verification(self):
        options = self.client.post(AUTH_BEGIN_URL, {}, format="json").data

        self.assertEqual(options["userVerification"], "required")
        self.assertEqual(options["rpId"], RP_ID)

    def test_authentication_without_a_password_sets_cookies(self):
        resp = sign_in_with(self.client, self.authenticator)

        self.assertEqual(resp.status_code, 200)
        self.assertIn("openzev_access", resp.cookies)
        self.assertIn("openzev_refresh", resp.cookies)
        event = AuditEvent.objects.get(action_type="auth.login", metadata_json__method="passkey")
        self.assertEqual(event.status, AuditEventStatus.SUCCESS)
        self.assertEqual(event.actor_user_id, self.user.pk)

    def test_successful_login_records_use_and_advances_the_counter(self):
        sign_in_with(self.client, self.authenticator)

        stored = WebAuthnCredential.objects.get()
        self.assertEqual(stored.sign_count, 1)
        self.assertIsNotNone(stored.last_used_at)

    def test_successful_login_stamps_last_login(self):
        self.assertIsNone(self.user.last_login)
        sign_in_with(self.client, self.authenticator)

        self.user.refresh_from_db()
        self.assertIsNotNone(self.user.last_login)

    def test_email_hint_narrows_allow_credentials_without_revealing_accounts(self):
        known = self.client.post(AUTH_BEGIN_URL, {"email": self.user.email}, format="json").data
        unknown = self.client.post(AUTH_BEGIN_URL, {"email": "nobody@example.com"}, format="json").data

        self.assertEqual(
            [c["id"] for c in known["allowCredentials"]],
            [bytes_to_base64url(self.authenticator.credential_id)],
        )
        self.assertEqual(unknown["allowCredentials"], [])
        self.assertEqual(set(known), set(unknown))

    def test_a_challenge_cannot_be_used_twice(self):
        options = self.client.post(AUTH_BEGIN_URL, {}, format="json").data
        credential = self.authenticator.assert_(options)

        first = self.client.post(AUTH_COMPLETE_URL, {"credential": credential}, format="json")
        replay = self.client.post(AUTH_COMPLETE_URL, {"credential": credential}, format="json")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(replay.status_code, 400)
        failure = AuditEvent.objects.get(action_type="auth.mfa.challenge_failed")
        self.assertEqual(failure.metadata_json["reason"], "expired_challenge")

    def test_assertion_without_user_verification_is_refused(self):
        self.authenticator.user_verified = False

        resp = sign_in_with(self.client, self.authenticator)

        self.assertEqual(resp.status_code, 400)
        self.assertNotIn("openzev_access", resp.cookies)
        failure = AuditEvent.objects.get(action_type="auth.mfa.challenge_failed")
        self.assertEqual(failure.metadata_json["reason"], "invalid_assertion")

    def test_assertion_for_the_wrong_origin_is_refused(self):
        resp = sign_in_with(self.client, self.authenticator, origin="https://evil.example")

        self.assertEqual(resp.status_code, 400)
        self.assertNotIn("openzev_access", resp.cookies)

    def test_unknown_credential_is_refused(self):
        resp = sign_in_with(self.client, SoftAuthenticator())

        self.assertEqual(resp.status_code, 400)
        failure = AuditEvent.objects.get(action_type="auth.mfa.challenge_failed")
        self.assertEqual(failure.metadata_json["reason"], "unknown_credential")

    def test_a_tampered_signature_is_refused(self):
        options = self.client.post(AUTH_BEGIN_URL, {}, format="json").data
        credential = self.authenticator.assert_(options)
        raw = bytearray(base64url_to_bytes(credential["response"]["signature"]))
        raw[-1] ^= 0xFF
        credential["response"]["signature"] = bytes_to_base64url(bytes(raw))

        resp = self.client.post(AUTH_COMPLETE_URL, {"credential": credential}, format="json")

        self.assertEqual(resp.status_code, 400)

    def test_sign_count_regression_is_refused_and_audited(self):
        sign_in_with(self.client, self.authenticator)  # stored count is now 1
        self.authenticator.sign_count = 0  # a clone starts counting from the copy point

        resp = sign_in_with(self.client, self.authenticator)  # reports 1 again

        self.assertEqual(resp.status_code, 400)
        self.assertNotIn("openzev_access", resp.cookies)
        event = AuditEvent.objects.get(action_type="auth.passkey.sign_count_regression")
        self.assertEqual(event.status, AuditEventStatus.DENIED)
        self.assertEqual(WebAuthnCredential.objects.get().sign_count, 1)

    def test_authenticators_that_always_report_zero_are_exempt(self):
        stored = WebAuthnCredential.objects.get()
        stored.sign_count = 0
        stored.save()

        # assert_() increments before signing, so -1 makes it report 0 each time.
        self.authenticator.sign_count = -1
        first = sign_in_with(self.client, self.authenticator)
        self.authenticator.sign_count = -1
        second = sign_in_with(self.client, self.authenticator)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)

    def test_inactive_user_is_refused(self):
        self.user.is_active = False
        self.user.save()

        resp = sign_in_with(self.client, self.authenticator)

        self.assertEqual(resp.status_code, 400)
        self.assertNotIn("openzev_access", resp.cookies)

    def test_removing_one_leaves_the_other_usable(self):
        second = SoftAuthenticator()
        owner = APIClient()
        auth(owner, self.user)
        register_passkey(owner, second, name="Second")
        first = WebAuthnCredential.objects.get(credential_id=self.authenticator.credential_id)
        owner.delete(f"{PASSKEYS_URL}{first.pk}/")

        resp = sign_in_with(self.client, second)

        self.assertEqual(resp.status_code, 200)

    def test_malformed_input_is_a_clean_400(self):
        for body in ({}, {"credential": "nope"}, {"credential": {}}, {"credential": {"response": {"clientDataJSON": "!!"}}}):
            resp = self.client.post(AUTH_COMPLETE_URL, body, format="json")
            self.assertEqual(resp.status_code, 400, body)


@override_settings(MFA_ENCRYPTION_KEYS=[TEST_KEY], WEBAUTHN_RP_ID=RP_ID, WEBAUTHN_ORIGIN=ORIGIN)
class PasskeyGatesThePasswordRouteTests(TestCase):
    """A passkey signs in on its own (ADR 0020), but an account that has one
    must not keep a password-only way in, or enrolling protects nothing
    against a stolen password. Every other route into a session — password,
    magic link, onboarding link — asks for a second step, and a recovery code
    is what a passkey-only account can answer it with."""

    def setUp(self):
        cache.clear()
        self.user = make_user("passkey_gate_user", UserRole.ZEV_OWNER)
        owner = APIClient()
        auth(owner, self.user)
        self.authenticator = SoftAuthenticator()
        self.recovery_codes = register_passkey(owner, self.authenticator).data["recovery_codes"]
        self.client = APIClient()

    def _password_login(self):
        return self.client.post(
            "/api/v1/auth/token/", {"email": self.user.email, "password": "pass1234"}, format="json"
        )

    def test_password_login_returns_a_recovery_only_challenge(self):
        resp = self._password_login()

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data["mfa_required"])
        self.assertEqual(resp.data["methods"], ["recovery_code"])
        self.assertNotIn("openzev_access", resp.cookies)

    def test_a_recovery_code_completes_it_exactly_once(self):
        token = self._password_login().data["mfa_token"]
        code = self.recovery_codes[0]

        first = self.client.post("/api/v1/auth/token/mfa/", {"mfa_token": token, "code": code}, format="json")
        again = self.client.post("/api/v1/auth/token/mfa/", {"mfa_token": token, "code": code}, format="json")

        self.assertEqual(first.status_code, 200)
        self.assertIn("openzev_access", first.cookies)
        self.assertEqual(again.status_code, 400)
        event = AuditEvent.objects.get(action_type="auth.login", metadata_json__method="recovery_code")
        self.assertEqual(event.actor_user_id, self.user.pk)

    def test_a_totp_shaped_code_is_refused_without_an_authenticator_app(self):
        token = self._password_login().data["mfa_token"]

        resp = self.client.post("/api/v1/auth/token/mfa/", {"mfa_token": token, "code": "123456"}, format="json")

        self.assertEqual(resp.status_code, 400)
        failure = AuditEvent.objects.get(action_type="auth.mfa.challenge_failed")
        self.assertEqual(failure.metadata_json["reason"], "invalid_code")

    def test_the_challenge_offers_totp_too_once_an_authenticator_app_exists(self):
        device = TotpDevice(user=self.user, confirmed_at=timezone.now())
        device.set_secret("JBSWY3DPEHPK3PXP")
        device.save()

        self.assertEqual(self._password_login().data["methods"], ["totp", "recovery_code"])

    def test_the_passkey_route_itself_is_never_challenged(self):
        resp = sign_in_with(self.client, self.authenticator)

        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("mfa_required", resp.data)

    def test_magic_link_asks_for_the_second_step(self):
        from accounts import magic_links

        token = magic_links.issue(self.user)

        resp = self.client.post("/api/v1/public/magic-link/consume/", {"token": token.token})

        self.assertTrue(resp.data["mfa_required"])
        self.assertEqual(resp.data["methods"], ["recovery_code"])
        self.assertNotIn("openzev_access", resp.cookies)

    def test_removing_the_last_passkey_restores_password_only_login(self):
        owner = APIClient()
        auth(owner, self.user)
        owner.delete(f"{PASSKEYS_URL}{WebAuthnCredential.objects.get().pk}/")

        resp = self._password_login()

        self.assertNotIn("mfa_required", resp.data)
        self.assertIn("openzev_access", resp.cookies)


@override_settings(WEBAUTHN_RP_ID=RP_ID, WEBAUTHN_ORIGIN=ORIGIN)
class PasskeyThrottleTests(TestCase):
    def test_passkey_budget_is_per_ip(self):
        cache.clear()
        rates = {**AuthPasskeyThrottle.THROTTLE_RATES, "auth_passkey": "3/hour"}
        with mock.patch.object(AuthPasskeyThrottle, "THROTTLE_RATES", rates):
            client = APIClient()
            statuses = [client.post(AUTH_BEGIN_URL, {}, format="json").status_code for _ in range(4)]
            other_ip = client.post(AUTH_BEGIN_URL, {}, format="json", REMOTE_ADDR="10.9.9.9").status_code

        self.assertEqual(statuses, [200, 200, 200, 429])
        self.assertEqual(other_ip, 200)


@override_settings(MFA_ENCRYPTION_KEYS=[TEST_KEY])
class MfaPolicyTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = make_user("policy_admin", UserRole.ADMIN)
        self.admin_client = APIClient()
        auth(self.admin_client, self.admin)

    def _set_policy(self, **payload):
        return self.admin_client.patch(APP_SETTINGS_URL, payload, format="json")

    def test_admin_can_set_the_policy_and_it_is_audited(self):
        resp = self._set_policy(mfa_required_roles=["admin", "zev_owner"], mfa_grace_period_days=7)

        self.assertEqual(resp.status_code, 200)
        settings_row = AppSettings.load()
        self.assertEqual(settings_row.mfa_required_roles, ["admin", "zev_owner"])
        self.assertEqual(settings_row.mfa_grace_period_days, 7)
        event = AuditEvent.objects.get(action_type="app_settings.update")
        self.assertIn("mfa_required_roles", event.changes_json)
        self.assertEqual(event.changes_json["mfa_required_roles"]["after"], ["admin", "zev_owner"])

    def test_non_admin_cannot_set_the_policy(self):
        client = APIClient()
        auth(client, make_user("policy_owner", UserRole.ZEV_OWNER))

        resp = client.patch(APP_SETTINGS_URL, {"mfa_required_roles": ["admin"]}, format="json")

        self.assertEqual(resp.status_code, 403)
        self.assertEqual(AppSettings.load().mfa_required_roles, [])

    def test_unknown_roles_are_rejected(self):
        resp = self._set_policy(mfa_required_roles=["admin", "wizard"])

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(AppSettings.load().mfa_required_roles, [])

    def test_policy_cannot_be_enabled_without_an_encryption_key(self):
        with override_settings(MFA_ENCRYPTION_KEYS=[]):
            resp = self._set_policy(mfa_required_roles=["admin"])
            with self.assertRaises(ValidationError):
                AppSettings(mfa_required_roles=["admin"]).clean()

        self.assertEqual(resp.status_code, 400)
        self.assertIn("MFA_ENCRYPTION_KEYS", json.dumps(resp.data))

    def test_clearing_the_policy_never_needs_a_key(self):
        self._set_policy(mfa_required_roles=["admin"])

        with override_settings(MFA_ENCRYPTION_KEYS=[]):
            resp = self._set_policy(mfa_required_roles=[])

        self.assertEqual(resp.status_code, 200)

    def test_status_reports_no_requirement_by_default(self):
        data = self.admin_client.get(MFA_STATUS_URL).data

        self.assertFalse(data["required"])
        self.assertIsNone(data["grace_until"])

    def test_grace_runs_from_the_later_of_account_creation_and_policy_change(self):
        # An admin whose account is years older than the policy must still get
        # a full grace period — never an immediate lockout.
        make_old = timezone.now() - timedelta(days=900)
        type(self.admin).objects.filter(pk=self.admin.pk).update(date_joined=make_old)

        self._set_policy(mfa_required_roles=["admin"], mfa_grace_period_days=14)
        data = self.admin_client.get(MFA_STATUS_URL).data

        self.assertTrue(data["required"])
        deadline = timezone.datetime.fromisoformat(data["grace_until"])
        self.assertGreater(deadline, timezone.now() + timedelta(days=13))
        self.assertLess(deadline, timezone.now() + timedelta(days=15))

    def test_a_newly_created_account_gets_its_own_grace_period(self):
        self._set_policy(mfa_required_roles=["participant"], mfa_grace_period_days=10)
        AppSettings.objects.update(mfa_policy_changed_at=timezone.now() - timedelta(days=400))
        newcomer = make_user("policy_newcomer", UserRole.PARTICIPANT)
        client = APIClient()
        auth(client, newcomer)

        deadline = timezone.datetime.fromisoformat(client.get(MFA_STATUS_URL).data["grace_until"])

        self.assertGreater(deadline, timezone.now() + timedelta(days=9))

    def test_role_outside_the_policy_is_not_required(self):
        self._set_policy(mfa_required_roles=["admin"])
        client = APIClient()
        auth(client, make_user("policy_participant", UserRole.PARTICIPANT))

        self.assertFalse(client.get(MFA_STATUS_URL).data["required"])

    def test_enrolled_user_has_no_grace_deadline(self):
        self._set_policy(mfa_required_roles=["admin"])
        with override_settings(WEBAUTHN_RP_ID=RP_ID, WEBAUTHN_ORIGIN=ORIGIN):
            register_passkey(self.admin_client, SoftAuthenticator())

        data = self.admin_client.get(MFA_STATUS_URL).data

        self.assertTrue(data["required"])
        self.assertIsNone(data["grace_until"])
        self.assertEqual(len(data["passkeys"]), 1)

    def test_status_reports_passkeys_and_recovery_count(self):
        with override_settings(WEBAUTHN_RP_ID=RP_ID, WEBAUTHN_ORIGIN=ORIGIN):
            register_passkey(self.admin_client, SoftAuthenticator(), name="Yubikey")

        data = self.admin_client.get(MFA_STATUS_URL).data

        self.assertEqual([p["name"] for p in data["passkeys"]], ["Yubikey"])
        self.assertEqual(data["recovery_codes_remaining"], 10)
        self.assertIsNone(data["totp"])


@override_settings(MFA_ENCRYPTION_KEYS=[TEST_KEY], WEBAUTHN_RP_ID=RP_ID, WEBAUTHN_ORIGIN=ORIGIN)
class MfaRemovalGuardTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_user("guard_user", UserRole.ZEV_OWNER)
        self.client = APIClient()
        auth(self.client, self.user)
        AppSettings.load()
        AppSettings.objects.update(mfa_required_roles=["zev_owner"])

    def _totp(self):
        device = TotpDevice(user=self.user, confirmed_at=timezone.now())
        device.set_secret("JBSWY3DPEHPK3PXP")
        device.save()

    def test_removal_refused_when_policy_requires_a_factor(self):
        self._totp()

        resp = self.client.delete("/api/v1/auth/me/mfa/totp/")

        self.assertEqual(resp.status_code, 409)
        self.assertTrue(TotpDevice.objects.filter(user=self.user).exists())

    def test_removal_allowed_while_another_factor_remains(self):
        self._totp()
        register_passkey(self.client, SoftAuthenticator())

        resp = self.client.delete("/api/v1/auth/me/mfa/totp/")

        self.assertEqual(resp.status_code, 204)

    def test_last_passkey_cannot_be_removed_when_required(self):
        register_passkey(self.client, SoftAuthenticator())

        resp = self.client.delete(f"{PASSKEYS_URL}{WebAuthnCredential.objects.get().pk}/")

        self.assertEqual(resp.status_code, 409)
        self.assertEqual(WebAuthnCredential.objects.count(), 1)

    def test_removal_is_free_when_the_policy_does_not_name_the_role(self):
        AppSettings.objects.update(mfa_required_roles=["admin"])
        self._totp()

        resp = self.client.delete("/api/v1/auth/me/mfa/totp/")

        self.assertEqual(resp.status_code, 204)

    def test_confirming_totp_keeps_recovery_codes_a_passkey_already_earned(self):
        register_passkey(self.client, SoftAuthenticator())
        before = set(MfaRecoveryCode.objects.filter(user=self.user).values_list("pk", flat=True))
        self.assertEqual(len(before), 10)

        begun = self.client.post("/api/v1/auth/me/mfa/totp/")
        resp = self.client.post(
            "/api/v1/auth/me/mfa/totp/confirm/", {"code": pyotp.TOTP(begun.data["secret"]).now()}, format="json"
        )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["recovery_codes"], [])
        after = set(MfaRecoveryCode.objects.filter(user=self.user).values_list("pk", flat=True))
        self.assertEqual(before, after)

    def test_recovery_codes_can_be_regenerated_with_only_a_passkey(self):
        register_passkey(self.client, SoftAuthenticator())

        resp = self.client.post("/api/v1/auth/me/mfa/recovery-codes/")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data["recovery_codes"]), 10)


@override_settings(MFA_ENCRYPTION_KEYS=[TEST_KEY], WEBAUTHN_RP_ID=RP_ID, WEBAUTHN_ORIGIN=ORIGIN)
class MfaAdminResetTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = make_user("reset_admin", UserRole.ADMIN)
        self.admin_client = APIClient()
        auth(self.admin_client, self.admin)
        self.target = make_user("reset_target", UserRole.ZEV_OWNER)
        target_client = APIClient()
        auth(target_client, self.target)
        register_passkey(target_client, SoftAuthenticator())
        device = TotpDevice(user=self.target, confirmed_at=timezone.now())
        device.set_secret("JBSWY3DPEHPK3PXP")
        device.save()

    def _url(self, pk=None):
        return f"/api/v1/auth/users/{pk or self.target.pk}/mfa/"

    def test_admin_reset_removes_all_factors_and_audits(self):
        resp = self.admin_client.delete(self._url())

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["removed"], {"totp": 1, "passkeys": 1, "recovery_codes": 10})
        self.assertFalse(TotpDevice.objects.filter(user=self.target).exists())
        self.assertFalse(WebAuthnCredential.objects.filter(user=self.target).exists())
        self.assertFalse(MfaRecoveryCode.objects.filter(user=self.target).exists())
        event = AuditEvent.objects.get(action_type="auth.mfa.reset")
        self.assertEqual(event.actor_user_id, self.admin.pk)
        self.assertEqual(event.target_id, str(self.target.pk))
        self.assertEqual(event.metadata_json["removed"]["passkeys"], 1)

    def test_reset_leaves_the_user_able_to_sign_in_with_a_password_alone(self):
        self.admin_client.delete(self._url())

        resp = APIClient().post(
            "/api/v1/auth/token/", {"email": self.target.email, "password": "pass1234"}, format="json"
        )

        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("mfa_required", resp.data)

    def test_non_admin_cannot_reset_another_user(self):
        client = APIClient()
        auth(client, make_user("reset_owner", UserRole.ZEV_OWNER))

        resp = client.delete(self._url())

        self.assertEqual(resp.status_code, 403)
        self.assertTrue(TotpDevice.objects.filter(user=self.target).exists())
        self.assertFalse(AuditEvent.objects.filter(action_type="auth.mfa.reset").exists())

    def test_unauthenticated_reset_is_refused(self):
        self.assertIn(APIClient().delete(self._url()).status_code, (401, 403))

    def test_unknown_user_is_404(self):
        self.assertEqual(self.admin_client.delete(self._url(999999)).status_code, 404)

    def test_admin_cannot_read_any_secret(self):
        resp = self.admin_client.delete(self._url())
        body = json.dumps(resp.data)

        for forbidden in ("secret", "public_key", "credential_id", "code_hash"):
            self.assertNotIn(forbidden, body)

    def test_an_api_key_cannot_reach_the_reset(self):
        from .api_keys import generate_key
        from .models import ApiKey

        raw, prefix, hashed = generate_key()
        ApiKey.objects.create(user=self.admin, name="k", prefix=prefix, hashed_key=hashed)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Api-Key {raw}")

        resp = client.delete(self._url())

        self.assertEqual(resp.status_code, 403)
        self.assertTrue(TotpDevice.objects.filter(user=self.target).exists())


class WebAuthnRpCheckTests(TestCase):
    def _ids(self):
        from .checks import webauthn_rp_configured

        return [w.id for w in webauthn_rp_configured(None)]

    @override_settings(DEBUG=False, WEBAUTHN_RP_ID="localhost")
    def test_warns_when_production_still_uses_the_development_rp_id(self):
        self.assertEqual(self._ids(), ["accounts.W002"])

    @override_settings(DEBUG=True, WEBAUTHN_RP_ID="localhost")
    def test_silent_under_debug(self):
        self.assertEqual(self._ids(), [])

    @override_settings(DEBUG=False, WEBAUTHN_RP_ID="zev.example.ch")
    def test_silent_once_configured(self):
        self.assertEqual(self._ids(), [])
