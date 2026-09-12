"""Invoice provenance and source-row locks shared by billing and maintenance."""

from allocation.validity import period_window
from .models import DynamicTariffSource


def lock_sources(source_ids):
    """Lock in a total order; the caller holds an atomic transaction."""
    return list(
        DynamicTariffSource.objects.select_for_update()
        .filter(pk__in=source_ids).order_by("pk")
    )


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

    return list(source.invoice_evidence.exclude(invoice__status=InvoiceStatus.CANCELLED)
                .values_list("evidence_from", "evidence_to"))
