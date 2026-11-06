from celery import shared_task

from zev.models import Zev

from .backfill import backfill_invoices


@shared_task
def inbox_backfill_task(zev_id: str | None = None, dry_run: bool = False) -> dict:
    """The ``openzev_inbox_backfill`` command as a task."""
    zev = Zev.objects.get(pk=zev_id) if zev_id else None
    report = backfill_invoices(zev=zev, dry_run=dry_run)
    return {
        "delivered": report.delivered,
        "already_delivered": report.already_delivered,
        "missing": report.missing,
        "failed": report.failed,
        "dry_run": report.dry_run,
    }
