"""Validation and storage of supplementary readings delivered by push or CSV.

One path for every non-pull source, so the rules cannot drift between the push
endpoint and the file upload (SPEC §5).

A reading is rejected, not coerced, when the timestamp is naive, not aligned to a
15-minute boundary, in the future or older than ``SUPPLEMENTARY_BACKFILL_MAX_DAYS``,
or when a value is missing, non-numeric, negative or absurdly large. Values are
rounded half-up to the four decimals the column stores: a Home Assistant sensor
reports ``0.0933500001``, and refusing that would make the endpoint unusable.
Intervals outside the periods the source's participant held the meter personally
are dropped and counted, not treated as errors.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from ..models import SupplementaryReading, SupplementarySource
from .stats import INTERVAL, personal_windows

VALUE_FIELDS = ("consumption_kwh", "production_kwh", "import_kwh", "export_kwh")
QUANTUM = Decimal("0.0001")
MAX_VALUE = Decimal("100000000")  # the column holds 12 digits: 10**8 kWh in one quarter hour is nonsense anyway
BATCH_SIZE = 500


@dataclass
class IngestResult:
    accepted: int = 0
    updated: int = 0
    rejected: list[dict] = field(default_factory=list)
    dropped_outside_assignment: int = 0

    def as_dict(self) -> dict:
        return {
            "accepted": self.accepted,
            "updated": self.updated,
            "rejected": self.rejected,
            "dropped_outside_assignment": self.dropped_outside_assignment,
        }


def _parse_timestamp(raw) -> datetime:
    if isinstance(raw, datetime):
        value = raw
    elif isinstance(raw, str) and raw.strip():
        try:
            value = parse_datetime(raw.strip())
        except ValueError:
            value = None
        if value is None:
            raise ValueError("timestamp is not a valid ISO 8601 date and time")
    else:
        raise ValueError("timestamp is required")
    if value.tzinfo is None:
        raise ValueError("timestamp needs a UTC offset")
    value = value.astimezone(dt_timezone.utc)
    if value.second or value.microsecond or value.minute % 15:
        raise ValueError("timestamp is not aligned to 15 minutes")
    return value


def _parse_value(raw, name: str) -> Decimal:
    if raw is None or isinstance(raw, bool) or (isinstance(raw, str) and not raw.strip()):
        raise ValueError(f"{name} is required")
    try:
        value = Decimal(str(raw).strip().replace(",", "."))
    except (InvalidOperation, ValueError):
        raise ValueError(f"{name} is not a number") from None
    if not value.is_finite():
        raise ValueError(f"{name} is not a number")
    if value < 0:
        raise ValueError(f"{name} is negative")
    if value > MAX_VALUE:
        raise ValueError(f"{name} is too large")
    return value.quantize(QUANTUM, rounding=ROUND_HALF_UP)


def _in_any(windows, ts: datetime) -> bool:
    return any(start <= ts < end for start, end in windows)


def validate_rows(source: SupplementarySource, rows, *, now: datetime | None = None):
    """Split ``rows`` into valid ``{timestamp, values}`` entries, rejections and a dropped count.

    ``rejected`` entries carry the row's ``index`` in ``rows`` and a ``reason``.
    """
    now = now or timezone.now()
    oldest = now - timedelta(days=settings.SUPPLEMENTARY_BACKFILL_MAX_DAYS)
    windows = personal_windows(source)

    valid: dict[datetime, dict] = {}
    rejected: list[dict] = []
    dropped = 0
    for index, row in enumerate(rows):
        try:
            if not isinstance(row, dict):
                raise ValueError("row is not an object")
            ts = _parse_timestamp(row.get("timestamp"))
            if ts > now:
                raise ValueError("timestamp is in the future")
            if ts < oldest:
                raise ValueError("timestamp is older than the backfill limit")
            values = {name: _parse_value(row.get(name), name) for name in VALUE_FIELDS}
            if ts in valid:
                raise ValueError("duplicate timestamp in this request")
        except ValueError as exc:
            rejected.append({"index": index, "reason": str(exc)})
            continue
        if not _in_any(windows, ts):
            dropped += 1
            continue
        valid[ts] = values
    return valid, rejected, dropped


@transaction.atomic
def store_rows(source: SupplementarySource, valid: dict[datetime, dict]) -> tuple[int, int]:
    """Upsert ``valid`` readings and advance the source's coverage. Returns ``(accepted, updated)``."""
    if not valid:
        return 0, 0
    timestamps = sorted(valid)
    existing = set(
        SupplementaryReading.objects.filter(
            metering_point_id=source.metering_point_id, timestamp__in=timestamps
        ).values_list("timestamp", flat=True)
    )
    for start in range(0, len(timestamps), BATCH_SIZE):
        chunk = timestamps[start:start + BATCH_SIZE]
        SupplementaryReading.objects.bulk_create(
            [
                SupplementaryReading(
                    source=source, metering_point_id=source.metering_point_id, timestamp=ts, **valid[ts]
                )
                for ts in chunk
            ],
            update_conflicts=True,
            unique_fields=["metering_point", "timestamp"],
            update_fields=[*VALUE_FIELDS, "source", "updated_at"],
        )

    first, last = timestamps[0], timestamps[-1] + INTERVAL
    source.covers_from = first if source.covers_from is None else min(source.covers_from, first)
    source.synced_through = last if source.synced_through is None else max(source.synced_through, last)
    source.mark_ok()
    source.save(update_fields=["covers_from", "synced_through", "status", "last_sync_at", "last_success_at",
                               "last_error", "updated_at"])
    return len(timestamps), len(existing)


def ingest(source: SupplementarySource, rows, *, dry_run: bool = False, now: datetime | None = None) -> IngestResult:
    """Validate ``rows`` and, unless ``dry_run``, store the valid ones."""
    valid, rejected, dropped = validate_rows(source, rows, now=now)
    result = IngestResult(rejected=rejected, dropped_outside_assignment=dropped)
    if dry_run:
        result.accepted = len(valid)
        return result
    result.accepted, result.updated = store_rows(source, valid)
    return result
