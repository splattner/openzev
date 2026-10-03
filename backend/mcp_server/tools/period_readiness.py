from __future__ import annotations

from .base import Tool, ToolContext

_LINK_KEYS = {"link", "assignment_link", "billing_settings_link", "issuer_link"}

# Steps whose status means "not done yet" — mirrors
# ``invoices.readiness._select_next_action``'s own definition of blocking.
_BLOCKING_STATUSES = {"warn", "todo"}


def _drop_links(value):
    if isinstance(value, dict):
        return {k: _drop_links(v) for k, v in value.items() if k not in _LINK_KEYS}
    if isinstance(value, list):
        return [_drop_links(v) for v in value]
    return value


def _blocking_entries(steps: list[dict]) -> list[str]:
    entries = []
    for step in steps:
        if step.get("status") in _BLOCKING_STATUSES:
            detail = step.get("detail") or step.get("status")
            entries.append(f"{step['key']}: {detail}")
    return entries


class PeriodReadinessTool(Tool):
    name = "period_readiness"
    title = "Period readiness"
    description = (
        "Check whether a ZEV's billing period can be billed, and what is "
        "blocking it (missing metering data, unresolved assignments, tariffs, "
        "unapproved or unsent invoices, ...). Without period_start/period_end, "
        "the cockpit's currently-relevant period is used."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "zev_id": {"type": "string", "format": "uuid"},
            "period_start": {"type": "string", "format": "date"},
            "period_end": {"type": "string", "format": "date"},
        },
        "required": ["zev_id"],
        "additionalProperties": False,
        # Enforced again defensively in run(); jsonschema's dependentRequired
        # keeps "one but not the other" out before the sub-request even runs.
        "dependentRequired": {"period_start": ["period_end"], "period_end": ["period_start"]},
    }
    allowed_url_names = frozenset({"invoice-readiness", "invoice-attention"})

    def run(self, ctx: ToolContext, arguments: dict) -> dict:
        zev_id = arguments["zev_id"]
        params = {"zev_id": zev_id}
        if arguments.get("period_start"):
            params["period_start"] = arguments["period_start"]
            params["period_end"] = arguments["period_end"]

        readiness = ctx.get_or_raise(
            "/api/v1/invoices/invoices/readiness/", params, allowed_url_names=self.allowed_url_names
        ).data
        attention = ctx.get_or_raise(
            "/api/v1/invoices/invoices/attention/", {"zev_id": zev_id}, allowed_url_names=self.allowed_url_names
        ).data

        period = readiness.get("period")
        steps = [_drop_links(step) for step in readiness.get("steps", [])]
        items = attention.get("items", [])
        capped_items = [_drop_links(item) for item in items[:20]]

        result = {
            "zev_id": readiness.get("zev_id", zev_id),
            "period": period,
            "next_action": readiness.get("next_action", "none"),
            "steps": steps,
            "blocking": _blocking_entries(steps),
            "attention": capped_items,
        }
        if len(items) > 20:
            result["attention_truncated"] = True

        # "period: null" responses carry their own reason (setup /
        # awaiting_first_period / caught_up) — pass those through unchanged
        # (spec §6.2) rather than re-deriving them.
        for key in ("setup", "awaiting_first_period", "caught_up"):
            if key in readiness:
                result[key] = _drop_links(readiness[key])

        return result
