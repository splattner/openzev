"""Transport-level coverage for POST /api/v1/mcp/ (SPEC-2026-mcp-server §5)."""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from accounts.models import FeatureFlag
from testing.factories import ParticipantUserFactory

from .conftest import MCP_URL, client_for, call_tool, rpc

pytestmark = pytest.mark.django_db


class TestFeatureFlagGate:
    def test_flag_off_is_404_even_unauthenticated(self, db):
        FeatureFlag.objects.update_or_create(
            name=FeatureFlag.MCP_SERVER_ENABLED, defaults={"enabled": False}
        )
        response = APIClient().post(MCP_URL, {"jsonrpc": "2.0", "id": 1, "method": "ping"}, format="json")
        assert response.status_code == 404

    def test_flag_off_is_404_even_for_a_valid_key(self, admin_user):
        FeatureFlag.objects.update_or_create(
            name=FeatureFlag.MCP_SERVER_ENABLED, defaults={"enabled": False}
        )
        client = client_for(admin_user)
        response = rpc(client, "ping")
        assert response.status_code == 404


class TestMethodNotAllowed:
    def test_get_is_405(self, admin_mcp_client):
        response = admin_mcp_client.get(MCP_URL)
        assert response.status_code == 405
        assert response["Allow"] == "POST"

    def test_delete_is_405(self, admin_mcp_client):
        response = admin_mcp_client.delete(MCP_URL)
        assert response.status_code == 405


class TestAuthentication:
    def test_no_credentials_is_401_with_bearer_challenge(self, db):
        response = APIClient().post(MCP_URL, {"jsonrpc": "2.0", "id": 1, "method": "ping"}, format="json")
        assert response.status_code == 401
        assert "Bearer" in response["WWW-Authenticate"]

    def test_cookie_jwt_alone_is_not_accepted(self, db, owner_user):
        """Only the API-key scheme is wired up (``McpApiKeyAuthentication`` is
        the endpoint's only authentication class); a bearer JWT is a
        different credential shape and reads as no credential at all here.
        """
        from rest_framework_simplejwt.tokens import RefreshToken

        client = APIClient()
        token = RefreshToken.for_user(owner_user).access_token
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        response = rpc(client, "ping")
        assert response.status_code == 401

    def test_api_key_scheme_is_accepted(self, admin_user):
        client = client_for(admin_user, scheme="Api-Key")
        response = rpc(client, "ping")
        assert response.status_code == 200

    def test_bearer_scheme_is_accepted(self, admin_user):
        client = client_for(admin_user, scheme="Bearer")
        response = rpc(client, "ping")
        assert response.status_code == 200

    def test_revoked_key_is_401(self, admin_user):
        from django.utils import timezone

        client = APIClient()
        from .conftest import make_api_key

        api_key, raw_key = make_api_key(admin_user)
        api_key.revoked_at = timezone.now()
        api_key.save(update_fields=["revoked_at"])
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw_key}")
        response = rpc(client, "ping")
        assert response.status_code == 401

    def test_expired_key_is_401(self, admin_user):
        from datetime import timedelta

        from django.utils import timezone

        from .conftest import make_api_key

        client = APIClient()
        api_key, raw_key = make_api_key(admin_user)
        api_key.expires_at = timezone.now() - timedelta(days=1)
        api_key.save(update_fields=["expires_at"])
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw_key}")
        response = rpc(client, "ping")
        assert response.status_code == 401


class TestRole:
    def test_participant_is_403(self, db):
        participant = ParticipantUserFactory()
        client = client_for(participant)
        response = rpc(client, "ping")
        assert response.status_code == 403

    def test_admin_is_allowed(self, admin_mcp_client):
        assert rpc(admin_mcp_client, "ping").status_code == 200

    def test_owner_is_allowed(self, owner_mcp_client):
        assert rpc(owner_mcp_client, "ping").status_code == 200


