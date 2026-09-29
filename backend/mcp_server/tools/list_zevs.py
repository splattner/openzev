from __future__ import annotations

from .base import Tool, ToolContext


class ListZevsTool(Tool):
    name = "list_zevs"
    title = "List ZEVs"
    description = (
        "Find the ZEVs (energy communities) the caller can see. Call this first "
        "to find a zev_id for the other tools."
    )
    input_schema = {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }
    allowed_url_names = frozenset({"zev-list"})

    def run(self, ctx: ToolContext, arguments: dict) -> dict:
        rows, truncated, total = ctx.get_all(
            "/api/v1/zev/zevs/",
            {},
            allowed_url_names=self.allowed_url_names,
            max_pages=2,  # PAGE_SIZE 50 * 2 comfortably covers the cap below
            limit=100,
        )
        zevs = [
            {
                "id": row["id"],
                "name": row["name"],
                "billing_interval": row["billing_interval"],
                "start_date": row["start_date"],
                "is_disabled": row.get("disabled_at") is not None,
            }
            for row in rows
        ]
        result = {"zevs": zevs}
        if truncated:
            result["truncated"] = True
            result["total"] = total
        return result
