"""Live samples in the cache (SPEC-2026-live-energy-data §4.4, ADR 0044).

Nothing here touches the database. A source's *latest* sample lives for ``LIVE_MAX_AGE_S``; a
5-minute bucket per source keeps the running mean for ``LIVE_CURVE_RETENTION_H``, so today's curve
survives a few minutes of silence but not a cache flush, which is accepted.

Sign convention (``meter_power_w``): positive is power drawn **in** through the meter, negative is
power fed **out**. This is the quantity the allocation uses.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal

from django.conf import settings
from django.core.cache import cache

PREFIX = "live:v1:"
_GET_MANY_CHUNK = 1000


@dataclass(frozen=True)
class LiveSample:
    source_id: str
    timestamp: datetime
    received_at: datetime
    meter_power_w: Decimal
    production_w: Decimal | None = None
    consumption_w: Decimal | None = None

    def age_s(self, now: datetime) -> float:
        return max((now - self.timestamp).total_seconds(), 0.0)

    def is_fresh(self, now: datetime) -> bool:
        return self.age_s(now) <= settings.LIVE_MAX_AGE_S


@dataclass(frozen=True)
class Bucket:
    """The mean of the samples that arrived in one bucket; ``None`` where no sample carried the field."""

    start: datetime
    n: int
    meter_power_w: Decimal
    production_w: Decimal | None
    consumption_w: Decimal | None


def _latest_key(source_id) -> str:
    return f"{PREFIX}src:{source_id}:latest"


def _bucket_key(source_id, epoch: int) -> str:
    return f"{PREFIX}src:{source_id}:b:{epoch}"


def _floor_key(source_id) -> str:
    return f"{PREFIX}src:{source_id}:last_push"


def bucket_epoch(moment: datetime) -> int:
    width = settings.LIVE_CURVE_BUCKET_S
    return int(moment.timestamp()) // width * width


def _dec(value) -> Decimal | None:
    return None if value is None else Decimal(value)


def _encode(sample: LiveSample) -> str:
    return json.dumps(
        {
            "t": sample.timestamp.isoformat(),
            "r": sample.received_at.isoformat(),
            "m": str(sample.meter_power_w),
            "p": None if sample.production_w is None else str(sample.production_w),
            "c": None if sample.consumption_w is None else str(sample.consumption_w),
        }
    )


def _decode(source_id, raw: str) -> LiveSample:
    data = json.loads(raw)
    return LiveSample(
        source_id=str(source_id),
        timestamp=datetime.fromisoformat(data["t"]),
        received_at=datetime.fromisoformat(data["r"]),
        meter_power_w=Decimal(data["m"]),
        production_w=_dec(data["p"]),
        consumption_w=_dec(data["c"]),
    )


def claim_push_slot(source_id, now: datetime) -> int:
    """Take the source's rate-floor slot. ``0`` when taken; otherwise the seconds to wait.

    ``cache.add`` is atomic, so two concurrent pushes cannot both pass.
    """
    window = settings.LIVE_MIN_PUSH_INTERVAL_S
    if window <= 0:
        return 0
    if cache.add(_floor_key(source_id), now.timestamp(), timeout=window):
        return 0
    taken = cache.get(_floor_key(source_id))
    if taken is None:  # expired between the two calls
        return 0
    return max(math.ceil(taken + window - now.timestamp()), 1)


def put_sample(sample: LiveSample) -> None:
    """Record ``sample`` as the source's latest and fold it into its bucket.

    An older sample (out-of-order delivery) still lands in its bucket but never replaces a newer
    ``latest``. Bucket updates are read-modify-write: a source has one writer, and the rate floor
    keeps it slow, so a lost update only lowers ``n``.
    """
    key = _latest_key(sample.source_id)
    current = cache.get(key)
    if current is None or _decode(sample.source_id, current).timestamp <= sample.timestamp:
        cache.set(key, _encode(sample), timeout=settings.LIVE_MAX_AGE_S)

    epoch = bucket_epoch(sample.timestamp)
    bucket_key = _bucket_key(sample.source_id, epoch)
    bucket = cache.get(bucket_key) or {
        "n": 0, "m": "0", "p": "0", "np": 0, "c": "0", "nc": 0,
    }
    bucket["n"] += 1
    bucket["m"] = str(Decimal(bucket["m"]) + sample.meter_power_w)
    if sample.production_w is not None:
        bucket["p"] = str(Decimal(bucket["p"]) + sample.production_w)
        bucket["np"] += 1
    if sample.consumption_w is not None:
        bucket["c"] = str(Decimal(bucket["c"]) + sample.consumption_w)
        bucket["nc"] += 1
    cache.set(bucket_key, bucket, timeout=settings.LIVE_CURVE_RETENTION_H * 3600)


def latest_many(source_ids) -> dict[str, LiveSample]:
    """The latest sample per source that still has one (expired keys are simply absent)."""
    ids = [str(source_id) for source_id in source_ids]
    found = cache.get_many([_latest_key(source_id) for source_id in ids])
    return {
        source_id: _decode(source_id, found[_latest_key(source_id)])
        for source_id in ids
        if _latest_key(source_id) in found
    }


def buckets_many(source_ids, start: datetime, end: datetime) -> dict[str, dict[int, Bucket]]:
    """Per source, the buckets starting in ``[start, end)``, keyed by bucket epoch."""
    width = settings.LIVE_CURVE_BUCKET_S
    first = bucket_epoch(start)
    epochs = list(range(first, int(end.timestamp()), width))
    ids = [str(source_id) for source_id in source_ids]
    keys = {_bucket_key(source_id, epoch): (source_id, epoch) for source_id in ids for epoch in epochs}
    result: dict[str, dict[int, Bucket]] = {source_id: {} for source_id in ids}
    names = list(keys)
    for offset in range(0, len(names), _GET_MANY_CHUNK):
        for name, raw in cache.get_many(names[offset:offset + _GET_MANY_CHUNK]).items():
            source_id, epoch = keys[name]
            n = raw["n"]
            if not n:
                continue
            result[source_id][epoch] = Bucket(
                start=datetime.fromtimestamp(epoch, tz=dt_timezone.utc),
                n=n,
                meter_power_w=Decimal(raw["m"]) / n,
                production_w=Decimal(raw["p"]) / raw["np"] if raw["np"] else None,
                consumption_w=Decimal(raw["c"]) / raw["nc"] if raw["nc"] else None,
            )
    return result


def bucket_width() -> timedelta:
    return timedelta(seconds=settings.LIVE_CURVE_BUCKET_S)
