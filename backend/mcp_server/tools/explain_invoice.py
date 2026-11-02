from __future__ import annotations

from datetime import date as date_type

from .base import Tool, ToolContext
from ._util import chf, kwh


def _invoice_block(data: dict) -> dict:
    block = {
        "id": data["id"],
        "invoice_number": data.get("invoice_number", ""),
        "participant_name": data.get("participant_name", ""),
        "period_start": data.get("period_start"),
        "period_end": data.get("period_end"),
        "status": data.get("status"),
        "subtotal_chf": chf(data.get("subtotal_chf")),
        "vat_chf": chf(data.get("vat_chf")),
        # 5-Rappen rounding inside the total, and of the amount due after credit.
        "rounding_chf": chf(data.get("rounding_chf")),
        "total_chf": chf(data.get("total_chf")),
        "credit_applied_chf": chf(data.get("credit_applied_chf")),
        "due_rounding_chf": chf(data.get("due_rounding_chf")),
        "amount_due_chf": chf(data.get("amount_due_chf")),
        "paid_chf": chf(data.get("paid_chf")),
        "outstanding_chf": chf(data.get("outstanding_chf")),
        # Credit notes set against this invoice, and credit notes issued for it.
        "credits_applied": [
            {
                "credit_number": application.get("credit_number"),
                "amount_chf": chf(application.get("amount_chf")),
                "released": application.get("released_at") is not None,
            }
            for application in data.get("credit_applications") or []
        ],
        "credits_issued": [
            {
                "credit_number": credit.get("credit_number"),
                "kind": credit.get("kind"),
                "amount_chf": chf(credit.get("amount_chf")),
                "remaining_chf": chf(credit.get("remaining_chf")),
                "status": credit.get("status"),
            }
            for credit in data.get("credits") or []
        ],
    }
    if data.get("vat_rate") is not None:
        block["vat_rate"] = data["vat_rate"]
    if data.get("vat_base_chf") is not None:
        block["vat_base_chf"] = chf(data["vat_base_chf"])
    return block


def _lines(data: dict) -> list[dict]:
    lines = []
    for item in data.get("items", []):
        unit = item.get("unit") or "kWh"
        line = {
            "type": item.get("item_type"),
            "description": item.get("description", ""),
            # The quantity is in ``unit``: kWh for energy lines, months for
            # fee lines. ``quantity_kwh`` is only set when it really is kWh.
            "quantity": kwh(item.get("quantity_kwh")),
            "unit": unit,
            "unit_price": item.get("unit_price_chf"),
            "amount_chf": chf(item.get("total_chf")),
        }
        if unit == "kWh":
            line["quantity_kwh"] = line["quantity"]
        lines.append(line)
    return lines


# Energy per item type comes from the invoice totals, never from adding up the
# lines: energy, grid use and each levy are separate lines over the same kWh,
# and fee lines carry months. Types not listed here (fee, credit, other) have
# no kWh figure.
_TYPE_KWH_TOTAL = {
    "local_energy": "total_local_kwh",
    "grid_energy": "total_grid_kwh",
    "feed_in": "total_feed_in_kwh",
}


def _by_type(data: dict) -> dict:
    amounts: dict[str, float] = {}
    for item in data.get("items", []):
        item_type = item.get("item_type") or "other"
        amounts[item_type] = amounts.get(item_type, 0.0) + float(item.get("total_chf") or 0)
    by_type: dict[str, dict] = {}
    for item_type, amount in amounts.items():
        entry: dict = {"amount_chf": f"{amount:.2f}"}
        total_field = _TYPE_KWH_TOTAL.get(item_type)
        if total_field:
            entry["kwh"] = round(float(data.get(total_field) or 0), 3)
            if item_type == "local_energy":
                # A producer's sale inside the ZEV is credited on the same
                # type; keep its kWh apart from what the participant bought.
                sold = float(data.get("total_local_sold_kwh") or 0)
                if sold:
                    entry["sold_kwh"] = round(sold, 3)
        by_type[item_type] = entry
    return by_type


def _energy(data: dict) -> dict:
    local = float(data.get("total_local_kwh") or 0)
    grid = float(data.get("total_grid_kwh") or 0)
    feed_in = data.get("total_feed_in_kwh")
    denom = local + grid
    energy = {
        "local_kwh": round(local, 3),
        "grid_kwh": round(grid, 3),
        "local_share_pct": round(100 * local / denom, 1) if denom else None,
    }
    if feed_in is not None:
        energy["feed_in_kwh"] = round(float(feed_in), 3)
    return energy


