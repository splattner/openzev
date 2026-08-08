from rest_framework import serializers

from .models import AuditEvent, AuditActionCategory, AuditEventStatus


class AuditEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditEvent
        fields = [
            "id",
            "created_at",
            "actor_user",
            "actor_role_snapshot",
            "actor_display",
            "zev",
            "action_category",
            "action_type",
            "target_type",
            "target_id",
            "target_display",
            "status",
            "request_id",
            "correlation_id",
            "source",
            "ip_address",
            "user_agent",
            "summary",
            "reason",
            "changes_json",
            "metadata_json",
        ]
        read_only_fields = fields


class AuditFilterZevOptionSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()


class AuditFilterActorOptionSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    username = serializers.CharField()


class AuditFilterOptionsSerializer(serializers.Serializer):
    zevs = AuditFilterZevOptionSerializer(many=True)
    actors = AuditFilterActorOptionSerializer(many=True)


class AuditEventFilterSerializer(serializers.Serializer):
    actor_user = serializers.IntegerField(required=False)
    zev = serializers.UUIDField(required=False)
    action_category = serializers.ChoiceField(
        choices=[choice[0] for choice in AuditActionCategory.choices],
        required=False,
    )
    action_type = serializers.CharField(required=False)
    target_type = serializers.CharField(required=False)
    target_id = serializers.CharField(required=False)
    status = serializers.ChoiceField(
        choices=[choice[0] for choice in AuditEventStatus.choices],
        required=False,
    )
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)
    q = serializers.CharField(required=False)

    def validate(self, attrs):
        date_from = attrs.get("date_from")
        date_to = attrs.get("date_to")
        if date_from and date_to and date_from > date_to:
            raise serializers.ValidationError({"date_to": "date_to must be on or after date_from."})
        return attrs
