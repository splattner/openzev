from copy import copy

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from zev.models import Zev

from .models import BackupDestination, BackupJob, BackupJobScope, BackupJobStatus, RestoreJob


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


class RestoreJobSerializer(serializers.ModelSerializer):
    """Read-only view of a restore and the plan it worked from."""

    source_archive_name = serializers.SerializerMethodField()
    source_created_at = serializers.SerializerMethodField()

    class Meta:
        model = RestoreJob
        fields = [
            "id", "target_zev_id", "target_zev_name", "source_backup_id", "source_archive_name",
            "source_created_at", "source_description", "dry_run", "force", "status", "plan_json",
            "safety_backup_id", "created_at", "started_at", "completed_at", "error_message",
        ]
        read_only_fields = fields

    def get_source_archive_name(self, obj) -> str:
        return obj.source_backup.archive_name if obj.source_backup_id else ""

    def get_source_created_at(self, obj) -> str | None:
        return (obj.source_backup.manifest_json or {}).get("created_at") if obj.source_backup_id else None


class RestoreJobCreateSerializer(serializers.Serializer):
    """``{source_backup_id, target_zev_id, dry_run, force, safety_destination_id}``.

    ``dry_run`` defaults to true: creating a job never destroys anything unless
    the caller says so in as many words. Whole-instance restore is not offered
    here (ADR 0023); naming it is an error, not a silent downgrade.
    """

    mode = serializers.CharField(required=False)
    source_backup_id = serializers.UUIDField()
    target_zev_id = serializers.UUIDField()
    dry_run = serializers.BooleanField(required=False, default=True)
    force = serializers.BooleanField(required=False, default=False)
    safety_destination_id = serializers.UUIDField(required=False, allow_null=True)

    def validate_mode(self, value):
        if value != "zev":
            raise serializers.ValidationError("Whole-instance restore is only available as a management command.")
        return value

    def validate(self, attrs):
        try:
            backup = BackupJob.objects.select_related("destination").get(pk=attrs["source_backup_id"])
        except BackupJob.DoesNotExist as exc:
            raise serializers.ValidationError({"source_backup_id": "Backup not found."}) from exc
        if backup.status != BackupJobStatus.COMPLETED:
            raise serializers.ValidationError({"source_backup_id": "This backup did not complete, so it cannot be restored."})

        target = str(attrs["target_zev_id"])
        held = {z["id"]: z["name"] for z in (backup.manifest_json or {}).get("zevs", [])}
        if target not in held:
            raise serializers.ValidationError({"target_zev_id": "This backup does not contain that community."})

        safety = None
        exists = Zev.objects.filter(pk=attrs["target_zev_id"]).exists()
        if attrs.get("safety_destination_id"):
            try:
                safety = BackupDestination.objects.get(pk=attrs["safety_destination_id"])
            except BackupDestination.DoesNotExist as exc:
                raise serializers.ValidationError({"safety_destination_id": "Destination not found."}) from exc
        elif backup.destination_id:
            safety = backup.destination
        if safety is not None and not safety.enabled:
            raise serializers.ValidationError({"safety_destination_id": "This destination is disabled."})
        if not attrs["dry_run"] and exists and safety is None:
            raise serializers.ValidationError(
                {"safety_destination_id": "Choose where to write the safety backup taken before the restore."}
            )

        attrs["backup"] = backup
        attrs["safety_destination"] = safety
        attrs["target_name"] = held[target]
        return attrs
