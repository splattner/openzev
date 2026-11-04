from rest_framework import serializers

from .models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    zev_name = serializers.CharField(source="zev.name", read_only=True)

    class Meta:
        model = Notification
        fields = [
            "id", "type", "audience", "zev", "zev_name", "payload",
            "target_type", "target_id", "created_at", "read_at",
        ]
        read_only_fields = fields
