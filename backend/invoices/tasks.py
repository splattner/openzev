"""Celery tasks for async invoice operations."""
import logging
from billiard.exceptions import SoftTimeLimitExceeded
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


def _render_pdfs(invoices) -> int:
    """Render each invoice's PDF serially, returning how many failed.

    Prefetches line items once for the whole batch: callers pass either the
    engine's freshly built list or a period queryset, and neither is required
    to have items loaded. Per-invoice render failures are isolated: one
    participant with an address the QR library rejects must not cost the rest
    of the period its documents. A shared period-context failure prevents
    every invoice in that period from rendering and is not retried once per
    participant.
    """
    from django.db.models import prefetch_related_objects

    from .pdf import build_invoice_pdf_period_context, save_invoice_pdf

    invoices = list(invoices)
    prefetch_related_objects(invoices, "items")
    failed = 0
    period_contexts = {}
    failed_periods = set()
    for invoice in invoices:
        key = (invoice.zev_id, invoice.period_start, invoice.period_end)
        if key in failed_periods:
            failed += 1
            continue

        if key not in period_contexts:
            try:
                period_contexts[key] = build_invoice_pdf_period_context(invoice)
            except SoftTimeLimitExceeded:
                raise
            except Exception:
                failed += 1
                failed_periods.add(key)
                logger.exception(
                    "PDF period context generation failed for ZEV %s, %s to %s",
                    invoice.zev_id,
                    invoice.period_start,
                    invoice.period_end,
                )
                continue

        try:
            save_invoice_pdf(invoice, period_context=period_contexts[key])
        except SoftTimeLimitExceeded:
            raise
        except Exception as exc:
            failed += 1
            logger.error("PDF generation failed for invoice %s: %s", invoice.invoice_number, exc)
    return failed


def _record_aborted_batch_event(
    *,
    action_type: str,
    zev,
    period_start: str,
    period_end: str,
    summary: str,
    extra_metadata: dict | None = None,
) -> None:
    """Record the FAILED audit event for a bulk ZEV task aborted mid-batch.

    Best-effort: an audit-write failure must not replace the original
    exception reaching Celery, so it is logged and swallowed here while the
    outer handler re-raises.
    """
    try:
        record_audit_event(
            action_category=AuditActionCategory.INVOICE,
            action_type=action_type,
            target_type="zev.Zev",
            target=zev,
            target_id=str(zev.id),
            target_display=zev.name,
            summary=summary,
            status=AuditEventStatus.FAILED,
            source=AuditEventSource.CELERY,
            metadata={
                "period_start": period_start,
                "period_end": period_end,
                "aborted": True,
                **(extra_metadata or {}),
            },
        )
    except Exception:
        logger.exception("Aborted-batch audit event could not be recorded")


@shared_task(bind=True, max_retries=1)
def generate_invoice_pdf_task(self, invoice_id: str):
    """Render one invoice's PDF off the request thread.

    A render takes seconds, so the single-invoice generate endpoint queues this
    rather than holding the response open for it.
    """
    from .models import Invoice

    try:
        invoice = Invoice.objects.select_related("participant", "zev").get(pk=invoice_id)
    except Invoice.DoesNotExist:
        logger.error("Invoice %s not found for PDF generation", invoice_id)
        return

    if _render_pdfs([invoice]):
        record_audit_event(
            action_category=AuditActionCategory.INVOICE,
            action_type="invoice.generate_pdf",
            target_type="invoices.Invoice",
            target=invoice,
            target_id=str(invoice.pk),
            target_display=invoice.invoice_number,
            summary=f"PDF generation failed for invoice {invoice.invoice_number}.",
            status=AuditEventStatus.FAILED,
            source=AuditEventSource.CELERY,
        )


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
        # generate_invoices_for_zev isolates per-participant failures itself, so
        # nothing here needs to catch them (see engine.generate_invoices_for_zev).
        invoices, failures = generate_invoices_for_zev(zev, start, end)
    except BaseException as exc:
        # Creation never returned — record the abort (see
        # _record_aborted_batch_event for the policy), then re-raise.
        logger.exception("Invoice creation aborted for ZEV %s", zev.name)
        _record_aborted_batch_event(
            action_type="invoice.generate_all",
            zev=zev,
            period_start=period_start,
            period_end=period_end,
            summary=f"Invoice creation for ZEV {zev.name} aborted: {exc}.",
            extra_metadata={"phase": "creation"},
        )
        raise

    # Rows are already committed before rendering; review, download, approval
    # and email do not require a PDF (see workflow.approve_invoice).
    try:
        pdf_failed = _render_pdfs(invoices)
    except BaseException as exc:
        # Invoices (and some PDFs) may already be saved — record the abort,
        # then re-raise.
        logger.exception("Invoice generation aborted after saving %d invoices", len(invoices))
        _record_aborted_batch_event(
            action_type="invoice.generate_all",
            zev=zev,
            period_start=period_start,
            period_end=period_end,
            summary=(
                f"Invoice generation for ZEV {zev.name} aborted after "
                f"{len(invoices)} invoices were saved: {exc}."
            ),
            extra_metadata={"phase": "rendering", "invoice_count": len(invoices), "failures": failures},
        )
        raise

    logger.info(
        "Generated %d invoices for ZEV %s (%d participant(s) failed, %d PDFs failed)",
        len(invoices), zev.name, len(failures), pdf_failed,
    )
    summary = (
        f"Generated {len(invoices)} invoices for ZEV {zev.name}"
        + (f"; {len(failures)} participant(s) failed" if failures else "")
        + "."
    )
    record_audit_event(
        action_category=AuditActionCategory.INVOICE,
        action_type="invoice.generate_all",
        target_type="zev.Zev",
        target=zev,
        target_id=str(zev.id),
        target_display=zev.name,
        summary=summary,
        status=AuditEventStatus.SUCCESS if not failures and pdf_failed == 0 else AuditEventStatus.FAILED,
        source=AuditEventSource.CELERY,
        metadata={
            "period_start": period_start,
            "period_end": period_end,
            "invoice_count": len(invoices),
            "failures": failures,
            "pdf_failed": pdf_failed,
        },
    )


@shared_task(bind=True, max_retries=1)
def generate_zev_pdfs_task(self, zev_id: str, period_start: str, period_end: str):
    """Re-render PDFs for every invoice of a ZEV period.

    Invoices normally carry a PDF from generation; this re-renders the whole
    period to pick up a changed PDF template, and also fills the gap for any
    invoice whose PDF is missing.
    """
    from zev.models import Zev
    from .models import Invoice

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

    try:
        failed = _render_pdfs(invoices)
    except BaseException as exc:
        # Some PDFs may already be saved — record the abort, then re-raise.
        logger.exception("Bulk PDF generation aborted for ZEV %s", zev.name)
        _record_aborted_batch_event(
            action_type="invoice.generate_pdfs_all",
            zev=zev,
            period_start=period_start,
            period_end=period_end,
            summary=f"Bulk PDF generation for ZEV {zev.name} aborted: {exc}.",
        )
        raise

    count = len(invoices) - failed

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
