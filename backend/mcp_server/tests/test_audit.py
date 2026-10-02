"""``mcp.tool.call`` audit coverage (SPEC-2026-mcp-server §8)."""

from __future__ import annotations

import uuid

import pytest

from audit.models import AuditEvent, AuditEventSource, AuditEventStatus
from testing.factories import ZevFactory

from .conftest import call_tool, rpc

pytestmark = pytest.mark.django_db


class TestToolCallAudit:
    def test_successful_call_is_recorded(self, zev, owner_mcp_client):
        call_tool(owner_mcp_client, "list_zevs")

        event = AuditEvent.objects.get(action_type="mcp.tool.call")
        assert event.source == AuditEventSource.MCP
        assert event.status == AuditEventStatus.SUCCESS
        assert event.target_type == "mcp.Tool"
        assert event.target_id == "list_zevs"
        assert event.metadata_json["tool"] == "list_zevs"
        assert "api_key_prefix" in event.metadata_json
        assert "duration_ms" in event.metadata_json
        assert "subrequests" in event.metadata_json

    def test_zev_id_argument_is_attached_when_visible(self, owner_mcp_client, owner_user):
        zev = ZevFactory(owner=owner_user)
        call_tool(owner_mcp_client, "period_readiness", {"zev_id": str(zev.id)})

        event = AuditEvent.objects.filter(action_type="mcp.tool.call").latest("created_at")
        assert event.zev_id == zev.id

    def test_zev_not_visible_to_caller_is_not_attached(self, zev, owner_mcp_client, owner_user):
        other_owner_zev = ZevFactory()  # a different owner
        call_tool(owner_mcp_client, "period_readiness", {"zev_id": str(other_owner_zev.id)})

        event = AuditEvent.objects.filter(action_type="mcp.tool.call").latest("created_at")
        assert event.zev_id is None
        # The tool call itself still resolves to isError, not a leak.
        assert event.status == AuditEventStatus.DENIED

    def test_failed_tool_call_is_recorded_as_denied_or_failed(self, zev, owner_mcp_client, owner_user):
        call_tool(owner_mcp_client, "explain_invoice", {"invoice_id": str(uuid.uuid4())})
        event = AuditEvent.objects.filter(action_type="mcp.tool.call").latest("created_at")
        assert event.status in (AuditEventStatus.FAILED, AuditEventStatus.DENIED)

    def test_tools_list_does_not_write_an_audit_event(self, owner_mcp_client):
        rpc(owner_mcp_client, "tools/list")
        assert not AuditEvent.objects.filter(action_type="mcp.tool.call").exists()

    def test_initialize_does_not_write_an_audit_event(self, owner_mcp_client):
        rpc(owner_mcp_client, "initialize")
        assert not AuditEvent.objects.filter(action_type="mcp.tool.call").exists()
