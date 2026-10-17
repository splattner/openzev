"""Exercise the actual Django transport behavior behind a trusted proxy."""

from pathlib import Path
import runpy

from django.core.handlers.wsgi import WSGIRequest
from django.http import HttpResponse
from django.middleware.security import SecurityMiddleware
from django.test import SimpleTestCase, override_settings
from django.urls import path
from gunicorn.config import Config
from gunicorn.http.parser import RequestParser
from gunicorn.http.wsgi import create


def transport_probe(request):
    return HttpResponse("ok")


urlpatterns = [path("transport/", transport_probe, name="transport-probe")]


def gunicorn_response(headers):
    """Pass real Gunicorn parsing and WSGI output through Django middleware."""
    # This interaction test follows the Gunicorn version pinned in requirements.txt.
    config = Config()
    deployed_config = runpy.run_path(str(Path(__file__).resolve().parents[1] / "gunicorn.conf.py"))
    config.set("secure_scheme_headers", deployed_config["secure_scheme_headers"])
    peer = ("127.0.0.1", 12345)
    raw_request = (
        "GET /transport/ HTTP/1.1\r\nHost: testserver\r\n"
        + "".join(f"{name}: {value}\r\n" for name, value in headers.items())
        + "\r\n"
    ).encode("ascii")
    request = next(RequestParser(config, [raw_request], peer))
    _, environ = create(request, None, peer, ("127.0.0.1", 8000), config)
    return SecurityMiddleware(transport_probe)(WSGIRequest(environ))


@override_settings(
    ROOT_URLCONF=__name__,
    ALLOWED_HOSTS=["testserver"],
    SECURE_SSL_REDIRECT=True,
    SECURE_HSTS_SECONDS=31536000,
)
class TransportBehaviorTests(SimpleTestCase):
    def test_plain_http_redirects_to_https(self):
        response = self.client.get("/transport/", secure=False)

        self.assertEqual(response.status_code, 301)
        self.assertEqual(response["Location"], "https://testserver/transport/")

    @override_settings(SECURE_PROXY_SSL_HEADER=None)
    def test_spoofed_forwarded_https_redirects_without_a_trusted_proxy(self):
        response = self.client.get(
            "/transport/",
            secure=False,
            HTTP_X_FORWARDED_PROTO="https",
        )

        self.assertEqual(response.status_code, 301)
        self.assertEqual(response["Location"], "https://testserver/transport/")

    @override_settings(SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"))
    def test_trusted_forwarded_https_avoids_redirect_and_sets_hsts(self):
        response = self.client.get(
            "/transport/",
            secure=False,
            HTTP_X_FORWARDED_PROTO="https",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Strict-Transport-Security"], "max-age=31536000")

    @override_settings(SECURE_PROXY_SSL_HEADER=None)
    def test_gunicorn_cannot_bypass_disabled_proxy_trust(self):
        for name, value in (
            ("X-Forwarded-Proto", "https"),
            ("X-Forwarded-SSL", "on"),
            ("X-Forwarded-Protocol", "ssl"),
        ):
            with self.subTest(header=name):
                response = gunicorn_response({name: value})
                self.assertEqual(response.status_code, 301)
                self.assertNotIn("Strict-Transport-Security", response)

    @override_settings(SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"))
    def test_gunicorn_preserves_django_trusted_https_detection(self):
        response = gunicorn_response({"X-Forwarded-Proto": "https", "X-Forwarded-SSL": "off"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Strict-Transport-Security"], "max-age=31536000")
