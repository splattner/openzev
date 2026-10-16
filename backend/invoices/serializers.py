from decimal import Decimal

from rest_framework import serializers
from zev import access
from .models import Credit, CreditApplication, CreditKind, Invoice, InvoiceItem, EmailLog, Payment
from .description_utils import strip_period_suffix


class InvoiceItemSerializer(serializers.ModelSerializer):
    def to_representation(self, instance):
        data = super().to_representation(instance)
        invoice = getattr(instance, "invoice", None)
        if invoice and data.get("description"):
            data["description"] = strip_period_suffix(
                data["description"],
                invoice.period_start,
                invoice.period_end,
            )
        return data

    class Meta:
        model = InvoiceItem
        fields = "__all__"
        read_only_fields = ["id"]


class EmailLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmailLog
        fields = "__all__"
        read_only_fields = ["id", "created_at"]


class PaymentSerializer(serializers.ModelSerializer):
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model = Payment
        fields = ["id", "invoice", "amount_chf", "paid_on", "note", "source", "created_by_name", "created_at"]
        read_only_fields = fields

    def get_created_by_name(self, obj) -> str | None:
        user = obj.created_by
        if user is None:
            return None
        return user.get_full_name() or user.email


class RecordPaymentSerializer(serializers.Serializer):
    amount_chf = serializers.DecimalField(max_digits=10, decimal_places=2)
    paid_on = serializers.DateField(required=False)
    note = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")


class MarkPaidSerializer(serializers.Serializer):
    paid_on = serializers.DateField(required=False)


class CorrectInvoiceSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=CreditKind.choices)
    reason = serializers.CharField(max_length=2000)
    amount_chf = serializers.DecimalField(max_digits=10, decimal_places=2, required=False)


class RefundCreditSerializer(serializers.Serializer):
    refunded_on = serializers.DateField()
    note = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")


class CreditApplicationSerializer(serializers.ModelSerializer):
    """Where a credit went: the invoice it was set against. ``released_at`` is
    set once that invoice was cancelled and the credit freed again."""

    invoice_number = serializers.CharField(source="invoice.invoice_number", read_only=True)

    class Meta:
        model = CreditApplication
        fields = ["id", "invoice", "invoice_number", "amount_chf", "released_at"]
        read_only_fields = fields


class InvoiceCreditApplicationSerializer(serializers.ModelSerializer):
    """The credit a given invoice used, seen from the invoice."""

    credit_number = serializers.CharField(source="credit.credit_number", read_only=True)

    class Meta:
        model = CreditApplication
        fields = ["id", "credit", "credit_number", "amount_chf", "released_at"]
        read_only_fields = fields


class CreditSerializer(serializers.ModelSerializer):
    """A credit note, read-only. ``remaining_chf`` and ``status`` are derived
    from the applications (prefetched, ``applications__invoice``) and the
    refund: ``open`` while money remains, then ``used`` or ``refunded``."""

    participant_name = serializers.SerializerMethodField()
    source_invoice_number = serializers.SerializerMethodField()
    remaining_chf = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    pdf_url = serializers.SerializerMethodField()
    created_by_name = serializers.SerializerMethodField()
    applications = CreditApplicationSerializer(many=True, read_only=True)

    class Meta:
        model = Credit
        fields = [
            "id", "credit_number", "zev", "participant", "participant_name", "kind",
            "source_invoice", "source_invoice_number", "reason", "amount_chf", "vat_mode",
            "vat_rate", "vat_chf", "embedded_vat_chf", "remaining_chf", "refunded_chf",
            "refunded_on", "refund_note", "status", "applications", "pdf_url",
            "pdf_status", "created_by_name", "created_at",
        ]
        read_only_fields = fields

    def get_participant_name(self, obj) -> str:
        return (obj.recipient or {}).get("name") or obj.participant.full_name

    def get_source_invoice_number(self, obj) -> str | None:
        return obj.source_invoice.invoice_number if obj.source_invoice_id else None

    def get_remaining_chf(self, obj) -> str:
        return f"{obj.remaining():.2f}"

    def get_status(self, obj) -> str:
        return obj.status

    def get_pdf_url(self, obj) -> str | None:
        request = self.context.get("request")
        if obj.pdf_file and request:
            return request.build_absolute_uri(f"/api/v1/invoices/credits/{obj.pk}/pdf/")
        return None

    def get_created_by_name(self, obj) -> str | None:
        user = obj.created_by
        if user is None:
            return None
        return user.get_full_name() or user.email


