"""Invoice provenance and source-row locks shared by billing and maintenance."""

from allocation.validity import period_window
from .models import DynamicTariffSource


def lock_sources(source_ids):
    """Lock in a total order; the caller holds an atomic transaction."""
    return fetch_sources(source_ids, lock=True)


def fetch_sources(source_ids, *, lock: bool = True):
    """Fetch dynamic tariff sources in total order, locking rows only when requested."""
    qs = DynamicTariffSource.objects.filter(pk__in=source_ids).order_by("pk")
    if lock:
        qs = qs.select_for_update()
    return list(qs)


def record_invoice_evidence(invoice, tariffs):
    from invoices.models import InvoiceDynamicSourceEvidence

    rows = []
    for tariff in tariffs:
        if not tariff.dynamic_source_id:
            continue
        start = max(invoice.period_start, tariff.valid_from)
        end = min(invoice.period_end, tariff.valid_to or invoice.period_end)
        if start <= end:
            evidence_from, evidence_to = period_window(start, end)
            rows.append(InvoiceDynamicSourceEvidence(
                invoice=invoice, source_id=tariff.dynamic_source_id,
                tariff_id_snapshot=tariff.pk,
                evidence_from=evidence_from, evidence_to=evidence_to,
            ))
    InvoiceDynamicSourceEvidence.objects.bulk_create(rows)


def billed_ranges(source):
    from invoices.models import InvoiceStatus

    # Many participants retain the same window. Merge it once, so storage can
    # bisect disjoint ranges instead of scanning every invoice for every point.
    rows = (source.invoice_evidence.exclude(invoice__status=InvoiceStatus.CANCELLED)
            .order_by("evidence_from", "evidence_to")
            .values_list("evidence_from", "evidence_to").distinct())
    ranges = []
    for start, end in rows:
        if ranges and start <= ranges[-1][1]:
            ranges[-1] = (ranges[-1][0], max(ranges[-1][1], end))
        else:
            ranges.append((start, end))
    return ranges
