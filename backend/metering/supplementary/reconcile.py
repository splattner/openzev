"""Compare a source with the official meter, as a diagnostic (SPEC §6.5, ADR 0030).

The source's ``export_kwh`` should equal the meter's ``out`` and its ``import_kwh`` the
meter's ``in``: both are what crosses the connection point. A deviation means the
participant's system and the grid operator disagree, a shift means timestamps are off by an
interval. The result is shown to the participant and the owner. It changes nothing: it never
blocks a sync, never alters a rate, and the meter stays authoritative.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone as dt_timezone
from decimal import Decimal

from django.conf import settings
from django.utils import timezone

from allocation.validity import civil_date, day_length, period_start_dt

from ..models import MeterReading, ReadingDirection, SupplementaryReading, SupplementarySource
from .stats import INTERVAL, INTERVAL_S

#: How far back to look for days that have both series. Official data is often imported in
#: batches, so the newest comparable days can be weeks old.
LOOKBACK_DAYS = 60
MIN_DAYS = 2
#: A civil day is comparable when at least this share of its intervals is in both series.
MIN_DAY_SHARE = Decimal("0.9")
SHIFTS = range(-2, 3)

STATE_OK = "ok"
STATE_WARN = "warn"
STATE_INSUFFICIENT = "insufficient"

ZERO = Decimal(0)


def _series(rows) -> dict[datetime, Decimal]:
    return {timestamp: value for timestamp, value in rows}


def _deviation_pct(source_total: Decimal, meter_total: Decimal) -> float:
    return round(float(abs(source_total - meter_total) / max(meter_total, Decimal(1)) * 100), 1)


def _shift_error(source: dict[datetime, Decimal], meter: dict[datetime, Decimal],
                 stamps: list[datetime], shift: int) -> Decimal:
    """Σ|source(t + shift) - meter(t)| over the meter's compared intervals."""
    offset = INTERVAL * shift
    return sum((abs(source.get(stamp + offset, ZERO) - meter[stamp]) for stamp in stamps), ZERO)


def reconcile(source: SupplementarySource, *, days: int = 7, include_days: bool = False,
              now: datetime | None = None) -> dict:
    """Compare the newest ``days`` civil days present in both series.

    Returns the result described in the module docstring; with ``include_days`` it also
    carries the per-day totals (the on-demand view).
    """
    now = now or timezone.now()
    today = civil_date(now)
    window_start = period_start_dt(today - timedelta(days=LOOKBACK_DAYS))
    window_end = now

    supplementary = defaultdict(dict)  # direction -> {timestamp: kWh}
    for timestamp, export_kwh, import_kwh in SupplementaryReading.objects.filter(
        metering_point_id=source.metering_point_id, timestamp__gte=window_start, timestamp__lt=window_end
    ).values_list("timestamp", "export_kwh", "import_kwh"):
        supplementary[ReadingDirection.OUT][timestamp] = export_kwh
        supplementary[ReadingDirection.IN][timestamp] = import_kwh

    meter = defaultdict(dict)
    for timestamp, direction, energy in MeterReading.objects.filter(
        metering_point_id=source.metering_point_id, timestamp__gte=window_start, timestamp__lt=window_end
    ).values_list("timestamp", "direction", "energy_kwh"):
        meter[direction][timestamp] = energy

    # Intervals present on both sides, per flow, grouped by civil day.
    by_day: dict[date, dict[str, list[datetime]]] = defaultdict(lambda: {ReadingDirection.OUT: [], ReadingDirection.IN: []})
    for direction in (ReadingDirection.OUT, ReadingDirection.IN):
        for stamp in meter[direction].keys() & supplementary[direction].keys():
            by_day[civil_date(stamp)][direction].append(stamp)

    comparable = []
    for day, flows in by_day.items():
        slots = int(day_length(day).total_seconds()) // INTERVAL_S
        if all(len(stamps) >= slots * MIN_DAY_SHARE for stamps in flows.values()):
            comparable.append(day)
    comparable = sorted(comparable)[-days:]

    result: dict = {
        "checked_at": now.astimezone(dt_timezone.utc).isoformat().replace("+00:00", "Z"),
        "days_compared": len(comparable),
        "export_deviation_pct": None,
        "import_deviation_pct": None,
        "best_shift_intervals": 0,
        "state": STATE_INSUFFICIENT,
    }
    if include_days:
        result["days"] = []
    if len(comparable) < MIN_DAYS:
        return result

    totals = {ReadingDirection.OUT: [ZERO, ZERO], ReadingDirection.IN: [ZERO, ZERO]}  # [source, meter]
    stamps_out: list[datetime] = []
    for day in comparable:
        row = {"date": day.isoformat()}
        for direction, label in ((ReadingDirection.OUT, "export"), (ReadingDirection.IN, "import")):
            stamps = by_day[day][direction]
            source_sum = sum((supplementary[direction][s] for s in stamps), ZERO)
            meter_sum = sum((meter[direction][s] for s in stamps), ZERO)
            totals[direction][0] += source_sum
            totals[direction][1] += meter_sum
            row[f"{label}_source_kwh"] = float(source_sum)
            row[f"{label}_meter_kwh"] = float(meter_sum)
        stamps_out.extend(by_day[day][ReadingDirection.OUT])
        if include_days:
            result["days"].append(row)

    export_pct = _deviation_pct(*totals[ReadingDirection.OUT])
    import_pct = _deviation_pct(*totals[ReadingDirection.IN])
    result["export_deviation_pct"] = export_pct
    result["import_deviation_pct"] = import_pct

    errors = {
        shift: _shift_error(supplementary[ReadingDirection.OUT], meter[ReadingDirection.OUT], stamps_out, shift)
        for shift in SHIFTS
    }
    best = min(SHIFTS, key=lambda shift: (errors[shift], abs(shift)))
    shifted = best != 0 and errors[best] * 2 < errors[0]
    result["best_shift_intervals"] = best if shifted else 0

    tolerance_pct = settings.SUPPLEMENTARY_RECONCILE_TOLERANCE * 100
    deviates = export_pct > tolerance_pct or import_pct > tolerance_pct
    result["state"] = STATE_WARN if (deviates or shifted) else STATE_OK
    return result


def reconcile_and_store(source: SupplementarySource, *, now: datetime | None = None) -> dict:
    """Run the 7-day check and keep the result on the source (SPEC §4.1 ``reconciliation``)."""
    result = reconcile(source, days=7, now=now)
    source.reconciliation = result
    SupplementarySource.objects.filter(pk=source.pk).update(reconciliation=result)
    return result
