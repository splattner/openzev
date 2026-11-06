from django.conf import settings
from rest_framework import serializers

from .models import DeliveredDocument


class DeliveredDocumentSerializer(serializers.ModelSerializer):
    zev_name = serializers.CharField(source="zev.name", read_only=True)
    participant_name = serializers.SerializerMethodField()
    delivered_by_name = serializers.SerializerMethodField()
    invoice_status = serializers.CharField(source="invoice.status", read_only=True, default=None)

    class Meta:
        model = DeliveredDocument
        fields = [
            "id", "zev", "zev_name", "participant", "participant_name", "kind", "title",
            "document_number", "period_start", "period_end", "file_name", "size_bytes", "sha256",
            "delivered_at", "delivered_by_name", "superseded_at", "superseded_by", "withdrawn_at",
            "batch_id", "invoice", "invoice_status", "contract_issue",
        ]
        read_only_fields = fields

    def get_participant_name(self, obj):
        return obj.participant.display_name if obj.participant_id else None

    def get_delivered_by_name(self, obj):
        user = obj.delivered_by
        return (user.get_full_name() or user.username) if user else None


class DeliverContractSerializer(serializers.Serializer):
    contract_issue = serializers.UUIDField()


class DeliveryResultSerializer(serializers.Serializer):
    """The response of every write that delivers documents (spec §5.2)."""

    batch_id = serializers.UUIDField()
    delivered = serializers.IntegerField()
    without_account = serializers.IntegerField()
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


class IssueYearSerializer(IssueSerializer):
    year = serializers.IntegerField(min_value=1900, max_value=9998)
