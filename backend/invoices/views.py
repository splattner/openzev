import io
import zipfile
from datetime import date as date_type

from rest_framework import mixins, viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.http import HttpResponse
from accounts.permissions import IsZevOwnerOrAdmin
from django.db.models import Count, Q, Sum
from django.conf import settings
from django.template import Template, Context
from zev.models import Zev, Participant
from zev.scoping import ZevScopedQuerySetMixin
from .models import Invoice, InvoiceStatus, EmailLog, PdfTemplate, EmailTemplate, EMAIL_TEMPLATE_DEFAULTS
from .serializers import (
    InvoiceSerializer, GenerateInvoiceSerializer, GenerateZevInvoicesSerializer
)
from .engine import generate_invoice
from .pdf import TEMPLATE_NAME, save_invoice_pdf
from .contract_pdf import CONTRACT_TEMPLATE_NAME
from .annual_statement import generate_annual_statement_pdf, ANNUAL_STATEMENT_TEMPLATE
from .financial_summary import generate_financial_summary_pdf
from .tasks import send_invoice_email_task, generate_zev_invoices_task, generate_zev_pdfs_task
from .template_context import build_sample_invoice_context, build_sample_contract_context, build_sample_annual_statement_context
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


def _read_default_template(template_name: str) -> str:
    """Read the on-disk (default) content for a template."""
    path = settings.BASE_DIR / "templates" / template_name
    return path.read_text(encoding="utf-8")



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
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Invoices are mutated only through the dedicated workflow actions below
    (generate/approve/mark-sent/mark-paid/cancel etc.), each of which is
    permission-checked and audit-logged. Generic update/partial_update is
    intentionally not exposed — it would let any caller with read access to
    an invoice overwrite status, totals, or participant/zev directly, bypassing
    those workflow guards and leaving no audit trail.
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

    @action(detail=True, methods=["post"], url_path="approve",
            permission_classes=[IsAuthenticated, IsZevOwnerOrAdmin])
    def approve(self, request, pk=None):
        invoice = self.get_object()
        try:
            before = approve_invoice(invoice)
        except InvoiceWorkflowError as exc:
            _record_invoice_event(
                request=request,
                action_type="invoice.approve",
                summary=f"Denied approval for {_invoice_target_display(invoice)} due to status guard.",
                status=AuditEventStatus.DENIED,
                invoice=invoice,
            )
            return Response({"error": exc.user_message}, status=status.HTTP_400_BAD_REQUEST)
        _record_invoice_event(
            request=request,
            action_type="invoice.approve",
            summary=f"Approved invoice {_invoice_target_display(invoice)}.",
            invoice=invoice,
            changes=build_diff(before, {"status": invoice.status}, ["status"]),
        )
        return Response(InvoiceSerializer(invoice, context={"request": request}).data)

    @action(detail=True, methods=["post"], url_path="mark-sent",
            permission_classes=[IsAuthenticated, IsZevOwnerOrAdmin])
    def mark_sent(self, request, pk=None):
        """Transition an approved invoice to sent/locked state."""
        invoice = self.get_object()
        try:
            before = mark_invoice_sent(invoice)
        except InvoiceWorkflowError as exc:
            _record_invoice_event(
                request=request,
                action_type="invoice.mark_sent",
                summary=f"Denied mark-sent for {_invoice_target_display(invoice)} due to status guard.",
                status=AuditEventStatus.DENIED,
                invoice=invoice,
            )
            return Response({"error": exc.user_message}, status=status.HTTP_400_BAD_REQUEST)
        _record_invoice_event(
            request=request,
            action_type="invoice.mark_sent",
            summary=f"Marked invoice {_invoice_target_display(invoice)} as sent.",
            invoice=invoice,
            changes=build_diff(before, {"status": invoice.status}, ["status"]),
        )
        return Response(InvoiceSerializer(invoice, context={"request": request}).data)

    @action(detail=True, methods=["post"], url_path="mark-paid",
            permission_classes=[IsAuthenticated, IsZevOwnerOrAdmin])
    def mark_paid(self, request, pk=None):
        """Record that a sent invoice has been paid."""
        invoice = self.get_object()
        try:
            before = mark_invoice_paid(invoice)
        except InvoiceWorkflowError as exc:
            _record_invoice_event(
                request=request,
                action_type="invoice.mark_paid",
                summary=f"Denied mark-paid for {_invoice_target_display(invoice)} due to status guard.",
                status=AuditEventStatus.DENIED,
                invoice=invoice,
            )
            return Response({"error": exc.user_message}, status=status.HTTP_400_BAD_REQUEST)
        _record_invoice_event(
            request=request,
            action_type="invoice.mark_paid",
            summary=f"Marked invoice {_invoice_target_display(invoice)} as paid.",
            invoice=invoice,
            changes=build_diff(before, {"status": invoice.status}, ["status"]),
        )
        return Response(InvoiceSerializer(invoice, context={"request": request}).data)

    @action(detail=True, methods=["post"], url_path="cancel",
            permission_classes=[IsAuthenticated, IsZevOwnerOrAdmin])
    def cancel(self, request, pk=None):
        """Cancel an invoice that has not yet been paid."""
        invoice = self.get_object()
        try:
            before = cancel_invoice(invoice)
        except InvoiceWorkflowError as exc:
            _record_invoice_event(
                request=request,
                action_type="invoice.cancel",
                summary=f"Denied cancellation for {_invoice_target_display(invoice)}: {exc.user_message}",
                status=AuditEventStatus.DENIED,
                invoice=invoice,
            )
            return Response({"error": exc.user_message}, status=status.HTTP_400_BAD_REQUEST)
        _record_invoice_event(
            request=request,
            action_type="invoice.cancel",
            summary=f"Cancelled invoice {_invoice_target_display(invoice)}.",
            invoice=invoice,
            changes=build_diff(before, {"status": invoice.status}, ["status"]),
        )
        return Response(InvoiceSerializer(invoice, context={"request": request}).data)

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

    @action(detail=False, methods=["get"], url_path="annual-statement",
            permission_classes=[IsAuthenticated])
    def annual_statement(self, request):
        """Generate and return an annual statement PDF for a participant."""
        participant_id = request.query_params.get("participant_id")
        year_raw = request.query_params.get("year")
        zev_id = request.query_params.get("zev_id")

        if not year_raw:
            return Response({"error": "year is required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            year = int(year_raw)
        except ValueError:
            return Response({"error": "year must be a number."}, status=status.HTTP_400_BAD_REQUEST)

        # Participants can generate their own statement
        if request.user.role == 'participant' and not request.user.is_admin:
            participant = Participant.objects.filter(user=request.user).first()
            if not participant:
                return Response({"error": "Participant not found."}, status=status.HTTP_404_NOT_FOUND)
            zev = participant.zev
        else:
            # Owner/admin must provide participant_id and zev_id
            if not participant_id or not zev_id:
                return Response(
                    {"error": "participant_id and zev_id are required."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            try:
                zev = Zev.objects.get(pk=zev_id)
            except Zev.DoesNotExist:
                return Response({"error": "ZEV not found."}, status=status.HTTP_404_NOT_FOUND)

            if not request.user.is_admin and zev.owner != request.user:
                return Response({"error": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)

            try:
                participant = Participant.objects.get(pk=participant_id, zev=zev)
            except Participant.DoesNotExist:
                return Response({"error": "Participant not found."}, status=status.HTTP_404_NOT_FOUND)

        pdf_bytes = generate_annual_statement_pdf(participant, zev, year)
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        filename = f"annual-statement-{year}-{participant.last_name}.pdf"
        response["Content-Disposition"] = f'inline; filename="{filename}"'
        return response

    @action(detail=False, methods=["get"], url_path="annual-statements-zip",
            permission_classes=[IsAuthenticated, IsZevOwnerOrAdmin])
    def annual_statements_zip(self, request):
        """Generate annual statement PDFs for all participants and return as ZIP."""
        year_raw = request.query_params.get("year")
        zev_id = request.query_params.get("zev_id")

        if not year_raw or not zev_id:
            return Response(
                {"error": "year and zev_id are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            year = int(year_raw)
        except ValueError:
            return Response({"error": "year must be a number."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            zev = Zev.objects.get(pk=zev_id)
        except Zev.DoesNotExist:
            return Response({"error": "ZEV not found."}, status=status.HTTP_404_NOT_FOUND)

        if not request.user.is_admin and zev.owner != request.user:
            return Response({"error": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)

        participants = list(
            zev.participants.filter(valid_from__year__lte=year)
            .exclude(valid_to__year__lt=year)
            .order_by("last_name", "first_name")
        )

        if not participants:
            return Response(
                {"error": "No participants found for this ZEV and year."},
                status=status.HTTP_404_NOT_FOUND,
            )

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for participant in participants:
                try:
                    pdf_bytes = generate_annual_statement_pdf(participant, zev, year)
                    safe_name = f"{participant.last_name}_{participant.first_name}".replace(" ", "_")
                    filename = f"annual-statement-{year}-{safe_name}.pdf"
                    zf.writestr(filename, pdf_bytes)
                except Exception:
                    continue

        buf.seek(0)
        response = HttpResponse(buf.getvalue(), content_type="application/zip")
        response["Content-Disposition"] = f'attachment; filename="annual-statements-{year}.zip"'
        return response

    @action(detail=False, methods=["get"], url_path="financial-summary",
            permission_classes=[IsAuthenticated])
    def financial_summary(self, request):
        """Generate annual financial summary PDF for a producer participant."""
        year_raw = request.query_params.get("year")
        zev_id = request.query_params.get("zev_id")
        participant_id = request.query_params.get("participant_id")

        if not year_raw:
            return Response(
                {"error": "year is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            year = int(year_raw)
        except ValueError:
            return Response({"error": "year must be a number."}, status=status.HTTP_400_BAD_REQUEST)

        # Participants can generate their own summary
        if request.user.role == 'participant' and not request.user.is_admin:
            participant = Participant.objects.filter(user=request.user).first()
            if not participant:
                return Response({"error": "Participant not found."}, status=status.HTTP_404_NOT_FOUND)
            zev = participant.zev
        else:
            # Owner/admin must provide zev_id
            if not zev_id:
                return Response(
                    {"error": "zev_id is required."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            try:
                zev = Zev.objects.get(pk=zev_id)
            except Zev.DoesNotExist:
                return Response({"error": "ZEV not found."}, status=status.HTTP_404_NOT_FOUND)

            if not request.user.is_admin and zev.owner != request.user:
                return Response({"error": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)

            if participant_id:
                try:
                    participant = Participant.objects.get(pk=participant_id, zev=zev)
                except Participant.DoesNotExist:
                    return Response({"error": "Participant not found."}, status=status.HTTP_404_NOT_FOUND)
            else:
                # Default to the current user's participant record, then try ZEV owner
                participant = Participant.objects.filter(user=request.user, zev=zev).first()
                if not participant and zev.owner:
                    participant = Participant.objects.filter(user=zev.owner, zev=zev).first()
                if not participant:
                    return Response(
                        {"error": "participant_id is required (no default participant found)."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

        pdf_bytes = generate_financial_summary_pdf(zev, participant, year)
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        filename = f"financial-summary-{year}-{participant.last_name}.pdf"
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response

    @action(detail=False, methods=["get"], permission_classes=[IsAuthenticated])
    def dashboard(self, request):
        """Get dashboard statistics (admin only)."""
        if not request.user.is_admin:
            return Response({"error": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)

        # ZEV statistics
        total_zevs = Zev.objects.count()
        total_participants = Participant.objects.count()
        
        # Invoice statistics
        invoice_stats = Invoice.objects.filter(~Q(status=InvoiceStatus.CANCELLED)).aggregate(
            draft_count=Count('id', filter=Q(status=InvoiceStatus.DRAFT)),
            approved_count=Count('id', filter=Q(status=InvoiceStatus.APPROVED)),
            sent_count=Count('id', filter=Q(status=InvoiceStatus.SENT)),
            paid_count=Count('id', filter=Q(status=InvoiceStatus.PAID)),
            cancelled_count=Count('id', filter=Q(status=InvoiceStatus.CANCELLED)),
            total_revenue=Sum('total_chf', filter=Q(status__in=[InvoiceStatus.SENT, InvoiceStatus.PAID])),
        )
        
        # Ensure total_revenue is a Decimal, not None
        total_revenue = invoice_stats['total_revenue'] or 0
        
        # Recent invoices
        recent_invoices = Invoice.objects.select_related("participant", "zev").order_by("-created_at")[:10]
        recent_data = [
            {
                "invoice_number": inv.invoice_number,
                "participant_name": inv.participant.full_name,
                "zev_name": inv.zev.name,
                "total_chf": float(inv.total_chf),
                "status": inv.status,
                "created_at": inv.created_at.isoformat(),
            }
            for inv in recent_invoices
        ]
        
        # Email statistics
        email_stats = EmailLog.objects.aggregate(
            total_emails=Count('id'),
            sent_emails=Count('id', filter=Q(status=EmailLog.Status.SENT)),
            failed_emails=Count('id', filter=Q(status=EmailLog.Status.FAILED)),
            pending_emails=Count('id', filter=Q(status=EmailLog.Status.PENDING)),
        )
        
        return Response({
            "zevs": {
                "total": total_zevs,
            },
            "participants": {
                "total": total_participants,
            },
            "invoices": {
                "draft": invoice_stats['draft_count'] or 0,
                "approved": invoice_stats['approved_count'] or 0,
                "sent": invoice_stats['sent_count'] or 0,
                "paid": invoice_stats['paid_count'] or 0,
                "cancelled": invoice_stats['cancelled_count'] or 0,
                "total_revenue": float(total_revenue),
            },
            "emails": {
                "total": email_stats['total_emails'],
                "sent": email_stats['sent_emails'],
                "failed": email_stats['failed_emails'],
                "pending": email_stats['pending_emails'],
            },
            "recent_invoices": recent_data,
        })

    def _handle_pdf_template(self, request, template_name: str, audit_action_prefix: str):
        """Shared GET/PATCH/DELETE handler for all three PDF template endpoints."""
        if not request.user.is_admin:
            record_audit_event(
                request=request,
                action_category=AuditActionCategory.GOVERNANCE,
                action_type=f"{audit_action_prefix}.update",
                target_type="invoices.PdfTemplate",
                target_id=template_name,
                target_display=template_name,
                summary=f"Denied PDF template mutation by non-admin ({template_name}).",
                status=AuditEventStatus.DENIED,
            )
            return Response({"error": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)

        if request.method == "GET":
            record = PdfTemplate.objects.filter(template_name=template_name).first()
            content = record.content if record else _read_default_template(template_name)
            return Response({"template_name": template_name, "content": content, "is_customized": record is not None})

        if request.method == "PATCH":
            content = request.data.get("content")
            if not isinstance(content, str) or not content.strip():
                return Response({"error": "Template content is required."}, status=status.HTTP_400_BAD_REQUEST)
            PdfTemplate.objects.update_or_create(template_name=template_name, defaults={"content": content})
            record_audit_event(
                request=request,
                action_category=AuditActionCategory.GOVERNANCE,
                action_type=f"{audit_action_prefix}.update",
                target_type="invoices.PdfTemplate",
                target_id=template_name,
                target_display=template_name,
                summary=f"Updated PDF template {template_name}.",
            )
            return Response({"template_name": template_name, "content": content, "is_customized": True, "detail": "PDF template updated successfully."})

        # DELETE — revert to default
        PdfTemplate.objects.filter(template_name=template_name).delete()
        record_audit_event(
            request=request,
            action_category=AuditActionCategory.GOVERNANCE,
            action_type=f"{audit_action_prefix}.reset",
            target_type="invoices.PdfTemplate",
            target_id=template_name,
            target_display=template_name,
            summary=f"Reset PDF template {template_name} to default.",
        )
        return Response({"template_name": template_name, "content": _read_default_template(template_name), "is_customized": False, "detail": "PDF template reset to default."})

    @action(detail=False, methods=["get", "patch", "delete"], url_path="pdf-template", permission_classes=[IsAuthenticated])
    def pdf_template(self, request):
        """Admin-only read/write/reset for the invoice PDF HTML template."""
        return self._handle_pdf_template(request, TEMPLATE_NAME, "template.invoice_pdf")

    @action(detail=False, methods=["get", "patch", "delete"], url_path="contract-pdf-template", permission_classes=[IsAuthenticated])
    def contract_pdf_template(self, request):
        """Admin-only read/write/reset for the contract PDF HTML template."""
        return self._handle_pdf_template(request, CONTRACT_TEMPLATE_NAME, "template.contract_pdf")

    @action(detail=False, methods=["get", "patch", "delete"], url_path="annual-statement-pdf-template", permission_classes=[IsAuthenticated])
    def annual_statement_pdf_template(self, request):
        """Admin-only read/write/reset for the annual statement PDF HTML template."""
        return self._handle_pdf_template(request, ANNUAL_STATEMENT_TEMPLATE, "template.annual_statement_pdf")

    @action(detail=False, methods=["post"], url_path="preview-pdf-template", permission_classes=[IsAuthenticated])
    def preview_pdf_template(self, request):
        """Render a PDF template with sample data and return the HTML preview.

        POST body: { "content": "<html>...", "template_type": "invoice" | "contract" }
        Returns: { "html": "<rendered html>" }
        """
        if not request.user.is_admin:
            return Response({"error": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)

        content = request.data.get("content")
        template_type = request.data.get("template_type", "invoice")

        if not isinstance(content, str) or not content.strip():
            return Response({"error": "Template content is required."}, status=status.HTTP_400_BAD_REQUEST)

        if template_type == "contract":
            context = build_sample_contract_context()
        elif template_type == "annual_statement":
            context = build_sample_annual_statement_context()
        else:
            context = build_sample_invoice_context()

        try:
            rendered = Template(content).render(Context(context))
        except Exception as exc:
            return Response(
                {"error": f"Template rendering error: {exc}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response({"html": rendered})

    @action(detail=False, methods=["get"], url_path="email-templates", permission_classes=[IsAuthenticated])
    def email_templates(self, request):
        """Admin-only: list all email templates with current content (DB override or hardcoded default)."""
        if not request.user.is_admin:
            return Response({"error": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)

        overrides = {et.template_key: et for et in EmailTemplate.objects.all()}
        result = []
        for key, defaults in EMAIL_TEMPLATE_DEFAULTS.items():
            override = overrides.get(key)
            result.append({
                "template_key": key,
                "subject": override.subject if override else defaults["subject"],
                "body": override.body if override else defaults["body"],
                "is_customized": override is not None,
            })
        return Response(result)

    @action(detail=False, methods=["get", "patch", "delete"], url_path="email-template/(?P<template_key>[a-z_]+)", permission_classes=[IsAuthenticated])
    def email_template(self, request, template_key=None):
        """Admin-only read/write/reset access to a single email template.

        GET    — returns current subject+body (DB override if present, else hardcoded default).
        PATCH  — saves subject/body to the database.
        DELETE — removes the DB override, reverting to the hardcoded default.
        """
        if not request.user.is_admin:
            record_audit_event(
                request=request,
                action_category=AuditActionCategory.GOVERNANCE,
                action_type="template.email.update",
                target_type="invoices.EmailTemplate",
                target_id=str(template_key or ""),
                target_display=str(template_key or ""),
                summary="Denied email template mutation by non-admin.",
                status=AuditEventStatus.DENIED,
            )
            return Response({"error": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)

        defaults = EMAIL_TEMPLATE_DEFAULTS.get(template_key)
        if not defaults:
            return Response({"error": "Unknown template key."}, status=status.HTTP_404_NOT_FOUND)

        if request.method == "GET":
            record = EmailTemplate.objects.filter(template_key=template_key).first()
            return Response({
                "template_key": template_key,
                "subject": record.subject if record else defaults["subject"],
                "body": record.body if record else defaults["body"],
                "is_customized": record is not None,
            })

        if request.method == "PATCH":
            subject = request.data.get("subject")
            body = request.data.get("body")
            if not isinstance(subject, str) or not subject.strip():
                return Response({"error": "Subject is required."}, status=status.HTTP_400_BAD_REQUEST)
            if not isinstance(body, str) or not body.strip():
                return Response({"error": "Body is required."}, status=status.HTTP_400_BAD_REQUEST)
            EmailTemplate.objects.update_or_create(
                template_key=template_key,
                defaults={"subject": subject, "body": body},
            )
            record_audit_event(
                request=request,
                action_category=AuditActionCategory.GOVERNANCE,
                action_type="template.email.update",
                target_type="invoices.EmailTemplate",
                target_id=template_key,
                target_display=template_key,
                summary=f"Updated email template {template_key}.",
            )
            return Response({
                "template_key": template_key,
                "subject": subject,
                "body": body,
                "is_customized": True,
                "detail": "Email template updated successfully.",
            })

        # DELETE — revert to default
        EmailTemplate.objects.filter(template_key=template_key).delete()
        record_audit_event(
            request=request,
            action_category=AuditActionCategory.GOVERNANCE,
            action_type="template.email.reset",
            target_type="invoices.EmailTemplate",
            target_id=template_key,
            target_display=template_key,
            summary=f"Reset email template {template_key} to default.",
        )
        return Response({
            "template_key": template_key,
            "subject": defaults["subject"],
            "body": defaults["body"],
            "is_customized": False,
            "detail": "Email template reset to default.",
        })

