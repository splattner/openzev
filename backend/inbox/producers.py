"""Delivering an invoice into the participant's inbox (SPEC-2026-11-participant-document-inbox §6.2).

An invoice reaches its participant when it is emailed or marked as sent. Both
hooks call ``deliver_sent_invoice`` after their own transition has committed;
it never raises, so a failure here cannot undo the transition it hangs off. A
failed delivery is logged and audited, and ``openzev_inbox_backfill`` picks the
invoice up later.
"""

from __future__ import annotations

import logging

from audit.models import AuditActionCategory, AuditEventSource, AuditEventStatus
from audit.services import record_audit_event

from .models import DocumentKind
from .services import deliver

logger = logging.getLogger(__name__)


def stored_invoice_bytes(invoice) -> bytes | None:
    """The invoice's stored PDF, or ``None`` when there is none or it cannot be read."""
    if not invoice.pdf_file:
        return None
    try:
        with invoice.pdf_file.open("rb") as source:
            return source.read()
    except (OSError, ValueError):
        return None


def deliver_invoice_document(invoice, body: bytes, *, delivered_at=None, user=None):
    """Deliver ``body`` as ``invoice``'s document. Idempotent: a second call returns the same row."""
    return deliver(
        participant=invoice.participant,
        kind=DocumentKind.INVOICE,
        title=invoice.invoice_number,
        body=body,
        file_name=f"invoice_{invoice.invoice_number}.pdf",
        invoice=invoice,
        document_number=invoice.invoice_number,
        period=(invoice.period_start, invoice.period_end),
        delivered_at=delivered_at,
        delivered_by=user,
    )


def deliver_sent_invoice(invoice, *, body: bytes | None = None, delivered_at=None, render_missing=False):
    """Hand a sent invoice to its participant's inbox. Never raises.

    ``body`` is the exact bytes that were emailed. Without it the stored PDF is
    used, or a fresh render of the invoice when ``render_missing`` is set and
    there is none (an invoice marked as sent by hand: the operator sent the
    document outside OpenZEV, so a render is the closest copy). Returns the document, or
    ``None`` when nothing could be delivered.
    """
    try:
        if body is None:
            body = stored_invoice_bytes(invoice)
        if body is None and render_missing:
            # Rendered for the inbox only: ``pdf_file`` stays as it is, so the
            # invoice's own PDF state (cleared on approval, generated on request) is unchanged.
            from invoices.pdf import generate_pdf

            body = generate_pdf(invoice)
        if body is None:
            raise FileNotFoundError(f"Invoice {invoice.invoice_number} has no document to deliver.")
        document, _ = deliver_invoice_document(invoice, body, delivered_at=delivered_at or invoice.sent_at)
        return document
    except Exception as exc:
        logger.exception("Inbox delivery of invoice %s failed", getattr(invoice, "invoice_number", invoice))
        _record_failure(invoice, exc)
        return None


def _record_failure(invoice, exc) -> None:
    try:
        record_audit_event(
            action_category=AuditActionCategory.PARTICIPANT,
            action_type="inbox.document.delivered",
            target_type="invoices.Invoice",
            target_id=str(invoice.pk),
            target_display=invoice.invoice_number,
            summary=f"Delivering invoice {invoice.invoice_number} to the participant inbox failed: {exc}",
            status=AuditEventStatus.FAILED,
            zev=invoice.zev,
            source=AuditEventSource.SYSTEM,
            metadata={"error": str(exc), "kind": DocumentKind.INVOICE},
        )
    except Exception:
        logger.exception("The failed inbox delivery of invoice %s could not be audited", invoice.pk)
