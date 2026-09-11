"""Management operations for shared dynamic tariff sources."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from django.db import transaction
from django.utils import timezone as djtimezone

from invoices.models import Invoice, InvoiceStatus

from .fetch import fetch_window, store_points
from .models import DynamicTariffSource, FetchStatus


def create_or_reuse_source(*, label, url, adapter, tariff_type, tariff_name):
    """Probe and create a source, or return the existing natural-key match."""

    natural_key = {
        "url": url,
        "tariff_type": tariff_type,
        "tariff_name": tariff_name,
    }
    existing = DynamicTariffSource.objects.filter(**natural_key).first()
    if existing is not None:
        return existing, False

    probe = DynamicTariffSource(
        label=label,
        adapter=adapter,
        **natural_key,
    )
    points, _warnings = fetch_window(probe, window=None)
    now = djtimezone.now()

    with transaction.atomic():
        source, created = DynamicTariffSource.objects.get_or_create(
            **natural_key,
            defaults={"label": label, "adapter": adapter},
        )
        if created:
            # Local import avoids a service/task import cycle.
            from ..tasks import fetch_dynamic_prices

            store_points(source, points)
            DynamicTariffSource.objects.filter(pk=source.pk).update(
                last_fetch_status=FetchStatus.OK,
                last_fetch_at=now,
                last_success_at=now,
                last_fetch_error="",
            )
            transaction.on_commit(
                lambda source_id=str(source.pk): fetch_dynamic_prices.delay(
                    source_id, backfill=True
                ),
                robust=True,
            )

    source.refresh_from_db()
    return source, created


def source_has_billing_evidence(source: DynamicTariffSource) -> bool:
    """Conservatively detect invoices whose calculation may use this source.

    Invoice items intentionally store rendered monetary values rather than a
    tariff FK, so overlap between a linked tariff version and an invoice period
    is the strongest evidence relationship available. Draft invoices count too:
    leaving their totals behind after deleting their inputs would be misleading.
    """

    for zev_id, valid_from, valid_to in source.tariffs.values_list(
        "zev_id", "valid_from", "valid_to"
    ):
        invoices = Invoice.objects.filter(
            zev_id=zev_id,
            period_end__gte=valid_from,
        ).exclude(status=InvoiceStatus.CANCELLED)
        if valid_to is not None:
            invoices = invoices.filter(period_start__lte=valid_to)
        if invoices.exists():
            return True
    return False


def clear_source_points(source: DynamicTariffSource) -> int:
    """Delete an unprotected source's points and reset its materialized state."""

    with transaction.atomic():
        deleted, _details = source.points.all().delete()
        DynamicTariffSource.objects.filter(pk=source.pk).update(
            covers_from=None,
            covers_to=None,
            last_fetch_status=FetchStatus.PENDING,
            last_fetch_at=None,
            last_success_at=None,
            last_fetch_error="",
        )
    return deleted


def utc_day_window(date_from, date_to):
    """Inclusive civil dates as a half-open UTC datetime window."""

    start = datetime.combine(date_from, datetime.min.time(), tzinfo=timezone.utc)
    end = datetime.combine(
        date_to + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc
    )
    return start, end
