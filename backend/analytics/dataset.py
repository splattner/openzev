"""The analytics series: a scoped, tidy dataset built on the allocation read model.

One row per (bucket, [metering point], [participant], direction) with the energy
split the invoices use (ADR 0013): consumption (``in``) is local or grid,
production (``out``) is sold locally or fed in. The splits come from
:mod:`allocation.read_model` and :mod:`allocation.split`, so a sum over the rows
reproduces the invoice and dashboard figures for the same period.

What the caller may see is decided here, once (:class:`Visibility`), not by the
view or the renderer: a participant gets only their own rows, a community meter
they merely share is never named, and ZEV-wide totals are refused below a
minimum community size.

The dataset is computed per request. :data:`~django.conf.settings.ANALYTICS_MAX_READINGS`
bounds the work until an hourly fact table replaces the live computation (see the
spec, §9); ``build_series`` is the seam a table-backed implementation slots into.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone as dt_timezone
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings

from allocation.errors import AllocationError
from allocation.read_model import (
    CONSUMPTION,
    PRODUCTION,
    community_totals_by_timestamp,
    eligible_participant_shares,
    iter_allocated_readings,
)
from allocation.validity import business_tz, civil_date, period_window
from allocation.windows import AssignmentWindows
from metering.models import MeterReading
from zev.models import AllocationMode, MeteringPoint, Participant

GRANULARITIES = ("15min", "hour", "day", "week", "month", "year")
GROUP_BYS = ("metering_point", "participant", "zev")
DIRECTIONS = ("in", "out")
SOURCE_METERING = "metering"

# Longest inclusive span, in days, per granularity. Fine buckets are only useful
# for short windows and produce the most rows per day.
MAX_SPAN_DAYS = {"15min": 14, "hour": 100, "day": 400, "week": 3660, "month": 3660, "year": 3660}

COLUMNS = (
    "bucket_start",
    "metering_point",
    "participant",
    "participant_id",
    "direction",
    "total_kwh",
    "local_kwh",
    "grid_kwh",
    "feed_in_kwh",
    "source",
)

_KWH = Decimal("0.001")
_ZERO = Decimal("0")


class DatasetError(Exception):
    """The request cannot be answered; ``code`` is machine-readable, ``status`` the HTTP status."""

    status = 400

    def __init__(self, message: str, code: str, status: int | None = None):
        super().__init__(message)
        self.message = message
        self.code = code
        if status is not None:
            self.status = status


@dataclass(frozen=True)
class SeriesQuery:
    zev: object
    start: date
    end: date  # inclusive
    granularity: str = "day"
    group_by: str = "metering_point"
    directions: frozenset = frozenset(DIRECTIONS)
    participant_id: uuid.UUID | None = None
    metering_point_id: uuid.UUID | None = None


@dataclass(frozen=True)
class Visibility:
    """What a caller may see inside one ZEV.

    ``full``: every row, every name (admin, manager, viewer, or a token scoped to
    the whole ZEV). Otherwise only the rows attributed to ``participant_ids``.
    """

    full: bool
    participant_ids: frozenset = frozenset()

    @property
    def scope(self) -> str:
        return "zev" if self.full else "participant"

    def sees(self, participant_id) -> bool:
        return self.full or participant_id in self.participant_ids


@dataclass
class Series:
    rows: list[dict]
    meta: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Validation of the request against the limits
# ---------------------------------------------------------------------------

def check_span(start: date, end: date, granularity: str) -> None:
    if end < start:
        raise DatasetError("'to' must not be before 'from'.", "invalid_range")
    days = (end - start).days + 1
    limit = MAX_SPAN_DAYS[granularity]
    if days > limit:
        raise DatasetError(
            f"A {granularity} series covers at most {limit} days; the range has {days}. "
            "Narrow the range or choose a coarser granularity.",
            "range_too_large",
        )


def _check_reading_budget(zev, start_dt: datetime, end_dt: datetime) -> None:
    count = MeterReading.objects.filter(
        metering_point__zev=zev, timestamp__gte=start_dt, timestamp__lt=end_dt,
    ).count()
    if count > settings.ANALYTICS_MAX_READINGS:
        raise DatasetError(
            f"The range holds {count} readings, more than the {settings.ANALYTICS_MAX_READINGS} "
            "one request may scan. Narrow the range.",
            "range_too_large",
        )


# ---------------------------------------------------------------------------
# Bucketing (Swiss civil time, ADR 0026)
# ---------------------------------------------------------------------------

def _local_midnight(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=business_tz())


def bucket_start(ts: datetime, granularity: str) -> datetime:
    """The start of the bucket ``ts`` falls in, as an aware Europe/Zurich datetime.

    Sub-day buckets are cut on the UTC instant (Zurich's offset is a whole number
    of hours, so the boundaries agree, and the two 02:00 hours of the autumn
    change stay apart); day and coarser buckets follow the civil date, so a DST
    day is a 23 or 25 hour bucket (dashboard ``_bucket_trunc`` does the same).
    """
    tz = business_tz()
    if granularity == "15min":
        utc = ts.astimezone(dt_timezone.utc)
        return utc.replace(minute=utc.minute - utc.minute % 15, second=0, microsecond=0).astimezone(tz)
    if granularity == "hour":
        utc = ts.astimezone(dt_timezone.utc)
        return utc.replace(minute=0, second=0, microsecond=0).astimezone(tz)
    day = civil_date(ts)
    if granularity == "week":
        day -= timedelta(days=day.weekday())
    elif granularity == "month":
        day = day.replace(day=1)
    elif granularity == "year":
        day = day.replace(month=1, day=1)
    return _local_midnight(day)


# ---------------------------------------------------------------------------
# Attribution
# ---------------------------------------------------------------------------

def _min_participants(shares_by_date: dict) -> int:
    """The fewest eligible participants on any day that had one."""
    return min((len(day_shares) for day_shares in shares_by_date.values()), default=0)


def _attribute(reading, shares_by_date):
    """``[(participant_id | None, share, community)]`` a reading is attributed to.

    A personal assignment: its holder, in full. A community assignment: each
    eligible participant, by weight. A gap, or a community day with nobody
    eligible: no participant (``None``), so the rows still add up to the ZEV
    totals.
    """
    if reading.holder_id is None:
        return [(None, Decimal("1"), False)]
    if reading.allocation_mode == AllocationMode.COMMUNITY:
        day_shares = shares_by_date.get(civil_date(reading.timestamp))
        if not day_shares:
            return [(None, Decimal("1"), True)]
        return [(pid, share, True) for pid, share in day_shares.items()]
    return [(reading.holder_id, Decimal("1"), False)]


def _participant_names(participant_ids) -> dict:
    ids = {pid for pid in participant_ids if pid is not None}
    if not ids:
        return {}
    return {
        participant.id: participant.full_name
        for participant in Participant.objects.filter(id__in=ids).select_related("party")
    }


# ---------------------------------------------------------------------------
# The series
# ---------------------------------------------------------------------------

def build_series(query: SeriesQuery, visibility: Visibility) -> Series:
    zev = query.zev
    check_span(query.start, query.end, query.granularity)
    if query.participant_id is not None and not visibility.sees(query.participant_id):
        raise DatasetError("You may only query your own data.", "participant_not_visible", 403)

    start_dt, end_dt = period_window(query.start, query.end)
    _check_reading_budget(zev, start_dt, end_dt)

    try:
        if query.group_by == "zev":
            rows = _zev_rows(query, visibility, start_dt, end_dt)
        else:
            rows = _attributed_rows(query, visibility, start_dt, end_dt)
    except AllocationError as exc:
        raise DatasetError(
            "The readings of this range are inconsistent, so they cannot be split reliably "
            f"({exc}). Check the data quality page.",
            "inconsistent_readings",
            422,
        ) from exc

    if len(rows) > settings.ANALYTICS_MAX_ROWS:
        raise DatasetError(
            f"The series has {len(rows)} rows, more than the {settings.ANALYTICS_MAX_ROWS} one request "
            "may return. Narrow the range or choose a coarser granularity or grouping.",
            "too_many_rows",
        )

    meta = {
        "zev": str(zev.pk),
        "scope": visibility.scope,
        "from": query.start.isoformat(),
        "to": query.end.isoformat(),
        "granularity": query.granularity,
        "group_by": query.group_by,
        "timezone": str(business_tz()),
        "row_count": len(rows),
    }
    return Series(rows=rows, meta=meta)


def _accumulate(acc: dict, key: tuple, total: Decimal, local: Decimal, other: Decimal) -> None:
    cell = acc.get(key)
    if cell is None:
        acc[key] = [total, local, other]
    else:
        cell[0] += total
        cell[1] += local
        cell[2] += other


def _kwh(value: Decimal) -> float:
    return float(value.quantize(_KWH, rounding=ROUND_HALF_UP))


def _row(bucket, metering_point, participant_id, participant_name, direction, cell) -> dict:
    total, local, other = cell
    return {
        "bucket_start": bucket.isoformat(),
        "metering_point": metering_point,
        "participant": participant_name,
        "participant_id": str(participant_id) if participant_id is not None else None,
        "direction": direction,
        "total_kwh": _kwh(total),
        "local_kwh": _kwh(local),
        # Consumption splits into local and grid, production into local and
        # feed-in; the column that does not apply to a direction is null.
        "grid_kwh": _kwh(other) if direction == "in" else None,
        "feed_in_kwh": _kwh(other) if direction == "out" else None,
        "source": SOURCE_METERING,
    }


def _zev_rows(query: SeriesQuery, visibility: Visibility, start_dt, end_dt) -> list[dict]:
    """ZEV-wide physical totals per bucket and direction."""
    if not visibility.full:
        shares_by_date = eligible_participant_shares(query.zev, query.start, query.end)
        minimum = settings.ANALYTICS_MIN_PARTICIPANTS_FOR_ZEV_AGGREGATE
        if _min_participants(shares_by_date) < minimum:
            raise DatasetError(
                f"ZEV-wide totals are shown to participants only for communities with at least "
                f"{minimum} participants on every day of the range.",
                "aggregate_suppressed",
                403,
            )

    cons_by_ts, prod_by_ts = community_totals_by_timestamp(query.zev, start_dt, end_dt)
    acc: dict = {}
    for ts in cons_by_ts.keys() | prod_by_ts.keys():
        consumed = cons_by_ts.get(ts, _ZERO)
        produced = prod_by_ts.get(ts, _ZERO)
        local = min(consumed, produced)
        bucket = bucket_start(ts, query.granularity)
        if "in" in query.directions and consumed:
            _accumulate(acc, (bucket, "in"), consumed, local, consumed - local)
        if "out" in query.directions and produced:
            _accumulate(acc, (bucket, "out"), produced, local, produced - local)

    return [
        _row(bucket, None, None, None, direction, cell)
        for (bucket, direction), cell in sorted(acc.items(), key=lambda item: (item[0][0], item[0][1]))
    ]


def _attributed_rows(query: SeriesQuery, visibility: Visibility, start_dt, end_dt) -> list[dict]:
    zev = query.zev
    windows = AssignmentWindows.for_zev(zev, query.start, query.end)
    shares_by_date = eligible_participant_shares(zev, query.start, query.end)
    cons_by_ts, prod_by_ts = community_totals_by_timestamp(zev, start_dt, end_dt)
    by_meter = query.group_by == "metering_point"

    kinds = []
    if "in" in query.directions:
        kinds.append((CONSUMPTION, "in"))
    if "out" in query.directions:
        kinds.append((PRODUCTION, "out"))

    acc: dict = {}
    bucket_cache: dict = {}
    for kind, direction in kinds:
        for reading in iter_allocated_readings(
            zev, start_dt, end_dt, kind=kind, windows=windows,
            consumption_by_ts=cons_by_ts, production_by_ts=prod_by_ts,
        ):
            if query.metering_point_id is not None and reading.metering_point_id != query.metering_point_id:
                continue
            if kind == CONSUMPTION:
                local, other = reading.split.local_kwh, reading.split.grid_kwh
            else:
                local, other = reading.split.local_sold_kwh, reading.split.exported_kwh

            ts = reading.timestamp
            bucket = bucket_cache.get(ts)
            if bucket is None:
                bucket = bucket_cache[ts] = bucket_start(ts, query.granularity)

            for participant_id, share, community in _attribute(reading, shares_by_date):
                if not visibility.sees(participant_id):
                    continue
                if query.participant_id is not None and participant_id != query.participant_id:
                    continue
                if not visibility.full and community and query.metering_point_id is not None:
                    # A share of a meter somebody else holds is not addressable by that meter.
                    continue
                # A community share of another participant's meter is never tied to that
                # meter for a participant: the identifier would name a neighbour's connection.
                meter = reading.metering_point_id if by_meter and (visibility.full or not community) else None
                _accumulate(
                    acc, (bucket, meter, participant_id, direction),
                    reading.energy_kwh * share, local * share, other * share,
                )

    meter_ids = {
        mp_id: meter_id
        for mp_id, meter_id in MeteringPoint.objects.filter(
            id__in={key[1] for key in acc if key[1] is not None}
        ).values_list("id", "meter_id")
    }
    names = _participant_names(key[2] for key in acc)

    def sort_key(item):
        bucket, meter, participant_id, direction = item[0]
        return (bucket, meter_ids.get(meter) or "", names.get(participant_id) or "", str(participant_id), direction)

    return [
        _row(bucket, meter_ids.get(meter), participant_id, names.get(participant_id), direction, cell)
        for (bucket, meter, participant_id, direction), cell in sorted(acc.items(), key=sort_key)
    ]
