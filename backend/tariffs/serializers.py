from rest_framework import serializers
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

    def validate(self, attrs):
        billing_mode = attrs.get("billing_mode") or getattr(self.instance, "billing_mode", BillingMode.ENERGY)
        energy_type = attrs.get("energy_type") if "energy_type" in attrs else getattr(self.instance, "energy_type", None)
        fixed_price_chf = attrs.get("fixed_price_chf") if "fixed_price_chf" in attrs else getattr(self.instance, "fixed_price_chf", None)

        if billing_mode == BillingMode.ENERGY:
            if not energy_type:
                raise serializers.ValidationError({"energy_type": "Energy tariffs require an energy type."})
            attrs["fixed_price_chf"] = None
        else:
            if fixed_price_chf in (None, ""):
                raise serializers.ValidationError({"fixed_price_chf": "Fixed-fee tariffs require a price."})
            attrs["energy_type"] = None

        return attrs

    class Meta:
        model = Tariff
        fields = "__all__"
        read_only_fields = ["id", "created_at", "updated_at"]