class ExplainInvoiceTool(Tool):
    name = "explain_invoice"
    title = "Explain invoice"
    description = (
        "Break down one invoice into its line items and energy split, and "
        "compare it with the same participant's previous invoice."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "invoice_id": {"type": "string", "format": "uuid"},
            "compare_previous": {"type": "boolean", "default": True},
        },
        "required": ["invoice_id"],
        "additionalProperties": False,
    }
    allowed_url_names = frozenset({"invoice-list", "invoice-detail"})

    def run(self, ctx: ToolContext, arguments: dict) -> dict:
        invoice_id = arguments["invoice_id"]
        compare_previous = arguments.get("compare_previous", True)

        data = ctx.get_or_raise(
            f"/api/v1/invoices/invoices/{invoice_id}/", None, allowed_url_names=self.allowed_url_names
        ).data

        result = {
            "invoice": _invoice_block(data),
            "lines": _lines(data),
            "by_type": _by_type(data),
            "energy": _energy(data),
            "previous": None,
            "change": None,
        }

        if not compare_previous:
            return result

        previous = self._find_previous(ctx, data)
        if previous is None:
            return result

        result["previous"] = _invoice_block(previous)
        result["change"] = self._change(data, previous)
        return result

    def _find_previous(self, ctx: ToolContext, data: dict) -> dict | None:
        # "zev"/"participant" are relation (FK) fields — the un-rendered
        # sub-response leaves them as raw ``uuid.UUID`` objects rather than
        # the strings the real HTTP JSON would carry.
        params = {
            "zev_id": str(data["zev"]) if data.get("zev") is not None else None,
            "participant_id": str(data["participant"]) if data.get("participant") is not None else None,
            "period_to": data.get("period_start"),
        }
        rows, _, _ = ctx.get_all(
            "/api/v1/invoices/invoices/",
            params,
            allowed_url_names=self.allowed_url_names,
            max_pages=3,
            limit=10,
        )
        this_start = data.get("period_start")
        for row in rows:
            # ``period_to`` already narrows to period_end <= this period_start
            # server-side; still exclude same-day and cancelled rows here.
            if row["id"] == data["id"]:
                continue
            if row.get("status") == "cancelled":
                continue
            if row.get("period_end") is not None and this_start is not None and row["period_end"] >= this_start:
                continue
            # Rows come back newest-period-first (Invoice.Meta.ordering); the
            # first surviving row is the most recent prior invoice.
            detail = ctx.get_or_raise(
                f"/api/v1/invoices/invoices/{row['id']}/", None, allowed_url_names=self.allowed_url_names
            ).data
            return detail
        return None

    @staticmethod
    def _change(current: dict, previous: dict) -> dict:
        cur_total = float(current.get("total_chf") or 0)
        prev_total = float(previous.get("total_chf") or 0)
        total_delta = cur_total - prev_total
        total_pct = round(100 * total_delta / prev_total, 1) if prev_total else None

        cur_by_type = _by_type(current)
        prev_by_type = _by_type(previous)
        by_type_change = {}
        for item_type in set(cur_by_type) | set(prev_by_type):
            cur = cur_by_type.get(item_type, {"amount_chf": "0.00"})
            prev = prev_by_type.get(item_type, {"amount_chf": "0.00"})
            delta = {"amount_delta_chf": f"{float(cur['amount_chf']) - float(prev['amount_chf']):.2f}"}
            for key in ("kwh", "sold_kwh"):
                if key in cur or key in prev:
                    delta[f"{key}_delta"] = round(cur.get(key, 0.0) - prev.get(key, 0.0), 3)
            by_type_change[item_type] = delta

        def _days(inv: dict) -> int | None:
            start, end = inv.get("period_start"), inv.get("period_end")
            if not start or not end:
                return None
            return (date_type.fromisoformat(end) - date_type.fromisoformat(start)).days + 1

        return {
            "total_chf": f"{total_delta:.2f}",
            "total_pct": total_pct,
            "by_type": by_type_change,
            "days_in_period": [_days(current), _days(previous)],
        }
