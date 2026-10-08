"""Integration credential encryption (ADR 0031): crypto, rotation command, system check."""

import os
from io import StringIO
from unittest import mock

from cryptography.fernet import Fernet
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings

from metering import checks
from metering.models import SupplementarySource
from metering.supplementary import crypto
from testing import factories
from zev.models import MeteringPointType

FLAG_ENV = "FEATURE_SUPPLEMENTARY_ENERGY_DATA_ENABLED"
OLD = Fernet.generate_key().decode()
NEW = Fernet.generate_key().decode()


class CryptoTests(SimpleTestCase):
    @override_settings(INTEGRATION_ENCRYPTION_KEYS=[OLD])
    def test_roundtrip(self):
        token = crypto.encrypt_secret("secret-value")
        self.assertNotIn(b"secret-value", token)
        self.assertEqual(crypto.decrypt_secret(token), "secret-value")

    @override_settings(INTEGRATION_ENCRYPTION_KEYS=[])
    def test_no_key_refuses_both_directions(self):
        self.assertFalse(crypto.encryption_configured())
        with self.assertRaises(crypto.IntegrationNotConfigured):
            crypto.encrypt_secret("x")
        with self.assertRaises(crypto.IntegrationNotConfigured):
            crypto.decrypt_secret(b"x")

    def test_old_token_stays_readable_after_a_new_key_is_prepended(self):
        with override_settings(INTEGRATION_ENCRYPTION_KEYS=[OLD]):
            token = crypto.encrypt_secret("secret-value")
        with override_settings(INTEGRATION_ENCRYPTION_KEYS=[NEW, OLD]):
            self.assertEqual(crypto.decrypt_secret(token), "secret-value")
            fresh = crypto.encrypt_secret("secret-value")
        # New tokens are written under the first key, so dropping the old one is safe.
        with override_settings(INTEGRATION_ENCRYPTION_KEYS=[NEW]):
            self.assertEqual(crypto.decrypt_secret(fresh), "secret-value")

    def test_unknown_key_raises_key_error_not_not_configured(self):
        with override_settings(INTEGRATION_ENCRYPTION_KEYS=[OLD]):
            token = crypto.encrypt_secret("secret-value")
        with override_settings(INTEGRATION_ENCRYPTION_KEYS=[NEW]):
            with self.assertRaises(crypto.IntegrationKeyError):
                crypto.decrypt_secret(token)


class RotateIntegrationKeyTests(TestCase):
    def make_source(self, **kwargs):
        zev = factories.ZevFactory()
        participant = factories.ParticipantFactory(zev=zev)
        point = factories.MeteringPointFactory(
            zev=zev, meter_type=MeteringPointType.BIDIRECTIONAL, has_behind_meter_generation=True
        )
        return SupplementarySource.objects.create(
            metering_point=point, participant=participant, provider="solar_manager",
            external_id="ABC123", **kwargs,
        )

    def run_command(self):
        out = StringIO()
        call_command("rotate_integration_key", stdout=out)
        return out.getvalue()

    def test_nothing_to_do(self):
        with override_settings(INTEGRATION_ENCRYPTION_KEYS=[OLD]):
            self.assertIn("No integration credentials", self.run_command())

    def test_reencrypts_under_the_first_key_and_is_idempotent(self):
        with override_settings(INTEGRATION_ENCRYPTION_KEYS=[OLD]):
            source = self.make_source()
            source.set_credential("refresh-token")
            source.save()
        with override_settings(INTEGRATION_ENCRYPTION_KEYS=[NEW, OLD]):
            self.assertIn("Re-encrypted 1", self.run_command())
            self.assertIn("Re-encrypted 1", self.run_command())
        source.refresh_from_db()
        with override_settings(INTEGRATION_ENCRYPTION_KEYS=[NEW]):
            self.assertEqual(source.credential, "refresh-token")

    def test_sources_without_a_credential_are_left_alone(self):
        self.make_source()
        with override_settings(INTEGRATION_ENCRYPTION_KEYS=[NEW]):
            self.assertIn("No integration credentials", self.run_command())

    def test_an_unreadable_credential_rolls_everything_back(self):
        with override_settings(INTEGRATION_ENCRYPTION_KEYS=[OLD]):
            good = self.make_source()
            good.set_credential("good-token")
            good.save()
        lost_key = Fernet.generate_key().decode()
        with override_settings(INTEGRATION_ENCRYPTION_KEYS=[lost_key]):
            bad = self.make_source()
            bad.set_credential("lost-token")
            bad.save()
        before = bytes(SupplementarySource.objects.get(pk=good.pk).credential_encrypted)
        with override_settings(INTEGRATION_ENCRYPTION_KEYS=[NEW, OLD]):
            with self.assertRaises(CommandError) as ctx:
                self.run_command()
        self.assertIn(str(bad.pk), str(ctx.exception))
        self.assertEqual(bytes(SupplementarySource.objects.get(pk=good.pk).credential_encrypted), before)

    def test_no_key_configured_is_a_command_error(self):
        with override_settings(INTEGRATION_ENCRYPTION_KEYS=[OLD]):
            source = self.make_source()
            source.set_credential("refresh-token")
            source.save()
        with override_settings(INTEGRATION_ENCRYPTION_KEYS=[]):
            with self.assertRaises(CommandError):
                self.run_command()


class IntegrationKeyCheckTests(SimpleTestCase):
    def run_check(self, env_value, keys):
        with mock.patch.dict("os.environ"):
            os.environ.pop(FLAG_ENV, None)
            if env_value is not None:
                os.environ[FLAG_ENV] = env_value
            with override_settings(INTEGRATION_ENCRYPTION_KEYS=keys):
                return checks.integration_key_configured(None)

    def test_silent_when_the_feature_is_not_forced_on(self):
        self.assertEqual(self.run_check(None, []), [])
        self.assertEqual(self.run_check("false", []), [])

    def test_warns_when_forced_on_without_a_key(self):
        result = self.run_check("true", [])
        self.assertEqual([w.id for w in result], ["metering.W001"])

    def test_silent_when_forced_on_with_a_key(self):
        self.assertEqual(self.run_check("true", [OLD]), [])
