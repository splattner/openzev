"""The events raised by the application (SPEC-2026-11-notification-center §4.3).

One function per event, each called from the place where the event already
happens. They build the payload and the recipients and are wrapped so that
nothing in here, not even a failing query, can fail the caller.
"""

from __future__ import annotations

import functools
import logging

from django.db.models import Max, Min
from django.utils import timezone

from .recipients import manager_accounts, metering_point_recipients, participant_recipient
from .services import notify

logger = logging.getLogger(__name__)

# Rejected means nothing was written; an import with errors and no rows imported failed too.
FAILED_RESULT_STATUS = "rejected"


def best_effort(function):
    @functools.wraps(function)
    def wrapper(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except Exception:
            logger.exception("Notification producer %s failed", function.__name__)
            return None

    return wrapper


@best_effort
def notify_invoice_sent(invoice) -> None:
    notify(
        "invoice.sent",
        zev=invoice.zev,
        recipients=participant_recipient(invoice.participant),
        payload={
            "invoice_number": invoice.invoice_number,
            "period_start": invoice.period_start.isoformat(),
            "period_end": invoice.period_end.isoformat(),
        },
        target_id=invoice.pk,
        dedupe_key=f"invoice.sent:{invoice.pk}",
    )


@best_effort
def notify_invoice_paid(invoice) -> None:
    notify(
        "invoice.paid",
        zev=invoice.zev,
        recipients=participant_recipient(invoice.participant),
        payload={"invoice_number": invoice.invoice_number},
        target_id=invoice.pk,
        dedupe_key=f"invoice.paid:{invoice.pk}",
    )


@best_effort
def notify_metering_data(log) -> None:
    """One notification per metering point that received readings of this import, per local day."""
    from metering.models import MeterReading
    from allocation.validity import business_tz

    if log.zev is None:
        return
    tz = business_tz()
    today = timezone.localdate()
    touched = (
        MeterReading.objects.filter(import_batch=log.batch_id)
        .values("metering_point_id", "metering_point__meter_id")
        .annotate(first=Min("timestamp"), last=Max("timestamp"))
    )
    for row in touched:
        first_day = row["first"].astimezone(tz).date()
        last_day = row["last"].astimezone(tz).date()
        notify(
            "metering.data",
            zev=log.zev,
            recipients=metering_point_recipients(row["metering_point_id"], first_day, last_day),
            payload={
                "meter_id": row["metering_point__meter_id"],
                "first_day": first_day.isoformat(),
                "last_day": last_day.isoformat(),
            },
            target_id=row["metering_point_id"],
            dedupe_key=f"metering.data:{row['metering_point_id']}:{today.isoformat()}",
        )


@best_effort
def notify_import_outcome(log) -> None:
    """Tell the ZEV's managers how an upload ended; the person who uploaded it already knows."""
    if log.zev is None:
        return
    issues = len(log.issues or []) + len(log.errors or [])
    failed = log.rows_imported == 0 and (bool(log.errors) or log.result_status == FAILED_RESULT_STATUS)
    base = {"import_log_id": str(log.pk), "source": log.source, "rows_skipped": log.rows_skipped, "issues": issues}
    notify(
        "import.failed" if failed else "import.finished",
        zev=log.zev,
        recipients=manager_accounts(log.zev),
        payload=base if failed else {**base, "rows_imported": log.rows_imported},
        target_id=log.pk,
        exclude=[log.imported_by] if log.imported_by_id else [],
    )


@best_effort
def notify_invoices_generated(zev, period_start, period_end, *, created: int, failed: int) -> None:
    notify(
        "invoices.generated",
        zev=zev,
        recipients=manager_accounts(zev),
        payload={
            "period_start": str(period_start),
            "period_end": str(period_end),
            "created": created,
            "failed": failed,
        },
        target_id=f"{period_start}:{period_end}",
    )


@best_effort
def notify_invoice_generation_failed(zev, period_start, period_end) -> None:
    notify(
        "invoices.generation_failed",
        zev=zev,
        recipients=manager_accounts(zev),
        payload={"period_start": str(period_start), "period_end": str(period_end)},
        target_id=f"{period_start}:{period_end}",
    )
