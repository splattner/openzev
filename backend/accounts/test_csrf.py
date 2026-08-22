"""CSRF for cookie-JWT — cookie unsafe requests need token, header clients don't."""

from datetime import timedelta

from django.conf import settings
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from testing.helpers import authenticate

from .api_keys import generate_key
from .cookies import ACCESS_COOKIE, REFRESH_COOKIE
from .models import ApiKey, User, UserRole

_PW = {"old_password": "pass1234", "new_password": "new-pass-1234"}


def _cookie_client(user, csrf_token=None):
    # enforce_csrf_checks=True is load-bearing: without it APIClient sets
    # _dont_enforce_csrf_checks and our negative tests would spuriously pass.
    client = APIClient(enforce_csrf_checks=True)
    refresh = RefreshToken.for_user(user)
    client.cookies[ACCESS_COOKIE] = str(refresh.access_token)
    client.cookies[REFRESH_COOKIE] = str(refresh)
    if csrf_token is not None:
        client.cookies[settings.CSRF_COOKIE_NAME] = csrf_token
        client.credentials(HTTP_X_CSRFTOKEN=csrf_token)
    return client


class CookieCsrfTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="csrf_user", password="pass1234", role=UserRole.PARTICIPANT)
        self.token = "a" * 32

    def test_safe_method_no_csrf_needed(self):
        resp = _cookie_client(self.user).get("/api/v1/auth/me/")
        self.assertEqual(resp.status_code, 200)

    def test_cookie_post_without_csrf_forbidden(self):
        resp = _cookie_client(self.user).post(
            "/api/v1/auth/me/change-password/",
            _PW,
            format="json",
        )
        self.assertEqual(resp.status_code, 403)
        self.assertIn("CSRF", str(resp.data))

    def test_cookie_present_header_missing_forbidden(self):
        # Classic axios misconfig: csrftoken cookie set but header not sent
        client = _cookie_client(self.user, self.token)
        client.credentials()  # clear header, keep cookie
        resp = client.post(
            "/api/v1/auth/me/change-password/",
            _PW,
            format="json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_cookie_post_invalid_csrf_forbidden(self):
        client = _cookie_client(self.user, self.token)
        client.credentials(HTTP_X_CSRFTOKEN="wrong" + self.token)
        resp = client.post(
            "/api/v1/auth/me/change-password/",
            _PW,
            format="json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_cookie_post_valid_csrf_succeeds(self):
        resp = _cookie_client(self.user, self.token).post(
            "/api/v1/auth/me/change-password/",
            _PW,
            format="json",
        )
        self.assertEqual(resp.status_code, 200)

    def test_bearer_no_csrf_needed(self):
        client = APIClient()
        authenticate(client, self.user)
        resp = client.post(
            "/api/v1/auth/me/change-password/",
            _PW,
            format="json",
        )
        self.assertEqual(resp.status_code, 200)

    def test_api_key_no_csrf_needed(self):
        # change-password is not on the API-key allowlist, so it would 403 either way.
        # Use a write the key is allowed to do (vat-rates) to prove CSRF is skipped.
        admin = User.objects.create_user(username="csrf_admin", password="pass1234", role=UserRole.ADMIN)
        full_key, prefix, hashed = generate_key()

        ApiKey.objects.create(
            user=admin, name="test", prefix=prefix, hashed_key=hashed, expires_at=timezone.now() + timedelta(days=1)
        )
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Api-Key {full_key}")
        resp = client.post(
            "/api/v1/auth/vat-rates/",
            {"rate": "0.0810", "valid_from": "2030-01-01"},
            format="json",
        )
        self.assertEqual(resp.status_code, 201)

    def test_login_sets_csrf_cookie(self):
        User.objects.create_user(username="login_csrf", password="pass1234", role=UserRole.PARTICIPANT, email="login_csrf@example.com")
        resp = APIClient().post("/api/v1/auth/token/", {"username": "login_csrf", "password": "pass1234"}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(settings.CSRF_COOKIE_NAME, resp.cookies)

    def test_refresh_needs_csrf_and_reissues_cookie(self):
        client = APIClient()
        User.objects.create_user(username="refresh_csrf", password="pass1234", role=UserRole.PARTICIPANT, email="refresh_csrf@example.com")
        login = client.post("/api/v1/auth/token/", {"username": "refresh_csrf", "password": "pass1234"}, format="json")
        csrf_token = login.cookies[settings.CSRF_COOKIE_NAME].value

        bare = APIClient(enforce_csrf_checks=True)
        bare.cookies[REFRESH_COOKIE] = login.cookies[REFRESH_COOKIE].value
        self.assertEqual(bare.post("/api/v1/auth/token/refresh/").status_code, 403)

        ok = APIClient(enforce_csrf_checks=True)
        ok.cookies[REFRESH_COOKIE] = login.cookies[REFRESH_COOKIE].value
        ok.cookies[settings.CSRF_COOKIE_NAME] = csrf_token
        ok.credentials(HTTP_X_CSRFTOKEN=csrf_token)
        resp = ok.post("/api/v1/auth/token/refresh/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(settings.CSRF_COOKIE_NAME, resp.cookies)
