"""Invoice PDF SVG chart builders — energy flow, comparison, and hourly profile."""

import logging

from .engine import _period_to_dt
from .pdf_stats import _compute_period_participant_stats

logger = logging.getLogger(__name__)

# Shared palette for SVG charts — matches the invoice template brand.
_CHART_LOCAL = "#1f5c3a"
_CHART_GRID = "#c9891a"
_CHART_INK = "#0f172a"
_CHART_MUTED = "#64748b"
_CHART_GRIDLINE = "#e8edeb"
_CHART_AXIS = "#94a3b8"
_CHART_BG = "#fbfcfb"
_CHART_LABEL = "#334155"

# Flow-diagram-specific colors not covered by the chart palette.
_FLOW_LOCAL_CONS = "#0e7490"
_FLOW_GRID_EXP = "#7c3aed"

# Approximate pixel width per character at 7.5pt font — used for legend layout.
_PX_PER_CHAR = 4.2


def _legend_offsets(ml: int, tr: dict) -> tuple[int, int]:
    """Return (rect_x, text_x) for the second legend item based on translated labels."""
    gap = 12  # space between first legend rect and its text
    spacing = 18  # gap between first legend text end and second legend rect
    first_label_w = len(tr.get("chart_from_zev", "")) * _PX_PER_CHAR
    second_rect_x = ml + gap + int(first_label_w) + spacing
    second_text_x = second_rect_x + 12
    return second_rect_x, second_text_x


