from __future__ import annotations

from datetime import datetime, timezone as dt_timezone

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from ..dispatch import sub_error_message
from .base import Tool, ToolContext, ToolError

# Cap on the per-metering-point rows, as for the other list-shaped tools.
_MAX_POINTS = 100
_DEFAULT_FORECAST_HOURS = 24
_MAX_FORECAST_HOURS = 72

# What each tier allows to say (SPEC-2026-live-energy-data §5.2, ADR 0044). The note is returned with the
# figures so a model does not fill the gap the tier leaves with a guess.
_TIER_NOTES = {
    "none": (
        "Not every producing plant reports live data, so no figure is stated. Only the forecast is shown."
    ),
    "production": (
        "Production is known; the other participants' current use is not known, so spare power and the local "
        "share cannot be stated."
    ),
    "exact": (
        "Production and consumption are both measured, so spare power and the local share are exact. "
        "Indicative only: never billing input."
    ),
}


def _kw(watts) -> float | None:
    return None if watts is None else round(float(watts) / 1000, 3)


def _moment(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    return parse_datetime(value)


def _iso(value) -> str | None:
    moment = _moment(value)
    return None if moment is None else moment.astimezone(dt_timezone.utc).isoformat().replace("+00:00", "Z")


class LiveEnergyTool(Tool):
    name = "live_energy"
    title = "Live energy now and production forecast"
    description = (
        "What a ZEV produces and uses right now, from the live sources its participants and managers have "
        "connected, plus the expected production for the coming hours. Power is in kW. The ZEV figures are "
        "measured, never estimated: 'tier' says what is known. 'none' means not every producing plant reports, "
        "so there are no figures; 'production' means only the ZEV's production is known (consumption, spare "
        "power and local share are null); 'exact' also gives consumption, spare power, grid import and the "
        "local share. Values older than max_age_s count as missing. Per metering point, 'live_state' says "
        "whether it reports. The forecast is production only (never a claim that power is spare) and carries "
        "peak windows per day. Indicative figures only, never billing input; for settled energy use "
        "consumption_summary. Needs a zev_id from list_zevs. Answers with an error while the live feature is "
        "switched off."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "zev_id": {"type": "string", "format": "uuid"},
            "forecast_hours": {
                "type": "integer",
                "minimum": 0,
                "maximum": _MAX_FORECAST_HOURS,
                "description": (
                    f"Hourly forecast values to return from the current hour on (default {_DEFAULT_FORECAST_HOURS}, "
                    "0 for the peak windows only)."
                ),
            },
        },
        "required": ["zev_id"],
        "additionalProperties": False,
    }
    allowed_url_names = frozenset({"live-snapshot", "live-forecast"})

    def run(self, ctx: ToolContext, arguments: dict) -> dict:
        zev_id = arguments["zev_id"]
        hours = arguments.get("forecast_hours", _DEFAULT_FORECAST_HOURS)

        snapshot = self._get(ctx, f"/api/v1/metering/live/zevs/{zev_id}/")
        forecast = self._get(ctx, f"/api/v1/metering/live/zevs/{zev_id}/forecast/")

        tier = snapshot["tier"]
        result: dict = {
            "zev_id": snapshot.get("zev_id", zev_id),
            "tier": tier,
            "note": _TIER_NOTES.get(tier, ""),
            "as_of": snapshot.get("as_of"),
            "max_age_s": snapshot.get("max_age_s"),
            "consumption_basis": snapshot.get("consumption_basis"),
            "production_kw": _kw(snapshot.get("production_w")),
            "consumption_kw": _kw(snapshot.get("consumption_w")),
            "surplus_kw": _kw(snapshot.get("surplus_w")),
            "grid_import_kw": _kw(snapshot.get("grid_import_w")),
            "local_share_pct": snapshot.get("local_share_pct"),
            "coverage": snapshot.get("coverage"),
        }

        points = snapshot.get("points") or []
        result["points"] = [
            {
                "meter_id": point.get("meter_id"),
                "target": point.get("target"),
                "meter_type": point.get("meter_type"),
                "participant_name": point.get("participant_name"),
                "held_by": point.get("held_by"),
                "live_state": point.get("live_state"),
                # Signed like the meter: negative while feeding in.
                "meter_power_kw": _kw(point.get("meter_power_w")),
                "age_s": point.get("age_s"),
            }
            for point in points[:_MAX_POINTS]
        ]
        if len(points) > _MAX_POINTS:
            result["points_truncated"] = True
            result["points_total"] = len(points)

        result["forecast"] = self._forecast(forecast, hours)
        return result

    def _get(self, ctx: ToolContext, path: str) -> dict:
        sub = ctx.get(path, allowed_url_names=self.allowed_url_names)
        if sub.status == 404:
            # The live API answers 404 for a switched-off feature as well as for a ZEV the caller may not see.
            raise ToolError("Live energy data is not available: the feature is switched off, or the ZEV was not found.")
        if sub.status >= 300:
            raise ToolError(sub_error_message(sub), status="denied" if sub.status == 403 else "failed")
        return sub.data

    @staticmethod
    def _forecast(data: dict, hours: int) -> dict:
        start = timezone.now().astimezone(dt_timezone.utc).replace(minute=0, second=0, microsecond=0)
        upcoming = [
            row for row in data.get("hours") or []
            if (moment := _moment(row["start"])) is not None and moment >= start
        ][:hours]
        return {
            "complete": data.get("complete"),
            "plants": data.get("plants"),
            "plants_with_forecast": data.get("plants_with_forecast"),
            "fetched_at": _iso(data.get("fetched_at")),
            "note": (
                "Expected production only, by the hour starting at 'start' (UTC); not a statement that power "
                "is spare."
            ),
            "hours": [
                {
                    "start": _iso(row["start"]),
                    "power_kw": _kw(row.get("power_w")),
                    "min_kw": _kw(row.get("min_w")),
                    "max_kw": _kw(row.get("max_w")),
                }
                for row in upcoming
            ],
            "peak_windows": [
                {
                    "date": window["date"],
                    "from": _iso(window["from"]),
                    "to": _iso(window["to"]),
                    "peak_kw": _kw(window.get("peak_w")),
                }
                for window in data.get("peak_windows") or []
                if (_moment(window["to"]) or start) > start
            ],
        }
