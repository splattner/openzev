from datetime import date as date_type, datetime, timedelta, timezone as dt_timezone

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from accounts.permissions import IsZevOwnerOrAdmin
from django.db.models import Count, Q, Sum, F, DecimalField
from django.conf import settings
from pathlib import Path
from zev.models import Zev, Participant, MeteringPoint, MeteringPointAssignment
from metering.models import MeterReading
from .models import Invoice, InvoiceStatus, EmailLog
from .serializers import (
    InvoiceSerializer, GenerateInvoiceSerializer, GenerateZevInvoicesSerializer
)
from .engine import generate_invoice, generate_invoices_for_zev
from .pdf import TEMPLATE_NAME, save_invoice_pdf
from .tasks import send_invoice_email_task


def _get_invoice_template_path() -> Path:
    return settings.BASE_DIR / "templates" / TEMPLATE_NAME


class InvoiceViewSet(viewsets.ModelViewSet):
    serializer_class = InvoiceSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        qs = Invoice.objects.select_related("participant", "zev").prefetch_related("items", "email_logs")
        if user.is_admin:
            return qs
        if user.is_zev_owner:
            return qs.filter(zev__owner=user)
        # Participants see only their own invoices
        return qs.filter(participant__user=user)

    def destroy(self, request, *args, **kwargs):
        invoice = self.get_object()
        if not request.user.is_zev_owner:
            return Response({"error": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)
        if not request.user.is_admin and invoice.zev.owner != request.user:
            return Response({"error": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)
        if not request.user.is_admin and invoice.status not in [InvoiceStatus.DRAFT, InvoiceStatus.CANCELLED]:
            return Response({"error": "Only draft or cancelled invoices can be deleted."}, status=status.HTTP_400_BAD_REQUEST)
        return super().destroy(request, *args, **kwargs)

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
            return Response({"error": str(exc)}, status=status.HTTP_409_CONFLICT)
        return Response(InvoiceSerializer(invoice, context={"request": request}).data,
                        status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["post"], url_path="generate-all",
            permission_classes=[IsAuthenticated, IsZevOwnerOrAdmin])
    def generate_all(self, request):
        """Generate invoices for all participants of a ZEV."""
        s = GenerateZevInvoicesSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            zev = Zev.objects.get(pk=s.validated_data["zev_id"])
        except Zev.DoesNotExist:
            return Response({"error": "ZEV not found."}, status=status.HTTP_404_NOT_FOUND)

        if not request.user.is_admin and zev.owner != request.user:
            return Response({"error": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)

        try:
            invoices = generate_invoices_for_zev(
                zev, s.validated_data["period_start"], s.validated_data["period_end"]
            )
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_409_CONFLICT)
        return Response(
            InvoiceSerializer(invoices, many=True, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
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

        participants = list(
            Participant.objects.filter(
                zev=zev,
                valid_from__lte=period_end,
            ).filter(
                Q(valid_to__isnull=True) | Q(valid_to__gte=period_start)
            ).order_by("last_name", "first_name")
        )

        period_start_dt = datetime.combine(period_start, datetime.min.time(), tzinfo=dt_timezone.utc)
        period_end_exclusive_dt = datetime.combine(period_end, datetime.min.time(), tzinfo=dt_timezone.utc) + timedelta(days=1)

        invoice_map = {
            invoice.participant_id: invoice
            for invoice in Invoice.objects.filter(
                zev=zev,
                period_start=period_start,
                period_end=period_end,
            ).select_related("participant", "zev").order_by("-created_at")
        }

        rows = []
        for participant in participants:
            # Find all metering point assignments for this participant that overlap the period.
            # Each assignment's valid_from/valid_to defines the exact days where readings are required.
            assignments = list(
                MeteringPointAssignment.objects.filter(
                    participant=participant,
                    valid_from__lte=period_end,
                ).filter(
                    Q(valid_to__isnull=True) | Q(valid_to__gte=period_start)
                ).select_related("metering_point")
            )

            # Skip participants with no active assignment in this period.
            if not assignments:
                continue

            # Fetch all readings for the involved metering points within the period, grouped by MP.
            assignment_mp_ids = [a.metering_point_id for a in assignments]
            readings_by_metering_point = {}
            for metering_point_id, timestamp in MeterReading.objects.filter(
                metering_point_id__in=assignment_mp_ids,
                timestamp__gte=period_start_dt,
                timestamp__lt=period_end_exclusive_dt,
            ).values_list("metering_point_id", "timestamp"):
                readings_by_metering_point.setdefault(metering_point_id, set()).add(timestamp.date())

            missing_meter_ids = []
            missing_meter_details = []
            for assignment in assignments:
                mp = assignment.metering_point
                # Effective required window: intersection of billing period and assignment validity.
                effective_start = max(period_start, assignment.valid_from)
                effective_end = min(
                    period_end,
                    assignment.valid_to if assignment.valid_to is not None else period_end,
                )

                if effective_start > effective_end:
                    continue

                reading_days = readings_by_metering_point.get(mp.id, set())
                cursor = effective_start
                missing_days = 0
                while cursor <= effective_end:
                    if cursor not in reading_days:
                        missing_days += 1
                    cursor = cursor + timedelta(days=1)

                if missing_days > 0:
                    missing_meter_ids.append(mp.meter_id)
                    missing_meter_details.append(
                        {
                            "meter_id": mp.meter_id,
                            "missing_days": missing_days,
                        }
                    )

            total_metering_points = len(assignments)
            metering_points_with_data = total_metering_points - len(missing_meter_ids)
            metering_data_complete = total_metering_points > 0 and metering_points_with_data == total_metering_points

            invoice = invoice_map.get(participant.id)
            rows.append(
                {
                    "participant_id": str(participant.id),
                    "participant_name": participant.full_name,
                    "participant_email": participant.email,
                    "invoice": InvoiceSerializer(invoice, context={"request": request}).data if invoice else None,
                    "metering_data_complete": metering_data_complete,
                    "metering_points_total": total_metering_points,
                    "metering_points_with_data": metering_points_with_data,
                    "missing_meter_ids": missing_meter_ids,
                    "missing_meter_details": missing_meter_details,
                }
            )

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
        return Response({"pdf_url": request.build_absolute_uri(invoice.pdf_file.url)})

    @action(detail=True, methods=["post"], url_path="send-email",
            permission_classes=[IsAuthenticated, IsZevOwnerOrAdmin])
    def send_email(self, request, pk=None):
        """Queue an invoice PDF email to the participant."""
        invoice = self.get_object()
        recipient = request.data.get("email") or invoice.participant.email
        if not recipient:
            return Response({"error": "No email address available."}, status=status.HTTP_400_BAD_REQUEST)
        send_invoice_email_task.delay(str(invoice.pk), recipient)
        return Response({"detail": f"Email queued for {recipient}."})

    @action(detail=True, methods=["post"], url_path="approve",
            permission_classes=[IsAuthenticated, IsZevOwnerOrAdmin])
    def approve(self, request, pk=None):
        invoice = self.get_object()
        if invoice.status != InvoiceStatus.DRAFT:
            return Response({"error": "Only draft invoices can be approved."}, status=status.HTTP_400_BAD_REQUEST)
        invoice.status = InvoiceStatus.APPROVED
        invoice.save(update_fields=["status", "updated_at"])
        return Response(InvoiceSerializer(invoice, context={"request": request}).data)

    @action(detail=True, methods=["post"], url_path="mark-sent",
            permission_classes=[IsAuthenticated, IsZevOwnerOrAdmin])
    def mark_sent(self, request, pk=None):
        """Transition an approved invoice to sent/locked state."""
        invoice = self.get_object()
        if invoice.status != InvoiceStatus.APPROVED:
            return Response({"error": "Only approved invoices can be marked as sent."}, status=status.HTTP_400_BAD_REQUEST)
        invoice.status = InvoiceStatus.SENT
        from django.utils import timezone as tz
        invoice.sent_at = tz.now()
        invoice.save(update_fields=["status", "sent_at", "updated_at"])
        return Response(InvoiceSerializer(invoice, context={"request": request}).data)

    @action(detail=True, methods=["post"], url_path="mark-paid",
            permission_classes=[IsAuthenticated, IsZevOwnerOrAdmin])
    def mark_paid(self, request, pk=None):
        """Record that a sent invoice has been paid."""
        invoice = self.get_object()
        if invoice.status != InvoiceStatus.SENT:
            return Response({"error": "Only sent invoices can be marked as paid."}, status=status.HTTP_400_BAD_REQUEST)
        invoice.status = InvoiceStatus.PAID
        invoice.save(update_fields=["status", "updated_at"])
        return Response(InvoiceSerializer(invoice, context={"request": request}).data)

    @action(detail=True, methods=["post"], url_path="cancel",
            permission_classes=[IsAuthenticated, IsZevOwnerOrAdmin])
    def cancel(self, request, pk=None):
        """Cancel an invoice that has not yet been paid."""
        invoice = self.get_object()
        if invoice.status == InvoiceStatus.PAID:
            return Response({"error": "Paid invoices cannot be cancelled."}, status=status.HTTP_400_BAD_REQUEST)
        if invoice.status == InvoiceStatus.CANCELLED:
            return Response({"error": "Invoice is already cancelled."}, status=status.HTTP_400_BAD_REQUEST)
        invoice.status = InvoiceStatus.CANCELLED
        invoice.save(update_fields=["status", "updated_at"])
        return Response(InvoiceSerializer(invoice, context={"request": request}).data)

    @action(detail=True, methods=["post"], url_path="retry-email/<str:email_log_id>/",
            permission_classes=[IsAuthenticated, IsZevOwnerOrAdmin])
    def retry_email(self, request, pk=None, email_log_id=None):
        """Retry sending a failed invoice email."""
        invoice = self.get_object()
        try:
            email_log = EmailLog.objects.get(pk=email_log_id, invoice=invoice)
        except EmailLog.DoesNotExist:
            return Response({"error": "Email log not found."}, status=status.HTTP_404_NOT_FOUND)

        if email_log.status == "sent":
            return Response({"error": "Email already sent."}, status=status.HTTP_400_BAD_REQUEST)

        # Queue retry
        send_invoice_email_task.delay(str(invoice.pk), email_log.recipient)
        return Response({"detail": f"Email retry queued for {email_log.recipient}."})

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
            sent_emails=Count('id', filter=Q(status='sent')),
            failed_emails=Count('id', filter=Q(status='failed')),
            pending_emails=Count('id', filter=Q(status='pending')),
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

    @action(detail=False, methods=["get", "patch"], url_path="pdf-template", permission_classes=[IsAuthenticated])
    def pdf_template(self, request):
        """Admin-only read/write access to the invoice PDF HTML template."""
        if not request.user.is_admin:
            return Response({"error": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)

        template_path = _get_invoice_template_path()

        if request.method == "GET":
            return Response(
                {
                    "template_name": TEMPLATE_NAME,
                    "content": template_path.read_text(encoding="utf-8"),
                }
            )

        content = request.data.get("content")
        if not isinstance(content, str) or not content.strip():
            return Response({"error": "Template content is required."}, status=status.HTTP_400_BAD_REQUEST)

        template_path.write_text(content, encoding="utf-8")
        return Response(
            {
                "template_name": TEMPLATE_NAME,
                "content": content,
                "detail": "PDF template updated successfully.",
            }
        )

