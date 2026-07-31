"""Invoice PDF statistics — savings, period stats, and energy summary computations."""

import datetime as _dt
from decimal import Decimal

from django.db import models as _dj

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
    from metering.models import MeterReading, ReadingDirection
    from zev.models import MeteringPoint as _MP
    from zev.models import MeteringPointType as _MPT

    zev = invoice.zev
    ps = invoice.period_start
    pe = invoice.period_end
    start_dt = _period_to_dt(ps)
    end_dt = _period_to_dt(pe) + _dt.timedelta(days=1)

    # All metering points in this ZEV
    cons_mps = _MP.objects.filter(
        zev=zev,
        meter_type__in=[_MPT.CONSUMPTION, _MPT.BIDIRECTIONAL],
        assignments__valid_from__lte=pe,
    ).filter(
        _dj.Q(assignments__valid_to__isnull=True) | _dj.Q(assignments__valid_to__gte=ps)
    ).distinct()

    prod_mps = _MP.objects.filter(
        zev=zev,
        meter_type__in=[_MPT.PRODUCTION, _MPT.BIDIRECTIONAL],
        assignments__valid_from__lte=pe,
    ).filter(
        _dj.Q(assignments__valid_to__isnull=True) | _dj.Q(assignments__valid_to__gte=ps)
    ).distinct()

    # ZEV-level aggregation by timestamp
    cons_by_ts: dict[_dt.datetime, Decimal] = {}
    prod_by_ts: dict[_dt.datetime, Decimal] = {}

    for row in (
        MeterReading.objects.filter(
            metering_point__in=cons_mps,
            timestamp__gte=start_dt, timestamp__lt=end_dt,
            direction=ReadingDirection.IN,
        ).values("timestamp").annotate(total=_dj.Sum("energy_kwh"))
    ):
        cons_by_ts[row["timestamp"]] = row["total"] or Decimal("0")

    for row in (
        MeterReading.objects.filter(
            metering_point__in=prod_mps,
            timestamp__gte=start_dt, timestamp__lt=end_dt,
            direction=ReadingDirection.OUT,
        ).values("timestamp").annotate(total=_dj.Sum("energy_kwh"))
    ):
        prod_by_ts[row["timestamp"]] = row["total"] or Decimal("0")

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

    # Per-participant consumption with local-pool allocation
    participant_rows = (
        MeterReading.objects.filter(
            metering_point__in=cons_mps,
            timestamp__gte=start_dt, timestamp__lt=end_dt,
            direction=ReadingDirection.IN,
        ).values(
            "metering_point__assignments__participant_id",
            "metering_point__assignments__participant__first_name",
            "metering_point__assignments__participant__last_name",
            "timestamp",
        ).annotate(consumed_kwh=_dj.Sum("energy_kwh"))
    )

    participant_map: dict[str, dict] = {}
    for row in participant_rows:
        pid = str(row["metering_point__assignments__participant_id"])
        ts = row["timestamp"]
        consumed = row["consumed_kwh"] or Decimal("0")
        total_consumed = cons_by_ts.get(ts, Decimal("0"))
        total_produced = prod_by_ts.get(ts, Decimal("0"))
        local_pool = min(total_produced, total_consumed)

        if total_consumed > 0 and local_pool > 0:
            from_zev = min(consumed, local_pool * (consumed / total_consumed))
        else:
            from_zev = Decimal("0")
        from_grid = max(consumed - from_zev, Decimal("0"))

        if pid not in participant_map:
            participant_map[pid] = {
                "participant_id": pid,
                "participant_name": (
                    f"{row['metering_point__assignments__participant__first_name']} "
                    f"{row['metering_point__assignments__participant__last_name']}"
                ).strip(),
                "total_consumed_kwh": Decimal("0"),
                "total_produced_kwh": Decimal("0"),
                "from_zev_kwh": Decimal("0"),
                "from_grid_kwh": Decimal("0"),
            }
        participant_map[pid]["total_consumed_kwh"] += consumed
        participant_map[pid]["from_zev_kwh"] += from_zev
        participant_map[pid]["from_grid_kwh"] += from_grid

    # Per-participant production
    prod_rows = (
        MeterReading.objects.filter(
            metering_point__in=prod_mps,
            timestamp__gte=start_dt, timestamp__lt=end_dt,
            direction=ReadingDirection.OUT,
        ).values(
            "metering_point__assignments__participant_id",
            "metering_point__assignments__participant__first_name",
            "metering_point__assignments__participant__last_name",
        ).annotate(produced_kwh=_dj.Sum("energy_kwh"))
    )
    for row in prod_rows:
        pid = str(row["metering_point__assignments__participant_id"])
        if pid not in participant_map:
            participant_map[pid] = {
                "participant_id": pid,
                "participant_name": (
                    f"{row['metering_point__assignments__participant__first_name']} "
                    f"{row['metering_point__assignments__participant__last_name']}"
                ).strip(),
                "total_consumed_kwh": Decimal("0"),
                "total_produced_kwh": Decimal("0"),
                "from_zev_kwh": Decimal("0"),
                "from_grid_kwh": Decimal("0"),
            }
        participant_map[pid]["total_produced_kwh"] += (row["produced_kwh"] or Decimal("0"))

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
