"""Request shape of the live push endpoint (SPEC-2026-live-energy-data §5.1)."""

from __future__ import annotations

from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.conf import settings
from django.utils import timezone
from rest_framework import serializers

FUTURE_TOLERANCE = timedelta(seconds=10)
TENTH = Decimal("0.1")


class AwareDateTimeField(serializers.DateTimeField):
    """A timestamp must say its zone: a device guessing at local time would shift every sample."""

    def enforce_timezone(self, value):
        if timezone.is_naive(value):
            raise serializers.ValidationError("Timestamp must include a time zone, for example 2026-10-30T11:02:10Z.")
        return value


class PowerField(serializers.Field):
    """A finite number of watts within the plausibility cap, rounded half up to one decimal."""

    default_error_messages = {
        "invalid": "A valid number is required.",
        "range": "Power must be within ±{cap} W.",
    }

    def __init__(self, *, minimum: int | None = None, **kwargs):
        self.minimum = minimum
        super().__init__(**kwargs)

    def to_internal_value(self, data):
        if isinstance(data, bool) or not isinstance(data, (int, float, str)):
            self.fail("invalid")
        try:
            value = Decimal(str(data).strip())
        except InvalidOperation:
            self.fail("invalid")
        if not value.is_finite():
            self.fail("invalid")
        cap = settings.LIVE_MAX_ABS_POWER_W
        if abs(value) > cap:
            self.fail("range", cap=cap)
        if self.minimum is not None and value < self.minimum:
            raise serializers.ValidationError(f"Must be at least {self.minimum}.")
        return value.quantize(TENTH, rounding=ROUND_HALF_UP)

    def to_representation(self, value):
        return float(value)


class LiveIngestSerializer(serializers.Serializer):
    timestamp = AwareDateTimeField(required=False)
    meter_power_w = PowerField(help_text="Signed power at the meter: positive drawn in, negative fed out.")
    production_w = PowerField(required=False, minimum=0, help_text="Optional gross production, for the household's own view.")
    consumption_w = PowerField(required=False, minimum=0, help_text="Optional gross consumption, for the household's own view.")

    def validate_timestamp(self, value):
        now = timezone.now()
        if value > now + FUTURE_TOLERANCE:
            raise serializers.ValidationError("Sample is in the future.")
        if now - value > timedelta(seconds=settings.LIVE_MAX_AGE_S):
            raise serializers.ValidationError(f"Sample is older than {settings.LIVE_MAX_AGE_S} seconds.")
        return value


class LiveIngestResultSerializer(serializers.Serializer):
    """Response shape of the push endpoint (documentation only)."""

    accepted = serializers.BooleanField()
