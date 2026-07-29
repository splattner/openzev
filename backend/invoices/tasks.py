"""Celery tasks for async invoice operations."""
import logging
from celery import shared_task
from django.core.mail import EmailMessage
from django.utils import timezone as djtimezone
from audit.models import AuditActionCategory, AuditEventSource, AuditEventStatus
from audit.services import record_audit_event

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def send_invoice_email_task(self, invoice_id: str, recipient_email: str = None):
    """Send an invoice PDF by email to the participant."""
    from accounts.models import AppSettings
    from .models import Invoice, EmailLog
    from .pdf import save_invoice_pdf, _format_date_value
    from .workflow import record_email_delivery

    try:
        invoice = Invoice.objects.select_related("participant", "zev").get(pk=invoice_id)
    except Invoice.DoesNotExist:
        logger.error("Invoice %s not found for email task", invoice_id)
        record_audit_event(
            action_category=AuditActionCategory.INVOICE,
            action_type="invoice.email_task",
            target_type="invoices.Invoice",
            target_id=str(invoice_id),
            target_display=str(invoice_id),
            summary=f"Invoice email task failed: invoice {invoice_id} not found.",
            status=AuditEventStatus.FAILED,
            source=AuditEventSource.CELERY,
        )
        return

    # Ensure PDF exists
    if not invoice.pdf_file:
        save_invoice_pdf(invoice)

    recipient = recipient_email or invoice.participant.email
    if not recipient:
        logger.warning("No email for participant %s — skipping", invoice.participant)
        record_audit_event(
            action_category=AuditActionCategory.INVOICE,
            action_type="invoice.email_task",
            target_type="invoices.Invoice",
            target=invoice,
            target_id=str(invoice.pk),
            target_display=invoice.invoice_number,
            summary=f"Invoice email task failed for {invoice.invoice_number}: no recipient email.",
            status=AuditEventStatus.FAILED,
            source=AuditEventSource.CELERY,
        )
        return

    app_settings = AppSettings.load()
    formatted_period_start = _format_date_value(invoice.period_start, app_settings.date_format_short)
    formatted_period_end = _format_date_value(invoice.period_end, app_settings.date_format_short)
    formatted_due_date = _format_date_value(invoice.due_date, app_settings.date_format_short) if invoice.due_date else ""

    from zev.models import DEFAULT_EMAIL_SUBJECT_TEMPLATE, DEFAULT_EMAIL_BODY_TEMPLATE
    from .models import EmailTemplate

    template_ctx = {
        "invoice_number": invoice.invoice_number,
        "zev_name": invoice.zev.name,
        "participant_name": invoice.participant.full_name,
        "period_start": formatted_period_start,
        "period_end": formatted_period_end,
        "total_chf": invoice.total_chf,
        "due_date": formatted_due_date,
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
        status=EmailLog.Status.PENDING,
    )

    try:
        email = EmailMessage(subject=subject, body=body, to=[recipient])
        email.attach(
            f"invoice_{invoice.invoice_number}.pdf",
            invoice.pdf_file.read(),
            "application/pdf",
        )
        email.send()
        log.status = EmailLog.Status.SENT
        log.sent_at = djtimezone.now()
        log.save()

        previous_status = record_email_delivery(invoice, log.sent_at)
        logger.info("Sent invoice %s to %s", invoice.invoice_number, recipient)
        record_audit_event(
            action_category=AuditActionCategory.INVOICE,
            action_type="invoice.email_sent",
            target_type="invoices.Invoice",
            target=invoice,
            target_id=str(invoice.pk),
            target_display=invoice.invoice_number,
            summary=f"Sent invoice email for {invoice.invoice_number} to {recipient}.",
            status=AuditEventStatus.SUCCESS,
            source=AuditEventSource.CELERY,
            changes={
                "status": {
                    "before": previous_status,
                    "after": invoice.status,
                }
            },
            metadata={"recipient": recipient, "email_log_id": str(log.id)},
        )
    except Exception as exc:
        log.status = EmailLog.Status.FAILED
        log.error_message = str(exc)
        log.save()
        logger.error("Failed to send invoice %s: %s", invoice.invoice_number, exc)
        record_audit_event(
            action_category=AuditActionCategory.INVOICE,
            action_type="invoice.email_sent",
            target_type="invoices.Invoice",
            target=invoice,
            target_id=str(invoice.pk),
            target_display=invoice.invoice_number,
            summary=f"Invoice email send failed for {invoice.invoice_number}.",
            status=AuditEventStatus.FAILED,
            source=AuditEventSource.CELERY,
            metadata={"recipient": recipient, "email_log_id": str(log.id), "error": str(exc)},
        )
        raise self.retry(exc=exc, countdown=60)


