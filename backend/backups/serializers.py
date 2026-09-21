from copy import copy

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from zev.models import Zev

from .models import BackupDestination, BackupJob, BackupJobScope


class BackupDestinationSerializer(serializers.ModelSerializer):
    """Admin CRUD for a destination.

    ``secret_access_key`` is write-only and never returned; ``has_secret_access_key``
    reports whether one is stored, mirroring ``OAuthProviderSerializer``. On update
    an *absent* secret leaves the stored one intact and an empty string clears it,
    so an edit form that leaves the field blank cannot wipe a credential by accident.
    """

    secret_access_key = serializers.CharField(
        write_only=True, required=False, allow_blank=True, trim_whitespace=False,
    )
    has_secret_access_key = serializers.SerializerMethodField()
    credential_mode = serializers.CharField(read_only=True)

    class Meta:
        model = BackupDestination
        fields = [
            "id", "name", "kind", "enabled", "path", "bucket", "prefix", "region", "endpoint_url",
            "access_key_id", "secret_access_key", "has_secret_access_key", "server_side_encryption",
            "credential_mode", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "credential_mode", "created_at", "updated_at"]

    def get_has_secret_access_key(self, obj) -> bool:
        return obj.has_stored_secret

    def validate(self, attrs):
        attrs = super().validate(attrs)
        secret = attrs.pop("secret_access_key", None)  # ``None``: not supplied

        if self.instance is not None:
            candidate = copy(self.instance)
            for key, value in attrs.items():
                setattr(candidate, key, value)
        else:
            candidate = BackupDestination(**attrs)

        try:
            if secret is not None:
                candidate.set_secret_access_key(secret)
                attrs["secret_access_key_encrypted"] = candidate.secret_access_key_encrypted
            candidate.full_clean()
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict) from exc
        return attrs


class BackupJobSerializer(serializers.ModelSerializer):
    """Read-only view of a backup job and its artifact."""

    destination_name = serializers.SerializerMethodField()
    zev_name = serializers.SerializerMethodField()

    class Meta:
        model = BackupJob
        fields = [
            "id", "scope", "zev_id", "zev_name", "trigger", "destination_id", "destination_name", "status",
            "created_at", "started_at", "completed_at", "archive_name", "archive_location",
            "archive_bytes", "archive_sha256", "encrypted", "encryption_key_fingerprint",
            "manifest_json", "error_message",
        ]
        read_only_fields = fields

    def get_destination_name(self, obj) -> str:
        return obj.destination.name if obj.destination_id else ""

    def get_zev_name(self, obj) -> str:
        return obj.zev.name if obj.zev_id else ""


class BackupJobCreateSerializer(serializers.Serializer):
    scope = serializers.ChoiceField(choices=BackupJobScope.choices)
    zev_id = serializers.UUIDField(required=False, allow_null=True)
    destination_id = serializers.UUIDField()

    def validate(self, attrs):
        try:
            destination = BackupDestination.objects.get(pk=attrs["destination_id"])
        except BackupDestination.DoesNotExist as exc:
            raise serializers.ValidationError({"destination_id": "Destination not found."}) from exc
        if not destination.enabled:
            raise serializers.ValidationError({"destination_id": "This destination is disabled."})

        zev = None
        if attrs["scope"] == BackupJobScope.ZEV:
            if not attrs.get("zev_id"):
                raise serializers.ValidationError({"zev_id": "A ZEV backup needs a ZEV."})
            try:
                zev = Zev.objects.get(pk=attrs["zev_id"])
            except Zev.DoesNotExist as exc:
                raise serializers.ValidationError({"zev_id": "ZEV not found."}) from exc
        elif attrs.get("zev_id"):
            raise serializers.ValidationError({"zev_id": "A whole-instance backup does not take a ZEV."})

        attrs["destination"] = destination
        attrs["zev"] = zev
        return attrs
