"""Gross-energy figures from supplementary readings: the one definition.

Every statistics surface reads supplementary data through this module and
nowhere else (ADR 0030). The official meter is never consulted here: numerator
and denominator of each rate come from one consistent measurement (the
participant's own system), and the meter is used only for reconciliation.

Per 15-minute interval *i*::

    self_consumption_i = min(max(production_i - export_i, 0), production_i, consumption_i)

Over a window::

    self_consumption_kwh   = sum(self_consumption_i)
    self_sufficiency_rate  = clamp(1 - sum(import_i) / sum(consumption_i), 0, 1)
    self_consumption_rate  = sum(self_consumption_i) / sum(production_i)

The vendor's own derived fields are deliberately not used: Solar Manager's
``cPvWh`` and ``scWh`` disagree without a battery, and it reports import and
export in the same interval, so only the measured flows are stored.

Which intervals count (SPEC §4.4): those inside a window in which the source's
participant held the metering point *personally*, between the source's
``covers_from`` and ``synced_through``, and inside the requested window.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from typing import Callable, Iterable

from django.conf import settings
from django.db.models import Q

from allocation.validity import period_end_exclusive_dt, period_start_dt
from zev.models import AllocationMode, MeteringPointAssignment

from ..models import SupplementaryReading, SupplementarySource

INTERVAL = timedelta(minutes=15)
INTERVAL_S = int(INTERVAL.total_seconds())

Window = tuple[datetime, datetime]

ZERO = Decimal("0")
ONE = Decimal("1")


def personal_windows(source: SupplementarySource) -> list[Window]:
    """UTC ``[start, end)`` windows during which the source's participant held its meter personally.

    Community-mode assignments are excluded: their readings are split by
    weight, and no single person's household is described by them. Adjacent or
    overlapping windows are merged, so an interval is never counted twice.
    """
    rows = MeteringPointAssignment.objects.filter(
        metering_point_id=source.metering_point_id,
        participant_id=source.participant_id,
        allocation_mode=AllocationMode.PERSONAL,
    ).values_list("valid_from", "valid_to")
    windows = sorted(
        (
            period_start_dt(valid_from),
            period_end_exclusive_dt(valid_to) if valid_to else datetime.max.replace(tzinfo=dt_timezone.utc),
        )
        for valid_from, valid_to in rows
    )
    merged: list[Window] = []
    for start, end in windows:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _clip(windows: Iterable[Window], start: datetime, end: datetime) -> list[Window]:
    clipped = []
    for w_start, w_end in windows:
        lo, hi = max(w_start, start), min(w_end, end)
        if lo < hi:
            clipped.append((lo, hi))
    return clipped


def expected_windows(source: SupplementarySource, start: datetime, end: datetime) -> list[Window]:
    """The stretches of ``[start, end)`` in which ``source`` should have data.

    A source that has never ingested anything (no ``covers_from`` or
    ``synced_through``) expects nothing: there is no stretch to be missing from.
    """
    if source.covers_from is None or source.synced_through is None:
        return []
    lo = max(start, source.covers_from)
    hi = min(end, source.synced_through)
    if lo >= hi:
        return []
    return _clip(personal_windows(source), lo, hi)


def _slots(windows: Iterable[Window]) -> int:
    return sum(int((end - start).total_seconds()) // INTERVAL_S for start, end in windows)


def self_consumption(production: Decimal, export: Decimal, consumption: Decimal) -> Decimal:
    """Directly self-consumed energy of one interval, in kWh."""
    return min(max(production - export, ZERO), production, consumption)


def _percent(numerator: Decimal, denominator: Decimal) -> float | None:
    """``numerator / denominator`` as a percentage to one decimal, ``None`` when undefined."""
    if denominator <= 0:
        return None
    return round(float(numerator / denominator * 100), 1)


def _window_q(windows: Iterable[Window]) -> Q:
    q = Q(pk__in=[])
    for w_start, w_end in windows:
        q |= Q(timestamp__gte=w_start, timestamp__lt=w_end)
    return q


def gross_energy(
    participant_ids: Iterable,
    start: datetime,
    end: datetime,
    *,
    bucket_key: Callable[[datetime], object] | None = None,
    min_coverage: float | None = None,
) -> dict | None:
    """Gross energy figures for the given participants over ``[start, end)``.

    Returns ``None`` when no source of theirs expects data in the window (no
    source, or one that has not ingested anything there). Otherwise the
    ``GrossEnergy`` shape of the spec (§5.1): kWh sums, the two rates, the
    coverage and the covered range. Rates are ``None`` with a
    ``rates_withheld_reason`` when there is no data or the coverage is below
    ``min_coverage`` (default ``SETTINGS.SUPPLEMENTARY_MIN_COVERAGE``).

    The caller decides whether the feature is enabled and which participants
    may see the figures; this function only computes. ``bucket_key`` maps an
    interval start to a bucket label; when given, a ``timeline`` is returned.
    A disconnected source still counts: its stored history is real.

    Several sources (one participant, several flagged meters) are summed. The
    reported ``source_provider`` is that of the earliest-created source.
    """
    if min_coverage is None:
        min_coverage = settings.SUPPLEMENTARY_MIN_COVERAGE

    sources = list(
        SupplementarySource.objects.filter(participant_id__in=list(participant_ids)).order_by("created_at", "id")
    )

    totals = {key: ZERO for key in ("consumption", "production", "import", "export", "self")}
    timeline: dict[object, dict[str, Decimal]] = {}
    expected = present = 0
    covered_from = covered_to = None
    provider = None

    for source in sources:
        windows = expected_windows(source, start, end)
        if not windows:
            continue
        provider = provider or source.provider
        expected += _slots(windows)
        covered_from = min(filter(None, [covered_from, windows[0][0]]))
        covered_to = max(filter(None, [covered_to, windows[-1][1]]))

        rows = SupplementaryReading.objects.filter(source=source).filter(_window_q(windows)).values_list(
            "timestamp", "consumption_kwh", "production_kwh", "import_kwh", "export_kwh"
        )
        for ts, consumption, production, imported, exported in rows:
            present += 1
            own = self_consumption(production, exported, consumption)
            totals["consumption"] += consumption
            totals["production"] += production
            totals["import"] += imported
            totals["export"] += exported
            totals["self"] += own
            if bucket_key is not None:
                bucket = timeline.setdefault(
                    bucket_key(ts),
                    {key: ZERO for key in ("production", "consumption", "import", "export", "self")},
                )
                bucket["production"] += production
                bucket["consumption"] += consumption
                bucket["import"] += imported
                bucket["export"] += exported
                bucket["self"] += own

    if expected == 0:
        return None

    coverage = present / expected
    reason = None
    if present == 0:
        reason = "no_data"
    elif coverage < min_coverage:
        reason = "low_coverage"

    self_sufficiency = self_consumption_rate = None
    if reason is None:
        if totals["consumption"] > 0:
            self_sufficiency = round(
                float(min(max(ONE - totals["import"] / totals["consumption"], ZERO), ONE) * 100), 1
            )
        self_consumption_rate = _percent(totals["self"], totals["production"])

    result = {
        "source_provider": provider,
        "covered_from": covered_from,
        "covered_to": covered_to,
        "coverage_pct": round(coverage * 100, 1),
        "production_kwh": float(totals["production"]),
        "consumption_kwh": float(totals["consumption"]),
        "import_kwh": float(totals["import"]),
        "export_kwh": float(totals["export"]),
        "self_consumption_kwh": float(totals["self"]),
        "self_consumption_rate": self_consumption_rate,
        "self_sufficiency_rate": self_sufficiency,
        "rates_withheld_reason": reason,
    }
    if bucket_key is not None:
        result["timeline"] = [
            {
                "bucket": key,
                "production_kwh": float(item["production"]),
                "consumption_kwh": float(item["consumption"]),
                "import_kwh": float(item["import"]),
                "export_kwh": float(item["export"]),
                "self_consumption_kwh": float(item["self"]),
            }
            for key, item in sorted(timeline.items(), key=lambda entry: entry[0])
        ]
    return result


def gross_hourly_consumption(
    participant_ids: Iterable,
    start: datetime,
    end: datetime,
    *,
    hour_of: Callable[[datetime], int],
    min_coverage: float | None = None,
) -> list[float] | None:
    """Average daily consumption per hour of day (24 kWh values), as the participants' own systems report it.

    Same inclusion rules and coverage gate as ``gross_energy``; ``None`` when
    that would withhold the rates (no source, no data, low coverage), since a
    thin profile next to a full-period meter profile would mislead. Each hour
    is averaged over the days that actually have data for it, so a source
    connected mid-period is not diluted by days it never saw. Several sources
    add up, each averaged on its own.
    """
    if min_coverage is None:
        min_coverage = settings.SUPPLEMENTARY_MIN_COVERAGE

    sources = SupplementarySource.objects.filter(participant_id__in=list(participant_ids)).order_by("created_at", "id")
    profile = [ZERO] * 24
    expected = present = 0
    for source in sources:
        windows = expected_windows(source, start, end)
        if not windows:
            continue
        expected += _slots(windows)
        sums = [ZERO] * 24
        counts = [0] * 24
        rows = SupplementaryReading.objects.filter(source=source).filter(_window_q(windows)).values_list(
            "timestamp", "consumption_kwh"
        )
        for ts, consumption in rows:
            hour = hour_of(ts)
            sums[hour] += consumption
            counts[hour] += 1
            present += 1
        for hour in range(24):
            if counts[hour]:
                profile[hour] += sums[hour] * 4 / counts[hour]  # four intervals per hour and day

    if expected == 0 or present == 0 or present / expected < min_coverage:
        return None
    return [float(value) for value in profile]


def civil_window(start: date, end: date) -> Window:
    """UTC bounds of the inclusive civil-date range ``[start, end]``."""
    return period_start_dt(start), period_end_exclusive_dt(end)
