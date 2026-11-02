"""Coverage for the in-process sub-request plumbing (mcp_server/dispatch.py,
ADR 0025 §2)."""

from __future__ import annotations

import pytest
from django.core.cache import cache
from django.http import HttpRequest
from unittest.mock import patch

from accounts.throttling import ApiKeyRateThrottle
from mcp_server.dispatch import DispatchError, SubResponse, dispatch_get
from mcp_server.tools.base import ToolContext, ToolError
from testing.factories import ZevFactory

from .conftest import make_api_key

pytestmark = pytest.mark.django_db


def _outer_request(user, api_key):
    request = HttpRequest()
    request.method = "POST"
    request.path = "/api/v1/mcp/"
    request.META["REMOTE_ADDR"] = "127.0.0.1"
    request._force_auth_user = user
    request._force_auth_token = api_key
    request.audit_request_id = "11111111-1111-4111-8111-111111111111"
    request.audit_ip_address = "127.0.0.1"
    request.audit_user_agent = "pytest"
    return request


class TestAllowList:
    def test_refuses_a_url_not_on_the_allow_list(self, owner_user):
        api_key, _ = make_api_key(owner_user)
        outer = _outer_request(owner_user, api_key)
        with pytest.raises(DispatchError):
            dispatch_get(
                outer,
                "/api/v1/auth/users/",
                {},
                allowed_url_names=frozenset({"zev-list"}),
                api_key=api_key,
                user=owner_user,
            )

    def test_allows_a_url_on_the_allow_list(self, zev, owner_user):
        api_key, _ = make_api_key(owner_user)
        outer = _outer_request(owner_user, api_key)
        sub = dispatch_get(
            outer,
            "/api/v1/zev/zevs/",
            {},
            allowed_url_names=frozenset({"zev-list"}),
            api_key=api_key,
            user=owner_user,
        )
        assert sub.status == 200


class TestForcedAuth:
    def test_subrequest_runs_as_the_forced_user_and_is_marked_mcp(self, owner_user):
        zev = ZevFactory(owner=owner_user)
        api_key, _ = make_api_key(owner_user)
        outer = _outer_request(owner_user, api_key)
        sub = dispatch_get(
            outer,
            "/api/v1/zev/zevs/",
            {},
            allowed_url_names=frozenset({"zev-list"}),
            api_key=api_key,
            user=owner_user,
        )
        ids = {row["id"] for row in sub.data["results"]}
        assert str(zev.id) in ids


class TestThrottleSkip:
    def setup_method(self):
        cache.clear()

    def teardown_method(self):
        cache.clear()

    def test_mcp_subrequest_is_not_throttled(self, owner_user, settings):
        """``ApiKeyRateThrottle`` returns no cache key for a sub-request
        (accounts/throttling.py), so a tool that fans out to several REST
        views spends only the throttle hit the outer MCP call already paid.
        """
        api_key, _ = make_api_key(owner_user)
        drf_request = type("R", (), {"auth": api_key, "mcp_subrequest": True})()

        throttle = ApiKeyRateThrottle()
        assert throttle.get_cache_key(drf_request, view=None) is None

    def test_a_normal_api_key_request_is_throttled(self, owner_user):
        api_key, _ = make_api_key(owner_user)
        drf_request = type("R", (), {"auth": api_key})()
        throttle = ApiKeyRateThrottle()
        assert throttle.get_cache_key(drf_request, view=None) is not None


@pytest.mark.parametrize("status", [403, 429, 500])
@pytest.mark.parametrize("failed_page", [1, 2])
def test_failed_page_raises_tool_error(owner_user, status, failed_page):
    api_key, _ = make_api_key(owner_user)
    ctx = ToolContext(_outer_request(owner_user, api_key), owner_user, api_key)
    responses = [SubResponse(200, {"results": [{"id": "first"}], "count": 2, "next": "page2"})] * (failed_page - 1)
    responses.append(SubResponse(status, {"detail": "Cannot read this page"}))
    with patch("mcp_server.dispatch.dispatch_get", side_effect=responses):
        with pytest.raises(ToolError, match="Cannot read this page") as error:
            ctx.get_all("/api/v1/audit/events/", allowed_url_names=frozenset({"audit-event-list"}))
    assert error.value.status == ("denied" if status == 403 else "failed")


@pytest.mark.parametrize("data", [{"count": 1}, []])
@pytest.mark.parametrize("failed_page", [1, 2])
def test_malformed_page_raises_tool_error(owner_user, data, failed_page):
    api_key, _ = make_api_key(owner_user)
    ctx = ToolContext(_outer_request(owner_user, api_key), owner_user, api_key)
    responses = [SubResponse(200, {"results": [{"id": "first"}], "count": 2, "next": "page2"})] * (failed_page - 1)
    responses.append(SubResponse(200, data))
    with patch("mcp_server.dispatch.dispatch_get", side_effect=responses):
        with pytest.raises(ToolError, match="Expected a paginated response") as error:
            ctx.get_all("/api/v1/audit/events/", allowed_url_names=frozenset({"audit-event-list"}))
    assert error.value.status == "failed"


class TestHostPropagation:
    def test_subrequest_resolves_the_outer_host_and_scheme(self):
        from mcp_server.dispatch import _build_request

        outer = HttpRequest()
        outer.META.update(
            SERVER_NAME="wsgi-internal",
            HTTP_HOST="testserver",
            HTTP_X_FORWARDED_HOST="zev.example.ch",
            HTTP_X_FORWARDED_PROTO="https",
            HTTP_X_FORWARDED_PORT="443",
        )

        request = _build_request(outer, "/api/v1/invoices/invoices/", {})

        assert request.get_host() == "testserver"
        for key in ("HTTP_X_FORWARDED_HOST", "HTTP_X_FORWARDED_PROTO", "HTTP_X_FORWARDED_PORT"):
            assert request.META[key] == outer.META[key]
        assert request.build_absolute_uri("/x/") == "http://testserver/x/"
