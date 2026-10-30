from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.db.models import Q
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import APIException, PermissionDenied

from zev import access
from zev.models import AllocationMode, MeteringPoint, MeteringPointAssignment, Participant, Zev
from allocation.validity import active_on

from ..models import (
    SOLAR_MANAGER_ID_RE,
    SourceHolder,
    SourceTarget,
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


def live_state_of(source: SupplementarySource, now=None) -> str | None:
    """``fresh``, ``stale`` or ``never`` for a source with live data, else ``None``.

    Judged on ``live_last_seen_at`` (written at coarse resolution), so it is a status hint, not the
    freshness of a value: that is decided on the sample itself.
    """
    if not source.provides_live:
        return None
    if source.live_last_seen_at is None:
        return "never"
    age = (now or timezone.now()) - source.live_last_seen_at
    return "fresh" if age <= timedelta(seconds=settings.LIVE_MAX_AGE_S) else "stale"


CAPABILITY_FIELDS = ("provides_history", "provides_live", "provides_forecast")


class SupplementarySourceSerializer(serializers.ModelSerializer):
    """The connection, never its secrets (SPEC §4.1)."""

    metering_point_meter_id = serializers.SerializerMethodField()
    participant_name = serializers.SerializerMethodField()
    has_credential = serializers.SerializerMethodField()
    live_state = serializers.SerializerMethodField()
    api_key = serializers.CharField(write_only=True, required=False, allow_blank=False, trim_whitespace=True)
    consent = serializers.BooleanField(write_only=True, required=False)
    provides_history = serializers.BooleanField(required=False)
    provides_live = serializers.BooleanField(required=False)
    provides_forecast = serializers.BooleanField(required=False)

    class Meta:
        model = SupplementarySource
        fields = [
            "id", "zev", "target", "held_by", "metering_point", "metering_point_meter_id", "participant",
            "participant_name", "provides_history", "provides_live", "provides_forecast",
            "provider", "label", "external_id", "enabled", "status", "consented_at", "last_sync_at",
            "last_success_at", "last_error", "synced_through", "covers_from", "reconciliation",
            "live_last_seen_at", "live_state",
            "has_credential", "push_token_prefix", "push_token_created_at", "push_token_last_used_at",
            "created_at", "updated_at", "api_key", "consent",
        ]
        read_only_fields = [
            "id", "status", "consented_at", "last_sync_at", "last_success_at", "last_error",
            "synced_through", "covers_from", "reconciliation", "push_token_prefix", "push_token_created_at",
            "push_token_last_used_at", "live_last_seen_at", "created_at", "updated_at",
        ]
        extra_kwargs = {
            # Set from the request; only an admin acting on a participant's behalf names one.
            "participant": {"required": False},
            # Derived from the metering point; only the grid connection point names its ZEV.
            "zev": {"required": False},
            "target": {"required": False},
            "held_by": {"required": False},
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
            self.fields["zev"].queryset = Zev.objects.filter(pk__in=access.viewable_zev_ids(user))

    def get_metering_point_meter_id(self, obj) -> str | None:
        return obj.metering_point.meter_id if obj.metering_point_id else None

    def get_participant_name(self, obj) -> str | None:
        if obj.participant_id is None:
            return None
        return f"{obj.participant.first_name} {obj.participant.last_name}".strip()

    def get_live_state(self, obj) -> str | None:
        return live_state_of(obj)

    def get_has_credential(self, obj) -> bool:
        return obj.has_credential

    # ---- field level ----

    def validate_metering_point(self, metering_point):
        if self.instance is not None and (metering_point is None or metering_point.pk != self.instance.metering_point_id):
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

    def _check_rollout(self, *, provider, live, forecast, history, adds_live, target=None, held_by=None):
        """Restrictions of the first live-data release; each lifts with the PR named in SPEC-live §10."""
        if forecast:
            raise serializers.ValidationError({"provides_forecast": ["Production forecasts are not available yet."]})
        if adds_live and not permissions.live_feature_enabled():
            raise serializers.ValidationError({"provides_live": ["Live energy data is not enabled."]})
        if target == SourceTarget.CONNECTION_POINT and not permissions.live_feature_enabled():
            raise serializers.ValidationError({"target": ["Live energy data is not enabled."]})
        if held_by == SourceHolder.ZEV and not permissions.live_feature_enabled():
            raise serializers.ValidationError({"held_by": ["Live energy data is not enabled."]})
        if live and provider != SupplementaryProvider.PUSH:
            raise serializers.ValidationError(
                {"provides_live": ["Live data is only available for push sources at the moment."]}
            )
        if provider == SupplementaryProvider.SOLAR_MANAGER and not history:
            raise serializers.ValidationError(
                {"provides_history": ["A Solar Manager source provides history."]}
            )

    def _check_conflicts(self, metering_point, *, history, live, forecast, exclude_pk=None):
        """A capability exists once per metering point (also guaranteed by partial unique constraints)."""
        existing = SupplementarySource.objects.filter(metering_point=metering_point)
        if exclude_pk is not None:
            existing = existing.exclude(pk=exclude_pk)
        errors = {}
        if history and existing.filter(provides_history=True).exists():
            errors["provides_history"] = ["This metering point already has an energy data source."]
        if live and existing.filter(provides_live=True).exists():
            errors["provides_live"] = ["This metering point already has a live data source."]
        if forecast and existing.filter(provides_forecast=True).exists():
            errors["provides_forecast"] = ["This metering point already has a forecast source."]
        if errors:
            raise serializers.ValidationError(errors)

    def _validate_create(self, attrs, user):
        target = attrs.get("target", SourceTarget.METERING_POINT)
        is_cp = target == SourceTarget.CONNECTION_POINT
        held_by = attrs.get("held_by", SourceHolder.ZEV if is_cp else SourceHolder.PARTICIPANT)
        provider = attrs.get("provider")
        if not provider:
            raise serializers.ValidationError({"provider": ["This field is required."]})
        history = attrs.get("provides_history", not is_cp and held_by == SourceHolder.PARTICIPANT)
        live = attrs.get("provides_live", is_cp)
        forecast = attrs.get("provides_forecast", False)
        attrs.update(target=target, held_by=held_by, provides_history=history, provides_live=live,
                     provides_forecast=forecast)

        self._check_rollout(
            provider=provider, live=live, forecast=forecast, history=history, adds_live=live,
            target=target, held_by=held_by,
        )
        if not (history or live or forecast):
            raise serializers.ValidationError({"provides_history": ["Choose what the source provides."]})
        if not attrs.get("consent"):
            raise serializers.ValidationError(
                {"consent": ["Consent is required to connect an energy data source."]}
            )

        if is_cp:
            self._validate_connection_point(attrs, user, held_by, history, live, forecast)
        else:
            self._validate_metering_point_target(attrs, user, held_by, history)

        self._validate_provider_fields(attrs, provider)
        return attrs

    def _validate_connection_point(self, attrs, user, held_by, history, live, forecast):
        if attrs.get("metering_point") is not None:
            raise serializers.ValidationError({"metering_point": ["The grid connection point has no metering point."]})
        if held_by != SourceHolder.ZEV or history or not live or forecast:
            raise serializers.ValidationError(
                {"target": ["The grid connection point is held by the ZEV and provides live data only."]}
            )
        zev = attrs.get("zev")
        if zev is None:
            raise serializers.ValidationError({"zev": ["This field is required."]})
        if not user.is_admin and not access.can_manage(user, zev):
            raise PermissionDenied("Only a manager of the ZEV can connect its grid connection point.")
        if zev.zev_type != "zev":
            raise serializers.ValidationError({"target": ["Only a physical ZEV has a grid connection point."]})
        if SupplementarySource.objects.filter(zev=zev, target=SourceTarget.CONNECTION_POINT).exists():
            raise serializers.ValidationError({"target": ["This ZEV already has a grid connection point source."]})
        attrs["participant"] = None

    def _validate_metering_point_target(self, attrs, user, held_by, history):
        metering_point = attrs.get("metering_point")
        if metering_point is None:
            raise serializers.ValidationError({"metering_point": ["This field is required."]})
        if attrs.get("zev") is not None and attrs["zev"].pk != metering_point.zev_id:
            raise serializers.ValidationError({"zev": ["This is not the ZEV of the metering point."]})
        attrs["zev"] = metering_point.zev

        # Who is the consenting holder (or operator)?
        if held_by == SourceHolder.ZEV:
            if attrs.get("participant") is not None:
                raise serializers.ValidationError({"participant": ["A ZEV-held source has no participant."]})
            if not user.is_admin and not access.can_manage(user, metering_point.zev):
                raise PermissionDenied("Only a manager of the ZEV can connect a metering point on its behalf.")
            if permissions.personally_held_today(metering_point):
                message = "A participant holds this metering point personally; they connect it themselves."
                if user.is_admin:
                    raise serializers.ValidationError({"metering_point": [message]})
                raise PermissionDenied(message)
            attrs["participant"] = None
        elif user.is_admin:
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

        if history:
            if held_by != SourceHolder.PARTICIPANT:
                raise serializers.ValidationError({"provides_history": ["History is only available for participant-held sources."]})
            if not metering_point.has_behind_meter_generation:
                raise serializers.ValidationError(
                    {"metering_point": ["Only metering points with generation behind the meter can have an energy data source."]}
                )
        if attrs["provides_live"] and not metering_point.is_active:
            raise serializers.ValidationError({"metering_point": ["The metering point is not active."]})
        self._check_conflicts(
            metering_point, history=history, live=attrs["provides_live"], forecast=attrs["provides_forecast"]
        )

    def _validate_provider_fields(self, attrs, provider):
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

    def _validate_update(self, attrs, user):
        role = permissions.role_for(user, self.instance)
        instance = self.instance
        consent = attrs.pop("consent", None)
        if "participant" in attrs and attrs["participant"] != instance.participant:
            raise serializers.ValidationError({"participant": ["A source cannot be handed to another participant."]})
        attrs.pop("participant", None)
        attrs.pop("metering_point", None)
        for name in ("target", "held_by", "zev"):
            value = attrs.pop(name, None)
            current = getattr(instance, name)
            if value is not None and value != current:
                raise serializers.ValidationError({name: ["This cannot be changed after the source is created."]})
        if "provider" in attrs and attrs["provider"] != instance.provider:
            raise serializers.ValidationError({"provider": ["The provider cannot be changed."]})
        attrs.pop("provider", None)

        if role == "manager":
            extra = set(attrs) - {"enabled"}
            if extra:
                raise PermissionDenied("A ZEV manager can only switch an energy data source on or off.")
            return attrs

        if any(name in attrs for name in CAPABILITY_FIELDS):
            history = attrs.get("provides_history", instance.provides_history)
            live = attrs.get("provides_live", instance.provides_live)
            forecast = attrs.get("provides_forecast", instance.provides_forecast)
            adds_live = live and not instance.provides_live
            self._check_rollout(
                provider=instance.provider, live=live, forecast=forecast, history=history, adds_live=adds_live,
            )
            if not (history or live or forecast):
                raise serializers.ValidationError({"provides_history": ["A source must provide at least one kind of data."]})
            if instance.target == SourceTarget.CONNECTION_POINT and (history or forecast or not live):
                raise serializers.ValidationError(
                    {"provides_live": ["The grid connection point provides live data only."]}
                )
            if adds_live and not consent:
                raise serializers.ValidationError(
                    {"consent": ["Consent is required to connect an energy data source."]}
                )
            if history and not instance.provides_history:
                if instance.held_by != SourceHolder.PARTICIPANT:
                    raise serializers.ValidationError({"provides_history": ["History is only available for participant-held sources."]})
                if not instance.metering_point.has_behind_meter_generation:
                    raise serializers.ValidationError({"provides_history": [
                        "Only metering points with generation behind the meter can have an energy data source."]})
            if instance.metering_point_id:
                self._check_conflicts(
                    instance.metering_point,
                    history=history and not instance.provides_history,
                    live=live and not instance.provides_live,
                    forecast=forecast and not instance.provides_forecast,
                    exclude_pk=instance.pk,
                )

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
