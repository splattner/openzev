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
    AuthLoginThrottle,
    AuthOAuthExchangeThrottle,
    AuthOAuthInitiateThrottle,
    AuthRefreshThrottle,
    AuthRegisterThrottle,
    AuthVerifyThrottle,
)

LOGIN = "/api/v1/auth/token/"
REFRESH = "/api/v1/auth/token/refresh/"
REGISTER = "/api/v1/auth/register/"
VERIFY = "/api/v1/auth/verify-email/"
OAUTH_INITIATE = "/api/v1/auth/oauth/login/bogus-provider/"
OAUTH_EXCHANGE = "/api/v1/auth/oauth/token-exchange/"


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
