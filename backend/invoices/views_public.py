"""Unauthenticated invoice access, reached from the QR printed on the invoice.

Everything in this module is served without a session, which is only defensible
because of one property: **a response describes exactly one invoice, the one the
reader is holding.** The argument is in
``docs/specs/2026-09-participant-invoice-access.md`` §9, and §9 also says what
must not happen — the moment a response here carries a second invoice, a
neighbour's figure or a ZEV-wide total, the reason it needs no login stops
holding.

Read that section before adding a field.
"""
import logging

from django.http import FileResponse
from rest_framework import status
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
    throttle_classes,
)
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from accounts.throttling import InvoiceLinkThrottle
from audit.models import AuditActionCategory, AuditEventSource, AuditEventStatus
from audit.services import record_audit_event

from . import access_tokens
from .models import InvoiceStatus
from .pdf_stats import _build_energy_summary

logger = logging.getLogger(__name__)

def _not_found():
    """Every failure looks the same from outside.

    Unknown prefix, revoked token, wrong secret and a ZEV that has not opted in
    all return this. Telling a caller that a prefix exists but the secret is
    wrong is the one piece of information that would make walking the keyspace
    worth starting.
    """
    return Response({"detail": "This link is not valid."}, status=status.HTTP_404_NOT_FOUND)


def _serialize_item(item) -> dict:
    return {
        "category": item.tariff_category,
        "description": item.description,
        "quantity": str(item.quantity_kwh),
        "unit": item.unit,
        "total_chf": str(item.total_chf),
    }


def _serialize(invoice) -> dict:
    """The public shape of one invoice.

    Deliberately absent: the participant's email and address, any bank detail,
    anything about another participant, and any ZEV-wide figure. What is here
    is what the paper already carries, plus the line items behind the total.
    """
    return {
        "invoice_number": invoice.invoice_number,
        "zev_name": invoice.zev.name,
        "participant_name": invoice.participant.full_name,
        "period_start": invoice.period_start.isoformat(),
        "period_end": invoice.period_end.isoformat(),
        "status": invoice.status,
        # The one field that can change after the paper was printed, which is
        # the point: "have I paid this?" is the reader's second question.
        "is_paid": invoice.status == InvoiceStatus.PAID,
        "total_chf": str(invoice.total_chf),
        "currency": "CHF",
        # Verbatim from the insights page rather than recomputed, so the page
        # and the paper cannot disagree. None when the invoice has no
        # consumption, which is also when no QR was printed.
        "energy_summary": _build_energy_summary(invoice),
        "items": [_serialize_item(item) for item in invoice.items.all()],
        "has_pdf": bool(invoice.pdf_file),
    }


def _resolve(request, prefix):
    """``(token, None)`` or ``(None, response)``.

    Marks the request so audit events name the credential rather than the
    generic ``api`` source the middleware sets. Same approach and same reason
    as ``ApiKeyAuthentication`` (``accounts/authentication.py:180``), including
    stamping the underlying ``HttpRequest``, since ``record_audit_event`` may
    be handed either.
    """
    token = access_tokens.resolve(prefix, request.query_params.get("s", ""))
    if token is None:
        return None, _not_found()

    request.audit_source = AuditEventSource.INVOICE_LINK
    underlying = getattr(request, "_request", None)
    if underlying is not None:
        underlying.audit_source = AuditEventSource.INVOICE_LINK
    return token, None


@api_view(["GET"])
@permission_classes([AllowAny])
@authentication_classes([])
@throttle_classes([InvoiceLinkThrottle])
def public_invoice(request, prefix):
    """One invoice, for the bearer of the link printed on it."""
    token, error = _resolve(request, prefix)
    if error is not None:
        return error

    invoice = token.invoice
    if access_tokens.note_use(token):
        record_audit_event(
            action_type="invoice_link.viewed",
            action_category=AuditActionCategory.INVOICE,
            status=AuditEventStatus.SUCCESS,
            source=AuditEventSource.INVOICE_LINK,
            request=request,
            zev=invoice.zev,
            target_type="invoices.Invoice",
            target_id=str(invoice.pk),
            target_display=invoice.invoice_number,
            summary=f"Invoice {invoice.invoice_number} opened from its printed link.",
            metadata={"token_prefix": token.prefix},
        )

    return Response(_serialize(invoice))


@api_view(["GET"])
@permission_classes([AllowAny])
@authentication_classes([])
@throttle_classes([InvoiceLinkThrottle])
def public_invoice_pdf(request, prefix):
    """The stored PDF for that invoice.

    Streams what is on disk and 404s when there is nothing — an unauthenticated
    caller must not be able to trigger a WeasyPrint render, which is the most
    expensive thing this process can be asked to do.
    """
    token, error = _resolve(request, prefix)
    if error is not None:
        return error

    invoice = token.invoice
    if not invoice.pdf_file:
        return _not_found()

    response = FileResponse(invoice.pdf_file.open("rb"), content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{invoice.invoice_number}.pdf"'
    return response
