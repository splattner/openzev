from rest_framework import serializers
from .models import MeterReading, ImportLog


class MeterReadingSerializer(serializers.ModelSerializer):
    class Meta:
        model = MeterReading
        fields = "__all__"
        read_only_fields = ["id", "created_at", "import_batch"]


class ImportLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = ImportLog
        fields = "__all__"
        read_only_fields = ["id", "created_at", "batch_id"]
