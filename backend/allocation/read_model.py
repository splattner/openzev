"""Allocation read-model — the shared fetch/resolve/split orchestration (ADR 0013 follow-up).

``allocation.split`` owns the formulas and ``allocation.windows`` owns the
assignment index. This module composes the two into the iteration every
consumer needs, so the "query readings -> build per-timestamp community
totals -> loop -> resolve holder -> call split" core is written once instead
of copy-pasted per consumer (engine, PDF stats, PDF charts, annual statement,
dashboards).

Two building blocks:

- :func:`community_totals_by_timestamp` — the *physical* per-timestamp ZEV
  totals (every meter, regardless of assignment; ADR 0013 pool decision).
- :func:`iter_allocated_readings` — a stream of per-(metering point,
  timestamp) groups, each resolved to its holder at that timestamp and split
  against the physical totals.

Consumers still own their own accumulation (CHF pricing, hourly/monthly
buckets, timelines); this removes only the duplicated fetch-and-filter core.
Gap readings (timestamp in an assignment gap, or predating every window) are
yielded with ``holder_id is None`` — the energy is real and already counted in
the physical totals, but belongs to no participant — so each consumer can skip
or count them as it sees fit.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from django.db import models

from metering.models import MeterReading, ReadingDirection
from zev.models import MeteringPoint, MeteringPointType

from .split import (
    ConsumptionSplit,
    ProductionSplit,
    split_consumption,
    split_production,
)
from .windows import AssignmentWindows

CONSUMPTION_METER_TYPES = [MeteringPointType.CONSUMPTION, MeteringPointType.BIDIRECTIONAL]
PRODUCTION_METER_TYPES = [MeteringPointType.PRODUCTION, MeteringPointType.BIDIRECTIONAL]

CONSUMPTION = "consumption"
PRODUCTION = "production"

_KINDS = {
    CONSUMPTION: (CONSUMPTION_METER_TYPES, ReadingDirection.IN),
    PRODUCTION: (PRODUCTION_METER_TYPES, ReadingDirection.OUT),
}


def community_totals_by_timestamp(zev, start_dt: datetime, end_dt: datetime) -> tuple[dict, dict]:
    """Physical per-timestamp community totals for ``zev`` in ``[start_dt, end_dt)``.

    Returns ``(consumption_by_ts, production_by_ts)``, each mapping a UTC
    timestamp to the summed kWh across every metering point of the relevant
    type. ``zev`` is a ``Zev`` instance or its pk. *Physical* means the totals
    cover every meter regardless of assignment (ADR 0013 pool decision): a
    never-assigned meter still feeds the pool even though its readings are
    billed to nobody.
    """

    def _by_ts(meter_types, direction) -> dict:
        metering_points = MeteringPoint.objects.filter(zev=zev, meter_type__in=meter_types)
        return {
            row["timestamp"]: row["total_kwh"] or Decimal("0")
            for row in MeterReading.objects.filter(
                metering_point__in=metering_points,
                timestamp__gte=start_dt,
                timestamp__lt=end_dt,
                direction=direction,
            )
            .values("timestamp")
            .annotate(total_kwh=models.Sum("energy_kwh"))
        }

    return (
        _by_ts(CONSUMPTION_METER_TYPES, ReadingDirection.IN),
        _by_ts(PRODUCTION_METER_TYPES, ReadingDirection.OUT),
    )


@dataclass(frozen=True)
class AllocatedReading:
    """One (metering point, timestamp) group, resolved to a holder and split.

    ``energy_kwh`` is the summed reading for that metering point at that
    timestamp; ``zev_consumption_kwh``/``zev_production_kwh`` are the physical
    community totals the split was computed against. ``holder_id`` is the
    participant's UUID (``Participant.id`` is a ``UUIDField``) or ``None`` for a
    gap reading (no assignment active at the timestamp). ``split`` is ``None``
    when the caller passed ``with_split=False``.
    """

    metering_point_id: uuid.UUID
    timestamp: datetime
    holder_id: uuid.UUID | None
    energy_kwh: Decimal
    zev_consumption_kwh: Decimal
    zev_production_kwh: Decimal
    split: ConsumptionSplit | ProductionSplit | None


def iter_allocated_readings(
    zev,
    start_dt: datetime,
    end_dt: datetime,
    *,
    kind: str,
    windows: AssignmentWindows,
    consumption_by_ts: dict | None = None,
    production_by_ts: dict | None = None,
    with_split: bool = True,
):
    """Yield an :class:`AllocatedReading` per (metering point, timestamp) group.

    ``kind`` is :data:`CONSUMPTION` or :data:`PRODUCTION`. ``windows`` resolves
    the holder at each timestamp (callers pass their ``AssignmentWindows.for_zev``
    so the index is fetched once and can be reused elsewhere). The physical
    community totals are fetched once via :func:`community_totals_by_timestamp`
    unless precomputed maps are passed in.

    The reading filter uses the caller's ``[start_dt, end_dt)`` bounds exactly,
    so migrating a consumer keeps its reading set byte-identical.

    ``with_split`` controls whether the per-reading split is computed. The
    default (``True``) runs ``split_consumption``/``split_production`` — and
    their fail-fast non-negative contracts — for every yielded reading, which is
    what the invoice engine and the consumption PDF stats want. A consumer that
    only needs holder-attributed totals (e.g. the PDF stats production loop,
    which sums each holder's production and never reads ``.split``) passes
    ``False``: the split is skipped, so a corrupt reading (a meter correction
    or bad import with a negative ``energy_kwh``) is attributed to its holder
    instead of raising for the whole community. The fail-fast contract on a
    participant's *own* readings is still enforced by the invoice engine, which
    iterates that participant's meters and calls ``split_production`` directly.
    """
    try:
        meter_types, direction = _KINDS[kind]
    except KeyError:
        raise ValueError(f"kind must be CONSUMPTION or PRODUCTION, got {kind!r}") from None

    if consumption_by_ts is None or production_by_ts is None:
        fetched_cons, fetched_prod = community_totals_by_timestamp(zev, start_dt, end_dt)
        if consumption_by_ts is None:
            consumption_by_ts = fetched_cons
        if production_by_ts is None:
            production_by_ts = fetched_prod

    metering_points = MeteringPoint.objects.filter(zev=zev, meter_type__in=meter_types)
    rows = (
        MeterReading.objects.filter(
            metering_point__in=metering_points,
            timestamp__gte=start_dt,
            timestamp__lt=end_dt,
            direction=direction,
        )
        .values("metering_point_id", "timestamp")
        .annotate(energy_kwh=models.Sum("energy_kwh"))
    )

    for row in rows:
        ts = row["timestamp"]
        metering_point_id = row["metering_point_id"]
        energy_kwh = row["energy_kwh"] or Decimal("0")
        zev_consumption = consumption_by_ts.get(ts, Decimal("0"))
        zev_production = production_by_ts.get(ts, Decimal("0"))
        if not with_split:
            split = None
        elif kind == CONSUMPTION:
            split = split_consumption(energy_kwh, zev_consumption, zev_production)
        else:
            split = split_production(energy_kwh, zev_production, zev_consumption)
        yield AllocatedReading(
            metering_point_id=metering_point_id,
            timestamp=ts,
            holder_id=windows.participant_at(metering_point_id, ts),
            energy_kwh=energy_kwh,
            zev_consumption_kwh=zev_consumption,
            zev_production_kwh=zev_production,
            split=split,
        )
