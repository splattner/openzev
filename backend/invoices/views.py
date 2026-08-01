import io
import logging
import zipfile
from datetime import date as date_type

from rest_framework import mixins, viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.http import HttpResponse
from accounts.permissions import IsZevOwnerOrAdmin
from zev.models import Zev, Participant
from zev.scoping import ZevScopedQuerySetMixin
from .models import Invoice, InvoiceStatus, EmailLog
from .serializers import (
    InvoiceSerializer, GenerateInvoiceSerializer, GenerateZevInvoicesSerializer
)
from .engine import generate_invoice
from .pdf import save_invoice_pdf
from .tasks import (
    generate_invoice_pdf_task,
    generate_zev_invoices_task,
    generate_zev_pdfs_task,
    send_invoice_email_task,
)
from .period_overview import compute_period_overview
from .workflow import (
    InvoiceWorkflowError,
    approve_invoice,
    cancel_invoice,
    can_delete_invoice,
    mark_invoice_paid,
    mark_invoice_sent,
)
from audit.models import AuditActionCategory, AuditEventStatus
from audit.services import build_diff, record_audit_event

logger = logging.getLogger(__name__)


def _invoice_target_display(invoice: Invoice) -> str:
    return invoice.invoice_number or str(invoice.pk)


def _record_invoice_event(*, invoice: Invoice | None = None, target_id: str = "", target_display: str = "", **kwargs):
    """Record an invoice audit event, defaulting the target to ``invoice``.

    Unlike the other apps this wrapper earns its keep: callers pass the invoice
    itself and get target/id/display derived from it.
    """
    record_audit_event(
        action_category=AuditActionCategory.INVOICE,
        target_type=kwargs.pop("target_type", "invoices.Invoice"),
        target=invoice,
        target_id=target_id or (str(invoice.pk) if invoice else ""),
        target_display=target_display or (_invoice_target_display(invoice) if invoice else ""),
        **kwargs,
    )


