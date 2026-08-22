"""Rate limits on the public auth endpoints.

Each public auth write endpoint carries a per-IP budget. The rest of the
suite runs with these rates disabled (``settings_test``); these tests
patch the rates onto the throttle classes, because DRF snapshots
``DEFAULT_THROTTLE_RATES`` onto ``SimpleRateThrottle`` at import time and
``override_settings`` cannot reach it.
"""

from unittest import mock

from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from .throttling import (
    ApiKeyRateThrottle,
    AuthLoginThrottle,
    AuthOAuthExchangeThrottle,
    AuthOAuthInitiateThrottle,
    AuthRefreshThrottle,
    AuthRegisterThrottle,
    AuthVerifyThrottle,
    ImportThrottle,
    TransferArchiveThrottle,
)
from .test_api_keys import create_api_key
from accounts.models import UserRole
from testing.helpers import authenticate as auth, make_user

LOGIN = "/api/v1/auth/token/"
REFRESH = "/api/v1/auth/token/refresh/"
REGISTER = "/api/v1/auth/register/"
VERIFY = "/api/v1/auth/verify-email/"
OAUTH_INITIATE = "/api/v1/auth/oauth/login/bogus-provider/"
OAUTH_EXCHANGE = "/api/v1/auth/oauth/token-exchange/"
IMPORT_CSV = "/api/v1/metering/import/csv/"
INSPECT_ARCHIVE = "/api/v1/zev/zevs/inspect-archive/"


@mock.patch.object(AuthLoginThrottle, "THROTTLE_RATES", {"auth_login": "3/hour"})
@mock.patch.object(AuthRefreshThrottle, "THROTTLE_RATES", {"auth_refresh": "3/hour"})
@mock.patch.object(AuthRegisterThrottle, "THROTTLE_RATES", {"auth_register": "3/hour"})
@mock.patch.object(AuthVerifyThrottle, "THROTTLE_RATES", {"auth_verify": "3/hour"})
@mock.patch.object(AuthOAuthInitiateThrottle, "THROTTLE_RATES", {"auth_oauth_initiate": "3/hour"})
@mock.patch.object(AuthOAuthExchangeThrottle, "THROTTLE_RATES", {"auth_oauth_exchange": "3/hour"})
class AuthEndpointThrottleTests(TestCase):
    """Each public auth endpoint is capped per client IP."""

    def setUp(self):
        cache.clear()
        self.client = APIClient()

    def tearDown(self):
        cache.clear()

    def test_login_past_its_budget_gets_429(self):
        for _ in range(3):
            response = self.client.post(
                LOGIN, {"username": "nobody", "password": "wrong"}, format="json"
            )
            self.assertNotEqual(response.status_code, 429)
        response = self.client.post(
            LOGIN, {"username": "nobody", "password": "wrong"}, format="json"
        )
        self.assertEqual(response.status_code, 429)

    def test_refresh_past_its_budget_gets_429(self):
        for _ in range(3):
            response = self.client.post(REFRESH, format="json")
            self.assertNotEqual(response.status_code, 429)
        self.assertEqual(self.client.post(REFRESH, format="json").status_code, 429)

    def test_register_past_its_budget_gets_429(self):
        for i in range(3):
            response = self.client.post(
                REGISTER, {"email": f"spam{i}@example.com"}, format="json"
            )
            self.assertNotEqual(response.status_code, 429)
        self.assertEqual(
            self.client.post(REGISTER, {"email": "spam3@example.com"}, format="json").status_code,
            429,
        )

    def test_verify_email_past_its_budget_gets_429(self):
        for _ in range(3):
            response = self.client.post(VERIFY, {"token": "bogus"}, format="json")
            self.assertNotEqual(response.status_code, 429)
        self.assertEqual(
            self.client.post(VERIFY, {"token": "bogus"}, format="json").status_code,
            429,
        )

    def test_oauth_login_initiate_past_its_budget_gets_429(self):
        for _ in range(3):
            response = self.client.post(OAUTH_INITIATE, format="json")
            self.assertNotEqual(response.status_code, 429)
        self.assertEqual(self.client.post(OAUTH_INITIATE, format="json").status_code, 429)

    def test_oauth_token_exchange_past_its_budget_gets_429(self):
        for _ in range(3):
            response = self.client.post(OAUTH_EXCHANGE, {"code": "bogus"}, format="json")
            self.assertNotEqual(response.status_code, 429)
        self.assertEqual(
            self.client.post(OAUTH_EXCHANGE, {"code": "bogus"}, format="json").status_code,
            429,
        )

    def test_each_endpoint_has_its_own_budget(self):
        for _ in range(4):
            self.client.post(LOGIN, {"username": "nobody", "password": "wrong"}, format="json")
        self.assertEqual(
            self.client.post(LOGIN, {"username": "nobody", "password": "wrong"}, format="json").status_code,
            429,
        )
        # Exhausting login must not cost refresh or registration their budgets.
        self.assertNotEqual(self.client.post(REFRESH, format="json").status_code, 429)
        self.assertNotEqual(
            self.client.post(REGISTER, {"email": "fresh@example.com"}, format="json").status_code,
            429,
        )


