from rest_framework import serializers
from django.core.exceptions import ValidationError as DjangoValidationError
from .models import BillingMode, Tariff, TariffPeriod


class TariffPeriodSerializer(serializers.ModelSerializer):
    def validate(self, attrs):
        tariff = attrs.get("tariff") or getattr(self.instance, "tariff", None)
        if tariff and tariff.billing_mode != BillingMode.ENERGY:
            raise serializers.ValidationError("Tariff periods are only supported for energy-based tariffs.")
        return attrs

    class Meta:
        model = TariffPeriod
        fields = "__all__"
        read_only_fields = ["id"]


class TariffSerializer(serializers.ModelSerializer):
    periods = TariffPeriodSerializer(many=True, read_only=True)

    def _raise_validation_error_from_model(self, exc: DjangoValidationError):
        if hasattr(exc, "message_dict"):
            raise serializers.ValidationError(exc.message_dict)
        raise serializers.ValidationError(exc.messages)

    def validate(self, attrs):
        billing_mode = attrs.get("billing_mode") or getattr(self.instance, "billing_mode", BillingMode.ENERGY)
        energy_type = attrs.get("energy_type") if "energy_type" in attrs else getattr(self.instance, "energy_type", None)
        fixed_price_chf = attrs.get("fixed_price_chf") if "fixed_price_chf" in attrs else getattr(self.instance, "fixed_price_chf", None)
        percentage = attrs.get("percentage") if "percentage" in attrs else getattr(self.instance, "percentage", None)

        if billing_mode == BillingMode.ENERGY:
            if not energy_type:
                raise serializers.ValidationError({"energy_type": "Energy tariffs require an energy type."})
            attrs["fixed_price_chf"] = None
            attrs["percentage"] = None

        elif billing_mode == BillingMode.PERCENTAGE_OF_ENERGY:
            if not energy_type:
                raise serializers.ValidationError({"energy_type": "Percentage-of-energy tariffs require an energy type."})
            if percentage in (None, ""):
                raise serializers.ValidationError({"percentage": "Percentage-of-energy tariffs require a percentage value."})
            attrs["fixed_price_chf"] = None

        else:
            # Fixed-fee billing modes
            if fixed_price_chf in (None, ""):
                raise serializers.ValidationError({"fixed_price_chf": "Fixed-fee tariffs require a price."})
            attrs["energy_type"] = None
            attrs["percentage"] = None

        return attrs

    def create(self, validated_data):
        tariff = Tariff(**validated_data)
        try:
            tariff.full_clean()
        except DjangoValidationError as exc:
            self._raise_validation_error_from_model(exc)
        tariff.save()
        return tariff

    def update(self, instance, validated_data):
        for field_name, value in validated_data.items():
            setattr(instance, field_name, value)

        try:
            instance.full_clean()
        except DjangoValidationError as exc:
            self._raise_validation_error_from_model(exc)

        instance.save()
        return instance

    class Meta:
        model = Tariff
        fields = "__all__"
        read_only_fields = ["id", "created_at", "updated_at"]


# ── VSE/AES tariff import ────────────────────────────────────────────────────
#
# Read-only serializers describing what the importer *would* create. They are
# hand-written rather than derived from ``Tariff`` because a candidate is not a
# tariff yet: it carries a status, warnings and provenance that only exist
# while the user is deciding, and none of which belong on the model.


class VseTariffImportPreviewRequestSerializer(serializers.Serializer):
    zev = serializers.UUIDField()
    url = serializers.URLField(max_length=500, required=False, allow_blank=True)


class VseTariffImportSelectionSerializer(serializers.Serializer):
    """One ticked row: which candidate, and how the user chose to bill it."""

    key = serializers.CharField(max_length=300)
    #: Validated against the candidate's own ``billing_mode_options`` rather
    #: than against ``BillingMode`` at large, so the preview and the write path
    #: allow exactly the same set. Omitted means the proposed mode.
    billing_mode = serializers.CharField(max_length=40, required=False, allow_null=True)


class VseTariffImportApplyRequestSerializer(serializers.Serializer):
    zev = serializers.UUIDField()
    url = serializers.URLField(max_length=500, required=False, allow_blank=True)
    selections = VseTariffImportSelectionSerializer(many=True, allow_empty=False)
    #: The digest the preview returned. The document is fetched again on apply
    #: rather than trusting tariff data sent by the client, so this is what
    #: proves the user is confirming the document they actually looked at.
    document_digest = serializers.CharField(max_length=64)
    remember_url = serializers.BooleanField(required=False, default=True)


class VseTariffPeriodPreviewSerializer(serializers.Serializer):
    period_type = serializers.CharField()
    price_chf_per_kwh = serializers.DecimalField(max_digits=8, decimal_places=5)
    time_from = serializers.TimeField(allow_null=True)
    time_to = serializers.TimeField(allow_null=True)
    weekdays = serializers.CharField(allow_blank=True)
    months = serializers.CharField(allow_blank=True)


class VseTariffCandidateSerializer(serializers.Serializer):
    key = serializers.CharField()
    name = serializers.CharField()
    category = serializers.CharField()
    billing_mode = serializers.CharField()
    #: Alternatives the user may pick in the preview; empty when there is
    #: nothing to choose.
    billing_mode_options = serializers.ListField(child=serializers.CharField())
    energy_type = serializers.CharField(allow_null=True)
    fixed_price_chf = serializers.DecimalField(max_digits=10, decimal_places=2, allow_null=True)
    valid_from = serializers.DateField()
    valid_to = serializers.DateField(allow_null=True)
    notes = serializers.CharField(allow_blank=True)
    periods = VseTariffPeriodPreviewSerializer(many=True)

    source_tariff_name = serializers.CharField(allow_blank=True)
    source_tariff_type = serializers.CharField(allow_blank=True)
    source_customer_type = serializers.CharField(allow_blank=True)
    source_voltage_level = serializers.IntegerField(allow_null=True)
    standard_basegroup = serializers.BooleanField()

    #: ``new`` / ``new_version`` / ``duplicate`` / ``conflict`` / ``unsupported``
    status = serializers.CharField()
    detail = serializers.CharField(allow_blank=True)
    warnings = serializers.ListField(child=serializers.CharField())
    recommended = serializers.BooleanField()
    effective_valid_to = serializers.DateField(allow_null=True)


class VseTariffImportErrorSerializer(serializers.Serializer):
    tariff = serializers.CharField()
    error = serializers.CharField()


class VseTariffImportPreviewSerializer(serializers.Serializer):
    dso_name = serializers.CharField()
    dso_number = serializers.IntegerField(allow_null=True)
    source_url = serializers.CharField()
    document_digest = serializers.CharField()
    candidates = VseTariffCandidateSerializer(many=True)
    errors = VseTariffImportErrorSerializer(many=True)


class VseTariffImportCreatedSerializer(serializers.Serializer):
    name = serializers.CharField()
    category = serializers.CharField()
    billing_mode = serializers.CharField()
    valid_from = serializers.DateField()
    valid_to = serializers.DateField(allow_null=True)


class VseTariffImportSkippedSerializer(serializers.Serializer):
    name = serializers.CharField()
    reason = serializers.CharField()


class VseTariffImportAppliedErrorSerializer(serializers.Serializer):
    name = serializers.CharField()
    error = serializers.CharField()


class VseTariffImportResultSerializer(serializers.Serializer):
    created = VseTariffImportCreatedSerializer(many=True)
    skipped = VseTariffImportSkippedSerializer(many=True)
    errors = VseTariffImportAppliedErrorSerializer(many=True)
