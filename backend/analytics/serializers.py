from django.utils import timezone
from rest_framework import serializers

from accounts.api_keys import default_api_key_expiry
from zev.models import Participant, Zev

from .dataset import DIRECTIONS, GRANULARITIES, GROUP_BYS
from .models import AnalyticsToken
from .scope import can_create_token


class SeriesQuerySerializer(serializers.Serializer):
    """The query string of ``GET /analytics/series/``."""

    zev = serializers.UUIDField(required=False)
    to = serializers.DateField(required=True)
    granularity = serializers.ChoiceField(choices=GRANULARITIES, default="day")
    group_by = serializers.ChoiceField(choices=GROUP_BYS, default="metering_point")
    direction = serializers.ChoiceField(choices=DIRECTIONS, required=False)
    participant = serializers.UUIDField(required=False)
    metering_point = serializers.UUIDField(required=False)

    def get_fields(self):
        fields = super().get_fields()
        # ``from`` is a Python keyword, so it cannot be declared as an attribute.
        fields["from"] = serializers.DateField()
        return fields

    def validate(self, attrs):
        if attrs["group_by"] == "zev" and ("participant" in attrs or "metering_point" in attrs):
            raise serializers.ValidationError(
                "group_by=zev totals cannot be filtered by participant or metering_point."
            )
        return attrs


class AnalyticsTokenSerializer(serializers.ModelSerializer):
    zev_name = serializers.CharField(source="zev.name", read_only=True)
    participant_name = serializers.SerializerMethodField()
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model = AnalyticsToken
        fields = [
            "id", "name", "zev", "zev_name", "participant", "participant_name", "prefix",
            "created_by_name", "created_at", "expires_at", "last_used_at",
        ]
        read_only_fields = fields

    def get_participant_name(self, obj):
        return obj.participant.full_name if obj.participant_id else None

    def get_created_by_name(self, obj):
        return obj.created_by.get_full_name() or obj.created_by.email or obj.created_by.username


class AnalyticsTokenCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100)
    zev = serializers.PrimaryKeyRelatedField(queryset=Zev.objects.all())
    participant = serializers.PrimaryKeyRelatedField(queryset=Participant.objects.all(), required=False, allow_null=True)
    expires_at = serializers.DateTimeField(required=False, allow_null=True)

    def validate_expires_at(self, value):
        if value is not None and value <= timezone.now():
            raise serializers.ValidationError("The expiry must be in the future.")
        return value

    def validate(self, attrs):
        zev, participant = attrs["zev"], attrs.get("participant")
        user = self.context["request"].user
        if participant is not None and participant.zev_id != zev.pk:
            raise serializers.ValidationError({"participant": "The participant belongs to another ZEV."})
        if not can_create_token(user, zev, participant):
            # Same message whether the ZEV is unknown to the account or the scope is too wide.
            raise serializers.ValidationError(
                {"detail": "You may not create a token for that ZEV or participant."}
            )
        if zev.disabled_at is not None:
            raise serializers.ValidationError({"detail": "This ZEV is disabled."})
        if "expires_at" not in attrs:
            attrs["expires_at"] = default_api_key_expiry()
        return attrs