@mock.patch.object(ImportThrottle, "THROTTLE_RATES", {"import": "3/hour"})
@mock.patch.object(TransferArchiveThrottle, "THROTTLE_RATES", {"transfer_import": "3/hour"})
class UploadEndpointThrottleTests(TestCase):
    """Metering imports and transfer archives are capped per user.

    Unlike the auth endpoints these need an authenticated request — DRF checks
    permissions before throttles, so an anonymous 401/403 would never reach
    the counter. The bodies are invalid on purpose: a 400 still consumes the
    budget, which is what is being asserted.
    """

    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.admin = make_user("throttle_upload_admin", UserRole.ADMIN)
        auth(self.client, self.admin)

    def tearDown(self):
        cache.clear()

    def test_import_past_its_budget_gets_429(self):
        for _ in range(3):
            self.assertNotEqual(self.client.post(IMPORT_CSV, format="multipart").status_code, 429)
        self.assertEqual(self.client.post(IMPORT_CSV, format="multipart").status_code, 429)

    def test_transfer_archive_past_its_budget_gets_429(self):
        for _ in range(3):
            self.assertNotEqual(self.client.post(INSPECT_ARCHIVE, format="multipart").status_code, 429)
        self.assertEqual(self.client.post(INSPECT_ARCHIVE, format="multipart").status_code, 429)

    def test_import_and_transfer_have_separate_budgets(self):
        for _ in range(4):
            self.client.post(IMPORT_CSV, format="multipart")
        self.assertEqual(self.client.post(IMPORT_CSV, format="multipart").status_code, 429)
        # Exhausting the import budget leaves the archive budget untouched.
        self.assertNotEqual(self.client.post(INSPECT_ARCHIVE, format="multipart").status_code, 429)

    @mock.patch.object(ApiKeyRateThrottle, "THROTTLE_RATES", {"api_key": "3/hour"})
    @mock.patch.object(ImportThrottle, "THROTTLE_RATES", {"import": "50/hour"})
    def test_import_requests_still_count_against_the_api_key_budget(self):
        # View-level ``throttle_classes`` replace DEFAULT_THROTTLE_CLASSES, so
        # the import view has to list ApiKeyRateThrottle itself or
        # key-authenticated requests stop counting against the key budget.
        client = APIClient()
        full_key = create_api_key(self.admin)[1]
        client.credentials(HTTP_AUTHORIZATION=f"Api-Key {full_key}")
        for _ in range(3):
            self.assertNotEqual(client.post(IMPORT_CSV, format="multipart").status_code, 429)
        self.assertEqual(client.post(IMPORT_CSV, format="multipart").status_code, 429)
