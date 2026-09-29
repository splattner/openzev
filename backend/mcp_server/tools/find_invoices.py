from __future__ import annotations

from .base import Tool, ToolContext
from ._util import chf

# InvoiceStatus.values (invoices/models.py) — kept as a literal list rather
# than importing the model, to keep this module free of ORM imports (only
# the plumbing in mcp_server/dispatch.py touches Django models directly).
_INVOICE_STATUSES = ["draft", "approved", "sent", "paid", "cancelled"]


def _row(item: dict) -> dict:
    # "id" is a UUIDField DRF explicitly stringifies; "participant" is a
    # relation (FK) field, which the un-rendered sub-response leaves as a
    # raw ``uuid.UUID`` — stringified here rather than relying on the final
    # HTTP JSON renderer to do it for us.
    participant_id = item.get("participant")
    return {
        "id": item["id"],
        "invoice_number": item.get("invoice_number", ""),
        "participant_id": str(participant_id) if participant_id is not None else None,
        "participant_name": item.get("participant_name", ""),
        "period_start": item.get("period_start"),
        "period_end": item.get("period_end"),
        "status": item.get("status"),
        "total_chf": chf(item.get("total_chf")),
    }


class FindInvoicesTool(Tool):
    name = "find_invoices"
    title = "Find invoices"
    description = (
        "Locate invoices for a ZEV, narrowed by participant (participant_id from "
        "list_participants, or a name substring), period or status — use this "
        "before explain_invoice to find an invoice id."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "zev_id": {"type": "string", "format": "uuid"},
            "participant_id": {"type": "string", "format": "uuid"},
            "participant_query": {"type": "string", "minLength": 1},
            "period_start": {"type": "string", "format": "date"},
            "period_end": {"type": "string", "format": "date"},
            "status": {"type": "string", "enum": _INVOICE_STATUSES},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20},
        },
        "required": ["zev_id"],
        "additionalProperties": False,
    }
    allowed_url_names = frozenset({"invoice-list", "invoice-detail"})

    def run(self, ctx: ToolContext, arguments: dict) -> dict:
        limit = arguments.get("limit", 20)
        params: dict = {"zev_id": arguments["zev_id"]}
        if arguments.get("participant_id"):
            params["participant_id"] = arguments["participant_id"]
        if arguments.get("status"):
            params["status"] = arguments["status"]
        if arguments.get("period_start"):
            params["period_from"] = arguments["period_start"]
        if arguments.get("period_end"):
            params["period_to"] = arguments["period_end"]

        # participant_id and period_start/period_end narrow server-side (the
        # filters added to InvoiceViewSet). A participant *name* has no REST
        # filter, so participant_query fetches without a limit, filters the
        # rows here, and caps after.
        fetch_limit = None if arguments.get("participant_query") else limit
        rows, truncated, total = ctx.get_all(
            "/api/v1/invoices/invoices/",
            params,
            allowed_url_names=self.allowed_url_names,
            max_pages=10,
            limit=fetch_limit,
        )

        query = (arguments.get("participant_query") or "").strip().lower()
        if query:
            rows = [r for r in rows if query in (r.get("participant_name") or "").lower()]
            total = None
            if len(rows) > limit:
                rows = rows[:limit]
                truncated = True
            else:
                truncated = False

        result = {"invoices": [_row(r) for r in rows]}
        if truncated:
            result["truncated"] = True
            if total is not None:
                result["total"] = total
        return result
