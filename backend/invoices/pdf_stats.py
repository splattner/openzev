"""Invoice PDF statistics — savings, period stats, and energy summary computations."""

import datetime as _dt
from decimal import Decimal

from allocation.read_model import (
    CONSUMPTION,
    PRODUCTION,
    community_totals_by_timestamp,
    iter_allocated_readings,
)
from allocation.windows import AssignmentWindows
from metering.analytics import _participant_names

from .engine import _period_to_dt


def _build_savings_data(invoice, tr: dict) -> dict | None:
    """Compute how much the participant saved by consuming local ZEV energy vs grid.

    Returns a dict with display-ready strings, or None if savings cannot be computed
    (e.g. no local energy, no grid energy, or local rate >= grid rate).
    """
    from .models import InvoiceItem

    local_kwh = float(invoice.total_local_kwh)
    grid_kwh = float(invoice.total_grid_kwh)

    if local_kwh <= 0 or grid_kwh <= 0:
        return None

    items = list(invoice.items.all())
    local_items = [i for i in items if i.item_type == InvoiceItem.ItemType.LOCAL_ENERGY]
    grid_items = [i for i in items if i.item_type == InvoiceItem.ItemType.GRID_ENERGY]

    local_chf = sum(float(i.total_chf) for i in local_items)
    grid_chf = sum(float(i.total_chf) for i in grid_items)

    if local_chf <= 0 or grid_chf <= 0:
        return None

    avg_local_rp = local_chf / local_kwh * 100
    avg_grid_rp = grid_chf / grid_kwh * 100

    if avg_local_rp >= avg_grid_rp:
        return None  # no savings (local tariff not cheaper than grid)

    hypothetical_chf = local_kwh * avg_grid_rp / 100
    saved_chf = hypothetical_chf - local_chf
    savings_bar_pct = round(saved_chf / hypothetical_chf * 100, 1) if hypothetical_chf > 0 else 0
    bar_pct = round(100 - savings_bar_pct, 1)

    return {
        "local_kwh": f"{local_kwh:.2f}",
        "local_chf": f"{local_chf:.2f}",
        "local_rp": f"{avg_local_rp:.2f}",
        "grid_rp": f"{avg_grid_rp:.2f}",
        "saved_rp": f"{avg_grid_rp - avg_local_rp:.2f}",
        "hypothetical_chf": f"{hypothetical_chf:.2f}",
        "saved_chf": f"{saved_chf:.2f}",
        "bar_pct": str(bar_pct),
        "savings_bar_pct": str(savings_bar_pct),
    }


def _compute_period_participant_stats(invoice) -> tuple[dict, list[dict]]:
    """Compute ZEV-level totals and per-participant energy stats for the invoice
    period, using the same local-pool allocation logic as the dashboard.

    Returns (totals, participant_stats) where:
      totals = {produced_kwh, consumed_kwh, imported_kwh, exported_kwh}
      participant_stats = [{participant_id, participant_name, total_consumed_kwh,
                            total_produced_kwh, from_zev_kwh, from_grid_kwh}, ...]
    """
    zev = invoice.zev
    ps = invoice.period_start
    pe = invoice.period_end
    start_dt = _period_to_dt(ps)
    end_dt = _period_to_dt(pe) + _dt.timedelta(days=1)

    # Physical per-timestamp community totals — every meter in the ZEV
    # regardless of assignment (ADR 0013): unassigned meters still feed the
    # community pool, even though their readings are billed to nobody.
    # Attribution to participants happens per timestamp below.
    cons_by_ts, prod_by_ts = community_totals_by_timestamp(zev, start_dt, end_dt)

    totals = {"produced_kwh": Decimal("0"), "consumed_kwh": Decimal("0"),
              "imported_kwh": Decimal("0"), "exported_kwh": Decimal("0")}
    all_ts = set(cons_by_ts) | set(prod_by_ts)
    for ts in all_ts:
        c = cons_by_ts.get(ts, Decimal("0"))
        p = prod_by_ts.get(ts, Decimal("0"))
        totals["consumed_kwh"] += c
        totals["produced_kwh"] += p
        totals["imported_kwh"] += max(c - p, Decimal("0"))
        totals["exported_kwh"] += max(p - c, Decimal("0"))

    # Per-participant consumption with local-pool allocation (ADR 0013): each
    # reading is attributed to the holder active at its timestamp — a
    # period-level join would fan out every reading across every assignment
    # overlapping the period and double-count transfers. Readings in an
    # assignment gap (holder None) belong to no participant.
    windows = AssignmentWindows.for_zev(zev, ps, pe)

    # Names are keyed off the assignment windows, not the current participant
    # list: the invoice is a historical document, and a holder who has since
    # left the ZEV must keep their name in the period stats.
    participant_names = _participant_names(windows.participant_ids)


    participant_map: dict[str, dict] = {}

    def _entry(pid: str) -> dict:
        if pid not in participant_map:
            participant_map[pid] = {
                "participant_id": pid,
                "participant_name": participant_names.get(pid, ""),
                "total_consumed_kwh": Decimal("0"),
                "total_produced_kwh": Decimal("0"),
                "from_zev_kwh": Decimal("0"),
                "from_grid_kwh": Decimal("0"),
            }
        return participant_map[pid]

    for reading in iter_allocated_readings(
        zev, start_dt, end_dt, kind=CONSUMPTION, windows=windows,
        consumption_by_ts=cons_by_ts, production_by_ts=prod_by_ts,
    ):
        if reading.holder_id is None:
            continue
        entry = _entry(str(reading.holder_id))
        entry["total_consumed_kwh"] += reading.energy_kwh
        entry["from_zev_kwh"] += reading.split.local_kwh
        entry["from_grid_kwh"] += reading.split.grid_kwh

    # Per-participant production, attributed the same way. The PDF only reports
    # each participant's total production, so the split is not needed here —
    # with_split=False skips split_production (and its fail-fast non-negative
    # contract) for every community reading, so a corrupt production meter
    # (a meter correction with a negative energy_kwh) is attributed to its
    # holder instead of making the PDF unrenderable for the whole ZEV.
    for reading in iter_allocated_readings(
        zev, start_dt, end_dt, kind=PRODUCTION, windows=windows,
        consumption_by_ts=cons_by_ts, production_by_ts=prod_by_ts,
        with_split=False,
    ):
        if reading.holder_id is None:
            continue
        _entry(str(reading.holder_id))["total_produced_kwh"] += reading.energy_kwh

    float_totals = {k: float(v) for k, v in totals.items()}
    stats = sorted(
        [
            {
                "participant_id": v["participant_id"],
                "participant_name": v["participant_name"],
                "total_consumed_kwh": float(v["total_consumed_kwh"]),
                "total_produced_kwh": float(v["total_produced_kwh"]),
                "from_zev_kwh": float(v["from_zev_kwh"]),
                "from_grid_kwh": float(v["from_grid_kwh"]),
            }
            for v in participant_map.values()
        ],
        key=lambda x: x["total_consumed_kwh"],
        reverse=True,
    )
    return float_totals, stats


def _build_energy_summary(invoice) -> dict | None:
    """Compact KPI values for the insights page header."""
    local_kwh = float(invoice.total_local_kwh or 0)
    grid_kwh = float(invoice.total_grid_kwh or 0)
    total = local_kwh + grid_kwh
    if total <= 0:
        return None
    share = (local_kwh / total) * 100
    return {
        "local_kwh": f"{local_kwh:.1f}",
        "grid_kwh": f"{grid_kwh:.1f}",
        "total_kwh": f"{total:.1f}",
        "local_share_pct": f"{share:.0f}",
    }
