from __future__ import annotations

from datetime import date as date_type

from .base import Tool, ToolContext, ToolError
from ._util import kwh

_MAX_SPAN_DAYS = 400


class ConsumptionProfileTool(Tool):
    name = "consumption_profile"
    title = "Consumption profile (average day)"
    description = (
        "A participant's average 24-hour consumption profile over a date range, "
        "split per hour into energy from the ZEV (local solar) and from the grid. "
        "Use it for questions like 'when is consumption highest' or 'how much of "
        "the evening load is covered by solar'. Needs a participant_id from "
        "list_participants."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "zev_id": {"type": "string", "format": "uuid"},
            "participant_id": {"type": "string", "format": "uuid"},
            "date_from": {"type": "string", "format": "date"},
            "date_to": {"type": "string", "format": "date"},
        },
        "required": ["zev_id", "participant_id", "date_from", "date_to"],
        "additionalProperties": False,
    }
    allowed_url_names = frozenset({"meterreading-hourly-profile"})

    def run(self, ctx: ToolContext, arguments: dict) -> dict:
        date_from = date_type.fromisoformat(arguments["date_from"])
        date_to = date_type.fromisoformat(arguments["date_to"])
        if date_to < date_from:
            raise ToolError("date_to must be on or after date_from.")
        if (date_to - date_from).days + 1 > _MAX_SPAN_DAYS:
            raise ToolError(f"date_from/date_to may span at most {_MAX_SPAN_DAYS} days.")

        data = ctx.get_or_raise(
            "/api/v1/metering/readings/hourly-profile/",
            {
                "zev_id": arguments["zev_id"],
                "participant_id": arguments["participant_id"],
                "date_from": arguments["date_from"],
                "date_to": arguments["date_to"],
            },
            allowed_url_names=self.allowed_url_names,
        ).data

        result: dict = {
            "zev_id": arguments["zev_id"],
            "participant_id": arguments["participant_id"],
            "date_from": arguments["date_from"],
            "date_to": arguments["date_to"],
        }

        # ``hourly_profile: None`` means the participant holds no metering
        # point with readings in the range — say so rather than returning
        # 24 zero rows that read as "consumes nothing".
        profile = data.get("hourly_profile")
        if not profile:
            result["profile"] = None
            result["note"] = "No consumption readings for this participant in the date range."
            return result

        rows = []
        for entry in profile:
            from_zev = float(entry.get("from_zev_kwh") or 0)
            from_grid = float(entry.get("from_grid_kwh") or 0)
            rows.append(
                {
                    "hour": entry["hour"],
                    "from_zev_kwh": kwh(from_zev),
                    "from_grid_kwh": kwh(from_grid),
                    "total_kwh": kwh(from_zev + from_grid),
                }
            )

        daily_zev = sum(float(e.get("from_zev_kwh") or 0) for e in profile)
        daily_total = daily_zev + sum(float(e.get("from_grid_kwh") or 0) for e in profile)
        peak = max(rows, key=lambda r: r["total_kwh"])

        result.update(
            {
                "profile": rows,
                "average_daily_kwh": kwh(daily_total),
                "average_daily_from_zev_kwh": kwh(daily_zev),
                "local_share_pct": round(100 * daily_zev / daily_total, 1) if daily_total else None,
                "peak_hour": peak["hour"] if daily_total else None,
            }
        )
        return result
