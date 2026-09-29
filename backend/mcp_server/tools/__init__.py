"""The MCP tool registry (SPEC-2026-mcp-server §6).

Each tool is a small adapter over one or more allow-listed REST GET
endpoints (``mcp_server/dispatch.py``); none of them query the ORM directly.
"""

from __future__ import annotations

from .audit_query import AuditQueryTool
from .base import Tool, ToolContext, ToolError
from .consumption_summary import ConsumptionSummaryTool
from .data_gaps import DataGapsTool
from .explain_invoice import ExplainInvoiceTool
from .find_invoices import FindInvoicesTool
from .import_triage import ImportTriageTool
from .list_participants import ListParticipantsTool
from .list_zevs import ListZevsTool
from .period_readiness import PeriodReadinessTool

TOOLS: dict[str, Tool] = {
    tool.name: tool
    for tool in (
        ListZevsTool(),
        ListParticipantsTool(),
        PeriodReadinessTool(),
        FindInvoicesTool(),
        ExplainInvoiceTool(),
        ImportTriageTool(),
        ConsumptionSummaryTool(),
        DataGapsTool(),
        AuditQueryTool(),
    )
}

__all__ = ["TOOLS", "Tool", "ToolContext", "ToolError"]
