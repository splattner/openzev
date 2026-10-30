"""The ZEV's live snapshot (SPEC-2026-live-energy-data §5.2, ADR 0044).

What is shown is *measured*: a source's sample is used while it is at most ``LIVE_MAX_AGE_S`` old
and never otherwise, and nothing fills a gap. The ZEV figures depend on how much of the ZEV is
covered (the tier):

* ``none``: no producing metering point exists, or one of them has no fresh value. Nothing is
  claimed about the ZEV, because a partial production figure is not "the ZEV's production".
* ``production``: every producing point is fresh, but the consumption is not known exactly. Only
  the production is shown, never a surplus, a split or a bound.
* ``exact``: production is complete *and* the consumption is known, from every consuming point or
  (physical ZEV) from the grid connection point, ``C = P + N``. Only now the surplus, the local
  share and each participant's own split are shown.

The split is the billing arithmetic (``allocation.split``) applied to watts instead of kWh. This
module reads from ``allocation/``; nothing there may read from here (ADR 0030, ADR 0044).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable, Mapping

from django.conf import settings
from django.utils import timezone

from allocation.errors import InvalidAllocationInputError
from allocation.read_model import CONSUMPTION_METER_TYPES, PRODUCTION_METER_TYPES
from allocation.split import split_consumption, split_production
from allocation.validity import active_on, civil_date
from zev import access
from zev.models import AllocationMode, MeteringPoint, MeteringPointAssignment, Zev, ZevType

from ..models import SourceTarget, SupplementarySource
from . import store

ZERO = Decimal("0")
TENTH = Decimal("0.1")

TIER_NONE = "none"
TIER_PRODUCTION = "production"
TIER_EXACT = "exact"
BASIS_ALL_POINTS = "all_points"
BASIS_CONNECTION_POINT = "connection_point"


def watts(value: Decimal | None) -> float | None:
    """A power as a JSON number with one decimal (half up), ``None`` stays ``None``."""
    return None if value is None else float(value.quantize(TENTH, rounding=ROUND_HALF_UP))


def iso(moment: datetime | None) -> str | None:
    return None if moment is None else moment.isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class Totals:
    """What the covered part of a ZEV allows to say. Powers are in W, ``None`` where the tier forbids them."""

    tier: str
    basis: str | None = None
    production_w: Decimal | None = None
    consumption_w: Decimal | None = None

    @property
    def surplus_w(self) -> Decimal | None:
        if self.tier != TIER_EXACT:
            return None
        return max(self.production_w - self.consumption_w, ZERO)

    @property
    def grid_import_w(self) -> Decimal | None:
        if self.tier != TIER_EXACT:
            return None
        return max(self.consumption_w - self.production_w, ZERO)

    @property
    def local_share_pct(self) -> Decimal | None:
        if self.tier != TIER_EXACT or self.consumption_w <= 0:
            return None
        return min(self.production_w, self.consumption_w) / self.consumption_w * 100


def classify(
    producing: Mapping[object, Decimal | None],
    consuming: Mapping[object, Decimal | None],
    *,
    connection_w: Decimal | None,
    physical: bool,
) -> Totals:
    """The tier and ZEV totals from one meter power per point, ``None`` where a point has no fresh value.

    ``producing`` and ``consuming`` map a metering point to its ``meter_power_w`` (positive: drawn
    in, negative: fed out); a bidirectional point is in both. ``connection_w`` is the net power at
    the grid connection (``None`` when absent or not fresh). A production-type point's own draw is
    ignored and so is a consumption-type point's feed-in, as in billing.
    """
    if not producing or any(value is None for value in producing.values()):
        return Totals(TIER_NONE)
    production = sum((max(-value, ZERO) for value in producing.values()), ZERO)
    if all(value is not None for value in consuming.values()):
        consumption = sum((max(value, ZERO) for value in consuming.values()), ZERO)
        return Totals(TIER_EXACT, BASIS_ALL_POINTS, production, consumption)
    if physical and connection_w is not None:
        return Totals(TIER_EXACT, BASIS_CONNECTION_POINT, production, max(production + connection_w, ZERO))
    return Totals(TIER_PRODUCTION, None, production, None)


def own_split(own_consumption: Decimal | None, own_production: Decimal | None, totals: Totals) -> dict:
    """A participant's local/grid and to-ZEV/to-grid split, through the billing arithmetic.

    Inputs that break the split's contract (a draw above the ZEV total, which timing between a
    household meter and the connection point can cause) withhold the split instead of clamping it.
    """
    blank = {"local_w": None, "grid_w": None, "to_zev_w": None, "to_grid_w": None}
    if totals.tier != TIER_EXACT:
        return blank
    try:
        if own_consumption is not None:
            local, grid = split_consumption(own_consumption, totals.consumption_w, totals.production_w)
            blank["local_w"], blank["grid_w"] = watts(local), watts(grid)
        if own_production is not None:
            to_zev, to_grid = split_production(own_production, totals.production_w, totals.consumption_w)
            blank["to_zev_w"], blank["to_grid_w"] = watts(to_zev), watts(to_grid)
    except InvalidAllocationInputError:
        return {**{key: None for key in blank}, "split_withheld_reason": "inconsistent"}
    return blank


def own_sums(points: Iterable[MeteringPoint], power: Mapping[object, Decimal | None]) -> tuple[Decimal | None, Decimal | None]:
    """The viewer's measured consumption and production, ``None`` for a side they have no point on."""
    consumption = production = None
    for point in points:
        value = power[point.pk]
        if point.meter_type in CONSUMPTION_METER_TYPES:
            consumption = (consumption or ZERO) + max(value, ZERO)
        if point.meter_type in PRODUCTION_METER_TYPES:
            production = (production or ZERO) + max(-value, ZERO)
    return consumption, production


