"""Management operations for shared dynamic tariff sources."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from django.db import transaction
from django.utils import timezone as djtimezone

from invoices.models import InvoiceDynamicSourceEvidence, InvoiceStatus

from .discovery import probe_source_configuration
from .fetch import store_points
from .models import DynamicTariffSource, FetchStatus
from .evidence import lock_sources


def create_or_reuse_source(
    *, label, url, api_version, tariff_type, tariff_name, enabled=True
):
    """Probe and create a source, or return the existing natural-key match.

    Returns ``(source, created, warnings)``. ``warnings`` names priced units
    the probe found but cannot bill (a demand charge, a fixed monthly fee
    riding alongside the requested energy component, ...) — the same
    warnings ``vse_v1``/``vse_v2`` already compute so nothing is silently
    dropped; a reused source returns none because nothing was probed.
    """

    natural_key = {
        "url": url,
        "api_version": api_version,
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

    natural_key["tariff_name"] = capabilities.tariff_name or tariff_name

    with transaction.atomic():
        source, created = DynamicTariffSource.objects.get_or_create(
            **natural_key,
            defaults={
                "label": label,
                "request_mode": capabilities.request_mode,
                "query_tariff_type": capabilities.query_tariff_type,
                "supports_range": capabilities.supports_range,
                "enabled": enabled,
            },
        )
        if created:
            # Local import avoids a service/task import cycle.
            from ..tasks import fetch_dynamic_prices

            initialise_source_from_probe(source, capabilities, now=now)
            transaction.on_commit(
                lambda source_id=str(source.pk): fetch_dynamic_prices.delay(
                    source_id, backfill=True
                ),
                robust=True,
            )

    source.refresh_from_db()
    return source, created, (capabilities.warnings if created else [])


def initialise_source_from_probe(source, capabilities, *, now=None):
    """Store probe points and mark the source as successfully fetched.

    The caller owns the surrounding transaction.
    """
    now = now or djtimezone.now()
    store_points(source, capabilities.points)
    DynamicTariffSource.objects.filter(pk=source.pk).update(
        last_fetch_status=FetchStatus.OK,
        last_fetch_at=now,
        last_success_at=now,
        last_fetch_error="",
        recovery_from=None,
    )
    source.refresh_from_db()


def recheck_source_capabilities(source: DynamicTariffSource) -> tuple[DynamicTariffSource, list[str]]:
    """Re-probe request capabilities without changing identity or the explicit 404 setting."""
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
    """Conservative workflow guard over frozen evidence overlapping this tariff window."""
    if not dynamic_source_id:
        return False
    start, _end = utc_day_window(valid_from, valid_from)
    evidence = InvoiceDynamicSourceEvidence.objects.filter(
        source_id=dynamic_source_id, invoice__zev_id=zev_id, evidence_to__gt=start,
    ).exclude(invoice__status=InvoiceStatus.CANCELLED)
    if valid_to is not None:
        _start, end = utc_day_window(valid_to, valid_to)
        evidence = evidence.filter(evidence_from__lt=end)
    return evidence.exists()


def source_has_billing_evidence(source: DynamicTariffSource) -> bool:
    """Conservatively detect invoices whose calculation may use this source."""

    return source.invoice_evidence.exclude(invoice__status=InvoiceStatus.CANCELLED).exists()


def clear_source_points(source: DynamicTariffSource) -> int:
    """Delete an unprotected source's points and reset its materialized state."""

    with transaction.atomic():
        lock_sources([source.pk])
        if source_has_billing_evidence(source):
            from .fetch import PriceSeriesConflict
            raise PriceSeriesConflict("Fetched prices cannot be cleared because an invoice retains this source as evidence.")
        deleted, _details = source.points.all().delete()
        DynamicTariffSource.objects.filter(pk=source.pk).update(
            covers_from=None,
            covers_to=None,
            recovery_from=None,
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
