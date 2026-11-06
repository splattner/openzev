"""The optional email for a delivered document (SPEC-2026-11-participant-document-inbox §6.5).

Link-only and without an attachment: the document lives in the inbox, the
email says it is there. An invoice is never emailed from here (its own email
carries the PDF), and the participant's address is never written to the audit
trail.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import EmailMessage
from django.db import transaction

from audit.models import AuditEventSource, AuditEventStatus
from config.safe_format import render_with_fallback

from .links import inbox_url
from .models import DocumentKind
from .services import _audit

logger = logging.getLogger(__name__)


def queue_document_emails(documents) -> tuple[int, int]:
    """Queue one email per document once the surrounding transaction commits.

    Returns ``(queued, without_email)``: a participant with no address is
    skipped and counted so the operator can tell. The in-app notification is
    independent of this and unaffected.
    """
    from .tasks import send_document_email_task

    queued = without_email = 0
    for document in documents:
        participant = document.participant
        if participant is None or document.kind == DocumentKind.INVOICE:
            continue
        if not participant.email:
            without_email += 1
            continue
        transaction.on_commit(lambda pk=str(document.pk): send_document_email_task.delay(pk))
        queued += 1
    return queued, without_email


def render_document_email(document) -> tuple[str, str]:
    """Subject and body: the ZEV language's default, or the admin's override for every language."""
    from invoices.email_context import build_document_email_context
    from invoices.models import DOCUMENT_EMAIL_DEFAULTS_BY_LANGUAGE, EmailTemplate

    zev = document.zev
    defaults = DOCUMENT_EMAIL_DEFAULTS_BY_LANGUAGE.get(
        zev.invoice_language or "de", DOCUMENT_EMAIL_DEFAULTS_BY_LANGUAGE["en"]
    )
    override = EmailTemplate.objects.filter(template_key="document_delivered").first()
    context = build_document_email_context(
        participant_name=document.participant.full_name,
        zev_name=zev.name,
        title=document.title,
        inbox_url=inbox_url(document.participant) or f"{settings.FRONTEND_URL.rstrip('/')}/me/documents",
    )

    def render(template: str, fallback: str) -> str:
        return render_with_fallback(
            template, fallback, context,
            on_error=lambda _exc: logger.warning("Invalid document_delivered template; using default."),
        )

    return (
        render(override.subject if override else defaults["subject"], defaults["subject"]),
        render(override.body if override else defaults["body"], defaults["body"]),
    )


def send_document_email(document) -> bool:
    """Send the email for ``document``; ``False`` when it no longer applies. Raises on a send failure."""
    participant = document.participant
    if participant is None or not participant.email or not document.is_current:
        return False
    subject, body = render_document_email(document)
    EmailMessage(
        subject=subject, body=body, from_email=settings.DEFAULT_FROM_EMAIL, to=[participant.email]
    ).send(fail_silently=False)
    _audit(
        "emailed", document, source=AuditEventSource.CELERY,
        summary=f"Emailed the participant that “{document.title}” was delivered.",
    )
    return True


def record_email_failure(document, exc: Exception) -> None:
    """Audit a send that gave up. Only the error class is kept: its text may quote the address."""
    try:
        _audit(
            "emailed", document, source=AuditEventSource.CELERY,
            summary=f"Emailing the participant about “{document.title}” failed.",
            status=AuditEventStatus.FAILED,
            metadata={"error": type(exc).__name__},
        )
    except Exception:
        logger.exception("The failed email for document %s could not be audited", document.pk)
