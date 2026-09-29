from __future__ import annotations

import re
from datetime import date, timedelta

from .base import Tool, ToolContext

# Matches meter-id-shaped tokens inside a free-text error/warning message
# (e.g. "meter CH-DEMO2-UNKNOWN-9 not found ..."): upper-case alnum segments
# joined by dashes, with at least one dash — good enough for the demo/real
# meter-id conventions in this codebase (``metering/importers``) without
# parsing each importer's own message templates.
_METER_ID_RE = re.compile(r"\b[A-Z0-9]+(?:-[A-Z0-9]+){2,}\b")


def _dedupe_capped(messages: list[str], limit: int) -> list[str]:
    seen: list[str] = []
    for message in messages:
        if message not in seen:
            seen.append(message)
        if len(seen) >= limit:
            break
    return seen


def _extract_meter_ids(messages: list[str]) -> list[str]:
    found: list[str] = []
    for message in messages:
        for match in _METER_ID_RE.findall(message):
            if match not in found:
                found.append(match)
    return found


class ImportTriageTool(Tool):
    name = "import_triage"
    title = "Import triage"
    description = "Summarise recent metering imports and what went wrong in them."
    input_schema = {
        "type": "object",
        "properties": {
            "zev_id": {"type": "string", "format": "uuid"},
            "since": {"type": "string", "format": "date"},
            "only_problems": {"type": "boolean", "default": True},
            "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 10},
        },
        "additionalProperties": False,
    }
    allowed_url_names = frozenset({"importlog-list"})

    def run(self, ctx: ToolContext, arguments: dict) -> dict:
        zev_id = arguments.get("zev_id")
        only_problems = arguments.get("only_problems", True)
        limit = arguments.get("limit", 10)
        since_raw = arguments.get("since")
        since = date.fromisoformat(since_raw) if since_raw else date.today() - timedelta(days=30)

        # ImportLogViewSet has no zev_id query filter (SPEC-2026-mcp-server
        # §6.5 — the endpoint does not support it), so scoping to one ZEV and
        # the "only recent" window both happen on the returned rows.
        rows, _, _ = ctx.get_all(
            "/api/v1/metering/import-logs/",
            {},
            allowed_url_names=self.allowed_url_names,
            max_pages=5,
        )

        filtered = []
        for row in rows:
            # ``row["zev"]`` is the raw FK value from the (un-rendered)
            # sub-response — a ``uuid.UUID`` instance, not the string the
            # real HTTP JSON would carry — so it is stringified before
            # comparing against the string argument.
            row_zev_id = row.get("zev")
            if zev_id and (row_zev_id is None or str(row_zev_id) != zev_id):
                continue
            created_at = row.get("created_at") or ""
            if created_at[:10] < since.isoformat():
                continue
            if only_problems and not (row.get("errors") or row.get("warnings") or row.get("rows_skipped")):
                continue
            filtered.append(row)

        # Newest first — the endpoint already orders by -created_at
        # (ImportLog.Meta), preserved through filtering.
        truncated = len(filtered) > limit
        page = filtered[:limit]

        imports = []
        for row in page:
            errors = row.get("errors") or []
            warnings = row.get("warnings") or []
            imports.append({
                "id": row["id"],
                "created_at": row.get("created_at"),
                "zev_name": row.get("zev_name", ""),
                "source": row.get("source"),
                "filename": row.get("filename", ""),
                "imported_by": row.get("imported_by_display", ""),
                "rows_total": row.get("rows_total"),
                "rows_imported": row.get("rows_imported"),
                "rows_overwritten": row.get("rows_overwritten"),
                "rows_skipped": row.get("rows_skipped"),
                "error_count": len(errors),
                "warning_count": len(warnings),
                "errors": _dedupe_capped(errors, 10),
                "warnings": _dedupe_capped(warnings, 10),
                "metering_points": _extract_meter_ids(errors + warnings),
            })

        totals = {
            "imports": len(filtered),
            "with_errors": sum(1 for row in filtered if row.get("errors")),
            "with_warnings": sum(1 for row in filtered if row.get("warnings")),
            "rows_skipped": sum(row.get("rows_skipped") or 0 for row in filtered),
        }

        result = {"imports": imports, "totals": totals}
        if truncated:
            result["truncated"] = True
        return result
