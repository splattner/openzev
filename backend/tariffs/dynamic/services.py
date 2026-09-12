"""Management operations for shared dynamic tariff sources."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from django.db import transaction
from django.utils import timezone as djtimezone

from invoices.models import Invoice, InvoiceStatus

from .discovery import probe_source_configuration
from .fetch import store_points
from .models import DynamicTariffSource, FetchStatus


def create_or_reuse_source(*, label, url, api_version, tariff_type, tariff_name):
    """Probe and create a source, or return the existing natural-key match.

    Returns ``(source, created, warnings)``. ``warnings`` names priced units
    the probe found but cannot bill (a demand charge, a fixed monthly fee
    riding alongside the requested energy component, ...) — the same
    warnings ``vse_v1``/``vse_v2`` already compute so nothing is silently
    dropped; a reused source returns none because nothing was probed.
    """

    natural_key = {
        "url": url,
        "tariff_type": tariff_type,
        "tariff_name": tariff_name,
    }
    existing = DynamicTariffSource.objects.filter(**natural_key).first()
    if existing is not None:
        return existing, False, []

    capabilities = probe_source_configuration(
        url,
        api_version=api_version,
        tariff_type=tariff_type,
        tariff_name=tariff_name,
    )
    now = djtimezone.now()

    with transaction.atomic():
        source, created = DynamicTariffSource.objects.get_or_create(
            **natural_key,
            defaults={
                "label": label,
                "api_version": capabilities.api_version,
                "request_mode": capabilities.request_mode,
                "query_tariff_type": capabilities.query_tariff_type,
                "supports_range": capabilities.supports_range,
            },
        )
        if created:
            # Local import avoids a service/task import cycle.
            from ..tasks import fetch_dynamic_prices

            store_points(source, capabilities.points)
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
    return source, created, (capabilities.warnings if created else [])


def recheck_source_capabilities(source: DynamicTariffSource) -> tuple[DynamicTariffSource, list[str]]:
    """Re-probe an existing source's own identity to correct capabilities.

    ``request_mode``/``query_tariff_type``/``supports_range`` are discovered
    once, at creation, and never revisited automatically. That first probe
    can under-detect: the range check asks for a narrow window around one
    sample interval, and a transient blip or an endpoint with nothing
    published at that exact moment makes an endpoint that genuinely supports
    range queries look like it does not. Because a source's identity fields
    (url/api_version/tariff_type/tariff_name) are immutable after creation —
    on purpose, so two price series can never mix — a wrongly-negative
    ``supports_range`` had no way back except deleting and recreating the
    source. This keeps the identity and only updates what discovery found.
    """
    capabilities = probe_source_configuration(
        source.url,
        api_version=source.api_version,
        tariff_type=source.tariff_type,
        tariff_name=source.tariff_name,
    )
    DynamicTariffSource.objects.filter(pk=source.pk).update(
        request_mode=capabilities.request_mode,
        query_tariff_type=capabilities.query_tariff_type,
        supports_range=capabilities.supports_range,
    )
    source.refresh_from_db()
    return source, capabilities.warnings


def tariff_has_dynamic_billing_evidence(*, zev_id, valid_from, valid_to, dynamic_source_id) -> bool:
    """Conservatively detect invoices that may have been priced through this
    one tariff's dynamic link, by validity-window overlap.

    Invoice items intentionally store rendered monetary values rather than a
    tariff FK, so overlap between the tariff's validity window and an invoice
    period is the strongest evidence relationship available. Draft invoices
    count too: leaving their totals behind after deleting their inputs would
    be misleading.

    This is called both per-source (``source_has_billing_evidence``, over
    every *currently* linked tariff) and per-tariff, before a mutation that
    would remove the link itself — deleting the tariff, or repointing its
    ``dynamic_source`` — because once the link is gone, the source-level
    check can no longer see it: ``source.tariffs`` only reflects tariffs that
    still point at it *right now*, not every tariff that ever did.
    """
    if not dynamic_source_id:
        return False
    invoices = Invoice.objects.filter(
        zev_id=zev_id,
        period_end__gte=valid_from,
    ).exclude(status=InvoiceStatus.CANCELLED)
    if valid_to is not None:
        invoices = invoices.filter(period_start__lte=valid_to)
    return invoices.exists()


def source_has_billing_evidence(source: DynamicTariffSource) -> bool:
    """Conservatively detect invoices whose calculation may use this source."""

    return any(
        tariff_has_dynamic_billing_evidence(
            zev_id=zev_id, valid_from=valid_from, valid_to=valid_to,
            dynamic_source_id=source.pk,
        )
        for zev_id, valid_from, valid_to in source.tariffs.values_list(
            "zev_id", "valid_from", "valid_to"
        )
    )


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
    """Inclusive civil dates, read in the app's local timezone, as a
    half-open UTC datetime window.

    The civil dates come from the UI's local calendar (``TIME_ZONE``,
    Europe/Zurich), so "today" has to resolve to local midnight-to-midnight,
    not UTC midnight — the two differ by one or two hours whenever
    Switzerland is off UTC, which is most of the year. Anchoring on UTC
    midnight instead made the price history report the local day's last
    hour or two as a gap even though a stored point covers it, and the same
    slip would under-report a real gap sitting right at a day boundary.
    """

    local_tz = djtimezone.get_current_timezone()
    start = djtimezone.make_aware(
        datetime.combine(date_from, datetime.min.time()), local_tz
    )
    end = djtimezone.make_aware(
        datetime.combine(date_to + timedelta(days=1), datetime.min.time()), local_tz
    )
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)
