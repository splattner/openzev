"""Celery tasks for supplementary energy data sources (SPEC §6.3).

``refresh_supplementary_sources`` is the beat entry: it fans out one
``sync_supplementary_source`` per pull source, so one unreachable vendor account cannot delay
the others. ``disable_orphaned_supplementary_sources`` is the consent boundary of ADR 0030:
when a participant no longer holds the metering point, their source stops.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from uuid import uuid4

from celery import shared_task
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from audit.models import AuditActionCategory, AuditEventSource, AuditEventStatus
from audit.services import record_audit_event

from .models import SourceHolder, SourceTarget, SupplementaryProvider, SupplementarySource, SupplementaryStatus
from .supplementary import permissions, sync
from .supplementary.providers import ProviderAuthError, ProviderError, ProviderRateLimited
from .supplementary.stats import personal_windows

logger = logging.getLogger(__name__)

SOURCE_LOCK_SECONDS = 30 * 60
AUDIT_TARGET = "metering.SupplementarySource"


@contextmanager
def source_lock(source_id):
    """One sync per source at a time, as a cache lease (same pattern as ``dynamic_source_lock``)."""
    key = f"supplementary-source-lock:{source_id}"
    token = str(uuid4())
    acquired = cache.add(key, token, timeout=SOURCE_LOCK_SECONDS)
    try:
        yield acquired
    finally:
        # Do not delete a successor's lease if ours expired while we were still running.
        if acquired and cache.get(key) == token:
            cache.delete(key)


def source_audit_metadata(source) -> dict:
    """What every source audit event says about the source's shape."""
    return {"capabilities": source.capabilities, "target": source.target, "held_by": source.held_by}


def _audit_best_effort(source, action_type, summary, *, status, metadata=None):
    """Record the outcome without ever replacing it: a failed audit write must not fail a sync."""
    try:
        record_audit_event(
            action_category=AuditActionCategory.METERING,
            action_type=f"supplementary_source.{action_type}",
            target_type=AUDIT_TARGET,
            target=source,
            target_id=str(source.pk),
            target_display=source.display_name,
            source=AuditEventSource.CELERY,
            status=status,
            summary=summary,
            metadata={**source_audit_metadata(source), **(metadata or {})},
        )
    except Exception:  # pragma: no cover - defensive
        logger.exception("Could not record audit event for supplementary source %s", source.pk)


def sync_supplementary_source_impl(source_id, *, backfill: bool = False) -> dict:
    """Sync one source. Split out of the task so tests can call it directly.

    Raises ``ProviderError`` for anything the retry should pick up; an auth failure is final
    (the source is ``reconnect_required``) and returns normally.
    """
    source = (
        SupplementarySource.objects.select_related("metering_point", "zev", "participant").filter(pk=source_id).first()
    )
    if source is None:
        # Deleted between fan-out and execution.
        return {"source_id": str(source_id), "skipped": "missing"}

    with source_lock(source.pk) as acquired:
        if not acquired:
            return {"source_id": str(source.pk), "skipped": "busy"}
        base = {"zev_id": str(source.zev_id), "provider": source.provider, "backfill": backfill}
        try:
            result = sync.sync_source(source, backfill=backfill)
        except sync.SyncSkipped as skipped:
            return {"source_id": str(source.pk), "skipped": skipped.reason}
        except ProviderAuthError as exc:
            _audit_best_effort(
                source, "sync", f"Energy data sync needs a new key: {exc}",
                status=AuditEventStatus.FAILED, metadata={**base, "outcome": "reconnect_required"},
            )
            return {"source_id": str(source.pk), "error": "reconnect_required"}
        except ProviderError as exc:
            _audit_best_effort(
                source, "sync", f"Energy data sync failed: {exc}",
                status=AuditEventStatus.FAILED, metadata={**base, "outcome": "error"},
            )
            raise
        _audit_best_effort(
            source, "sync",
            f"Synced {result.accepted} reading(s) for {source.display_name}.",
            status=AuditEventStatus.SUCCESS, metadata={**base, **result.as_dict()},
        )
    return {"source_id": str(source.pk), **result.as_dict()}


@shared_task(bind=True, max_retries=2, default_retry_delay=600)
def sync_supplementary_source(self, source_id, backfill: bool = False):
    """Sync one source, retrying transient vendor problems.

    The next beat tick would pick a failure up anyway; retrying shortens the hole, and honours
    the vendor's ``Retry-After`` when it sent one.
    """
    try:
        return sync_supplementary_source_impl(source_id, backfill=backfill)
    except ProviderRateLimited as exc:
        raise self.retry(exc=exc, countdown=max(exc.retry_after, self.default_retry_delay))
    except ProviderError as exc:
        raise self.retry(exc=exc)


@shared_task
def refresh_supplementary_sources() -> dict:
    """Queue a sync for every enabled pull source, when the feature is on."""
    if not permissions.feature_enabled():
        return {"queued": 0, "skipped": "feature_off"}
    ids = list(
        SupplementarySource.objects.filter(enabled=True, provides_history=True)
        .exclude(provider=SupplementaryProvider.PUSH)
        .exclude(status=SupplementaryStatus.RECONNECT_REQUIRED)
        .filter(zev__disabled_at__isnull=True)
        .values_list("pk", flat=True)
    )
    for source_id in ids:
        sync_supplementary_source.delay(str(source_id))
    return {"queued": len(ids)}


def queue_sync(source, *, backfill: bool = False) -> None:
    """Queue a sync once the surrounding transaction commits (never for a push source)."""
    if source.provider == SupplementaryProvider.PUSH or not source.provides_history:
        return

    def enqueue():
        try:
            sync_supplementary_source.delay(str(source.pk), backfill=backfill)
        except Exception:  # a broker outage must not fail the request that already committed
            logger.exception("Could not queue a sync for supplementary source %s", source.pk)

    transaction.on_commit(enqueue)


@shared_task
def disable_orphaned_supplementary_sources() -> dict:
    """Disconnect every source whose holder is gone.

    Run daily. The readings stay; the credential or push token is wiped.

    * A participant-held source stops when the participant no longer holds the metering point
      personally (reason ``assignment_ended``).
    * A ZEV-held source on a metering point stops once somebody holds it personally
      (reason ``personal_holder_assigned``): a household's live data must not keep flowing to
      the manager without the household's consent.
    * Grid connection point sources are never orphaned.
    """
    if not permissions.feature_enabled():
        return {"disabled": 0, "skipped": "feature_off"}
    now = timezone.now()
    today = timezone.localdate()
    disabled = 0
    for source in SupplementarySource.objects.filter(enabled=True).select_related("metering_point"):
        if source.target == SourceTarget.CONNECTION_POINT:
            continue
        if source.held_by == SourceHolder.ZEV:
            if not permissions.personally_held_today(source.metering_point, today):
                continue
            reason, text = "personal_holder_assigned", "a participant now holds the metering point"
        else:
            if any(start <= now < end for start, end in personal_windows(source)):
                continue
            reason, text = "assignment_ended", "the tenancy has ended"
        with transaction.atomic():
            source.disconnect()
            source.save()
            _audit_best_effort(
                source, "disconnect",
                f"Disconnected the energy data source for {source.display_name}: {text}.",
                status=AuditEventStatus.SUCCESS,
                metadata={"reason": reason, "zev_id": str(source.zev_id)},
            )
        disabled += 1
    return {"disabled": disabled}
