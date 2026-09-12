"""Celery tasks for keeping dynamic tariff price series up to date.

``refresh_dynamic_tariff_sources`` is the beat entry: it fans out one
``fetch_dynamic_prices`` per configured source. ``fetch_dynamic_prices`` is also
enqueued directly when a source is created, with ``backfill=True``, to pull
whatever history the operator still has.

It is scheduled several times a day rather than once because endpoints can
publish day-ahead prices or republish today's series at different times. There
is no single moment at which a day's prices are final, and
``publication_timestamp`` only says when the operator last wrote — not what it
covers.
"""

import logging

from celery import shared_task
from django.utils import timezone as djtimezone

from audit.models import AuditActionCategory, AuditEventSource, AuditEventStatus
from audit.services import record_audit_event

from .dynamic.fetch import PriceSeriesConflict, refresh_source
from .dynamic.locking import dynamic_source_lock
from .dynamic.models import DynamicTariffSource
from .importers.remote import TariffFetchError

logger = logging.getLogger(__name__)


def _audit_best_effort(
    source, *, summary, status, metadata=None, correlation_id: str | None = None
):
    """Record the outcome without ever replacing it.

    The audit log is a side channel: a write failure here must not turn a
    successful fetch into an error, nor swallow the one about to be re-raised.
    """
    try:
        record_audit_event(
            action_category=AuditActionCategory.TARIFF,
            action_type="tariff.dynamic_fetch",
            target_type="tariffs.DynamicTariffSource",
            target=source,
            target_id=str(source.pk),
            target_display=source.label,
            source=AuditEventSource.CELERY,
            status=status,
            correlation_id=correlation_id,
            summary=summary,
            metadata=metadata or {},
        )
    except Exception:  # pragma: no cover - defensive
        logger.exception("Could not record audit event for dynamic tariff source %s", source.pk)


def fetch_dynamic_prices_impl(
    source_id, *, backfill: bool = False, correlation_id: str | None = None
) -> dict:
    """Refresh one source. Split out of the task so tests can call it directly."""
    source = DynamicTariffSource.objects.filter(pk=source_id).first()
    if source is None:
        # A source deleted between fan-out and execution is not an error.
        logger.info("Dynamic tariff source %s no longer exists; nothing to fetch.", source_id)
        return {"source_id": str(source_id), "skipped": "missing"}

    with dynamic_source_lock(source.pk) as acquired:
        if not acquired:
            logger.info("Dynamic tariff source %s is already being maintained; skipping.", source.pk)
            return {"source_id": str(source.pk), "skipped": "busy"}

        try:
            result = refresh_source(source, backfill=backfill)
        except TariffFetchError as exc:
            _audit_best_effort(
                source, summary=f"Dynamic tariff fetch failed: {exc}",
                status=AuditEventStatus.FAILED, metadata={"source_id": str(source.pk)},
                correlation_id=correlation_id,
            )
            raise
        except PriceSeriesConflict as exc:
            _audit_best_effort(
                source, summary=f"Dynamic tariff prices were refused: {exc}",
                status=AuditEventStatus.FAILED, metadata={"source_id": str(source.pk)},
                correlation_id=correlation_id,
            )
            raise
        except Exception as exc:
            _audit_best_effort(
                source,
                summary=(
                    f"Dynamic tariff fetch failed with unexpected {type(exc).__name__}; "
                    "see the server log."
                ),
                status=AuditEventStatus.FAILED, metadata={"source_id": str(source.pk)},
                correlation_id=correlation_id,
            )
            raise

        _audit_best_effort(
            source,
            summary=f"Fetched {result.points_written} price point(s) for {source.label}.",
            status=AuditEventStatus.SUCCESS,
            metadata=result.as_dict(),
            correlation_id=correlation_id,
        )
    return result.as_dict()


@shared_task(bind=True, max_retries=2, default_retry_delay=600)
def fetch_dynamic_prices(
    self, source_id, backfill: bool = False, correlation_id: str | None = None
):
    """Refresh one dynamic tariff source (see :func:`fetch_dynamic_prices_impl`).

    Retried rather than failed on a transport problem: an operator's endpoint
    being briefly unreachable is ordinary, and the next beat tick would pick it
    up anyway — retrying just shortens the hole.
    """
    try:
        return fetch_dynamic_prices_impl(
            source_id, backfill=backfill, correlation_id=correlation_id
        )
    except TariffFetchError as exc:
        raise self.retry(exc=exc)


@shared_task
def refresh_dynamic_tariff_sources() -> dict:
    """Queue a refresh for every configured source.

    Fans out instead of looping so that one unreachable operator cannot delay
    or fail the refresh of the others.
    """
    source_ids = list(
        DynamicTariffSource.objects.filter(enabled=True).values_list("pk", flat=True)
    )
    for source_id in source_ids:
        fetch_dynamic_prices.delay(str(source_id))
    return {"queued": len(source_ids), "at": djtimezone.now().isoformat()}
