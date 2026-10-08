from __future__ import annotations

from django.db.models import Q
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import APIException, PermissionDenied

from zev import access
from zev.models import AllocationMode, MeteringPoint, MeteringPointAssignment, Participant
from allocation.validity import active_on

from ..models import (
    SOLAR_MANAGER_ID_RE,
    SupplementaryProvider,
    SupplementarySource,
    SupplementaryStatus,
)
from . import crypto, permissions
from .providers import PROVIDERS, ProviderAuthError, ProviderError


class IntegrationNotConfiguredError(APIException):
    status_code = 503
    default_detail = "INTEGRATION_ENCRYPTION_KEYS is not configured, so a Solar Manager key cannot be stored."
    default_code = "integration_not_configured"


def _holds_personally(participant: Participant, metering_point: MeteringPoint) -> bool:
    return active_on(
        MeteringPointAssignment.objects.filter(
            metering_point=metering_point, participant=participant, allocation_mode=AllocationMode.PERSONAL
        ),
        timezone.localdate(),
    ).exists()


class SupplementarySourceSerializer(serializers.ModelSerializer):
    """The connection, never its secrets (SPEC §4.1)."""

    metering_point_meter_id = serializers.CharField(source="metering_point.meter_id", read_only=True)
    participant_name = serializers.SerializerMethodField()
    has_credential = serializers.SerializerMethodField()
    api_key = serializers.CharField(write_only=True, required=False, allow_blank=False, trim_whitespace=True)
    consent = serializers.BooleanField(write_only=True, required=False)

    class Meta:
        model = SupplementarySource
        fields = [
            "id", "metering_point", "metering_point_meter_id", "participant", "participant_name",
            "provider", "label", "external_id", "enabled", "status", "consented_at", "last_sync_at",
            "last_success_at", "last_error", "synced_through", "covers_from", "reconciliation",
            "has_credential", "push_token_prefix", "created_at", "updated_at",
            "api_key", "consent",
        ]
        read_only_fields = [
            "id", "status", "consented_at", "last_sync_at", "last_success_at", "last_error",
            "synced_through", "covers_from", "reconciliation", "push_token_prefix", "created_at", "updated_at",
        ]
        extra_kwargs = {
            # Set from the request; only an admin acting on a participant's behalf names one.
            "participant": {"required": False},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and not user.is_admin and "metering_point" in self.fields:
            # Name only metering points the caller can already see, so a refusal
            # does not reveal that somebody else's exists.
            self.fields["metering_point"].queryset = MeteringPoint.objects.filter(
                Q(zev__in=access.viewable_zev_ids(user)) | Q(assignments__participant__user=user)
            ).distinct()

    def get_participant_name(self, obj) -> str:
        return f"{obj.participant.first_name} {obj.participant.last_name}".strip()

    def get_has_credential(self, obj) -> bool:
        return obj.has_credential

    # ---- field level ----

    def validate_metering_point(self, metering_point):
        if self.instance is not None and metering_point.pk != self.instance.metering_point_id:
            raise serializers.ValidationError("A source cannot be moved to another metering point.")
        return metering_point

    def validate_external_id(self, value):
        value = (value or "").strip()
        if value and not SOLAR_MANAGER_ID_RE.match(value):
            raise serializers.ValidationError("A Solar Manager id has 3 to 24 letters or digits.")
        return value

    # ---- object level ----

    def validate(self, attrs):
        request = self.context["request"]
        user = request.user
        if self.instance is None:
            return self._validate_create(attrs, user)
        return self._validate_update(attrs, user)

    def _validate_create(self, attrs, user):
        metering_point = attrs.get("metering_point")
        if metering_point is None:
            raise serializers.ValidationError({"metering_point": ["This field is required."]})
        provider = attrs.get("provider")
        if not provider:
            raise serializers.ValidationError({"provider": ["This field is required."]})

        if not attrs.get("consent"):
            raise serializers.ValidationError(
                {"consent": ["Consent is required to connect an energy data source."]}
            )

        # Who is the consenting holder?
        if user.is_admin:
            participant = attrs.get("participant")
            if participant is None:
                raise serializers.ValidationError({"participant": ["An admin names the participant to connect for."]})
            if participant.zev_id != metering_point.zev_id or not _holds_personally(participant, metering_point):
                raise serializers.ValidationError(
                    {"participant": ["This participant does not personally hold the metering point today."]}
                )
        else:
            participant = permissions.can_create_for(user, metering_point)
            if participant is None:
                raise PermissionDenied(
                    "Only the participant who personally holds this metering point can connect an energy data source."
                )
        attrs["participant"] = participant

        if not metering_point.has_behind_meter_generation:
            raise serializers.ValidationError(
                {"metering_point": ["Only metering points with generation behind the meter can have an energy data source."]}
            )
        if SupplementarySource.objects.filter(metering_point=metering_point).exists():
            raise serializers.ValidationError({"metering_point": ["This metering point already has an energy data source."]})

        if provider == SupplementaryProvider.SOLAR_MANAGER:
            errors = {}
            if not attrs.get("external_id"):
                errors["external_id"] = ["A Solar Manager id is required."]
            if not attrs.get("api_key"):
                errors["api_key"] = ["A Solar Manager API key is required."]
            if provider not in PROVIDERS:
                errors["provider"] = ["This provider is not available yet."]
            if errors:
                raise serializers.ValidationError(errors)
        else:
            if attrs.get("external_id"):
                raise serializers.ValidationError({"external_id": ["Only Solar Manager sources have an external id."]})
            if attrs.get("api_key"):
                raise serializers.ValidationError({"api_key": ["Only Solar Manager sources take an API key."]})
        return attrs

    def _validate_update(self, attrs, user):
        role = permissions.role_for(user, self.instance)
        attrs.pop("consent", None)
        if "participant" in attrs and attrs["participant"] != self.instance.participant:
            raise serializers.ValidationError({"participant": ["A source cannot be handed to another participant."]})
        attrs.pop("participant", None)
        attrs.pop("metering_point", None)
        if "provider" in attrs and attrs["provider"] != self.instance.provider:
            raise serializers.ValidationError({"provider": ["The provider cannot be changed."]})
        attrs.pop("provider", None)

        if role == "manager":
            extra = set(attrs) - {"enabled"}
            if extra:
                raise PermissionDenied("A ZEV manager can only switch an energy data source on or off.")
            return attrs

        instance = self.instance
        if instance.provider != SupplementaryProvider.SOLAR_MANAGER:
            if attrs.get("external_id"):
                raise serializers.ValidationError({"external_id": ["Only Solar Manager sources have an external id."]})
            if attrs.get("api_key"):
                raise serializers.ValidationError({"api_key": ["Only Solar Manager sources take an API key."]})
        elif "external_id" in attrs and attrs["external_id"] != instance.external_id and not attrs.get("api_key"):
            # A different installation needs its own key: re-entering it proves it belongs to this one.
            raise serializers.ValidationError({"api_key": ["Enter the API key again when the Solar Manager id changes."]})
        if "external_id" in attrs and not attrs["external_id"] and instance.provider == SupplementaryProvider.SOLAR_MANAGER:
            raise serializers.ValidationError({"external_id": ["A Solar Manager id is required."]})
        return attrs

    # ---- writes ----

    def _verified_credential(self, provider: str, external_id: str, api_key: str) -> str:
        """Check ``api_key`` with the vendor and return the credential to store.

        Nothing is saved before this succeeds, so a wrong key never leaves a broken row behind.
        """
        if not crypto.encryption_configured():
            raise IntegrationNotConfiguredError()
        try:
            return PROVIDERS[provider].verify(external_id, api_key)
        except ProviderAuthError as exc:
            raise serializers.ValidationError({"api_key": [str(exc) or "The vendor rejected this API key."]}) from exc
        except ProviderError as exc:
            raise serializers.ValidationError({"api_key": [str(exc) or "The vendor could not be reached."]}) from exc

    def create(self, validated_data):
        api_key = validated_data.pop("api_key", "")
        validated_data.pop("consent", None)
        request = self.context["request"]
        validated_data["created_by"] = request.user
        source = SupplementarySource(**validated_data)
        source.full_clean(exclude=["credential_encrypted", "push_token_prefix", "push_token_hash"])
        if source.provider == SupplementaryProvider.SOLAR_MANAGER:
            credential = self._verified_credential(source.provider, source.external_id, api_key)
            source.set_credential(credential)
        else:
            self.push_token = source.issue_push_token()
        source.save()
        return source

    def update(self, instance, validated_data):
        api_key = validated_data.pop("api_key", None)
        for name, value in validated_data.items():
            setattr(instance, name, value)
        self.credential_changed = False
        if api_key:
            credential = self._verified_credential(instance.provider, instance.external_id, api_key)
            instance.set_credential(credential)
            self.credential_changed = True
            # A fresh key is a fresh start: the next sync decides the status.
            instance.status = SupplementaryStatus.PENDING
            instance.last_error = ""
        instance.full_clean(exclude=["credential_encrypted", "push_token_prefix", "push_token_hash"])
        instance.save()
        return instance


class PurgeSerializer(serializers.Serializer):
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)

    def validate(self, attrs):
        start, end = attrs.get("date_from"), attrs.get("date_to")
        if start and end and end < start:
            raise serializers.ValidationError({"date_to": ["date_to must be on or after date_from."]})
        return attrs


class CsvUploadSerializer(serializers.Serializer):
    file = serializers.FileField()


class IngestSerializer(serializers.Serializer):
    # Rows are validated one by one (a bad row is rejected, not the batch), so any JSON is accepted here.
    readings = serializers.ListField(child=serializers.JSONField(), allow_empty=False)


class IngestResultSerializer(serializers.Serializer):
    """Response shape of the push endpoint and the CSV import (documentation only)."""

    accepted = serializers.IntegerField()
    updated = serializers.IntegerField()
    rejected = serializers.ListField(child=serializers.DictField())
    dropped_outside_assignment = serializers.IntegerField()