@dataclass
class Topology:
    zev: Zev
    points: list[MeteringPoint]
    sources: dict[object, SupplementarySource]  # metering point id -> its live source
    connection: SupplementarySource | None
    holders: dict[object, object]  # metering point id -> the participant holding it personally today

    @property
    def producing(self) -> list[MeteringPoint]:
        return [point for point in self.points if point.meter_type in PRODUCTION_METER_TYPES]

    @property
    def consuming(self) -> list[MeteringPoint]:
        return [point for point in self.points if point.meter_type in CONSUMPTION_METER_TYPES]

    @property
    def physical(self) -> bool:
        return self.zev.zev_type == ZevType.ZEV

    def source_ids(self) -> list:
        ids = [source.pk for source in self.sources.values()]
        if self.connection is not None:
            ids.append(self.connection.pk)
        return ids

    def own_points(self, user) -> list[MeteringPoint]:
        """Active points ``user`` holds personally today. Community-mode points are nobody's."""
        return [
            point for point in self.points
            if (holder := self.holders.get(point.pk)) is not None and holder.user_id == user.pk
        ]


def load_topology(zev: Zev, *, today: date | None = None) -> Topology:
    points = list(MeteringPoint.objects.filter(zev=zev, is_active=True).order_by("meter_id"))
    live = SupplementarySource.objects.filter(zev=zev, provides_live=True, enabled=True)
    sources = {}
    connection = None
    for source in live:
        if source.target == SourceTarget.CONNECTION_POINT:
            connection = source
        else:
            sources[source.metering_point_id] = source
    assignments = active_on(
        MeteringPointAssignment.objects.filter(
            metering_point__in=[point.pk for point in points], allocation_mode=AllocationMode.PERSONAL
        ),
        today or civil_date(timezone.now()),
    ).select_related("participant__party")
    holders = {assignment.metering_point_id: assignment.participant for assignment in assignments}
    return Topology(zev, points, sources, connection, holders)


def live_state(source: SupplementarySource | None, sample: store.LiveSample | None, now: datetime) -> str:
    """``fresh``, ``stale`` (has reported before, not recently) or ``never`` (also: no source)."""
    if sample is not None and sample.is_fresh(now):
        return "fresh"
    if source is not None and source.live_last_seen_at is not None:
        return "stale"
    return "never"


