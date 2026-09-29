from __future__ import annotations

from datetime import date as date_type

from .base import Tool, ToolContext, ToolError
from ._util import kwh

_MAX_SPAN_DAYS = 400
_MAX_DAY_BUCKETS = 31
_MAX_MONTH_BUCKETS = 14
# Hourly buckets are only offered for short spans: a week of hours is enough
# to answer "what happened on Tuesday", and anything finer stays out of MCP
# (SPEC-2026-mcp-server §2 — no raw 15-minute data).
_MAX_HOUR_SPAN_DAYS = 7
_MAX_HOUR_BUCKETS = _MAX_HOUR_SPAN_DAYS * 24
_MAX_PARTICIPANTS = 50


def _series_entry(item: dict) -> dict:
    return {
        "bucket": item.get("bucket"),
        "consumed_kwh": kwh(item.get("consumed_kwh")),
        "produced_kwh": kwh(item.get("produced_kwh")),
        "imported_kwh": kwh(item.get("imported_kwh")),
        "exported_kwh": kwh(item.get("exported_kwh")),
    }


def _participant_entry(item: dict) -> dict:
    consumed = float(item.get("total_consumed_kwh") or 0)
    from_zev = float(item.get("from_zev_kwh") or 0)
    return {
        # FK-free: the analytics layer already builds these as strings.
        "participant_id": str(item.get("participant_id")),
        "participant_name": item.get("participant_name", ""),
        "consumed_kwh": kwh(consumed),
        "from_zev_kwh": kwh(from_zev),
        "from_grid_kwh": kwh(item.get("from_grid_kwh")),
        "produced_kwh": kwh(item.get("total_produced_kwh")),
        "local_share_pct": round(100 * from_zev / consumed, 1) if consumed else None,
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
        "over a date range, bucketed by month, day, or hour (hour only for spans "
        "of up to 7 days). Without participant_id the result also breaks the "
        "ZEV down per participant (consumption, from ZEV, from grid, local "
        "share), largest consumer first; with participant_id the totals and "
        "series are that participant's."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "zev_id": {"type": "string", "format": "uuid"},
            "date_from": {"type": "string", "format": "date"},
            "date_to": {"type": "string", "format": "date"},
            "bucket": {"type": "string", "enum": ["hour", "day", "month"], "default": "month"},
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
        if bucket == "hour" and (date_to - date_from).days + 1 > _MAX_HOUR_SPAN_DAYS:
            raise ToolError(f"bucket 'hour' is only available for spans of up to {_MAX_HOUR_SPAN_DAYS} days.")
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
        cap = {"hour": _MAX_HOUR_BUCKETS, "day": _MAX_DAY_BUCKETS}.get(bucket, _MAX_MONTH_BUCKETS)
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
            result["participant_id"] = str(data["selected_participant_id"])
            result["participant_name"] = data.get("selected_participant_name")
            if result["participant_name"] is None:
                # The analytics layer only swaps in the participant's own
                # totals/timeline when the participant has readings in the
                # range; otherwise it silently leaves the ZEV-wide figures in
                # place. Passing those on under this participant's id would
                # attribute the whole ZEV's consumption to them.
                result["totals"] = _totals({})
                result["series"] = []
                result["note"] = "No readings attributed to this participant in the date range."
                return result
        else:
            stats = data.get("participant_stats") or []
            result["participants"] = [_participant_entry(item) for item in stats[:_MAX_PARTICIPANTS]]
            if len(stats) > _MAX_PARTICIPANTS:
                result["participants_truncated"] = True
                result["participants_total"] = len(stats)
        if len(timeline) > cap:
            result["truncated"] = True
        return result
