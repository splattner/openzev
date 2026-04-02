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


class InvoiceSerializer(serializers.ModelSerializer):
    items = InvoiceItemSerializer(many=True, read_only=True)
    email_logs = EmailLogSerializer(many=True, read_only=True)
    participant_name = serializers.CharField(source="participant.full_name", read_only=True)
    zev_name = serializers.CharField(source="zev.name", read_only=True)
    pdf_url = serializers.SerializerMethodField()

    class Meta:
        model = Invoice
        fields = "__all__"
        read_only_fields = ["id", "invoice_number", "created_at", "updated_at", "pdf_file"]

    def get_pdf_url(self, obj):
        if obj.pdf_file:
            request = self.context.get("request")
            if request:
                return request.build_absolute_uri(obj.pdf_file.url)
        return None


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
