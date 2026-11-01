"""Today's curve from the 5-minute buckets (SPEC-2026-live-energy-data §5.3).

The tier rule of the snapshot is applied per bucket, with a point counting as live in a bucket
when it has at least one sample in it. A bucket's values are means, so its split is a split of
means: indicative, like everything live. A bucket with nothing to say is a gap, never filled.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone as dt_timezone

from django.conf import settings

from allocation.validity import period_end_exclusive_dt, period_start_dt
from zev import access
from zev.models import Zev

from ..supplementary import own_series
from . import store
from .snapshot import (
    TIER_EXACT,
    TIER_NONE,
    classify,
    iso,
    load_topology,
    own_split,
    own_sums,
    watts,
)


def earliest_day_start(now: datetime) -> datetime:
    return now - timedelta(hours=settings.LIVE_CURVE_RETENTION_H)


def zev_curve(zev: Zev, day: date, *, now: datetime, viewer, participant_id=None) -> dict:
    """The day's buckets, plus the viewer's own history of that day for the hand-over (SPEC §5.3).

    ``participant_id`` (manager, viewer, admin) makes "own" mean that participant: the ``own_*`` values
    of the buckets and the history. The view has already checked who may ask. History and live are
    never merged here: ``own_history`` is stored data, the ``own_*`` bucket values are live, and the
    page decides where one hands over to the other (history up to ``own_history_through``).
    """
    topology = load_topology(zev, today=day)
    start, end = period_start_dt(day), min(period_end_exclusive_dt(day), now)
    detailed = access.can_view(viewer, zev)

    buckets = store.buckets_many(topology.source_ids(), start, end) if end > start else {}
    by_point = {
        point.pk: buckets.get(str(topology.sources[point.pk].pk), {})
        for point in topology.points
        if point.pk in topology.sources
    }
    connection = buckets.get(str(topology.connection.pk), {}) if topology.connection is not None else {}
    history_ids = own_series.participant_ids_for(viewer, zev, participant_id)
    own_points = topology.points_of(history_ids) if participant_id else topology.own_points(viewer)
    has_own = any(point.pk in topology.sources for point in own_points)

    width = settings.LIVE_CURVE_BUCKET_S
    rows = []
    epoch = store.bucket_epoch(start)
    while epoch < end.timestamp():
        rows.append(_bucket(topology, epoch, by_point, connection, own_points, detailed, has_own))
        epoch += width
    through = own_series.history_through(history_ids)
    return {
        "date": day.isoformat(),
        "bucket_s": width,
        "buckets": rows,
        "own_history": own_series.own_history_of_day(history_ids, day),
        "own_history_through": iso(through),
    }


def _bucket(topology, epoch, by_point, connection, own_points, detailed, has_own) -> dict:
    def mean(buckets):
        found = buckets.get(epoch)
        return None if found is None else found.meter_power_w

    power = {point.pk: mean(by_point.get(point.pk, {})) for point in topology.points}
    totals = classify(
        {point.pk: power[point.pk] for point in topology.producing},
        {point.pk: power[point.pk] for point in topology.consuming},
        connection_w=mean(connection),
        physical=topology.physical,
    )
    row = {"start": iso(datetime.fromtimestamp(epoch, tz=dt_timezone.utc)), "tier": totals.tier}
    if totals.tier == TIER_NONE:
        return row
    row["production_w"] = watts(totals.production_w)
    if totals.tier == TIER_EXACT:
        row["consumption_w"] = watts(totals.consumption_w)
        row["surplus_w"] = watts(totals.surplus_w)
    if has_own:
        complete = all(power[point.pk] is not None for point in own_points)
        consumption, production = own_sums(own_points, power) if complete else (None, None)
        row["own_consumption_w"] = watts(consumption)
        row["own_production_w"] = watts(production)
        row["own_local_w"] = own_split(consumption, production, totals)["local_w"] if complete else None
    if detailed:
        row["points"] = [
            {"metering_point_id": str(point.pk), "target": "metering_point", "meter_power_w": watts(power[point.pk])}
            for point in topology.points
            if power[point.pk] is not None
        ]
        if (value := mean(connection)) is not None:
            row["points"].append({"metering_point_id": None, "target": "connection_point", "meter_power_w": watts(value)})
    return row
