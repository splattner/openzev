"""Celery tasks for async invoice operations."""
import logging
from datetime import datetime, timezone
from celery import shared_task
from django.core.mail import EmailMessage
from django.utils import timezone as djtimezone

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def send_invoice_email_task(self, invoice_id: str, recipient_email: str = None):
    """Send an invoice PDF by email to the participant."""
    from accounts.models import AppSettings
    from .models import Invoice, EmailLog, InvoiceStatus
    from .pdf import save_invoice_pdf, _format_date_value

    try:
        invoice = Invoice.objects.select_related("participant", "zev").get(pk=invoice_id)
    except Invoice.DoesNotExist:
        logger.error("Invoice %s not found for email task", invoice_id)
        return

    # Ensure PDF exists
    if not invoice.pdf_file:
        save_invoice_pdf(invoice)

    recipient = recipient_email or invoice.participant.email
    if not recipient:
        logger.warning("No email for participant %s — skipping", invoice.participant)
        return

    app_settings = AppSettings.load()
    formatted_period_start = _format_date_value(invoice.period_start, app_settings.date_format_short)
    formatted_period_end = _format_date_value(invoice.period_end, app_settings.date_format_short)

    from zev.models import DEFAULT_EMAIL_SUBJECT_TEMPLATE, DEFAULT_EMAIL_BODY_TEMPLATE
    from .models import EmailTemplate, EMAIL_TEMPLATE_DEFAULTS

    template_ctx = {
        "invoice_number": invoice.invoice_number,
        "zev_name": invoice.zev.name,
        "participant_name": invoice.participant.full_name,
        "period_start": formatted_period_start,
        "period_end": formatted_period_end,
        "total_chf": invoice.total_chf,
    }

    # Resolution order: per-ZEV override → admin global override → hardcoded default
    global_override = EmailTemplate.objects.filter(template_key="invoice_email").first()
    global_subject = global_override.subject if global_override else DEFAULT_EMAIL_SUBJECT_TEMPLATE
    global_body = global_override.body if global_override else DEFAULT_EMAIL_BODY_TEMPLATE

    subject_tpl = invoice.zev.email_subject_template or global_subject
    body_tpl = invoice.zev.email_body_template or global_body

    try:
        subject = subject_tpl.format_map(template_ctx)
        body = body_tpl.format_map(template_ctx)
    except (KeyError, ValueError) as exc:
        logger.warning(
            "Email template rendering failed for ZEV %s (%s); falling back to defaults: %s",
            invoice.zev.name, invoice.zev_id, exc,
        )
        subject = DEFAULT_EMAIL_SUBJECT_TEMPLATE.format_map(template_ctx)
        body = DEFAULT_EMAIL_BODY_TEMPLATE.format_map(template_ctx)

    log = EmailLog.objects.create(
        invoice=invoice,
        recipient=recipient,
        subject=subject,
        status="pending",
    )

    try:
        email = EmailMessage(subject=subject, body=body, to=[recipient])
        email.attach(
            f"invoice_{invoice.invoice_number}.pdf",
            invoice.pdf_file.read(),
            "application/pdf",
        )
        email.send()
        log.status = "sent"
        log.sent_at = djtimezone.now()
        log.save()

        invoice_update_fields = ["sent_at"]
        if invoice.status == InvoiceStatus.APPROVED:
            invoice.status = InvoiceStatus.SENT
            invoice_update_fields.append("status")

        invoice.sent_at = log.sent_at
        invoice.save(update_fields=invoice_update_fields)
        logger.info("Sent invoice %s to %s", invoice.invoice_number, recipient)
    except Exception as exc:
        log.status = "failed"
        log.error_message = str(exc)
        log.save()
        logger.error("Failed to send invoice %s: %s", invoice.invoice_number, exc)
        raise self.retry(exc=exc, countdown=60)
