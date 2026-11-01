"""Hourly production forecast values, shared by the providers (SPEC-2026-live-energy-data §6.3).

Both vendors report finer or irregular time steps; the app shows and stores one value per UTC hour,
the mean of the vendor's values inside it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable

TENTH = Decimal("0.1")
HOUR = timedelta(hours=1)


@dataclass(frozen=True)
class ForecastHour:
    """Expected mean power over the UTC hour starting at ``start``. ``min_w`` / ``max_w`` only where the vendor gives a band."""

    start: datetime
    power_w: Decimal
    min_w: Decimal | None = None
    max_w: Decimal | None = None


def floor_hour(moment: datetime) -> datetime:
    return moment.astimezone(dt_timezone.utc).replace(minute=0, second=0, microsecond=0)


def _mean(values: list[Decimal]) -> Decimal:
    return (sum(values) / len(values)).quantize(TENTH, rounding=ROUND_HALF_UP)


def to_hours(
    samples: Iterable[tuple[datetime, Decimal, Decimal | None, Decimal | None]], *, marks: str
) -> list[ForecastHour]:
    """Average ``(instant, power, min, max)`` samples into UTC hours, oldest first.

    ``marks`` says what an instant stands for: ``"start"`` of the interval its value covers, or its
    ``"end"`` (forecast.solar's ``watts`` cover the time since the previous key). Negative power is read as zero:
    a plant does not consume in the forecast.
    """
    groups: dict[datetime, list[tuple[Decimal, Decimal | None, Decimal | None]]] = {}
    for instant, power, low, high in samples:
        anchor = instant - timedelta(microseconds=1) if marks == "end" else instant
        groups.setdefault(floor_hour(anchor), []).append(
            (max(power, Decimal(0)), None if low is None else max(low, Decimal(0)), None if high is None else max(high, Decimal(0)))
        )
    hours = []
    for start in sorted(groups):
        rows = groups[start]
        lows = [row[1] for row in rows if row[1] is not None]
        highs = [row[2] for row in rows if row[2] is not None]
        hours.append(
            ForecastHour(
                start=start,
                power_w=_mean([row[0] for row in rows]),
                # A band is only claimed when every value in the hour has one.
                min_w=_mean(lows) if lows and len(lows) == len(rows) else None,
                max_w=_mean(highs) if highs and len(highs) == len(rows) else None,
            )
        )
    return hours


def sum_hours(series: Iterable[list[ForecastHour]]) -> list[ForecastHour]:
    """Add per-plane series hour by hour. A band survives only where every plane has one."""
    series = [hours for hours in series if hours]
    if not series:
        return []
    by_hour: dict[datetime, list[ForecastHour]] = {}
    for hours in series:
        for hour in hours:
            by_hour.setdefault(hour.start, []).append(hour)
    total = []
    for start in sorted(by_hour):
        rows = by_hour[start]
        bands = len(rows) == len(series) and all(r.min_w is not None and r.max_w is not None for r in rows)
        total.append(
            ForecastHour(
                start=start,
                power_w=sum((r.power_w for r in rows), Decimal(0)),
                min_w=sum((r.min_w for r in rows), Decimal(0)) if bands else None,
                max_w=sum((r.max_w for r in rows), Decimal(0)) if bands else None,
            )
        )
    return total
