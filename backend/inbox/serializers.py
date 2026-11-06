from decimal import Decimal

from django.conf import settings
from rest_framework import serializers

from invoices.models import Credit

from .models import DeliveredDocument, DocumentKind


def _chf(value) -> str:
    return f"{Decimal(value):.2f}"


class DeliveredDocumentListSerializer(serializers.ListSerializer):
    """Looks the credit notes of a page up in one query instead of one per row."""

    def to_representation(self, data):
        rows = list(data)
        self.child.prime_credits(rows)
        return super().to_representation(rows)


class DeliveredDocumentSerializer(serializers.ModelSerializer):
    zev_name = serializers.CharField(source="zev.name", read_only=True)
    participant_name = serializers.SerializerMethodField()
    delivered_by_name = serializers.SerializerMethodField()
    invoice_status = serializers.CharField(source="invoice.status", read_only=True, default=None)
    invoice_figures = serializers.SerializerMethodField()
    credit_figures = serializers.SerializerMethodField()

    class Meta:
        model = DeliveredDocument
        fields = [
            "id", "zev", "zev_name", "participant", "participant_name", "kind", "title",
            "document_number", "period_start", "period_end", "file_name", "size_bytes", "sha256",
            "delivered_at", "delivered_by_name", "superseded_at", "superseded_by", "withdrawn_at",
            "batch_id", "invoice", "invoice_status", "invoice_figures", "credit_figures", "contract_issue",
        ]
        read_only_fields = fields
        list_serializer_class = DeliveredDocumentListSerializer

    def prime_credits(self, documents) -> None:
        wanted = {(d.zev_id, d.document_number) for d in documents if d.kind == DocumentKind.CREDIT_NOTE}
        credits = {}
        if wanted:
            found = Credit.objects.filter(
                zev_id__in={zev for zev, _ in wanted}, credit_number__in={number for _, number in wanted}
            ).select_related("source_invoice").prefetch_related("applications__invoice")
            credits = {(c.zev_id, c.credit_number): c for c in found if (c.zev_id, c.credit_number) in wanted}
        self._credits = credits

    def _credit_of(self, obj):
        if hasattr(self, "_credits"):
            return self._credits.get((obj.zev_id, obj.document_number))
        return (
            Credit.objects.filter(zev_id=obj.zev_id, credit_number=obj.document_number)
            .select_related("source_invoice").prefetch_related("applications__invoice").first()
        )

    def get_invoice_figures(self, obj):
        """What the participant needs to see of an invoice that is live and so not in the file:
        what it comes to and where it stands. Read from the invoice, never stored in the row."""
        invoice = obj.invoice
        if invoice is None:
            return None
        paid = sum((p.amount_chf for p in invoice.payments.all()), Decimal("0"))
        outstanding = Decimal("0") if invoice.status == "cancelled" else invoice.amount_due_chf - paid
        return {
            "status": invoice.status,
            "due_date": invoice.due_date.isoformat() if invoice.due_date else None,
            "total_chf": _chf(invoice.total_chf),
            "credit_applied_chf": _chf(invoice.credit_applied_chf),
            "amount_due_chf": _chf(invoice.amount_due_chf),
            "paid_chf": _chf(paid),
            "outstanding_chf": _chf(outstanding),
            "open_data_impact_count": getattr(obj, "open_data_impacts", 0) or 0,
        }

    def get_credit_figures(self, obj):
        if obj.kind != DocumentKind.CREDIT_NOTE:
            return None
        credit = self._credit_of(obj)
        if credit is None:
            return None
        return {
            "amount_chf": _chf(credit.amount_chf),
            "remaining_chf": _chf(credit.remaining()),
            "status": credit.status,
            "source_invoice_number": credit.source_invoice.invoice_number if credit.source_invoice_id else None,
            "applied_to": [
                {"invoice_number": a.invoice.invoice_number, "amount_chf": _chf(a.amount_chf)}
                for a in credit.applications.all() if a.released_at is None
            ],
        }

    def get_participant_name(self, obj):
        return obj.participant.display_name if obj.participant_id else None

    def get_delivered_by_name(self, obj):
        user = obj.delivered_by
        return (user.get_full_name() or user.username) if user else None


class DeliverContractSerializer(serializers.Serializer):
    """A stored contract version, or a participant whose latest issued version is meant."""

    contract_issue = serializers.UUIDField(required=False)
    participant = serializers.UUIDField(required=False)
    notify = serializers.BooleanField(default=False)

    def validate(self, attrs):
        if ("contract_issue" in attrs) == ("participant" in attrs):
            raise serializers.ValidationError("Give exactly one of contract_issue and participant.")
        return attrs


class DeliveryResultSerializer(serializers.Serializer):
    """The response of every write that delivers documents (spec §5.2)."""

    batch_id = serializers.UUIDField()
    delivered = serializers.IntegerField()
    without_account = serializers.IntegerField()
    # Emails queued, and recipients skipped for want of an address; both 0 unless ``notify`` was set.
    emailed = serializers.IntegerField()
    without_email = serializers.IntegerField()
    documents = DeliveredDocumentSerializer(many=True)


class UploadDocumentSerializer(serializers.Serializer):
    """An operator document for the whole ZEV or a chosen few (spec §5.2).

    The file is judged by its content, never by its name or the client's
    content type: it has to start with the PDF magic bytes.
    """

    zev = serializers.UUIDField()
    title = serializers.CharField(max_length=200)
    file = serializers.FileField(allow_empty_file=True)
    audience = serializers.ChoiceField(choices=["all", "selected"], default="all")
    participant_ids = serializers.ListField(child=serializers.UUIDField(), required=False, allow_empty=True)
    notify = serializers.BooleanField(default=False)

    def validate_title(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("This field may not be blank.")
        return value

    def validate_file(self, value):
        limit = settings.INBOX_MAX_UPLOAD_BYTES
        if value.size == 0:
            raise serializers.ValidationError("The file is empty.")
        if value.size > limit:
            raise serializers.ValidationError(f"The file is larger than {limit // (1024 * 1024)} MiB.")
        head = value.read(5)
        value.seek(0)
        if head != b"%PDF-":
            raise serializers.ValidationError("Only PDF files can be delivered.")
        return value

    def validate(self, attrs):
        if attrs["audience"] == "selected" and not attrs.get("participant_ids"):
            raise serializers.ValidationError({"participant_ids": ["Choose at least one participant."]})
        return attrs


class IssueSerializer(serializers.Serializer):
    """Shared by the three issue endpoints; ``year`` and ``participant_ids`` apply where meaningful."""

    zev = serializers.UUIDField()
    participant_ids = serializers.ListField(child=serializers.UUIDField(), required=False, allow_empty=False)
    notify = serializers.BooleanField(default=False)


class IssueYearSerializer(IssueSerializer):
    year = serializers.IntegerField(min_value=1900, max_value=9998)