@shared_task(bind=True, max_retries=1)
def generate_zev_invoices_task(self, zev_id: str, period_start: str, period_end: str):
    """Generate invoices for all participants of a ZEV in the background."""
    from datetime import date

    from zev.models import Zev
    from .engine import generate_invoices_for_zev

    try:
        zev = Zev.objects.get(pk=zev_id)
    except Zev.DoesNotExist:
        logger.error("ZEV %s not found for bulk invoice generation", zev_id)
        record_audit_event(
            action_category=AuditActionCategory.INVOICE,
            action_type="invoice.generate_all",
            target_type="zev.Zev",
            target_id=str(zev_id),
            target_display=str(zev_id),
            summary=f"Bulk invoice generation failed: ZEV {zev_id} not found.",
            status=AuditEventStatus.FAILED,
            source=AuditEventSource.CELERY,
        )
        return

    start = date.fromisoformat(period_start)
    end = date.fromisoformat(period_end)
    try:
        invoices = generate_invoices_for_zev(zev, start, end)
    except ValueError as exc:
        logger.error("Bulk invoice generation failed for ZEV %s: %s", zev.name, exc)
        record_audit_event(
            action_category=AuditActionCategory.INVOICE,
            action_type="invoice.generate_all",
            target_type="zev.Zev",
            target=zev,
            target_id=str(zev.id),
            target_display=zev.name,
            summary=f"Bulk invoice generation failed for ZEV {zev.name}.",
            status=AuditEventStatus.FAILED,
            source=AuditEventSource.CELERY,
            metadata={"period_start": period_start, "period_end": period_end, "error": str(exc)},
        )
        return

    logger.info("Generated %d invoices for ZEV %s", len(invoices), zev.name)
    record_audit_event(
        action_category=AuditActionCategory.INVOICE,
        action_type="invoice.generate_all",
        target_type="zev.Zev",
        target=zev,
        target_id=str(zev.id),
        target_display=zev.name,
        summary=f"Generated {len(invoices)} invoices for ZEV {zev.name}.",
        status=AuditEventStatus.SUCCESS,
        source=AuditEventSource.CELERY,
        metadata={
            "period_start": period_start,
            "period_end": period_end,
            "invoice_count": len(invoices),
        },
    )


@shared_task(bind=True, max_retries=1)
def generate_zev_pdfs_task(self, zev_id: str, period_start: str, period_end: str):
    """Generate PDFs for all invoices of a ZEV period in the background."""
    from zev.models import Zev
    from .models import Invoice
    from .pdf import save_invoice_pdf

    try:
        zev = Zev.objects.get(pk=zev_id)
    except Zev.DoesNotExist:
        logger.error("ZEV %s not found for bulk PDF generation", zev_id)
        record_audit_event(
            action_category=AuditActionCategory.INVOICE,
            action_type="invoice.generate_pdfs_all",
            target_type="zev.Zev",
            target_id=str(zev_id),
            target_display=str(zev_id),
            summary=f"Bulk PDF generation failed: ZEV {zev_id} not found.",
            status=AuditEventStatus.FAILED,
            source=AuditEventSource.CELERY,
        )
        return

    invoices = Invoice.objects.filter(
        zev=zev,
        period_start=period_start,
        period_end=period_end,
    ).select_related("participant", "zev")

    count = 0
    failed = 0
    for invoice in invoices:
        try:
            save_invoice_pdf(invoice)
            count += 1
        except Exception as exc:
            failed += 1
            logger.error("PDF generation failed for invoice %s: %s", invoice.invoice_number, exc)

    logger.info("Generated %d invoice PDFs for ZEV %s (%d failed)", count, zev.name, failed)
    record_audit_event(
        action_category=AuditActionCategory.INVOICE,
        action_type="invoice.generate_pdfs_all",
        target_type="zev.Zev",
        target=zev,
        target_id=str(zev.id),
        target_display=zev.name,
        summary=f"Generated {count} invoice PDFs in batch.",
        status=AuditEventStatus.SUCCESS if failed == 0 else AuditEventStatus.FAILED,
        source=AuditEventSource.CELERY,
        metadata={
            "period_start": period_start,
            "period_end": period_end,
            "generated": count,
            "failed": failed,
        },
    )
