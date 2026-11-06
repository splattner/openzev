"""Give every invoice and credit note that already reached a participant a row in the inbox (spec §6.6).

Invoices sent and credit notes issued before the inbox existed have no row. This
delivers the stored PDF of each one that has a document, dated by when the invoice
was sent or the credit note issued. It is
idempotent (an invoice with a row is skipped) and never renders: a document
that is gone is reported, not recreated, because a render would be today's
template rather than what the participant received. The cut-over to the inbox
(phase 6) waits for ``missing`` to be empty or accepted by the operator.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from django.core.files.storage import default_storage

from invoices.models import Credit, Invoice, sent_to_participant

from .models import DeliveredDocument, DocumentKind
from .producers import deliver_credit_document, deliver_invoice_document

logger = logging.getLogger(__name__)

NO_DOCUMENT = "no_document"
FILE_MISSING = "file_missing"


@dataclass
class BackfillReport:
    delivered: int = 0
    already_delivered: int = 0
    # (invoice number, reason) for each invoice that has no document to deliver.
    missing: list[tuple[str, str]] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    dry_run: bool = False

    @property
    def clean(self) -> bool:
        return not self.missing and not self.failed


def backfill_invoices(*, zev=None, dry_run: bool = False) -> BackfillReport:
    report = BackfillReport(dry_run=dry_run)
    invoices = (
        Invoice.objects.filter(sent_to_participant())
        .select_related("zev", "participant__party")
        .order_by("zev_id", "sent_at", "invoice_number")
    )
    if zev is not None:
        invoices = invoices.filter(zev=zev)
    delivered_ids = set(
        DeliveredDocument.objects.filter(invoice__isnull=False).values_list("invoice_id", flat=True)
    )
    for invoice in invoices.iterator(chunk_size=200):
        if invoice.pk in delivered_ids:
            report.already_delivered += 1
            continue
        if not invoice.pdf_file:
            report.missing.append((invoice.invoice_number, NO_DOCUMENT))
            continue
        if not default_storage.exists(invoice.pdf_file.name):
            report.missing.append((invoice.invoice_number, FILE_MISSING))
            continue
        if dry_run:
            report.delivered += 1
            continue
        try:
            with invoice.pdf_file.open("rb") as source:
                body = source.read()
            deliver_invoice_document(
                invoice, body, delivered_at=invoice.sent_at or invoice.approved_at or invoice.updated_at
            )
        except Exception as exc:
            logger.exception("Backfill of invoice %s failed", invoice.invoice_number)
            report.failed.append((invoice.invoice_number, str(exc)))
            continue
        report.delivered += 1
    return report


def backfill_credits(*, zev=None, dry_run: bool = False) -> BackfillReport:
    """The same for credit notes. One that has no PDF yet (its render failed or is
    still queued) is listed; regenerating the PDF delivers it."""
    report = BackfillReport(dry_run=dry_run)
    credits = Credit.objects.select_related(
        "zev", "participant__party", "source_invoice"
    ).order_by("zev_id", "created_at", "credit_number")
    if zev is not None:
        credits = credits.filter(zev=zev)
    delivered_numbers = set(
        DeliveredDocument.objects.filter(kind=DocumentKind.CREDIT_NOTE).values_list("zev_id", "document_number")
    )
    for credit in credits.iterator(chunk_size=200):
        if (credit.zev_id, credit.credit_number) in delivered_numbers:
            report.already_delivered += 1
            continue
        if not credit.pdf_file:
            report.missing.append((credit.credit_number, NO_DOCUMENT))
            continue
        if not default_storage.exists(credit.pdf_file.name):
            report.missing.append((credit.credit_number, FILE_MISSING))
            continue
        if dry_run:
            report.delivered += 1
            continue
        try:
            with credit.pdf_file.open("rb") as source:
                body = source.read()
            deliver_credit_document(credit, body)
        except Exception as exc:
            logger.exception("Backfill of credit note %s failed", credit.credit_number)
            report.failed.append((credit.credit_number, str(exc)))
            continue
        report.delivered += 1
    return report