class TestOrigin:
    def test_untrusted_origin_is_403(self, admin_user):
        client = client_for(admin_user)
        response = client.post(
            MCP_URL,
            {"jsonrpc": "2.0", "id": 1, "method": "ping"},
            format="json",
            HTTP_ORIGIN="https://evil.example",
        )
        assert response.status_code == 403

    def test_no_origin_header_passes(self, admin_mcp_client):
        assert rpc(admin_mcp_client, "ping").status_code == 200

    def test_trusted_origin_passes(self, admin_user, settings):
        settings.CORS_ALLOWED_ORIGINS = ["https://trusted.example"]
        client = client_for(admin_user)
        response = client.post(
            MCP_URL,
            {"jsonrpc": "2.0", "id": 1, "method": "ping"},
            format="json",
            HTTP_ORIGIN="https://trusted.example",
        )
        assert response.status_code == 200


class TestBodyParsing:
    def test_malformed_json_is_parse_error(self, admin_user):
        client = client_for(admin_user)
        response = client.post(MCP_URL, data="not json", content_type="application/json")
        assert response.status_code == 400
        body = response.json()
        assert body["error"]["code"] == -32700

    def test_non_object_message_is_invalid_request(self, admin_mcp_client):
        response = admin_mcp_client.post(MCP_URL, data="42", content_type="application/json")
        assert response.status_code == 200
        assert response.json()["error"]["code"] == -32600

    def test_unknown_method_is_method_not_found(self, admin_mcp_client):
        response = rpc(admin_mcp_client, "nope/nope")
        assert response.status_code == 200
        assert response.json()["error"]["code"] == -32601


class TestBatch:
    def test_mixed_request_and_notification(self, admin_mcp_client):
        response = admin_mcp_client.post(
            MCP_URL,
            [
                {"jsonrpc": "2.0", "id": 1, "method": "ping"},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
            ],
            format="json",
        )
        assert response.status_code == 200
        body = response.json()
        assert isinstance(body, list)
        assert len(body) == 1
        assert body[0]["id"] == 1

    def test_batch_over_ten_is_rejected(self, admin_mcp_client):
        batch = [{"jsonrpc": "2.0", "id": i, "method": "ping"} for i in range(11)]
        response = admin_mcp_client.post(MCP_URL, batch, format="json")
        assert response.status_code == 200
        assert response.json()["error"]["code"] == -32600

    def test_notification_only_is_202_with_empty_body(self, admin_mcp_client):
        response = admin_mcp_client.post(
            MCP_URL,
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            format="json",
        )
        assert response.status_code == 202
        assert response.content == b""


class TestInitialize:
    def test_negotiates_requested_supported_version(self, admin_mcp_client):
        response = rpc(admin_mcp_client, "initialize", {"protocolVersion": "2025-03-26"})
        result = response.json()["result"]
        assert result["protocolVersion"] == "2025-03-26"
        assert result["capabilities"] == {"tools": {"listChanged": False}}
        assert result["serverInfo"]["name"] == "openzev"

    def test_unsupported_version_falls_back_to_preferred(self, admin_mcp_client):
        response = rpc(admin_mcp_client, "initialize", {"protocolVersion": "1999-01-01"})
        assert response.json()["result"]["protocolVersion"] == "2025-06-18"


class TestPing:
    def test_ping_returns_empty_object(self, admin_mcp_client):
        response = rpc(admin_mcp_client, "ping")
        assert response.json()["result"] == {}


class TestToolsList:
    def test_lists_all_nine_tools_read_only(self, admin_mcp_client):
        response = rpc(admin_mcp_client, "tools/list")
        tools = response.json()["result"]["tools"]
        names = {t["name"] for t in tools}
        assert names == {
            "list_zevs", "list_participants", "period_readiness", "find_invoices", "explain_invoice",
            "import_triage", "consumption_summary", "data_gaps", "audit_query",
        }
        assert all(t["annotations"]["readOnlyHint"] is True for t in tools)


class TestToolsCall:
    def test_unknown_tool_is_invalid_params(self, admin_mcp_client):
        response = call_tool(admin_mcp_client, "does_not_exist")
        assert response.json()["error"]["code"] == -32602

    def test_invalid_arguments_is_invalid_params_with_errors(self, admin_mcp_client):
        response = call_tool(admin_mcp_client, "list_zevs", {"unexpected": True})
        body = response.json()
        assert body["error"]["code"] == -32602
        assert body["error"]["data"]["errors"]
