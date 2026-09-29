from __future__ import annotations

from datetime import date as date_type

from .base import Tool, ToolContext, ToolError
from ._util import kwh

_MAX_SPAN_DAYS = 400
_MAX_DAY_BUCKETS = 31
_MAX_MONTH_BUCKETS = 14


def _series_entry(item: dict) -> dict:
    return {
        "bucket": item.get("bucket"),
        "consumed_kwh": kwh(item.get("consumed_kwh")),
        "produced_kwh": kwh(item.get("produced_kwh")),
        "imported_kwh": kwh(item.get("imported_kwh")),
        "exported_kwh": kwh(item.get("exported_kwh")),
    }


def _totals(totals: dict) -> dict:
    consumed = float(totals.get("consumed_kwh") or 0)
    produced = float(totals.get("produced_kwh") or 0)
    imported = float(totals.get("imported_kwh") or 0)
    self_consumed = consumed - imported

    out = {
        "consumed_kwh": kwh(consumed),
        "produced_kwh": kwh(produced),
        "imported_kwh": kwh(imported),
        "exported_kwh": kwh(totals.get("exported_kwh")),
        "self_consumed_kwh": kwh(self_consumed),
        "self_consumption_pct": round(100 * self_consumed / produced, 1) if produced else None,
        "self_sufficiency_pct": round(100 * self_consumed / consumed, 1) if consumed else None,
    }
    return out


class ConsumptionSummaryTool(Tool):
    name = "consumption_summary"
    title = "Consumption summary"
    description = (
        "Aggregated consumption, production and self-consumption for a ZEV "
        "over a date range, bucketed by day or month."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "zev_id": {"type": "string", "format": "uuid"},
            "date_from": {"type": "string", "format": "date"},
            "date_to": {"type": "string", "format": "date"},
            "bucket": {"type": "string", "enum": ["day", "month"], "default": "month"},
            "participant_id": {"type": "string", "format": "uuid"},
        },
        "required": ["zev_id", "date_from", "date_to"],
        "additionalProperties": False,
    }
    allowed_url_names = frozenset({"meterreading-dashboard-summary"})

    def run(self, ctx: ToolContext, arguments: dict) -> dict:
        date_from = date_type.fromisoformat(arguments["date_from"])
        date_to = date_type.fromisoformat(arguments["date_to"])
        if date_to < date_from:
            raise ToolError("date_to must be on or after date_from.")
        if (date_to - date_from).days + 1 > _MAX_SPAN_DAYS:
            raise ToolError(f"date_from/date_to may span at most {_MAX_SPAN_DAYS} days.")

        bucket = arguments.get("bucket", "month")
        params = {
            "zev_id": arguments["zev_id"],
            "date_from": arguments["date_from"],
            "date_to": arguments["date_to"],
            "bucket": bucket,
        }
        if arguments.get("participant_id"):
            params["participant_id"] = arguments["participant_id"]

        data = ctx.get_or_raise(
            "/api/v1/metering/readings/dashboard-summary/", params, allowed_url_names=self.allowed_url_names
        ).data

        timeline = data.get("timeline", [])
        cap = _MAX_DAY_BUCKETS if bucket == "day" else _MAX_MONTH_BUCKETS
        series = [_series_entry(item) for item in timeline[:cap]]

        result = {
            "zev_id": arguments["zev_id"],
            "date_from": arguments["date_from"],
            "date_to": arguments["date_to"],
            "bucket": bucket,
            "totals": _totals(data.get("totals", {})),
            "series": series,
        }
        if data.get("selected_participant_id"):
            result["participant_id"] = data["selected_participant_id"]
            result["participant_name"] = data.get("selected_participant_name")
        if len(timeline) > cap:
            result["truncated"] = True
        return result
