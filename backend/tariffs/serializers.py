from rest_framework import serializers
from django.core.exceptions import ValidationError as DjangoValidationError
from .models import BillingMode, Tariff, TariffPeriod

ENERGY_BILLING_MODES = {BillingMode.ENERGY, BillingMode.PERCENTAGE_OF_ENERGY}


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
