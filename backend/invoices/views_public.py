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

from django.core.cache import cache
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

from accounts import magic_links
from accounts.cookies import set_auth_cookies
from accounts.jwt_utils import make_jwt_for_user
from accounts.throttling import InvoiceLinkThrottle, MagicLinkRequestThrottle
from audit.models import AuditActionCategory, AuditEventSource, AuditEventStatus
from audit.services import record_audit_event

from . import access_tokens
from .emails import send_magic_link_email
from .pdf import build_invoice_pdf_period_context
from .pdf_charts import (
    _build_energy_chart_svg,
    _build_energy_flow_svg,
    _build_hourly_profile_chart_svg,
)
from .models import InvoiceStatus
from .pdf_translations import INVOICE_TRANSLATIONS
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


@api_view(["POST"])
@permission_classes([AllowAny])
@authentication_classes([])
@throttle_classes([MagicLinkRequestThrottle, InvoiceLinkThrottle])
def magic_link_request(request):
    """Email a sign-in link to the address already on file.

    The invoice token identifies the participant, so **the caller never
    supplies an email address.** That is what removes account enumeration from
    this design rather than mitigating it: there is no address field to probe,
    and no answer that could confirm one.

    Always 202, including when the participant has no address on file. Saying
    "there is no account here" would answer a question the requester is not
    entitled to ask.
    """
    prefix = (request.data or {}).get("prefix", "")
    secret = (request.data or {}).get("s", "")
    accepted = Response(
        {"detail": "If the account can be reached, a link has been sent."},
        status=status.HTTP_202_ACCEPTED,
    )

    token = access_tokens.resolve(prefix, secret)
    if token is None:
        return accepted

    invoice = token.invoice
    user = magic_links.account_for_participant(invoice.participant)
    if user is None:
        return accepted

    try:
        link = magic_links.issue(user)
        send_magic_link_email(invoice.participant, invoice.zev, link)
    except Exception:
        # The requester is told the same thing either way; the operator gets
        # the traceback. Leaking a send failure would distinguish a reachable
        # participant from an unreachable one.
        logger.exception("Magic-link delivery failed for invoice %s", invoice.pk)
        return accepted

    record_audit_event(
        action_type="invoice_link.magic_link_requested",
        action_category=AuditActionCategory.AUTH,
        status=AuditEventStatus.SUCCESS,
        source=AuditEventSource.INVOICE_LINK,
        request=request,
        zev=invoice.zev,
        target_type="accounts.User",
        target_id=str(user.pk),
        target_display=user.username,
        # Records the invoice it came from, not the address it went to.
        summary=f"Sign-in link requested from invoice {invoice.invoice_number}.",
        metadata={"token_prefix": token.prefix},
    )
    return accepted


@api_view(["POST"])
@permission_classes([AllowAny])
@authentication_classes([])
@throttle_classes([InvoiceLinkThrottle])
def magic_link_consume(request):
    """Trade a one-time link for an ordinary participant session."""
    user = magic_links.consume((request.data or {}).get("token", ""))
    if user is None:
        return Response(
            {"detail": "This sign-in link has expired or already been used."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    record_audit_event(
        action_type="invoice_link.magic_link_consumed",
        action_category=AuditActionCategory.AUTH,
        status=AuditEventStatus.SUCCESS,
        source=AuditEventSource.INVOICE_LINK,
        request=request,
        user=user,
        target_type="accounts.User",
        target=user,
        target_id=str(user.pk),
        target_display=user.username,
        summary=f"Signed in with a link from an invoice: {user.username}.",
    )

    tokens = make_jwt_for_user(user)
    response = Response({"detail": "Signed in."})
    set_auth_cookies(request, response, access=tokens["access"], refresh=tokens["refresh"])
    return response


# Charts are minutes of allocation work away from the figures beside them:
# building them reads every meter reading in the period
# (``community_totals_by_timestamp``). They therefore live behind their own
# route, so the invoice itself renders without waiting, and behind a cache, so
# an unauthenticated caller cannot make the server redo that work per request.
#
# Keyed on the invoice's ``updated_at`` as well as its id: a regenerated
# invoice must not keep serving the previous period's picture.
_CHART_CACHE_SECONDS = 60 * 60

# (key, title, description), in the order the insights page prints them.
#
# The headings travel with the pictures rather than being looked up in the
# frontend's own locale, because a chart's *embedded* labels are written in the
# ZEV's ``invoice_language``. A reader whose browser is English opening an
# invoice a ZEV issues in German must not get an English heading over a German
# diagram — the document has one language, and this is it.
_CHART_COPY = (
    ("energy", "chart_title", "chart_description"),
    ("hourly", "hourly_chart_title", "hourly_chart_description"),
    ("flow", "flow_title", "flow_description"),
)


def _empty_charts() -> dict:
    return {"title": "", "intro": "", "charts": []}


def _chart_cache_key(invoice) -> str:
    stamp = invoice.updated_at.isoformat() if invoice.updated_at else "new"
    return f"public-invoice-charts:{invoice.pk}:{stamp}"


@api_view(["GET"])
@permission_classes([AllowAny])
@authentication_classes([])
@throttle_classes([InvoiceLinkThrottle])
def public_invoice_charts(request, prefix):
    """The three figures the invoice's insights page prints.

    Served **verbatim** from ``pdf_charts``, the same builders the PDF uses.
    That is the point rather than an optimisation: the reader is holding the
    page these came from, and a second rendering path would be somewhere the
    screen and the paper could quietly start disagreeing.

    This is also why the energy-flow diagram is here despite naming other
    producers and showing community totals — it is printed on the same sheet as
    the QR that led here, so serving it discloses nothing to this bearer. See
    the spec's §9, which states that limit as "nothing beyond the printed
    document" rather than as a list of forbidden fields.
    """
    token, error = _resolve(request, prefix)
    if error is not None:
        return error

    invoice = token.invoice
    cache_key = _chart_cache_key(invoice)
    cached = cache.get(cache_key)
    if cached is not None:
        return Response(cached)

    lang = invoice.zev.invoice_language or "de"
    # Copied, not used in place: INVOICE_TRANSLATIONS is a module-level
    # constant shared by every invoice in the process, and pdf.py documents
    # why writing into it is a bug. Nothing here mutates it today; copying
    # costs nothing and removes the chance that something later does.
    tr = dict(INVOICE_TRANSLATIONS.get(lang, INVOICE_TRANSLATIONS["de"]))
    try:
        period_context = build_invoice_pdf_period_context(invoice)
        svgs = {
            "energy": _build_energy_chart_svg(invoice, tr),
            "hourly": _build_hourly_profile_chart_svg(
                invoice, tr, shares_by_date=period_context.shares_by_date,
            ),
            "flow": _build_energy_flow_svg(
                invoice, tr, period_stats=period_context.participant_stats,
            ),
        }
    except Exception:
        # The invoice already rendered without these. Failing the whole page
        # for a missing picture would be the wrong trade.
        logger.exception("Public charts failed for invoice %s", invoice.pk)
        return Response(_empty_charts())

    payload = {
        "title": tr["insights_page_title"],
        "intro": tr["insights_page_intro"],
        "charts": [
            {"key": key, "title": tr[title_key], "description": tr[desc_key], "svg": svgs[key]}
            for key, title_key, desc_key in _CHART_COPY
            if svgs[key]
        ],
    }
    cache.set(cache_key, payload, _CHART_CACHE_SECONDS)
    return Response(payload)
