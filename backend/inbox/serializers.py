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