class InvoiceListSerializer(serializers.ModelSerializer):
    """Every invoice field except the nested ``items`` and ``email_logs``.

    List responses are unbounded in a way detail responses are not: the admin
    invoice view walks every invoice in the instance, so each nested line item
    and email-log row is paid for once per invoice across the whole dataset.
    Measured on 50 invoices x 8 items, dropping them takes one page from
    151.4 KiB to 33.2 KiB (4.6x) and from 4 queries to 2. No list consumer
    reads them (see :class:`InvoiceSerializer` for the detail shape that does).
    """

    participant_name = serializers.CharField(source="participant.full_name", read_only=True)
    zev_name = serializers.CharField(source="zev.name", read_only=True)
    pdf_url = serializers.SerializerMethodField()
    last_email_status = serializers.SerializerMethodField()
    last_email_log_id = serializers.SerializerMethodField()
    paid_chf = serializers.SerializerMethodField()
    outstanding_chf = serializers.SerializerMethodField()
    amount_due_chf = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)

    class Meta:
        model = Invoice
        fields = "__all__"
        read_only_fields = [
            "id",
            "invoice_number",
            "created_at",
            "updated_at",
            "pdf_file",
            # Written only by the render pipeline (save_invoice_pdf and the
            # tasks around it), never by client input.
            "pdf_status",
            # Managed by workflow actions / billing engine, never by client input:
            "status",
            "total_local_kwh",
            "total_grid_kwh",
            "total_feed_in_kwh",
            "total_local_sold_kwh",
            "local_sale_chf",
            "local_sale_feed_in_chf",
            "subtotal_chf",
            "vat_rate",
            "vat_base_chf",
            "vat_chf",
            "embedded_vat_chf",
            "total_chf",
            "credit_applied_chf",
            "period_start",
            "period_end",
            "zev",
            "participant",
            "sent_at",
            "approved_at",
            "due_date",
        ]

    def _paid(self, obj) -> Decimal:
        # The list annotates the sum; detail reads prefetch the payments.
        if "paid_sum" in obj.__dict__:
            return obj.paid_sum or Decimal("0")
        payments = getattr(obj, "_prefetched_objects_cache", {}).get("payments")
        if payments is None:
            payments = obj.payments.all()
        return sum((p.amount_chf for p in payments), Decimal("0"))

    def get_paid_chf(self, obj) -> str:
        return f"{self._paid(obj):.2f}"

    def get_outstanding_chf(self, obj) -> str:
        if obj.status == "cancelled":
            return "0.00"
        return f"{obj.amount_due_chf - self._paid(obj):.2f}"

    def get_pdf_url(self, obj) -> str | None:
        if obj.pdf_file:
            request = self.context.get("request")
            if request:
                return request.build_absolute_uri(
                    f"/api/v1/invoices/invoices/{obj.pk}/pdf/"
                )
        return None

    def get_last_email_status(self, obj) -> str | None:
        """Newest email attempt status; falls back to a per-object lookup.

        ``None`` is a real value (no email logs), so presence of the list
        subquery annotation is checked by attribute, never by value — an
        annotated null must not send every log-less invoice back to the DB.
        """
        if "last_email_status" in obj.__dict__:
            return obj.last_email_status
        log = self._latest_email_log(obj)
        return log.status if log else None

    def get_last_email_log_id(self, obj) -> str | None:
        """Id of the newest email log — the retry endpoint is log-scoped, so
        the Billing email-delivery tab (phase 3) can offer an inline retry
        off the list payload without fetching the nested logs."""
        if "last_email_log_id" in obj.__dict__:
            annotated = obj.last_email_log_id
            return str(annotated) if annotated else None
        log = self._latest_email_log(obj)
        return str(log.id) if log else None

    @staticmethod
    def _latest_email_log(obj):
        # Detail and period-overview already load all logs. Reuse that data,
        # including an empty prefetch, instead of querying again per invoice.
        logs = getattr(obj, "_prefetched_objects_cache", {}).get("email_logs")
        if logs is not None:
            return max(logs, key=lambda log: (log.created_at, log.id), default=None)
        return (
            EmailLog.objects.filter(invoice_id=obj.pk)
            .order_by("-created_at", "-id")
            .only("id", "status")
            .first()
        )


