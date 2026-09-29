from __future__ import annotations

from datetime import date

from .base import Tool, ToolContext


def _active_on(valid_from, valid_to, day: str) -> bool:
    # ISO ``YYYY-MM-DD`` strings compare correctly as strings.
    return (valid_from is None or valid_from <= day) and (valid_to is None or valid_to >= day)


class ListParticipantsTool(Tool):
    name = "list_participants"
    title = "List participants"
    description = (
        "List the participants of a ZEV with their validity and metering-point "
        "assignments. Use it to find a participant_id for consumption_summary or "
        "find_invoices, or to see who is assigned to which meter. Contact details "
        "(email, phone, address, IBAN) are deliberately not returned."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "zev_id": {"type": "string", "format": "uuid"},
            "query": {"type": "string", "minLength": 1},
            "active_on": {"type": "string", "format": "date"},
            "include_inactive": {"type": "boolean", "default": False},
            "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 50},
        },
        "required": ["zev_id"],
        "additionalProperties": False,
    }
    allowed_url_names = frozenset({"zev-detail", "participant-list", "meteringpointassignment-list"})

    def run(self, ctx: ToolContext, arguments: dict) -> dict:
        zev_id = arguments["zev_id"]
        limit = arguments.get("limit", 50)

        # The participant list answers an empty page for a ZEV the caller
        # cannot see (scoping narrows, it never errors), which would read as
        # "no participants". Ask the ZEV detail first so a foreign or unknown
        # ZEV surfaces the view's own 403/404 message instead.
        ctx.get_or_raise(f"/api/v1/zev/zevs/{zev_id}/", allowed_url_names=self.allowed_url_names)

        participants, p_truncated, _ = ctx.get_all(
            "/api/v1/zev/participants/",
            {"zev_id": zev_id},
            allowed_url_names=self.allowed_url_names,
            max_pages=5,
        )
        assignments, a_truncated, _ = ctx.get_all(
            "/api/v1/zev/metering-point-assignments/",
            {"zev_id": zev_id},
            allowed_url_names=self.allowed_url_names,
            max_pages=10,
        )

        day = None
        if not arguments.get("include_inactive"):
            day = arguments.get("active_on") or date.today().isoformat()

        by_participant: dict[str, list[dict]] = {}
        for row in assignments:
            # FK values are raw ``uuid.UUID`` in an un-rendered sub-response
            # (spec §7) — stringify before comparing or returning them.
            by_participant.setdefault(str(row["participant"]), []).append(row)

        query = (arguments.get("query") or "").strip().lower()
        out = []
        for row in participants:
            if query and query not in (row.get("full_name") or "").lower():
                continue
            if day is not None and not _active_on(row.get("valid_from"), row.get("valid_to"), day):
                continue
            meters = {str(mp["id"]): mp for mp in row.get("metering_points") or []}
            out.append(
                {
                    "id": str(row["id"]),
                    "full_name": row.get("full_name", ""),
                    "valid_from": row.get("valid_from"),
                    "valid_to": row.get("valid_to"),
                    "has_account": row.get("user") is not None,
                    "onboarding_status": row.get("onboarding_status"),
                    "metering_points": [
                        {
                            "meter_id": meters.get(str(a["metering_point"]), {}).get("meter_id"),
                            "meter_type": meters.get(str(a["metering_point"]), {}).get("meter_type"),
                            "valid_from": a.get("valid_from"),
                            "valid_to": a.get("valid_to"),
                        }
                        for a in sorted(
                            by_participant.get(str(row["id"]), []),
                            key=lambda a: a.get("valid_from") or "",
                        )
                    ],
                }
            )

        out.sort(key=lambda p: p["full_name"].lower())
        total = len(out)
        result: dict = {"participants": out[:limit]}
        if total > limit or p_truncated or a_truncated:
            result["truncated"] = True
            result["total"] = total
        if day is not None:
            result["active_on"] = day
        return result