def zev_snapshot(zev: Zev, *, now: datetime | None = None, viewer, topology: Topology | None = None) -> dict:
    """The snapshot of ``zev`` for ``viewer`` (SPEC §5.2). Managers, viewers and admins also get ``points``."""
    now = now or timezone.now()
    topology = topology or load_topology(zev, today=civil_date(now))
    samples = store.latest_many(topology.source_ids())

    def sample_of(source) -> store.LiveSample | None:
        found = samples.get(str(source.pk)) if source is not None else None
        return found if found is not None and found.is_fresh(now) else None

    fresh: dict[object, store.LiveSample | None] = {
        point.pk: sample_of(topology.sources.get(point.pk)) for point in topology.points
    }
    power = {pk: None if sample is None else sample.meter_power_w for pk, sample in fresh.items()}
    connection_sample = sample_of(topology.connection)
    totals = classify(
        {point.pk: power[point.pk] for point in topology.producing},
        {point.pk: power[point.pk] for point in topology.consuming},
        connection_w=None if connection_sample is None else connection_sample.meter_power_w,
        physical=topology.physical,
    )

    used: list[datetime] = []
    if totals.tier != TIER_NONE:
        used += [fresh[point.pk].timestamp for point in topology.producing]
        if totals.basis == BASIS_ALL_POINTS:
            used += [fresh[point.pk].timestamp for point in topology.consuming]
        elif totals.basis == BASIS_CONNECTION_POINT:
            used.append(connection_sample.timestamp)

    own = _own_block(topology, viewer, fresh, power, totals, used)

    consuming = topology.consuming
    snapshot = {
        "zev_id": str(zev.pk),
        "as_of": None,
        "tier": totals.tier,
        "consumption_basis": totals.basis,
        "production_w": watts(totals.production_w),
        "consumption_w": watts(totals.consumption_w),
        "surplus_w": watts(totals.surplus_w),
        "grid_import_w": watts(totals.grid_import_w),
        "local_share_pct": watts(totals.local_share_pct),
        "coverage": {
            "producing_points": len(topology.producing),
            "producing_fresh": sum(1 for point in topology.producing if fresh[point.pk] is not None),
            "consuming_points": len(consuming),
            "consuming_fresh": sum(1 for point in consuming if fresh[point.pk] is not None),
            "connection_point": (
                live_state(topology.connection, connection_sample, now) if topology.connection is not None else None
            ),
        },
        "own": own,
        "max_age_s": settings.LIVE_MAX_AGE_S,
    }
    snapshot["as_of"] = iso(min(used)) if used else None
    if access.can_view(viewer, zev):
        snapshot["points"] = _points(topology, samples, fresh, connection_sample, now)
    return snapshot


def _own_block(topology, viewer, fresh, power, totals, used) -> dict | None:
    held = topology.own_points(viewer)
    if not any(point.pk in topology.sources for point in held):
        return None
    points_fresh = sum(1 for point in held if fresh[point.pk] is not None)
    complete = points_fresh == len(held)
    block = {
        "consumption_w": None, "local_w": None, "grid_w": None,
        "production_w": None, "to_zev_w": None, "to_grid_w": None,
        "gross": {"production_w": None, "consumption_w": None},
        "complete": complete, "points": len(held), "points_fresh": points_fresh,
    }
    if not complete:
        return block
    consumption, production = own_sums(held, power)
    block["consumption_w"], block["production_w"] = watts(consumption), watts(production)
    block.update(own_split(consumption, production, totals))
    block["gross"] = {
        "production_w": _gross_sum(fresh[point.pk].production_w for point in held),
        "consumption_w": _gross_sum(fresh[point.pk].consumption_w for point in held),
    }
    used += [fresh[point.pk].timestamp for point in held]
    return block


def _gross_sum(values: Iterable[Decimal | None]) -> float | None:
    """The sum of an optional gross value, only when every point reported it."""
    values = list(values)
    if not values or any(value is None for value in values):
        return None
    return watts(sum(values, ZERO))


def _points(topology, samples, fresh, connection_sample, now) -> list[dict]:
    def entry(point, source, sample) -> dict:
        return {
            "metering_point_id": str(point.pk) if point is not None else None,
            "target": SourceTarget.METERING_POINT if point is not None else SourceTarget.CONNECTION_POINT,
            "meter_id": point.meter_id if point is not None else None,
            "meter_type": point.meter_type if point is not None else None,
            "participant_name": (
                holder.display_name if point is not None and (holder := topology.holders.get(point.pk)) else None
            ),
            "held_by": source.held_by if source is not None else None,
            "live_state": live_state(source, sample, now),
            "meter_power_w": None if sample is None else watts(sample.meter_power_w),
            "age_s": None if sample is None else int(sample.age_s(now)),
            "source_id": str(source.pk) if source is not None else None,
        }

    rows = [entry(point, topology.sources.get(point.pk), fresh[point.pk]) for point in topology.points]
    if topology.connection is not None:
        rows.append(entry(None, topology.connection, connection_sample))
    return rows
