import logging

from celery import shared_task

from zev.models import Zev

from .backfill import backfill_credits, backfill_invoices

logger = logging.getLogger(__name__)


@shared_task
def inbox_backfill_task(zev_id: str | None = None, dry_run: bool = False) -> dict:
    """The ``openzev_inbox_backfill`` command as a task."""
    zev = Zev.objects.get(pk=zev_id) if zev_id else None
    invoices = backfill_invoices(zev=zev, dry_run=dry_run)
    credits = backfill_credits(zev=zev, dry_run=dry_run)
    return {
        "delivered": invoices.delivered + credits.delivered,
        "already_delivered": invoices.already_delivered + credits.already_delivered,
        "missing": invoices.missing + credits.missing,
        "failed": invoices.failed + credits.failed,
        "credit_notes": {
            "delivered": credits.delivered,
            "already_delivered": credits.already_delivered,
            "missing": credits.missing,
            "failed": credits.failed,
        },
        "dry_run": dry_run,
    }


@shared_task(bind=True, max_retries=3)
def send_document_email_task(self, document_id: str) -> bool:
    """Email one participant that a document is in their inbox (retries on a send failure)."""
    from .emails import record_email_failure, send_document_email
    from .models import DeliveredDocument

    document = (
        DeliveredDocument.objects.select_related("zev", "participant__party", "participant__user")
        .filter(pk=document_id)
        .first()
    )
    if document is None:
        return False
    try:
        return send_document_email(document)
    except Exception as exc:
        logger.warning("Emailing document %s failed: %s", document_id, type(exc).__name__)
        if self.request.retries >= self.max_retries:
            record_email_failure(document, exc)
            return False
        raise self.retry(exc=exc, countdown=60)
