"""Admin-only, cross-tenant statistics for the dashboard landing page.

Like the template endpoints in ``views_templates``, this used to be an
``@action`` on ``InvoiceViewSet`` despite not being invoice-domain code: it
aggregates over Zev, Participant, Invoice and EmailLog, and it deliberately
queries ``Invoice.objects`` unscoped rather than the viewset's tenant-scoped
``get_queryset()``. Sitting on the viewset made that unscoped access look like
an oversight; on its own admin-only view it reads as the intent it is.
"""

from django.db.models import Count, Q, Sum
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsAdmin
from zev.models import Participant, Zev

from .models import EmailLog, Invoice, InvoiceStatus

RECENT_INVOICE_LIMIT = 10


class InvoiceDashboardView(APIView):
    """Aggregate counts across every tenant, for the admin dashboard.

    Admin-only, and enforced declaratively — this view reports across all
    tenants, so the permission class is the only thing standing between a ZEV
    owner and every other owner's revenue figures.
    """

    permission_classes = [IsAdmin]

    def get(self, request, *args, **kwargs):
        # Aggregate over every invoice: each count carries its own status
        # filter, so pre-filtering the queryset only ever suppressed the
        # cancelled count (the other statuses are disjoint from CANCELLED).
        invoice_stats = Invoice.objects.aggregate(
            draft_count=Count("id", filter=Q(status=InvoiceStatus.DRAFT)),
            approved_count=Count("id", filter=Q(status=InvoiceStatus.APPROVED)),
            sent_count=Count("id", filter=Q(status=InvoiceStatus.SENT)),
            paid_count=Count("id", filter=Q(status=InvoiceStatus.PAID)),
            cancelled_count=Count("id", filter=Q(status=InvoiceStatus.CANCELLED)),
            total_revenue=Sum("total_chf", filter=Q(status__in=[InvoiceStatus.SENT, InvoiceStatus.PAID])),
        )

        email_stats = EmailLog.objects.aggregate(
            total_emails=Count("id"),
            sent_emails=Count("id", filter=Q(status=EmailLog.Status.SENT)),
            failed_emails=Count("id", filter=Q(status=EmailLog.Status.FAILED)),
            pending_emails=Count("id", filter=Q(status=EmailLog.Status.PENDING)),
        )

        recent_invoices = (
            Invoice.objects.select_related("participant", "zev")
            .order_by("-created_at")[:RECENT_INVOICE_LIMIT]
        )

        return Response({
            "zevs": {
                "total": Zev.objects.count(),
            },
            "participants": {
                "total": Participant.objects.count(),
            },
            "invoices": {
                "draft": invoice_stats["draft_count"] or 0,
                "approved": invoice_stats["approved_count"] or 0,
                "sent": invoice_stats["sent_count"] or 0,
                "paid": invoice_stats["paid_count"] or 0,
                "cancelled": invoice_stats["cancelled_count"] or 0,
                "total_revenue": float(invoice_stats["total_revenue"] or 0),
            },
            "emails": {
                "total": email_stats["total_emails"],
                "sent": email_stats["sent_emails"],
                "failed": email_stats["failed_emails"],
                "pending": email_stats["pending_emails"],
            },
            "recent_invoices": [
                {
                    "invoice_number": inv.invoice_number,
                    "participant_name": inv.participant.full_name,
                    "zev_name": inv.zev.name,
                    "total_chf": float(inv.total_chf),
                    "status": inv.status,
                    "created_at": inv.created_at.isoformat(),
                }
                for inv in recent_invoices
            ],
        })
