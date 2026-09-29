from __future__ import annotations

from .base import Tool, ToolContext

_MAX_POINTS = 50
_MAX_GAPS = 10


def _point(row: dict) -> dict:
    gaps = [
        {"from": gap.get("start_date"), "to": gap.get("end_date")}
        for gap in (row.get("gaps") or [])[:_MAX_GAPS]
    ]
    point = {
        "id": row.get("id"),
        "meter_id": row.get("meter_id"),
        "completeness_pct": row.get("data_completeness"),
        "missing_days": row.get("total_days", 0) - row.get("days_with_data", 0),
        "gaps": gaps,
    }
    if row.get("participant_name"):
        point["participant"] = row["participant_name"]
    return point


class DataGapsTool(Tool):
    name = "data_gaps"
    title = "Data gaps"
    description = "Which metering points in a ZEV have missing readings, and where."
    input_schema = {
        "type": "object",
        "properties": {
            "zev_id": {"type": "string", "format": "uuid"},
            "date_from": {"type": "string", "format": "date"},
            "date_to": {"type": "string", "format": "date"},
            "only_incomplete": {"type": "boolean", "default": True},
        },
        "required": ["zev_id"],
        "additionalProperties": False,
    }
    allowed_url_names = frozenset({"meterreading-data-quality-status"})

    def run(self, ctx: ToolContext, arguments: dict) -> dict:
        only_incomplete = arguments.get("only_incomplete", True)
        params = {"zev_id": arguments["zev_id"]}
        if arguments.get("date_from"):
            params["date_from"] = arguments["date_from"]
        if arguments.get("date_to"):
            params["date_to"] = arguments["date_to"]

        data = ctx.get_or_raise(
            "/api/v1/metering/readings/data-quality-status/", params, allowed_url_names=self.allowed_url_names
        ).data

        rows = data.get("metering_points", [])
        if only_incomplete:
            rows = [r for r in rows if r.get("data_completeness", 100) < 100]

        truncated = len(rows) > _MAX_POINTS
        points = [_point(row) for row in rows[:_MAX_POINTS]]

        result = {"metering_points": points}
        if truncated:
            result["truncated"] = True
        return result