def _esc(text: str) -> str:
    """Escape text for safe embedding in SVG."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _build_energy_flow_svg(invoice, tr: dict) -> str | None:
    """Generate an SVG Sankey-style energy flow diagram for the invoice period.

    Shows producers → total production → local consumption / grid export → consumers,
    with the invoice participant highlighted and all other consumers aggregated as 'Others'.
    """
    totals, all_stats = _compute_period_participant_stats(invoice)
    total_produced = totals["produced_kwh"]

    pid = str(invoice.participant_id)
    producers = [p for p in all_stats if p["total_produced_kwh"] > 0]
    all_consumers = [p for p in all_stats if p["total_consumed_kwh"] > 0]

    # Highlight invoice participant, aggregate others
    highlighted = next((c for c in all_consumers if c["participant_id"] == pid), None)
    others = [c for c in all_consumers if c["participant_id"] != pid]
    consumers = []
    if highlighted:
        consumers.append(highlighted)
    if others:
        consumers.append({
            "participant_id": "__others__",
            "participant_name": tr["flow_others"],
            "total_consumed_kwh": sum(c["total_consumed_kwh"] for c in others),
            "total_produced_kwh": sum(c["total_produced_kwh"] for c in others),
            "from_zev_kwh": sum(c["from_zev_kwh"] for c in others),
            "from_grid_kwh": sum(c["from_grid_kwh"] for c in others),
        })

    sum_from_zev = sum(c["from_zev_kwh"] for c in consumers)
    sum_from_grid = sum(c["from_grid_kwh"] for c in consumers)
    local_cons = sum_from_zev if sum_from_zev > 0 else max(0, total_produced - totals["exported_kwh"])
    grid_import = sum_from_grid if sum_from_grid > 0 else totals["imported_kwh"]
    grid_export = max(0, total_produced - local_cons)

    if total_produced <= 0 and grid_import <= 0:
        return None
    if not consumers and grid_export <= 0:
        return None

    # ── Node definitions ───────────────────────────────────────────────────
    PROD_COLORS = [_CHART_LOCAL, "#2f7a4d", "#15803d", "#0f766e", "#3d8b5c", "#4d9b6a"]
    CONS_COLORS = ["#1d4ed8", "#2563eb", "#1e40af", "#4f46e5", "#3b82f6", "#6366f1"]
    OTHERS_COLOR = _CHART_AXIS
    TOTAL_PROD_C = _CHART_LOCAL
    LOCAL_CONS_C = _FLOW_LOCAL_CONS
    GRID_IMP_C = _CHART_GRID
    GRID_EXP_C = _FLOW_GRID_EXP

    class N:
        __slots__ = ("id", "label", "value", "color", "col", "y", "h", "pct")

        def __init__(self, id, label, value, color, col, pct=""):
            self.id = id
            self.label = label
            self.value = value
            self.color = color
            self.col = col
            self.y = 0.0
            self.h = 0.0
            self.pct = pct

    col0, col1, col2, col3, col4 = [], [], [], [], []

    # Col 0: individual producers
    attributed = sum(p["total_produced_kwh"] for p in producers)
    if total_produced > 0:
        if attributed > 0:
            sf = min(1.0, total_produced / attributed) if attributed > total_produced else 1.0
            for i, p in enumerate(producers):
                col0.append(N(f"prod-{p['participant_id']}", p["participant_name"],
                              p["total_produced_kwh"] * sf, PROD_COLORS[i % len(PROD_COLORS)], 0))
            remainder = total_produced - attributed * sf
            if remainder > 0.01:
                col0.append(N("prod-other", tr["flow_local_production"], remainder,
                              PROD_COLORS[len(producers) % len(PROD_COLORS)], 0))
        else:
            col0.append(N("prod-local", tr["flow_local_production"], total_produced, TOTAL_PROD_C, 0))

    # Col 1: total local production
    if total_produced > 0:
        col1.append(N("total-prod", tr["flow_total_local_production"], total_produced, TOTAL_PROD_C, 1))

    # Col 2: local consumption + grid export
    self_pct = ((total_produced - grid_export) / total_produced * 100) if total_produced > 0 else 0
    exp_pct = (grid_export / total_produced * 100) if total_produced > 0 else 0
    if local_cons > 0:
        col2.append(N("local-cons", tr["flow_local_consumption"], local_cons, LOCAL_CONS_C, 2,
                       pct=f"{self_pct:.1f}%"))
    if grid_export > 0:
        col2.append(N("grid-export", tr["flow_grid_export"], grid_export, GRID_EXP_C, 2,
                       pct=f"{exp_pct:.1f}%"))

    # Col 3: grid import
    if grid_import > 0:
        col3.append(N("grid-import", tr["flow_grid_import"], grid_import, GRID_IMP_C, 3))

    # Col 4: consumers (highlighted + others)
    for i, c in enumerate(consumers):
        color = OTHERS_COLOR if c["participant_id"] == "__others__" else CONS_COLORS[i % len(CONS_COLORS)]
        col4.append(N(f"cons-{c['participant_id']}", c["participant_name"],
                      c["total_consumed_kwh"], color, 4))

    all_cols = [col0, col1, col2, col3, col4]
    if all(len(c) == 0 for c in all_cols):
        return None

    # ── Layout constants ────────────────────────────────────────────────────
    W, H_MIN, H_MAX = 540, 210, 360
    PAD_TOP, PAD_BOTTOM = 26, 38
    PAD_LEFT, PAD_RIGHT = 84, 84
    BAR_W = 12
    MIN_H = 5
    OUTER_GAP, INNER_GAP = 10, 42

    col_usable = W - PAD_LEFT - PAD_RIGHT - BAR_W
    col_x = [
        PAD_LEFT,
        round(PAD_LEFT + col_usable / 4),
        round(PAD_LEFT + col_usable * 2 / 4),
        round(PAD_LEFT + col_usable * 3 / 4),
        PAD_LEFT + col_usable,
    ]

    max_nodes = max(len(c) for c in all_cols) if any(all_cols) else 1
    view_h = max(H_MIN, min(H_MAX, max_nodes * 44 + PAD_TOP + PAD_BOTTOM))
    usable_h = view_h - PAD_TOP - PAD_BOTTOM

    # Compute unified scale
    scale = float("inf")
    for col in all_cols:
        if not col:
            continue
        total_val = sum(n.value for n in col)
        if total_val <= 0:
            continue
        is_inner = col[0].col in (1, 2, 3)
        gap = INNER_GAP if is_inner else OUTER_GAP
        avail = usable_h - (len(col) - 1) * gap
        if avail > 0:
            scale = min(scale, avail / total_val)
    if not (0 < scale < float("inf")):
        return None

    # Position nodes vertically centered per column
    def pos_col(nodes):
        if not nodes:
            return
        is_inner = nodes[0].col in (1, 2, 3)
        gap = INNER_GAP if is_inner else OUTER_GAP
        total_h = sum(max(MIN_H, n.value * scale) for n in nodes) + (len(nodes) - 1) * gap
        y = PAD_TOP + (usable_h - total_h) / 2
        for n in nodes:
            n.h = max(MIN_H, n.value * scale)
            n.y = y
            y += n.h + gap

    for c in all_cols:
        pos_col(c)

    node_map = {}
    for c in all_cols:
        for n in c:
            node_map[n.id] = n

    # ── Build links ────────────────────────────────────────────────────────
    links = []  # (src_id, tgt_id, value, color)

    # Col 0→1: producers → total production
    if "total-prod" in node_map:
        for n in col0:
            links.append((n.id, "total-prod", n.value, n.color))

    # Col 1→2: total prod → local cons + grid export
    if "total-prod" in node_map and "local-cons" in node_map:
        links.append(("total-prod", "local-cons", local_cons, LOCAL_CONS_C))
    if "total-prod" in node_map and "grid-export" in node_map:
        links.append(("total-prod", "grid-export", grid_export, GRID_EXP_C))

    # Col 2→4: local cons → consumers (from_zev)
    if "local-cons" in node_map:
        for c in consumers:
            if c["from_zev_kwh"] < 0.01:
                continue
            tid = f"cons-{c['participant_id']}"
            if tid in node_map:
                links.append(("local-cons", tid, c["from_zev_kwh"], LOCAL_CONS_C))

    # Col 3→4: grid import → consumers (from_grid)
    if "grid-import" in node_map:
        for c in consumers:
            if c["from_grid_kwh"] < 0.01:
                continue
            tid = f"cons-{c['participant_id']}"
            if tid in node_map:
                links.append(("grid-import", tid, c["from_grid_kwh"], GRID_IMP_C))

    # Position links (compute y offsets per node port)
    src_out = {n.id: n.y for c in all_cols for n in c}
    tgt_in = {n.id: n.y for c in all_cols for n in c}

    positioned_links = []
    for src_id, tgt_id, value, color in links:
        src = node_map[src_id]
        tgt = node_map[tgt_id]
        th = max(1, value * scale)
        sy = src_out[src_id]
        ty = tgt_in[tgt_id]
        src_out[src_id] += th
        tgt_in[tgt_id] += th
        sx = col_x[src.col] + BAR_W
        tx = col_x[tgt.col]
        positioned_links.append((sx, sy, tx, ty, th, color, value))

    # ── SVG rendering ─────────────────────────────────────────────────────
    header = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{view_h}" '
        f'viewBox="0 0 {W} {view_h}">'
    )
    svg = [header]

    # Flow ribbons
    for sx, sy, tx, ty, th, color, val in positioned_links:
        mx = (sx + tx) / 2
        svg.append(
            f'<path d="M{sx},{sy:.1f} C{mx},{sy:.1f} {mx},{ty:.1f} {tx},{ty:.1f} '
            f'L{tx},{ty + th:.1f} C{mx},{ty + th:.1f} {mx},{sy + th:.1f} {sx},{sy + th:.1f} Z" '
            f'fill="{color}" fill-opacity="0.22" stroke="{color}" stroke-opacity="0.28" stroke-width="0.5"/>'
        )
        # Value label on ribbon (if thick enough)
        if th >= 12:
            mid_x = (sx + tx) / 2
            mid_y = (sy + ty + th) / 2
            svg.append(
                f'<text x="{mid_x:.1f}" y="{mid_y:.1f}" text-anchor="middle" '
                f'dominant-baseline="central" font-size="6.5" fill="{_CHART_INK}" '
                f'fill-opacity="0.8" font-weight="600">{val:.1f} kWh</text>'
            )

    # Node bars + labels
    for col_nodes in all_cols:
        for n in col_nodes:
            x = col_x[n.col]
            svg.append(f'<rect x="{x}" y="{n.y:.1f}" width="{BAR_W}" '
                       f'height="{n.h:.1f}" fill="{n.color}" rx="2.5"/>')

            if n.col == 0:  # left labels
                svg.append(
                    f'<text x="{x - 6}" y="{n.y + n.h / 2 - 4:.1f}" text-anchor="end" '
                    f'dominant-baseline="central" font-size="7.5" fill="{_CHART_INK}" font-weight="600">'
                    f'{_esc(n.label)}</text>')
                svg.append(
                    f'<text x="{x - 6}" y="{n.y + n.h / 2 + 6:.1f}" text-anchor="end" '
                    f'dominant-baseline="central" font-size="6.5" fill="{_CHART_MUTED}">'
                    f'{n.value:.1f} kWh</text>')
            elif n.col == 4:  # right labels
                svg.append(
                    f'<text x="{x + BAR_W + 6}" y="{n.y + n.h / 2 - 4:.1f}" text-anchor="start" '
                    f'dominant-baseline="central" font-size="7.5" fill="{_CHART_INK}" font-weight="600">'
                    f'{_esc(n.label)}</text>')
                svg.append(
                    f'<text x="{x + BAR_W + 6}" y="{n.y + n.h / 2 + 6:.1f}" text-anchor="start" '
                    f'dominant-baseline="central" font-size="6.5" fill="{_CHART_MUTED}">'
                    f'{n.value:.1f} kWh</text>')
            else:  # mid-column labels below bar
                svg.append(
                    f'<text x="{x + BAR_W / 2}" y="{n.y + n.h + 11:.1f}" text-anchor="middle" '
                    f'font-size="7" fill="{_CHART_INK}" font-weight="600">{_esc(n.label)}</text>')
                svg.append(
                    f'<text x="{x + BAR_W / 2}" y="{n.y + n.h + 21:.1f}" text-anchor="middle" '
                    f'font-size="6.5" fill="{_CHART_MUTED}">{n.value:.1f} kWh</text>')
                if n.pct:
                    svg.append(
                        f'<text x="{x + BAR_W / 2}" y="{n.y + n.h + 31:.1f}" text-anchor="middle" '
                        f'font-size="7.5" font-weight="700" fill="{n.color}">{n.pct}</text>')

    svg.append("</svg>")
    return "\n".join(svg)


def _build_energy_chart_svg(invoice, tr: dict) -> str | None:
    """Generate an SVG stacked bar chart comparing local-ZEV vs grid kWh for the
    current invoice period alongside equivalent periods from prior years."""
    from .models import Invoice, InvoiceStatus

    ps = invoice.period_start
    pe = invoice.period_end

    # Collect final invoices for the same participant/ZEV that cover the same
    # seasonal window.  Drafts and cancelled invoices are excluded so the
    # comparison only shows billed periods.
    comparable = []
    for h in (
        Invoice.objects.filter(participant=invoice.participant, zev=invoice.zev)
        .exclude(id=invoice.id)
        .exclude(status__in=[InvoiceStatus.DRAFT, InvoiceStatus.CANCELLED])
        .order_by("period_start")
    ):
        if (
            h.period_start.month == ps.month
            and h.period_start.day == ps.day
            and h.period_end.month == pe.month
            and h.period_end.day == pe.day
        ):
            comparable.append(
                (h.period_start.year, float(h.total_local_kwh), float(h.total_grid_kwh))
            )

    data = comparable + [(ps.year, float(invoice.total_local_kwh), float(invoice.total_grid_kwh))]
    data.sort(key=lambda x: x[0])
    _MAX_COMPARISON_ROWS = 5
    data = data[-_MAX_COMPARISON_ROWS:]

    max_val = max((local + grid) for _, local, grid in data) if data else 0
    if max_val == 0:
        return None

    # ── SVG geometry (horizontal bars) ─────────────────────────────────────
    W, H = 548, 96
    ML, MR, MT, MB = 82, 40, 6, 30  # margins: left, right, top, bottom
    cw = W - ML - MR    # chart area width (kWh axis)
    ch = H - MT - MB    # chart area height (years axis)

    n = len(data)
    group_h = ch / n
    bar_h = max(8, min(14, group_h * 0.38))

    def s(v):        # value → pixel bar width
        return cw * v / max_val

    svg = []
    svg.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}"'
        f' viewBox="0 0 {W} {H}">'
    )
    # Soft chart background
    svg.append(
        f'<rect x="{ML - 4}" y="{MT - 4}" width="{cw + 8}" height="{ch + 8}"'
        f' fill="{_CHART_BG}" rx="4"/>'
    )

    # X-axis vertical grid lines & labels (6 steps: 0 .. max)
    for i in range(6):
        frac = i / 5
        gx = ML + cw * frac
        val = max_val * frac
        svg.append(
            f'<line x1="{gx:.1f}" y1="{MT}" x2="{gx:.1f}" y2="{MT + ch}"'
            f' stroke="{_CHART_GRIDLINE}" stroke-width="1"/>'
        )
        svg.append(
            f'<text x="{gx:.1f}" y="{MT + ch + 8}" text-anchor="middle"'
            f' font-size="7.5" fill="{_CHART_MUTED}">{val:.0f}</text>'
        )

    # kWh unit label — placed below the axis and year labels
    svg.append(
        f'<text x="{ML}" y="{MT + ch + 16}" text-anchor="start"'
        f' font-size="7" fill="{_CHART_MUTED}">kWh</text>'
    )

    # Y-axis baseline (left edge of bars)
    svg.append(
        f'<line x1="{ML}" y1="{MT}" x2="{ML}" y2="{MT + ch}"'
        f' stroke="{_CHART_AXIS}" stroke-width="1.2"/>'
    )

    # ── Stacked bars (local ZEV left, grid right) ──────────────────────────
    for idx, (year, local, grid) in enumerate(data):
        cy = MT + group_h * idx + group_h / 2
        by = cy - bar_h / 2          # top edge of bar
        is_current = year == ps.year
        wl = s(local)
        wg = s(grid)
        total_w = wl + wg

        # Left segment: local ZEV (brand green)
        xl = ML
        svg.append(
            f'<rect x="{xl:.1f}" y="{by:.1f}" width="{max(wl, 0):.1f}"'
            f' height="{bar_h:.1f}" fill="{_CHART_LOCAL}"/>'
        )
        # Label inside segment if wide enough
        if wl > 16:
            svg.append(
                f'<text x="{xl + wl / 2:.1f}" y="{by + bar_h / 2 + 3:.1f}"'
                f' text-anchor="middle" font-size="6.5" fill="#fff" font-weight="600">'
                f'{local:.1f}</text>'
            )

        # Right segment: grid (warm amber), rounded right corners
        xg = ML + wl
        svg.append(
            f'<rect x="{xg:.1f}" y="{by:.1f}" width="{max(wg, 0):.1f}"'
            f' height="{bar_h:.1f}" fill="{_CHART_GRID}" rx="2.5" ry="2.5"/>'
        )
        # Square off the left corners of the grid segment by overlaying a rect
        if wg > 3:
            overlap = min(3, wg)
            svg.append(
                f'<rect x="{xg:.1f}" y="{by:.1f}" width="{overlap:.1f}"'
                f' height="{bar_h:.1f}" fill="{_CHART_GRID}"/>'
            )
        # Label inside segment if wide enough
        if wg > 16:
            svg.append(
                f'<text x="{xg + wg / 2:.1f}" y="{by + bar_h / 2 + 3:.1f}"'
                f' text-anchor="middle" font-size="6.5" fill="#fff" font-weight="600">'
                f'{grid:.1f}</text>'
            )

        # Total label to the right of the full bar
        if total_w > 0:
            svg.append(
                f'<text x="{ML + total_w + 5:.1f}" y="{by + bar_h / 2 + 3:.1f}"'
                f' text-anchor="start" font-size="7.5" font-weight="700" fill="{_CHART_INK}">'
                f'{local + grid:.1f}</text>'
            )

        # Year label (bold + "(current)" suffix for current period)
        fw = "700" if is_current else "500"
        col = _CHART_INK if is_current else _CHART_LABEL
        year_label = f"{year} {tr['chart_current']}" if is_current else str(year)
        svg.append(
            f'<text x="{ML - 6}" y="{cy + 3:.1f}" text-anchor="end"'
            f' font-size="8" fill="{col}" font-weight="{fw}">{year_label}</text>'
        )

    # ── Period text below year labels (bottom-left) ─────────────────────────
    period_str = f"{ps.day:02d}.{ps.month:02d}.–{pe.day:02d}.{pe.month:02d}."
    svg.append(
        f'<text x="{ML - 6}" y="{MT + ch + 14}" text-anchor="end"'
        f' font-size="7" fill="{_CHART_MUTED}">{period_str}</text>'
    )

    # ── Legend ──────────────────────────────────────────────────────────────
    ly = MT + ch + 20
    svg.append(f'<rect x="{ML}" y="{ly}" width="8" height="7" fill="{_CHART_LOCAL}" rx="1.5"/>')
    svg.append(
        f'<text x="{ML + 12}" y="{ly + 6}" font-size="7.5" fill="{_CHART_LABEL}">'
        f'{tr["chart_from_zev"]}</text>'
    )
    r2_x, t2_x = _legend_offsets(ML, tr)
    svg.append(f'<rect x="{r2_x}" y="{ly}" width="8" height="7" fill="{_CHART_GRID}" rx="1.5"/>')
    svg.append(
        f'<text x="{t2_x}" y="{ly + 6}" font-size="7.5" fill="{_CHART_LABEL}">'
        f'{tr["chart_from_grid"]}</text>'
    )

    svg.append('</svg>')
    return '\n'.join(svg)


def _build_hourly_profile_chart_svg(invoice, tr: dict) -> str | None:
    """Generate an SVG stacked bar chart showing the average hourly energy profile
    (local ZEV vs grid) over the invoice period.

    Returns None when sub-daily metering data is not available or all values are zero.
    """
    import datetime as _dt

    from decimal import Decimal as _Dec
    from django.db import models as _dj
    from allocation.read_model import (
        CONSUMPTION_METER_TYPES as _CONS_METER_TYPES,
        community_totals_by_timestamp,
    )
    from allocation.split import split_consumption
    from allocation.windows import AssignmentWindows
    from metering.models import MeterReading, ReadingDirection, ReadingResolution
    from zev.models import MeteringPoint as _MP

    ps = invoice.period_start
    pe = invoice.period_end
    participant = invoice.participant
    zev = invoice.zev

    start_dt = _period_to_dt(ps)
    end_dt = _period_to_dt(pe) + _dt.timedelta(days=1)

    # ── Participant consumption readings ────────────────────────────────────
    consumption_mps = _MP.objects.filter(
        zev=zev,
        meter_type__in=_CONS_METER_TYPES,
        assignments__participant=participant,
        assignments__valid_from__lte=pe,
    ).filter(
        _dj.Q(assignments__valid_to__isnull=True) | _dj.Q(assignments__valid_to__gte=ps)
    ).distinct()
    participant_readings = list(
        MeterReading.objects.filter(
            metering_point__in=consumption_mps,
            timestamp__gte=start_dt,
            timestamp__lt=end_dt,
            direction=ReadingDirection.IN,
        ).order_by("timestamp")
    )
    if not participant_readings:
        return None

    windows = AssignmentWindows.for_participant(participant, ps, pe)

    # Only show chart when sub-daily data is present
    resolutions = {r.resolution for r in participant_readings}
    if resolutions == {ReadingResolution.DAILY}:
        return None

    # ── ZEV-level production and consumption by timestamp ───────────────────
    # The pool covers every metering point of the ZEV regardless of assignment
    # (ADR 0013), matching the engine and the dashboards.
    zev_cons_by_ts, zev_prod_by_ts = community_totals_by_timestamp(zev, start_dt, end_dt)

    # ── Accumulate local/grid per local-hour-of-day ─────────────────────────
    # Decimal arithmetic end to end (the billing contract); floats only enter
    # at SVG serialization.
    hourly_local = [_Dec("0")] * 24
    hourly_grid = [_Dec("0")] * 24

    for reading in participant_readings:
        ts = reading.timestamp
        if not windows.is_held_by(participant.id, reading.metering_point_id, ts):
            # Reading predates this participant's assignment (or falls in an
            # assignment gap): it must not shape their profile.
            continue
        hour = ts.hour
        p_kwh = reading.energy_kwh
        zev_cons = zev_cons_by_ts.get(ts, _Dec("0"))
        zev_prod = zev_prod_by_ts.get(ts, _Dec("0"))
        r_local, r_grid = split_consumption(p_kwh, zev_cons, zev_prod)

        hourly_local[hour] += r_local
        hourly_grid[hour] += r_grid

    total_days = (pe - ps).days + 1
    hourly_local = [v / total_days for v in hourly_local]
    hourly_grid = [v / total_days for v in hourly_grid]

    max_val = max((loc + grd) for loc, grd in zip(hourly_local, hourly_grid))
    if max_val == 0:
        return None

    # ── SVG geometry ────────────────────────────────────────────────────────
    W, H = 540, 196
    ML, MR, MT, MB = 52, 14, 18, 56
    cw = W - ML - MR
    ch = H - MT - MB

    group_w = cw / 24
    bar_w = max(6.5, group_w * 0.74)

    def s(v) -> float:
        return ch * float(v) / float(max_val)

    svg: list[str] = []
    svg.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}"'
        f' viewBox="0 0 {W} {H}">'
    )
    svg.append(
        f'<rect x="{ML - 4}" y="{MT - 6}" width="{cw + 8}" height="{ch + 10}"'
        f' fill="{_CHART_BG}" rx="4"/>'
    )

    # Y-axis grid lines & labels (5 steps)
    for i in range(5):
        frac = i / 4
        gy = MT + ch - ch * frac
        val = float(max_val) * frac
        svg.append(
            f'<line x1="{ML}" y1="{gy:.1f}" x2="{ML + cw}" y2="{gy:.1f}"'
            f' stroke="{_CHART_GRIDLINE}" stroke-width="1"/>'
        )
        svg.append(
            f'<text x="{ML - 5}" y="{gy + 3:.1f}" text-anchor="end"'
            f' font-size="7.5" fill="{_CHART_MUTED}">{val:.2f}</text>'
        )

    # Rotated Y-axis unit label
    mid_y = MT + ch // 2
    svg.append(
        f'<text transform="rotate(-90 10 {mid_y})" x="10" y="{mid_y}"'
        f' text-anchor="middle" font-size="7.5" fill="{_CHART_MUTED}">kWh</text>'
    )

    # Soft daylight band (06:00–18:00) — drawn before baseline so axis stays crisp
    day_x = ML + group_w * 6
    day_w = group_w * 12
    svg.append(
        f'<rect x="{day_x:.1f}" y="{MT}" width="{day_w:.1f}" height="{ch}"'
        f' fill="#eef5f0" opacity="0.7"/>'
    )

    # X-axis baseline — on top of the band
    svg.append(
        f'<line x1="{ML}" y1="{MT + ch}" x2="{ML + cw}" y2="{MT + ch}"'
        f' stroke="{_CHART_AXIS}" stroke-width="1.2"/>'
    )

    # ── Stacked bars per hour ───────────────────────────────────────────────
    for hour in range(24):
        local = hourly_local[hour]
        grid = hourly_grid[hour]
        cx = ML + group_w * hour + group_w / 2
        bx = cx - bar_w / 2
        hl = s(local)
        hg = s(grid)
        total_h = hl + hg

        # Local segment (brand green, bottom)
        yl = MT + ch - hl
        if hl > 0:
            svg.append(
                f'<rect x="{bx:.1f}" y="{yl:.1f}" width="{bar_w:.1f}"'
                f' height="{hl:.1f}" fill="{_CHART_LOCAL}" data-hour="{hour}"/>'
            )

        # Grid segment (warm amber, top), rounded top corners
        yg = MT + ch - total_h
        if hg > 0:
            svg.append(
                f'<rect x="{bx:.1f}" y="{yg:.1f}" width="{bar_w:.1f}"'
                f' height="{hg:.1f}" fill="{_CHART_GRID}" rx="2" ry="2" data-hour="{hour}"/>'
            )
            # Square off bottom corners of amber segment
            overlap = min(3.0, hg)
            svg.append(
                f'<rect x="{bx:.1f}" y="{yg + hg - overlap:.1f}" width="{bar_w:.1f}"'
                f' height="{overlap:.1f}" fill="{_CHART_GRID}"/>'
            )

        # Hour label every 3 hours
        if hour % 3 == 0:
            svg.append(
                f'<text x="{cx:.1f}" y="{MT + ch + 12:.1f}" text-anchor="middle"'
                f' font-size="7.5" fill="{_CHART_LABEL}">{hour:02d}:00</text>'
            )

    # ── Legend ─────────────────────────────────────────────────────────────
    ly = MT + ch + 28
    svg.append(f'<rect x="{ML}" y="{ly}" width="8" height="7" fill="{_CHART_LOCAL}" rx="1.5"/>')
    svg.append(
        f'<text x="{ML + 12}" y="{ly + 6}" font-size="7.5" fill="{_CHART_LABEL}">'
        f'{tr["chart_from_zev"]}</text>'
    )
    r2_x, t2_x = _legend_offsets(ML, tr)
    svg.append(f'<rect x="{r2_x}" y="{ly}" width="8" height="7" fill="{_CHART_GRID}" rx="1.5"/>')
    svg.append(
        f'<text x="{t2_x}" y="{ly + 6}" font-size="7.5" fill="{_CHART_LABEL}">'
        f'{tr["chart_from_grid"]}</text>'
    )

    svg.append('</svg>')
    return '\n'.join(svg)
