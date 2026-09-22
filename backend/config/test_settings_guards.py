"""Guards that keep a DEBUG=False deployment from starting insecure."""

from django.core.checks import Error
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.core.management.base import CommandError, SystemCheckError
from django.test import SimpleTestCase, TestCase, override_settings

from accounts.checks import production_hosts_configured
from config.settings import _INSECURE_SECRET_KEY, validate_secret_key


class ValidateSecretKeyTests(SimpleTestCase):
    def test_rejects_placeholder_in_production(self):
        with self.assertRaises(ImproperlyConfigured):
            validate_secret_key(False, _INSECURE_SECRET_KEY)

    def test_rejects_empty_key_in_production(self):
        with self.assertRaises(ImproperlyConfigured):
            validate_secret_key(False, "")

    def test_accepts_real_key_in_production(self):
        validate_secret_key(False, "a-long-random-secret-key-for-production-use")

    def test_silent_in_debug(self):
        validate_secret_key(True, _INSECURE_SECRET_KEY)
        validate_secret_key(True, "")


class ProductionHostsCheckTests(SimpleTestCase):
    def test_silent_under_debug(self):
        with override_settings(DEBUG=True):
            self.assertEqual(production_hosts_configured(None), [])

    @override_settings(DEBUG=False, ALLOWED_HOSTS=[], FRONTEND_URL="https://zev.example.ch")
    def test_errors_on_empty_allowed_hosts(self):
        (error,) = production_hosts_configured(None)
        self.assertEqual(error.id, "accounts.E003")

    @override_settings(DEBUG=False, ALLOWED_HOSTS=["localhost"], FRONTEND_URL="https://zev.example.ch")
    def test_errors_on_subset_of_development_hosts(self):
        (error,) = production_hosts_configured(None)
        self.assertEqual(error.id, "accounts.E003")

    @override_settings(DEBUG=False, ALLOWED_HOSTS=["127.0.0.1", "localhost"], FRONTEND_URL="https://zev.example.ch")
    def test_errors_regardless_of_order(self):
        (error,) = production_hosts_configured(None)
        self.assertEqual(error.id, "accounts.E003")

    @override_settings(DEBUG=False, ALLOWED_HOSTS=["*"], FRONTEND_URL="https://zev.example.ch")
    def test_errors_on_wildcard_allowed_hosts(self):
        (error,) = production_hosts_configured(None)
        self.assertEqual(error.id, "accounts.E003")

    @override_settings(DEBUG=False, ALLOWED_HOSTS=["zev.example.ch"], FRONTEND_URL="")
    def test_errors_on_empty_frontend_url(self):
        (error,) = production_hosts_configured(None)
        self.assertEqual(error.id, "accounts.E004")

    @override_settings(DEBUG=False, ALLOWED_HOSTS=["zev.example.ch"], FRONTEND_URL="https://127.0.0.1:8080")
    def test_errors_on_loopback_frontend_url(self):
        (error,) = production_hosts_configured(None)
        self.assertEqual(error.id, "accounts.E004")

    @override_settings(
        DEBUG=False,
        ALLOWED_HOSTS=["localhost", "127.0.0.1"],
        FRONTEND_URL="http://localhost:5173",
    )
    def test_errors_carry_distinct_ids(self):
        errors = production_hosts_configured(None)
        self.assertTrue(all(isinstance(e, Error) for e in errors))
        self.assertEqual([e.id for e in errors], ["accounts.E003", "accounts.E004"])

    @override_settings(
        DEBUG=False,
        ALLOWED_HOSTS=["zev.example.ch"],
        FRONTEND_URL="https://zev.example.ch",
        WEBAUTHN_RP_ID="zev.example.ch",
        MFA_ENCRYPTION_KEYS=["dummy"],
    )
    def test_check_command_passes_when_configured(self):
        call_command("check")

    @override_settings(DEBUG=False, ALLOWED_HOSTS=["localhost"], FRONTEND_URL="http://localhost:5173")
    def test_check_command_raises_for_localhost_in_prod(self):
        with self.assertRaises(SystemCheckError):
            call_command("check")


class SeedDemoGuardTests(TestCase):    # TestCase, not SimpleTestCase: @transaction.atomic on handle() opens a DB
    # transaction before the DEBUG guard raises.
    @override_settings(DEBUG=False)
    def test_seed_demo_refuses_in_production(self):
        with self.assertRaises(CommandError):
            call_command("seed_demo")
