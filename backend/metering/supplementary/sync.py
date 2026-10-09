"""Pull a source's data and store it (SPEC §6.3).

The window is ``[max(synced_through - 2 days, floor), floor(now to 15 min))``. The overlap
re-fetches the last two days so late or revised vendor values are upserted. ``floor`` is the
later of the backfill limit and the start of the participant's personal tenancy: nothing is
requested for a period the participant did not hold the meter, because it would only be
dropped again.

Each civil day is stored before the next is requested, so an interrupted run resumes where
it stopped. Everything goes through ``ingest.ingest``, the same validation and clipping as
push and CSV.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.conf import settings
from django.utils import timezone

from ..models import SupplementaryProvider, SupplementarySource, SupplementaryStatus
from . import ingest, permissions, reconcile
from .providers import PROVIDERS, Point, ProviderAuthError, ProviderError
from .stats import _clip, personal_windows

logger = logging.getLogger(__name__)

OVERLAP = timedelta(days=2)


class SyncSkipped(Exception):
    """Nothing to do. ``reason`` is one of the strings below; it is a normal outcome, not an error."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass
class SyncResult:
    accepted: int = 0
    updated: int = 0
    rejected: int = 0
    dropped_outside_assignment: int = 0
    days: int = 0

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def floor_quarter(value: datetime) -> datetime:
    return value.replace(minute=value.minute - value.minute % 15, second=0, microsecond=0)


def sync_window(source: SupplementarySource, now: datetime, *, backfill: bool = False):
    """The UTC ``[start, end)`` to request, and the personal windows inside it."""
    windows = personal_windows(source)
    if not windows:
        return None
    floor = max(now - timedelta(days=settings.SUPPLEMENTARY_BACKFILL_MAX_DAYS), windows[0][0])
    start = floor
    if source.synced_through and not backfill:
        start = max(source.synced_through - OVERLAP, floor)
    end = floor_quarter(now)
    if start >= end:
        return None
    return _clip(windows, start, end)


def _as_row(point: Point) -> dict:
    return {
        "timestamp": point.timestamp,
        "consumption_kwh": point.consumption_kwh,
        "production_kwh": point.production_kwh,
        "import_kwh": point.import_kwh,
        "export_kwh": point.export_kwh,
    }


def _still_enabled(source: SupplementarySource) -> bool:
    return SupplementarySource.objects.filter(pk=source.pk, enabled=True).exists()


def record_failure(source: SupplementarySource, status: str, safe_text: str, *, now: datetime | None = None) -> None:
    """Store a failed outcome without overwriting a concurrent disconnect."""
    now = now or timezone.now()
    if status == SupplementaryStatus.RECONNECT_REQUIRED:
        source.mark_reconnect_required(safe_text, at=now)
    else:
        source.mark_error(safe_text, at=now)
    SupplementarySource.objects.filter(pk=source.pk, enabled=True).update(
        status=source.status, last_sync_at=source.last_sync_at, last_error=source.last_error, updated_at=now
    )


def sync_source(source: SupplementarySource, *, backfill: bool = False, now: datetime | None = None) -> SyncResult:
    """Fetch and store what is new for ``source``.

    Raises ``SyncSkipped`` when there is nothing to do, ``ProviderAuthError`` when the vendor
    no longer accepts the credential (the source is then ``reconnect_required``), and
    ``ProviderError`` for anything transient (the source is then ``error``). Both are
    recorded on the source before they propagate.
    """
    if not permissions.feature_enabled():
        raise SyncSkipped("feature_off")
    provider = PROVIDERS.get(source.provider)
    if source.provider == SupplementaryProvider.PUSH or provider is None:
        raise SyncSkipped("not_a_pull_source")
    if not source.enabled:
        raise SyncSkipped("disabled")
    if source.status == SupplementaryStatus.RECONNECT_REQUIRED:
        raise SyncSkipped("reconnect_required")

    now = now or timezone.now()
    windows = sync_window(source, now, backfill=backfill)
    if windows is None:
        raise SyncSkipped("nothing_to_sync")

    result = SyncResult()
    try:
        for start, end in windows:
            for points in provider.fetch(source, start, end):
                if not _still_enabled(source):
                    raise SyncSkipped("disabled")
                stored = ingest.ingest(source, [_as_row(point) for point in points], now=now)
                result.days += 1
                result.accepted += stored.accepted
                result.updated += stored.updated
                result.rejected += len(stored.rejected)
                result.dropped_outside_assignment += stored.dropped_outside_assignment
    except ProviderAuthError as exc:
        record_failure(source, SupplementaryStatus.RECONNECT_REQUIRED, str(exc), now=now)
        raise
    except ProviderError as exc:
        record_failure(source, SupplementaryStatus.ERROR, str(exc), now=now)
        raise

    # A run that stored nothing (the vendor had no new data yet) still succeeded.
    source.mark_ok(at=now)
    SupplementarySource.objects.filter(pk=source.pk, enabled=True).update(
        status=source.status, last_sync_at=now, last_success_at=now, last_error="", updated_at=now
    )
    try:
        reconcile.reconcile_and_store(source, now=now)
    except Exception:  # diagnostic only: it must never turn a good sync into a failure
        logger.exception("Reconciliation failed for supplementary source %s", source.pk)
    return result
