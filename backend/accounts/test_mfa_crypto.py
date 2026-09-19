"""Tests for accounts.mfa_crypto and the rotate_mfa_key management command.

See ADR 0021 for why the key is independent of SECRET_KEY, and spec
2026-09-two-factor-authentication.md §9 (MfaCryptoTests) for the five tests
this module is required to carry.
"""

from cryptography.fernet import Fernet, InvalidToken
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.test.utils import override_settings

from audit.models import AuditEvent
from testing.helpers import make_user

from . import mfa_crypto
from .checks import mfa_key_configured
from .models import TotpDevice, UserRole

SECRET = "JBSWY3DPEHPK3PXP"


def _key() -> str:
    return Fernet.generate_key().decode()


class MfaCryptoTests(TestCase):
    def test_round_trip(self):
        with override_settings(MFA_ENCRYPTION_KEYS=[_key()]):
            token = mfa_crypto.encrypt_secret(SECRET)
            self.assertEqual(mfa_crypto.decrypt_secret(token), SECRET)

    def test_second_key_still_decrypts_after_rotation(self):
        """A token from the old key decrypts when it is second in the list —
        the point of MultiFernet: rotation doesn't orphan existing secrets."""
        old_key = _key()
        new_key = _key()
        with override_settings(MFA_ENCRYPTION_KEYS=[old_key]):
            token = mfa_crypto.encrypt_secret(SECRET)

        with override_settings(MFA_ENCRYPTION_KEYS=[new_key, old_key]):
            self.assertEqual(mfa_crypto.decrypt_secret(token), SECRET)

    def test_new_writes_use_the_first_key(self):
        """Encrypting with two keys configured produces a token the FIRST
        key alone can open, and the second key alone cannot — proving which
        key was actually used to write it, not merely that some configured
        key can read it back."""
        key_a = _key()
        key_b = _key()
        with override_settings(MFA_ENCRYPTION_KEYS=[key_a, key_b]):
            token = mfa_crypto.encrypt_secret(SECRET)

        self.assertEqual(Fernet(key_a.encode()).decrypt(token), SECRET.encode())
        with self.assertRaises(InvalidToken):
            Fernet(key_b.encode()).decrypt(token)

    def test_rotate_command_re_encrypts_every_device(self):
        old_key = _key()
        new_key = _key()
        user = make_user("mfa_rotate_user", UserRole.PARTICIPANT)
        with override_settings(MFA_ENCRYPTION_KEYS=[old_key]):
            device = TotpDevice(user=user)
            device.set_secret(SECRET)
            device.save()

        with override_settings(MFA_ENCRYPTION_KEYS=[new_key, old_key]):
            call_command("rotate_mfa_key")

        device.refresh_from_db()
        # The new key ALONE can now open it — proving re-encryption
        # happened, not merely that the old key still works via
        # MultiFernet's fallback.
        with override_settings(MFA_ENCRYPTION_KEYS=[new_key]):
            self.assertEqual(device.secret, SECRET)

    def test_missing_key_raises_mfa_not_configured(self):
        with override_settings(MFA_ENCRYPTION_KEYS=[]):
            with self.assertRaises(mfa_crypto.MfaNotConfigured):
                mfa_crypto.encrypt_secret(SECRET)


class RotateMfaKeyCommandTests(TestCase):
    def test_no_devices_is_a_no_op(self):
        with override_settings(MFA_ENCRYPTION_KEYS=[_key()]):
            call_command("rotate_mfa_key")  # must not raise

        self.assertFalse(AuditEvent.objects.filter(action_type="auth.mfa.key_rotated").exists())

    def test_refuses_when_no_key_is_configured(self):
        key = _key()
        user = make_user("mfa_rotate_no_key", UserRole.PARTICIPANT)
        with override_settings(MFA_ENCRYPTION_KEYS=[key]):
            device = TotpDevice(user=user)
            device.set_secret(SECRET)
            device.save()

        with override_settings(MFA_ENCRYPTION_KEYS=[]):
            with self.assertRaises(CommandError):
                call_command("rotate_mfa_key")

        # Nothing was modified — the transaction rolled back, so the
        # original key still opens it.
        device.refresh_from_db()
        with override_settings(MFA_ENCRYPTION_KEYS=[key]):
            self.assertEqual(device.secret, SECRET)

    def test_records_an_audit_event(self):
        key = _key()
        user = make_user("mfa_rotate_audit", UserRole.PARTICIPANT)
        with override_settings(MFA_ENCRYPTION_KEYS=[key]):
            device = TotpDevice(user=user)
            device.set_secret(SECRET)
            device.save()

            call_command("rotate_mfa_key")

        event = AuditEvent.objects.get(action_type="auth.mfa.key_rotated")
        self.assertEqual(event.metadata_json["devices_reencrypted"], 1)
        self.assertEqual(event.source, "management_command")
        self.assertIsNone(event.actor_user_id)


class MfaKeyConfiguredCheckTests(TestCase):
    def test_warns_when_unset(self):
        with override_settings(MFA_ENCRYPTION_KEYS=[]):
            warnings = mfa_key_configured(None)

        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0].id, "accounts.W001")

    def test_silent_when_configured(self):
        with override_settings(MFA_ENCRYPTION_KEYS=[_key()]):
            self.assertEqual(mfa_key_configured(None), [])
