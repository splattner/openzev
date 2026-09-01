from rest_framework import serializers
from .models import Invoice, InvoiceItem, EmailLog
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

    class Meta:
        model = Invoice
        fields = "__all__"
        read_only_fields = [
            "id",
            "invoice_number",
            "created_at",
            "updated_at",
            "pdf_file",
            # Managed by workflow actions / billing engine, never by client input:
            "status",
            "total_local_kwh",
            "total_grid_kwh",
            "total_feed_in_kwh",
            "subtotal_chf",
            "vat_rate",
            "vat_chf",
            "total_chf",
            "period_start",
            "period_end",
            "zev",
            "participant",
            "sent_at",
            "due_date",
        ]

    def get_pdf_url(self, obj) -> str | None:
        if obj.pdf_file:
            request = self.context.get("request")
            if request:
                return request.build_absolute_uri(
                    f"/api/v1/invoices/invoices/{obj.pk}/pdf/"
                )
        return None


class InvoiceSerializer(InvoiceListSerializer):
    """The full invoice: list fields plus the nested items and email logs.

    Used for detail reads, the workflow actions that echo an invoice back, and
    the period overview — all of which are bounded to a single invoice or a
    single ZEV-and-period.
    """

    items = InvoiceItemSerializer(many=True, read_only=True)
    email_logs = EmailLogSerializer(many=True, read_only=True)


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
