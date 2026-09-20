"""Cookie-auth and OAuth exchange edge-case tests.

These tests protect the httpOnly-cookie migration and OAuth exchange boundary:
refresh/logout/token-exchange should never leak JWTs in JSON response bodies and
one-time OAuth exchange codes must be consumed exactly once.
"""

from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import OAuthExchangeCode
from testing.factories import ParticipantUserFactory

pytestmark = pytest.mark.django_db


def test_token_refresh_requires_refresh_cookie():
    client = APIClient()

    response = client.post("/api/v1/auth/token/refresh/")

    assert response.status_code == 401
    assert response.data["detail"] == "Refresh token not found."


def test_token_refresh_sets_cookies_without_returning_tokens():
    user = ParticipantUserFactory()
    refresh = RefreshToken.for_user(user)
    client = APIClient()
    client.cookies["openzev_refresh"] = str(refresh)

    response = client.post("/api/v1/auth/token/refresh/")

    assert response.status_code == 200
    assert response.data == {"detail": "Token refreshed."}
    assert "openzev_access" in response.cookies
    assert "openzev_refresh" in response.cookies
    assert response.cookies["openzev_access"]["httponly"]
    assert response.cookies["openzev_refresh"]["httponly"]
    assert "access" not in response.data
    assert "refresh" not in response.data


def test_logout_clears_user_and_admin_impersonation_cookies():
    client = APIClient()
    for cookie_name in (
        "openzev_access",
        "openzev_refresh",
        "openzev_admin_access",
        "openzev_admin_refresh",
    ):
        client.cookies[cookie_name] = "token"

    response = client.post("/api/v1/auth/logout/")

    assert response.status_code == 200
    assert response.data == {"detail": "Logged out."}
    for cookie_name in (
        "openzev_access",
        "openzev_refresh",
        "openzev_admin_access",
        "openzev_admin_refresh",
    ):
        assert cookie_name in response.cookies
        assert response.cookies[cookie_name].value == ""
        assert response.cookies[cookie_name]["max-age"] == 0


def test_oauth_token_exchange_sets_cookies_and_consumes_code_once():
    user = ParticipantUserFactory()
    exchange_code = OAuthExchangeCode.objects.create(code="one-time-code", user=user)
    client = APIClient()

    response = client.post("/api/v1/auth/oauth/token-exchange/", {"code": exchange_code.code}, format="json")

    assert response.status_code == 200
    assert response.data == {"detail": "Login successful."}
    assert "openzev_access" in response.cookies
    assert "openzev_refresh" in response.cookies
    assert response.cookies["openzev_access"]["httponly"]
    assert "access" not in response.data
    assert "refresh" not in response.data
    assert not OAuthExchangeCode.objects.filter(pk=exchange_code.pk).exists()

    second_response = client.post("/api/v1/auth/oauth/token-exchange/", {"code": exchange_code.code}, format="json")
    assert second_response.status_code == 400
    assert second_response.data["detail"] == "Invalid or expired code."


def test_oauth_token_exchange_stamps_last_login():
    user = ParticipantUserFactory()
    assert user.last_login is None
    exchange_code = OAuthExchangeCode.objects.create(code="last-login-code", user=user)
    client = APIClient()

    client.post("/api/v1/auth/oauth/token-exchange/", {"code": exchange_code.code}, format="json")

    user.refresh_from_db()
    assert user.last_login is not None


def test_oauth_token_exchange_rejects_expired_code_and_deletes_it():
    user = ParticipantUserFactory()
    exchange_code = OAuthExchangeCode.objects.create(code="expired-code", user=user)
    OAuthExchangeCode.objects.filter(pk=exchange_code.pk).update(created_at=timezone.now() - timedelta(seconds=61))
    client = APIClient()

    response = client.post("/api/v1/auth/oauth/token-exchange/", {"code": exchange_code.code}, format="json")

    assert response.status_code == 400
    assert response.data["detail"] == "Code has expired."
    assert not OAuthExchangeCode.objects.filter(pk=exchange_code.pk).exists()


def test_oauth_token_exchange_requires_code():
    client = APIClient()

    response = client.post("/api/v1/auth/oauth/token-exchange/", {}, format="json")

    assert response.status_code == 400
    assert response.data["detail"] == "code is required."
