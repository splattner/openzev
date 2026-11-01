"""Refreshing and reading the production forecast (SPEC-2026-live-energy-data §4.2, §5.4, §6.3).

``refresh_source`` fetches one source's forecast and replaces its points from the current hour on. The
read side (``zev_forecast``) sums the stored points of a ZEV's producing metering points. Display only:
nothing here is read by billing (ADR 0044).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from allocation.read_model import PRODUCTION_METER_TYPES
from allocation.validity import civil_date, period_start_dt
from zev import access
from zev.models import MeteringPoint, Zev

from ..models import ProductionForecastPoint, SupplementaryProvider, SupplementarySource
from ..supplementary.providers import PROVIDERS
from .forecast_hours import ForecastHour, floor_hour, sum_hours

#: Points older than this are dropped by a refresh; they only exist to draw today's earlier hours.
KEEP_PAST = timedelta(hours=24)


def fetch_hours(source: SupplementarySource) -> list[ForecastHour]:
    """Ask the source's provider. Raises ``ProviderError`` (or a subclass) and ``ForecastDeferred``."""
    if source.provider == SupplementaryProvider.FORECAST_SOLAR:
        from ..supplementary.forecast_solar import ForecastSolarProvider

        return ForecastSolarProvider().fetch_forecast(source)
    return PROVIDERS[source.provider].fetch_forecast(source)


def store_hours(source: SupplementarySource, hours: list[ForecastHour], now: datetime) -> int:
    """Replace the source's points from the current hour on; drop the ones older than a day. Returns rows stored."""
    current = floor_hour(now)
    horizon = current + timedelta(hours=settings.FORECAST_HORIZON_H)
    rows = [
        ProductionForecastPoint(
            source=source, metering_point_id=source.metering_point_id, timestamp=hour.start, power_w=hour.power_w,
            power_min_w=hour.min_w, power_max_w=hour.max_w, fetched_at=now,
        )
        for hour in hours
        if current <= hour.start < horizon
    ]
    with transaction.atomic():
        ProductionForecastPoint.objects.filter(source=source, timestamp__gte=current).delete()
        ProductionForecastPoint.objects.filter(source=source, timestamp__lt=now - KEEP_PAST).delete()
        ProductionForecastPoint.objects.bulk_create(rows)
    return len(rows)


# ---- reading ----


@dataclass(frozen=True)
class PlantForecast:
    point: MeteringPoint
    hours: list[ForecastHour]
    fetched_at: datetime | None


def _hours_of(points) -> list[ForecastHour]:
    return [
        ForecastHour(start=p.timestamp, power_w=p.power_w, min_w=p.power_min_w, max_w=p.power_max_w) for p in points
    ]


def _num(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


def peak_windows(hours: list[ForecastHour]) -> list[dict]:
    """Per Swiss civil day, the longest run of hours at or above half of that day's highest hour (earliest wins a tie).

    Production only: a window says when the plants are expected to produce most, never that power is spare.
    """
    by_day: dict = {}
    for hour in hours:
        by_day.setdefault(civil_date(hour.start), []).append(hour)
    windows = []
    for day in sorted(by_day):
        day_hours = sorted(by_day[day], key=lambda h: h.start)
        top = max(h.power_w for h in day_hours)
        if top <= 0:
            continue
        threshold = top / 2
        best: list[ForecastHour] = []
        run: list[ForecastHour] = []
        for hour in day_hours:
            if hour.power_w >= threshold and (not run or hour.start == run[-1].start + timedelta(hours=1)):
                run.append(hour)
            elif hour.power_w >= threshold:
                run = [hour]
            else:
                run = []
            if len(run) > len(best):
                best = list(run)
        if best:
            windows.append({
                "date": day.isoformat(), "from": best[0].start, "to": best[-1].start + timedelta(hours=1),
                "peak_w": float(max(h.power_w for h in best)),
            })
    return windows


def load_plants(zev: Zev, now: datetime) -> tuple[list[MeteringPoint], dict]:
    """The active producing points of ``zev`` and, per point, its stored points from the start of today."""
    producing = list(
        MeteringPoint.objects.filter(zev=zev, is_active=True, meter_type__in=PRODUCTION_METER_TYPES)
        .order_by("meter_id")
    )
    since = period_start_dt(civil_date(now))
    stored: dict = {}
    for point in ProductionForecastPoint.objects.filter(
        metering_point__in=[p.pk for p in producing], timestamp__gte=since, source__enabled=True
    ).order_by("timestamp"):
        stored.setdefault(point.metering_point_id, []).append(point)
    return producing, stored


def zev_forecast(zev: Zev, *, now: datetime | None = None, viewer) -> dict:
    """The ZEV production forecast for ``viewer`` (SPEC §5.4). Managers, viewers and admins also get ``per_plant``."""
    now = now or timezone.now()
    producing, stored = load_plants(zev, now)
    plants = [(point, _hours_of(stored.get(point.pk, []))) for point in producing]
    with_forecast = [(point, hours) for point, hours in plants if hours]
    total = sum_hours(hours for _, hours in with_forecast)
    fetched = [
        p.fetched_at for rows in stored.values() for p in rows
    ]
    payload = {
        "zev_id": str(zev.pk),
        "horizon_h": settings.FORECAST_HORIZON_H,
        "complete": bool(plants) and len(with_forecast) == len(plants),
        "plants": len(plants),
        "plants_with_forecast": len(with_forecast),
        "fetched_at": max(fetched) if fetched else None,
        "hours": [
            {"start": h.start, "power_w": _num(h.power_w), "min_w": _num(h.min_w), "max_w": _num(h.max_w)} for h in total
        ],
        "peak_windows": peak_windows(total),
    }
    if access.can_view(viewer, zev):
        payload["per_plant"] = [
            {
                "metering_point_id": str(point.pk),
                "meter_id": point.meter_id,
                "hours": [
                    {"start": h.start, "power_w": _num(h.power_w), "min_w": _num(h.min_w), "max_w": _num(h.max_w)}
                    for h in hours
                ],
            }
            for point, hours in with_forecast
        ]
    return payload


def next_peak(zev: Zev, *, now: datetime | None = None) -> dict | None:
    """The coming peak window as ``{from, to, peak_w}`` for ``/live/me/``: the current or next one that has not ended."""
    now = now or timezone.now()
    producing, stored = load_plants(zev, now)
    total = sum_hours(_hours_of(stored.get(p.pk, [])) for p in producing)
    for window in peak_windows(total):
        if window["to"] > now:
            return {"from": window["from"], "to": window["to"], "peak_w": window["peak_w"]}
    return None


def latest_fetch(source_ids) -> dict:
    """Newest ``fetched_at`` per source, for health and staleness."""
    return dict(
        ProductionForecastPoint.objects.filter(source_id__in=source_ids).values_list("source_id").annotate(m=Max("fetched_at"))
    )
