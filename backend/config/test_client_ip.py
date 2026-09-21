"""Hop selection for persisted audit IPs.

Moved out of ``accounts/test_throttling.py``: these exercise
``config.client_ip``, not account throttling.
"""

from django.conf import settings as dj_settings
from django.test import SimpleTestCase, TestCase, override_settings
from django.test.client import RequestFactory
from rest_framework.throttling import SimpleRateThrottle

from audit.middleware import AuditRequestContextMiddleware
from audit.models import AuditActionCategory
from audit.services import record_audit_event
from config.client_ip import client_ip
from testing.helpers import trusted_proxies


class ClientIpHelperTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def request(self, remote_addr="192.0.2.10", xff=None):
        extra = {"REMOTE_ADDR": remote_addr}
        if xff is not None:
            extra["HTTP_X_FORWARDED_FOR"] = xff
        return self.factory.get("/", **extra)

    def test_no_trusted_proxy_uses_remote_addr(self):
        with trusted_proxies(0):
            self.assertEqual(client_ip(self.request(xff="198.51.100.1")), "192.0.2.10")

    def test_no_xff_falls_back_to_remote_addr(self):
        with trusted_proxies(1):
            self.assertEqual(client_ip(self.request()), "192.0.2.10")

    def test_one_hop_picks_rightmost_entry(self):
        with trusted_proxies(1):
            request = self.request(xff="192.0.2.1, 203.0.113.7")
            self.assertEqual(client_ip(request), "203.0.113.7")

    def test_two_hops_picks_second_from_right(self):
        with trusted_proxies(2):
            request = self.request(xff="192.0.2.1, 203.0.113.7, 10.0.0.1")
            self.assertEqual(client_ip(request), "203.0.113.7")

    def test_clamps_when_fewer_entries_than_hops(self):
        with trusted_proxies(2):
            self.assertEqual(client_ip(self.request(xff="203.0.113.7")), "203.0.113.7")

    def test_forged_header_returns_none(self):
        with trusted_proxies(1):
            self.assertIsNone(client_ip(self.request(xff="not an ip")))

    def test_empty_xff_returns_none(self):
        # DRF selects the empty string as the bucket; the helper validates
        # it to None so it stays safe for the inet column.
        with trusted_proxies(1):
            self.assertIsNone(client_ip(self.request(xff="")))

    def test_ipv6_addresses_validate(self):
        with trusted_proxies(1):
            request = self.request(xff="192.0.2.1, 2001:db8::1")
            self.assertEqual(client_ip(request), "2001:db8::1")

    def test_scoped_ipv6_returns_none(self):
        # fe80::1%eth0 parses as IPv6 but PostgreSQL inet rejects zone IDs.
        with trusted_proxies(1):
            request = self.request(xff="192.0.2.1, fe80::1%eth0")
            self.assertIsNone(client_ip(request))

    def test_missing_setting_falls_back_to_remote_addr(self):
        # The REST_FRAMEWORK key is always set at startup; if it is ever
        # removed, the helper must fail closed to the direct peer rather
        # than trusting the header (DRF's legacy None branch trusts it).
        rest_framework = {
            key: value
            for key, value in dj_settings.REST_FRAMEWORK.items()
            if key != "NUM_PROXIES"
        }
        with override_settings(REST_FRAMEWORK=rest_framework):
            self.assertEqual(client_ip(self.request(xff="198.51.100.1")), "192.0.2.10")


class ClientIpThrottleAgreementTests(SimpleTestCase):
    """client_ip() must agree with DRF's throttle identity on valid addresses.

    Both read the same effective ``REST_FRAMEWORK["NUM_PROXIES"]`` setting,
    so overriding only that key must move them together.
    """

    class AgreementThrottle(SimpleRateThrottle):
        scope = "client_ip_agreement"
        THROTTLE_RATES = {"client_ip_agreement": "100/hour"}

    def setUp(self):
        self.factory = RequestFactory()
        self.throttle = self.AgreementThrottle()

    def request(self):
        return self.factory.get(
            "/",
            REMOTE_ADDR="10.0.0.1",
            HTTP_X_FORWARDED_FOR="192.0.2.1, 203.0.113.7, 198.51.100.5",
        )

    def test_zero_hops_uses_remote_addr(self):
        with trusted_proxies(0):
            request = self.request()
            self.assertEqual(client_ip(request), "10.0.0.1")
            self.assertEqual(self.throttle.get_ident(request), "10.0.0.1")

    def test_one_hop_selects_rightmost_entry(self):
        with trusted_proxies(1):
            request = self.request()
            self.assertEqual(client_ip(request), "198.51.100.5")
            self.assertEqual(self.throttle.get_ident(request), "198.51.100.5")

    def test_two_hops_selects_second_from_right(self):
        with trusted_proxies(2):
            request = self.request()
            self.assertEqual(client_ip(request), "203.0.113.7")
            self.assertEqual(self.throttle.get_ident(request), "203.0.113.7")


class AuditMiddlewareIpTests(SimpleTestCase):
    """The middleware must persist the helper's selection, not the raw header."""

    def middleware_request(self, remote_addr="192.0.2.10", xff=None):
        factory = RequestFactory()
        extra = {"REMOTE_ADDR": remote_addr}
        if xff is not None:
            extra["HTTP_X_FORWARDED_FOR"] = xff
        request = factory.get("/", **extra)
        middleware = AuditRequestContextMiddleware(get_response=lambda r: r)
        return middleware(request)

    def test_middleware_stores_trusted_hop(self):
        with trusted_proxies(1):
            request = self.middleware_request(
                remote_addr="10.0.0.1", xff="192.0.2.1, 203.0.113.7"
            )
            self.assertEqual(request.audit_ip_address, "203.0.113.7")

    def test_middleware_stores_none_for_malformed_xff(self):
        with trusted_proxies(1):
            request = self.middleware_request(xff="not an ip")
            self.assertIsNone(request.audit_ip_address)


class AuditIpPersistenceTests(TestCase):
    """Malformed XFF must persist as NULL, not fail the audit write."""

    def test_malformed_xff_persists_null(self):
        factory = RequestFactory()
        request = factory.get(
            "/", REMOTE_ADDR="192.0.2.10", HTTP_X_FORWARDED_FOR="not an ip"
        )
        with trusted_proxies(1):
            request.audit_ip_address = client_ip(request)
            request.audit_request_id = "test-request"
            request.audit_user_agent = "test"
            request.audit_source = "api"
        event = record_audit_event(
            action_category=AuditActionCategory.SYSTEM,
            action_type="system.test",
            target_type="system.Event",
            summary="test",
            request=request,
        )
        self.assertIsNone(event.ip_address)
