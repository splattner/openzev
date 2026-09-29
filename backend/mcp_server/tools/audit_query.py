from __future__ import annotations

from .base import Tool, ToolContext

_ACTION_CATEGORIES = [
    "auth", "governance", "participant", "metering", "tariff",
    "invoice", "import", "template", "system",
]
_EVENT_STATUSES = ["started", "queued", "success", "failed", "denied"]


def _event(row: dict) -> dict:
    event = {
        "id": row.get("id"),
        "created_at": row.get("created_at"),
        "actor": row.get("actor_display", ""),
        "source": row.get("source"),
        "action_category": row.get("action_category"),
        "action_type": row.get("action_type"),
        "status": row.get("status"),
        "target_type": row.get("target_type"),
        "target_display": row.get("target_display", ""),
        "summary": row.get("summary", ""),
    }
    changes = row.get("changes_json")
    if changes:
        event["changes"] = changes
    return event


class AuditQueryTool(Tool):
    name = "audit_query"
    title = "Audit query"
    description = (
        "Filtered audit events within the caller's scope — who did what, "
        "when. `q` free-text search is not available through MCP; use the "
        "structured filters."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "zev_id": {"type": "string", "format": "uuid"},
            "action_category": {"type": "string", "enum": _ACTION_CATEGORIES},
            "action_type": {"type": "string"},
            "target_type": {"type": "string"},
            "target_id": {"type": "string"},
            "status": {"type": "string", "enum": _EVENT_STATUSES},
            "date_from": {"type": "string", "format": "date"},
            "date_to": {"type": "string", "format": "date"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20},
        },
        "additionalProperties": False,
    }
    allowed_url_names = frozenset({"audit-event-list"})

    def run(self, ctx: ToolContext, arguments: dict) -> dict:
        limit = arguments.get("limit", 20)
        params = {}
        if arguments.get("zev_id"):
            params["zev"] = arguments["zev_id"]
        for key in ("action_category", "action_type", "target_type", "target_id", "status", "date_from", "date_to"):
            if arguments.get(key):
                params[key] = arguments[key]

        rows, truncated, total = ctx.get_all(
            "/api/v1/audit/events/",
            params,
            allowed_url_names=self.allowed_url_names,
            max_pages=5,
            limit=limit,
        )

        result = {"events": [_event(row) for row in rows]}
        if truncated:
            result["truncated"] = True
            if total is not None:
                result["total"] = total
        return result