class InvoiceSerializer(InvoiceListSerializer):
    """The full invoice: list fields plus the nested items and email logs.

    Used for detail reads, the workflow actions that echo an invoice back, and
    the period overview — all of which are bounded to a single invoice or a
    single ZEV-and-period.
    """

    items = InvoiceItemSerializer(many=True, read_only=True)
    email_logs = EmailLogSerializer(many=True, read_only=True)
    access_link = serializers.SerializerMethodField()
    payments = serializers.SerializerMethodField()
    credits = serializers.SerializerMethodField()
    credit_applications = serializers.SerializerMethodField()

    def get_credit_applications(self, obj) -> list[dict]:
        """The credit notes set against this invoice. The participant sees them
        too: they are on their own invoice."""
        applications = getattr(obj, "_prefetched_objects_cache", {}).get("credit_applications")
        if applications is None:
            applications = obj.credit_applications.select_related("credit")
        return InvoiceCreditApplicationSerializer(applications, many=True).data

    def get_credits(self, obj) -> list[dict]:
        """The credit notes issued for this invoice. Unlike the payments, the
        participant sees these: a credit note exists from the moment it is
        issued."""
        credits = getattr(obj, "_prefetched_objects_cache", {}).get("credits")
        if credits is None:
            credits = obj.credits.select_related("source_invoice", "participant__party", "created_by").prefetch_related(
                "applications__invoice"
            )
        return CreditSerializer(credits, many=True, context=self.context).data

    def get_payments(self, obj) -> list[dict] | None:
        """The payment history, for the ZEV's managers and viewers only; a
        participant sees ``paid_chf``/``outstanding_chf`` but not the rows."""
        request = self.context.get("request")
        if request is None or not access.can_view(request.user, obj.zev_id):
            return None
        return PaymentSerializer(obj.payments.all(), many=True).data

    def get_access_link(self, obj) -> dict | None:
        """State of the access link printed on this invoice, or ``None``.

        **Never the secret.** The prefix identifies the row but cannot open
        anything on its own — resolving compares the secret as well — so it is
        safe to show, and it is what ties this to the ``invoice_link.*`` audit
        events. Whoever needs the working link reads it off the printed QR.

        ``last_used_at`` is stamped at most hourly (``access_tokens.note_use``),
        so it answers "has this been opened at all?" rather than "how often".
        """
        token = obj.access_tokens.filter(revoked_at__isnull=True).first()
        if token is None:
            return None
        return {
            "prefix": token.prefix,
            "created_at": token.created_at,
            "last_used_at": token.last_used_at,
        }


class GenerateInvoiceSerializer(serializers.Serializer):
    participant_id = serializers.UUIDField()
    period_start = serializers.DateField()
    period_end = serializers.DateField()

    def validate(self, attrs):
        if attrs["period_start"] >= attrs["period_end"]:
            raise serializers.ValidationError("period_start must be before period_end.")
        return attrs


class GenerateZevInvoicesSerializer(serializers.Serializer):
    zev_id = serializers.UUIDField()
    period_start = serializers.DateField()
    period_end = serializers.DateField()
