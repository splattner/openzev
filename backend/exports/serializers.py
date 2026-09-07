from rest_framework import serializers

from .models import ExportJob


class ExportJobSerializer(serializers.ModelSerializer):
    """Read-only view of an export job for its requester.

    ``expired`` is computed rather than stored: an artifact past its retention
    window is not downloadable even before the sweep deletes the file.
    """

    class Meta:
        model = ExportJob
        fields = [
            "id",
            "export_type",
            "zev_id",
            "params",
            "status",
            "created_at",
            "started_at",
            "completed_at",
            "file_expires_at",
            "generated_count",
            "omitted_count",
            "omitted_participant_ids",
            "error_message",
            "expired",
        ]
        read_only_fields = fields

    expired = serializers.BooleanField(read_only=True)
