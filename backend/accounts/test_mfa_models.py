"""Model-level tests for TotpDevice and MfaRecoveryCode.

Not named in spec 2026-09-two-factor-authentication.md's own test plan (§9
lists API-level tests, which need the enrolment/login endpoints landing in
PR2) — but the replay-protection logic in TotpDevice.verify() ships now, so
it is unit-tested now rather than left uncovered until the endpoints exist.
"""

import secrets
from datetime import datetime, timedelta, timezone as dt_timezone
from unittest.mock import patch

import pyotp
from cryptography.fernet import Fernet
from django.test import TestCase
from django.test.utils import override_settings
from django.utils import timezone

from testing.helpers import make_user

from .api_keys import hash_secret, verify_secret
from .models import TOTP_VALID_WINDOW, MfaRecoveryCode, TotpDevice, UserRole

SECRET = pyotp.random_base32()


@override_settings(MFA_ENCRYPTION_KEYS=[Fernet.generate_key().decode()])
class TotpDeviceTests(TestCase):
    def setUp(self):
        self.user = make_user("totp_device_user", UserRole.PARTICIPANT)
        self.device = TotpDevice(user=self.user)
        self.device.set_secret(SECRET)
        self.device.save()

    @staticmethod
    def _code_at(when: datetime) -> str:
        return pyotp.TOTP(SECRET).at(when)

    def test_secret_round_trips_through_the_property(self):
        self.assertEqual(self.device.secret, SECRET)

    def test_unconfirmed_device_reports_inactive(self):
        self.assertIsNone(self.device.confirmed_at)
        self.assertFalse(self.device.is_active)

    def test_confirming_makes_it_active(self):
        self.device.confirmed_at = timezone.now()
        self.device.save()
        self.assertTrue(self.device.is_active)

    def test_valid_code_is_accepted(self):
        now = datetime(2026, 1, 1, tzinfo=dt_timezone.utc)
        with patch("accounts.models.timezone.now", return_value=now):
            self.assertTrue(self.device.verify(self._code_at(now)))

    def test_wrong_code_is_rejected(self):
        now = datetime(2026, 1, 1, tzinfo=dt_timezone.utc)
        real_code = self._code_at(now)
        wrong_code = "000000" if real_code != "000000" else "111111"
        with patch("accounts.models.timezone.now", return_value=now):
            self.assertFalse(self.device.verify(wrong_code))

    def test_a_code_cannot_be_replayed(self):
        now = datetime(2026, 1, 1, tzinfo=dt_timezone.utc)
        code = self._code_at(now)
        with patch("accounts.models.timezone.now", return_value=now):
            self.assertTrue(self.device.verify(code))
            # Same code, still inside its own valid window — must not work twice.
            self.assertFalse(self.device.verify(code))

    def test_a_later_step_is_still_accepted_after_an_earlier_one(self):
        t0 = datetime(2026, 1, 1, tzinfo=dt_timezone.utc)
        t1 = t0 + timedelta(seconds=30)
        with patch("accounts.models.timezone.now", return_value=t0):
            self.assertTrue(self.device.verify(self._code_at(t0)))
        with patch("accounts.models.timezone.now", return_value=t1):
            self.assertTrue(self.device.verify(self._code_at(t1)))

    def test_code_outside_the_skew_window_is_rejected(self):
        now = datetime(2026, 1, 1, tzinfo=dt_timezone.utc)
        far_future = now + timedelta(seconds=30 * (TOTP_VALID_WINDOW + 5))
        with patch("accounts.models.timezone.now", return_value=now):
            self.assertFalse(self.device.verify(self._code_at(far_future)))

    def test_last_used_step_persists_across_instances(self):
        """Replay protection survives a fresh load from the database, not
        just repeated calls on the same in-memory object."""
        now = datetime(2026, 1, 1, tzinfo=dt_timezone.utc)
        code = self._code_at(now)
        with patch("accounts.models.timezone.now", return_value=now):
            self.assertTrue(self.device.verify(code))

        reloaded = TotpDevice.objects.get(pk=self.device.pk)
        with patch("accounts.models.timezone.now", return_value=now):
            self.assertFalse(reloaded.verify(code))


class MfaRecoveryCodeTests(TestCase):
    def test_hash_round_trips_via_the_shared_api_key_hasher(self):
        """Spec §4.3: reuse api_keys.hash_secret/verify_secret rather than a
        second hashing path."""
        user = make_user("mfa_recovery_user", UserRole.PARTICIPANT)
        plaintext = secrets.token_hex(5)
        code = MfaRecoveryCode.objects.create(user=user, code_hash=hash_secret(plaintext))

        self.assertTrue(verify_secret(plaintext, code.code_hash))
        self.assertFalse(verify_secret("0" * 10, code.code_hash))

    def test_is_active_reflects_use(self):
        user = make_user("mfa_recovery_use", UserRole.PARTICIPANT)
        code = MfaRecoveryCode.objects.create(user=user, code_hash=hash_secret(secrets.token_hex(5)))

        self.assertTrue(code.is_active)

        code.used_at = timezone.now()
        code.save()

        self.assertFalse(code.is_active)