class InvoiceViewSet(
    ZevScopedQuerySetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Invoices are mutated only through the dedicated workflow actions below
    (generate/approve/mark-sent/mark-paid/cancel etc.), each of which is
    permission-checked and audit-logged. Generic create/update/partial_update
    are intentionally not exposed — they would let any caller with read access
    to an invoice overwrite status, totals, or participant/zev directly,
    bypassing those workflow guards and leaving no audit trail.
    """

    serializer_class = InvoiceSerializer
    permission_classes = [IsAuthenticated]
    zev_owner_filter = "zev__owner"
    participant_filter = "participant__user"

    def get_queryset(self):
        # Participants see only their own invoices
        return self.scope_queryset(
            Invoice.objects.select_related("participant", "zev").prefetch_related("items", "email_logs")
        )

    def destroy(self, request, *args, **kwargs):
        invoice = self.get_object()
        if not request.user.is_zev_owner:
            _record_invoice_event(
                request=request,
                action_type="invoice.delete",
                summary=f"Denied invoice deletion for {_invoice_target_display(invoice)}.",
                status=AuditEventStatus.DENIED,
                invoice=invoice,
            )
            return Response({"error": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)
        if not request.user.is_admin and invoice.zev.owner != request.user:
            _record_invoice_event(
                request=request,
                action_type="invoice.delete",
                summary=f"Denied invoice deletion for {_invoice_target_display(invoice)} due to tenant scope.",
                status=AuditEventStatus.DENIED,
                invoice=invoice,
            )
            return Response({"error": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)
        if not request.user.is_admin and not can_delete_invoice(invoice):
            _record_invoice_event(
                request=request,
                action_type="invoice.delete",
                summary=f"Denied invoice deletion for {_invoice_target_display(invoice)} due to status guard.",
                status=AuditEventStatus.DENIED,
                invoice=invoice,
                changes={"status": {"before": invoice.status, "after": invoice.status}},
            )
            return Response({"error": "Only draft or cancelled invoices can be deleted."}, status=status.HTTP_400_BAD_REQUEST)
        invoice_number = _invoice_target_display(invoice)
        invoice_id = str(invoice.pk)
        participant_id = str(invoice.participant_id)
        zev_id = str(invoice.zev_id)
        response = super().destroy(request, *args, **kwargs)
        _record_invoice_event(
            request=request,
            action_type="invoice.delete",
            summary=f"Deleted invoice {invoice_number}.",
            target_id=invoice_id,
            target_display=invoice_number,
            changes={"status": {"before": invoice.status, "after": "deleted"}},
            metadata={"participant_id": participant_id, "zev_id": zev_id},
        )
        return response

    @action(detail=False, methods=["post"], url_path="generate",
            permission_classes=[IsAuthenticated, IsZevOwnerOrAdmin])
    def generate(self, request):
        """Generate a single invoice for a participant."""
        s = GenerateInvoiceSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            participant = Participant.objects.get(pk=s.validated_data["participant_id"])
        except Participant.DoesNotExist:
            return Response({"error": "Participant not found."}, status=status.HTTP_404_NOT_FOUND)

        if not request.user.is_admin and participant.zev.owner != request.user:
            return Response({"error": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)

        try:
            invoice = generate_invoice(
                participant,
                s.validated_data["period_start"],
                s.validated_data["period_end"],
            )
        except ValueError as exc:
            _record_invoice_event(
                request=request,
                action_type="invoice.generate",
                summary=f"Failed to generate invoice for participant {participant.id}.",
                status=AuditEventStatus.FAILED,
                target_type="zev.Participant",
                target_id=str(participant.id),
                target_display=participant.full_name,
                metadata={
                    "period_start": s.validated_data["period_start"],
                    "period_end": s.validated_data["period_end"],
                    "error": str(exc),
                },
            )
            return Response(
                {"error": "Invoice generation failed. The invoice may already exist in a non-regenerable state."},
                status=status.HTTP_409_CONFLICT,
            )
        # Queued rather than rendered inline: a render takes seconds, and the
        # caller only needs the invoice back. The PDF follows on its own so it
        # is never something the operator has to ask for.
        #
        # A broker outage must not fail the request. The invoice is the
        # deliverable and it is already committed; failing here would return an
        # error for work that succeeded, and the operator would have no idea the
        # invoice exists. The PDF is recoverable — the email task renders one
        # lazily if it is still missing, and there is a per-invoice regenerate
        # action — so the failure is recorded and the response stands.
        try:
            generate_invoice_pdf_task.delay(str(invoice.pk))
        except Exception as exc:
            logger.error("Could not queue PDF generation for invoice %s: %s", invoice.invoice_number, exc)
            _record_invoice_event(
                request=request,
                action_type="invoice.generate_pdf",
                summary=f"Could not queue PDF generation for invoice {_invoice_target_display(invoice)}.",
                status=AuditEventStatus.FAILED,
                invoice=invoice,
                metadata={"error": str(exc)},
            )
        _record_invoice_event(
            request=request,
            action_type="invoice.generate",
            summary=f"Generated invoice {_invoice_target_display(invoice)}.",
            invoice=invoice,
            changes=build_diff({}, {"status": invoice.status}, ["status"]),
            metadata={
                "participant_id": str(participant.id),
                "period_start": s.validated_data["period_start"],
                "period_end": s.validated_data["period_end"],
            },
        )
        return Response(InvoiceSerializer(invoice, context={"request": request}).data,
                        status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["post"], url_path="generate-all",
            permission_classes=[IsAuthenticated, IsZevOwnerOrAdmin])
    def generate_all(self, request):
        """Queue background generation of invoices for all participants of a ZEV."""
        s = GenerateZevInvoicesSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            zev = Zev.objects.get(pk=s.validated_data["zev_id"])
        except Zev.DoesNotExist:
            return Response({"error": "ZEV not found."}, status=status.HTTP_404_NOT_FOUND)

        if not request.user.is_admin and zev.owner != request.user:
            return Response({"error": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)

        period_start = s.validated_data["period_start"]
        period_end = s.validated_data["period_end"]
        participant_count = Participant.objects.filter(zev=zev).count()

        generate_zev_invoices_task.delay(str(zev.id), str(period_start), str(period_end))
        _record_invoice_event(
            request=request,
            action_type="invoice.generate_all",
            summary=f"Queued invoice generation for ZEV {zev.name}.",
            status=AuditEventStatus.QUEUED,
            target_type="zev.Zev",
            target_id=str(zev.id),
            target_display=zev.name,
            metadata={
                "period_start": str(period_start),
                "period_end": str(period_end),
                "participant_count": participant_count,
            },
        )
        return Response(
            {
                "detail": "Invoice generation queued.",
                "queued": True,
                "participant_count": participant_count,
            },
            status=status.HTTP_202_ACCEPTED,
        )

    @action(detail=False, methods=["get"], url_path="period-overview", permission_classes=[IsAuthenticated, IsZevOwnerOrAdmin])
    def period_overview(self, request):
        """Return one row per participant for a ZEV/period with invoice + metering data readiness."""
        zev_id = request.query_params.get("zev_id")
        period_start_raw = request.query_params.get("period_start")
        period_end_raw = request.query_params.get("period_end")

        if not zev_id or not period_start_raw or not period_end_raw:
            return Response(
                {"error": "zev_id, period_start and period_end are required query parameters."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            period_start = date_type.fromisoformat(period_start_raw)
            period_end = date_type.fromisoformat(period_end_raw)
        except ValueError:
            return Response({"error": "period_start/period_end must be YYYY-MM-DD."}, status=status.HTTP_400_BAD_REQUEST)

        if period_start > period_end:
            return Response({"error": "period_start must be on or before period_end."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            zev = Zev.objects.get(pk=zev_id)
        except Zev.DoesNotExist:
            return Response({"error": "ZEV not found."}, status=status.HTTP_404_NOT_FOUND)

        if not request.user.is_admin and zev.owner_id != request.user.id:
            return Response({"error": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)

        rows = compute_period_overview(zev=zev, period_start=period_start, period_end=period_end, request=request)

        return Response(
            {
                "zev_id": str(zev.id),
                "zev_name": zev.name,
                "billing_interval": zev.billing_interval,
                "period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(),
                "rows": rows,
            }
        )

    @action(detail=True, methods=["post"], url_path="generate-pdf",
            permission_classes=[IsAuthenticated, IsZevOwnerOrAdmin])
    def generate_pdf(self, request, pk=None):
        """Generate / regenerate the PDF for an invoice."""
        invoice = self.get_object()
        save_invoice_pdf(invoice)
        _record_invoice_event(
            request=request,
            action_type="invoice.generate_pdf",
            summary=f"Generated PDF for invoice {_invoice_target_display(invoice)}.",
            invoice=invoice,
        )
        return Response({"pdf_url": request.build_absolute_uri(invoice.pdf_file.url)})

    @action(detail=True, methods=["post"], url_path="send-email",
            permission_classes=[IsAuthenticated, IsZevOwnerOrAdmin])
    def send_email(self, request, pk=None):
        """Queue an invoice PDF email to the participant."""
        invoice = self.get_object()
        recipient = request.data.get("email") or invoice.participant.email
        if not recipient:
            _record_invoice_event(
                request=request,
                action_type="invoice.send_email",
                summary=f"Failed to queue email for invoice {_invoice_target_display(invoice)}: no recipient.",
                status=AuditEventStatus.FAILED,
                invoice=invoice,
            )
            return Response({"error": "No email address available."}, status=status.HTTP_400_BAD_REQUEST)
        send_invoice_email_task.delay(str(invoice.pk), recipient)
        _record_invoice_event(
            request=request,
            action_type="invoice.send_email",
            summary=f"Queued invoice email for {_invoice_target_display(invoice)} to {recipient}.",
            status=AuditEventStatus.QUEUED,
            invoice=invoice,
            metadata={"recipient": recipient},
        )
        return Response({"detail": f"Email queued for {recipient}."})

    def _perform_status_transition(self, request, *, action_type, workflow_fn, denied_verb, success_summary):
        """Shared body for the four status-transition actions below.

        Each just picks a workflow function (which raises InvoiceWorkflowError
        on an invalid transition) and phrasing for the audit log; this method
        owns the get-object/try-except/audit-event/response shape they all
        share identically.
        """
        invoice = self.get_object()
        try:
            before = workflow_fn(invoice)
        except InvoiceWorkflowError as exc:
            _record_invoice_event(
                request=request,
                action_type=action_type,
                summary=f"Denied {denied_verb} for {_invoice_target_display(invoice)}: {exc.user_message}",
                status=AuditEventStatus.DENIED,
                invoice=invoice,
            )
            return Response({"error": exc.user_message}, status=status.HTTP_400_BAD_REQUEST)
        _record_invoice_event(
            request=request,
            action_type=action_type,
            summary=success_summary(invoice),
            invoice=invoice,
            changes=build_diff(before, {"status": invoice.status}, ["status"]),
        )
        return Response(InvoiceSerializer(invoice, context={"request": request}).data)

    @action(detail=True, methods=["post"], url_path="approve",
            permission_classes=[IsAuthenticated, IsZevOwnerOrAdmin])
    def approve(self, request, pk=None):
        """Transition a draft invoice to approved."""
        return self._perform_status_transition(
            request,
            action_type="invoice.approve",
            workflow_fn=approve_invoice,
            denied_verb="approval",
            success_summary=lambda invoice: f"Approved invoice {_invoice_target_display(invoice)}.",
        )

    @action(detail=True, methods=["post"], url_path="mark-sent",
            permission_classes=[IsAuthenticated, IsZevOwnerOrAdmin])
    def mark_sent(self, request, pk=None):
        """Transition an approved invoice to sent/locked state."""
        return self._perform_status_transition(
            request,
            action_type="invoice.mark_sent",
            workflow_fn=mark_invoice_sent,
            denied_verb="mark-sent",
            success_summary=lambda invoice: f"Marked invoice {_invoice_target_display(invoice)} as sent.",
        )

    @action(detail=True, methods=["post"], url_path="mark-paid",
            permission_classes=[IsAuthenticated, IsZevOwnerOrAdmin])
    def mark_paid(self, request, pk=None):
        """Record that a sent invoice has been paid."""
        return self._perform_status_transition(
            request,
            action_type="invoice.mark_paid",
            workflow_fn=mark_invoice_paid,
            denied_verb="mark-paid",
            success_summary=lambda invoice: f"Marked invoice {_invoice_target_display(invoice)} as paid.",
        )

    @action(detail=True, methods=["post"], url_path="cancel",
            permission_classes=[IsAuthenticated, IsZevOwnerOrAdmin])
    def cancel(self, request, pk=None):
        """Cancel an invoice that has not yet been paid."""
        return self._perform_status_transition(
            request,
            action_type="invoice.cancel",
            workflow_fn=cancel_invoice,
            denied_verb="cancellation",
            success_summary=lambda invoice: f"Cancelled invoice {_invoice_target_display(invoice)}.",
        )

    @action(detail=True, methods=["post"], url_path=r"retry-email/(?P<email_log_id>[^/.]+)",
            permission_classes=[IsAuthenticated, IsZevOwnerOrAdmin])
    def retry_email(self, request, pk=None, email_log_id=None):
        """Retry sending a failed invoice email."""
        invoice = self.get_object()
        try:
            email_log = EmailLog.objects.get(pk=email_log_id, invoice=invoice)
        except EmailLog.DoesNotExist:
            _record_invoice_event(
                request=request,
                action_type="invoice.retry_email",
                summary=f"Failed email retry for {_invoice_target_display(invoice)}: email log not found.",
                status=AuditEventStatus.FAILED,
                invoice=invoice,
                metadata={"email_log_id": email_log_id},
            )
            return Response({"error": "Email log not found."}, status=status.HTTP_404_NOT_FOUND)

        if email_log.status == "sent":
            _record_invoice_event(
                request=request,
                action_type="invoice.retry_email",
                summary=f"Denied email retry for {_invoice_target_display(invoice)}: email already sent.",
                status=AuditEventStatus.DENIED,
                invoice=invoice,
                metadata={"email_log_id": str(email_log.id), "recipient": email_log.recipient},
            )
            return Response({"error": "Email already sent."}, status=status.HTTP_400_BAD_REQUEST)

        # Queue retry
        send_invoice_email_task.delay(str(invoice.pk), email_log.recipient)
        _record_invoice_event(
            request=request,
            action_type="invoice.retry_email",
            summary=f"Queued email retry for {_invoice_target_display(invoice)} to {email_log.recipient}.",
            status=AuditEventStatus.QUEUED,
            invoice=invoice,
            metadata={"email_log_id": str(email_log.id), "recipient": email_log.recipient},
        )
        return Response({"detail": f"Email retry queued for {email_log.recipient}."})

    # ── Batch operations ────────────────────────────────────────────────

    def _get_period_invoices(self, request):
        """Helper: resolve ZEV and period invoices from request data, with permission check."""
        s = GenerateZevInvoicesSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            zev = Zev.objects.get(pk=s.validated_data["zev_id"])
        except Zev.DoesNotExist:
            return None, None, Response({"error": "ZEV not found."}, status=status.HTTP_404_NOT_FOUND)

        if not request.user.is_admin and zev.owner != request.user:
            return None, None, Response({"error": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)

        invoices = Invoice.objects.filter(
            zev=zev,
            period_start=s.validated_data["period_start"],
            period_end=s.validated_data["period_end"],
        ).select_related("participant", "zev").prefetch_related("items", "email_logs")
        return zev, invoices, None

    @action(detail=False, methods=["post"], url_path="approve-all",
            permission_classes=[IsAuthenticated, IsZevOwnerOrAdmin])
    def approve_all(self, request):
        """Approve all draft invoices for a ZEV period."""
        _zev, invoices, error = self._get_period_invoices(request)
        if error:
            return error

        drafts = invoices.filter(status=InvoiceStatus.DRAFT)
        count = drafts.update(status=InvoiceStatus.APPROVED)
        _record_invoice_event(
            request=request,
            action_type="invoice.approve_all",
            summary=f"Approved {count} invoices in batch.",
            target_type="zev.Zev",
            target_id=str(_zev.id),
            target_display=_zev.name,
            metadata={"approved": count},
        )
        return Response({"approved": count})

    @action(detail=False, methods=["post"], url_path="send-all",
            permission_classes=[IsAuthenticated, IsZevOwnerOrAdmin])
    def send_all(self, request):
        """Queue emails for all approved invoices in a ZEV period."""
        _zev, invoices, error = self._get_period_invoices(request)
        if error:
            return error

        approved = list(invoices.filter(status=InvoiceStatus.APPROVED))
        queued = 0
        skipped = 0
        for invoice in approved:
            recipient = invoice.participant.email
            if not recipient:
                skipped += 1
                continue
            send_invoice_email_task.delay(str(invoice.pk), recipient)
            queued += 1
        _record_invoice_event(
            request=request,
            action_type="invoice.send_all",
            summary=f"Queued {queued} invoice emails in batch; skipped {skipped}.",
            status=AuditEventStatus.QUEUED,
            target_type="zev.Zev",
            target_id=str(_zev.id),
            target_display=_zev.name,
            metadata={"queued": queued, "skipped": skipped},
        )
        return Response({"queued": queued, "skipped": skipped})

    @action(detail=False, methods=["post"], url_path="generate-pdfs-all",
            permission_classes=[IsAuthenticated, IsZevOwnerOrAdmin])
    def generate_pdfs_all(self, request):
        """Queue background PDF generation for all invoices in a ZEV period."""
        _zev, invoices, error = self._get_period_invoices(request)
        if error:
            return error

        invoice_count = invoices.count()
        generate_zev_pdfs_task.delay(
            str(_zev.id),
            str(request.data["period_start"]),
            str(request.data["period_end"]),
        )
        _record_invoice_event(
            request=request,
            action_type="invoice.generate_pdfs_all",
            summary=f"Queued PDF generation for {invoice_count} invoices.",
            status=AuditEventStatus.QUEUED,
            target_type="zev.Zev",
            target_id=str(_zev.id),
            target_display=_zev.name,
            metadata={"invoice_count": invoice_count},
        )
        return Response(
            {
                "detail": "PDF generation queued.",
                "queued": True,
                "invoice_count": invoice_count,
            },
            status=status.HTTP_202_ACCEPTED,
        )

    @action(detail=False, methods=["post"], url_path="download-pdfs",
            permission_classes=[IsAuthenticated, IsZevOwnerOrAdmin])
    def download_pdfs(self, request):
        """Download all period PDFs as a single ZIP file."""
        _zev, invoices, error = self._get_period_invoices(request)
        if error:
            return error

        invoices_with_pdf = list(invoices.exclude(pdf_file="").exclude(pdf_file__isnull=True))
        if not invoices_with_pdf:
            return Response({"error": "No PDFs available for this period."}, status=status.HTTP_404_NOT_FOUND)

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for invoice in invoices_with_pdf:
                try:
                    pdf_content = invoice.pdf_file.read()
                    filename = f"{invoice.invoice_number}.pdf"
                    zf.writestr(filename, pdf_content)
                except Exception:
                    continue
        buf.seek(0)

        response = HttpResponse(buf.getvalue(), content_type="application/zip")
        period = invoices_with_pdf[0].period_start.isoformat()
        response["Content-Disposition"] = f'attachment; filename="invoices-{period}.zip"'
        return response
