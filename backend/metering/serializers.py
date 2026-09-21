from rest_framework import serializers
from .models import MeterReading, ImportLog


class MeterReadingSerializer(serializers.ModelSerializer):
    class Meta:
        model = MeterReading
        fields = "__all__"
        read_only_fields = ["id", "created_at", "import_batch"]


class ImportLogSerializer(serializers.ModelSerializer):
    zev_name = serializers.CharField(source="zev.name", read_only=True, allow_null=True)
    imported_by_display = serializers.SerializerMethodField()

    class Meta:
        model = ImportLog
        fields = "__all__"
        read_only_fields = ["id", "created_at", "batch_id"]

    def get_imported_by_display(self, obj):
        user = obj.imported_by
        if user is None:
            return None
        return user.get_full_name() or user.username or user.email or None
