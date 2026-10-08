import re
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from zev.models import MeteringPoint, Participant


class ReadingDirection(models.TextChoices):
    IN = "in", "Consumption (IN)"
    OUT = "out", "Production / Feed-in (OUT)"


class ReadingResolution(models.TextChoices):
    FIFTEEN_MIN = "15min", "15 minutes"
    HOURLY = "hourly", "Hourly"
    DAILY = "daily", "Daily"


class ImportSource(models.TextChoices):
    CSV = "csv", "CSV Upload"
    SDATCH = "sdatch", "SDAT-CH (ebIX XML)"
    MANUAL = "manual", "Manual entry"


class MeterReading(models.Model):
    """A single energy reading for a metering point."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    metering_point = models.ForeignKey(
        MeteringPoint, on_delete=models.CASCADE, related_name="readings"
    )
    timestamp = models.DateTimeField(help_text="Start of the measurement interval (UTC)")
    energy_kwh = models.DecimalField(max_digits=12, decimal_places=4)
    direction = models.CharField(max_length=5, choices=ReadingDirection.choices, default=ReadingDirection.IN)
    resolution = models.CharField(
        max_length=10, choices=ReadingResolution.choices, default=ReadingResolution.FIFTEEN_MIN
    )
    import_source = models.CharField(max_length=20, choices=ImportSource.choices, default=ImportSource.CSV)
    import_batch = models.UUIDField(null=True, blank=True, help_text="Groups readings from the same import")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["metering_point", "timestamp", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["metering_point", "timestamp", "direction"],
                name="unique_reading_per_point_time_direction",
            )
        ]

    def __str__(self):
        return (
            f"{self.metering_point.meter_id} {self.timestamp.isoformat()} "
            f"{self.direction} {self.energy_kwh} kWh"
        )


class ImportLog(models.Model):
    """Audit log for each metering data import."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    batch_id = models.UUIDField(default=uuid.uuid4)
    zev = models.ForeignKey(
        "zev.Zev",
        on_delete=models.CASCADE,
        related_name="import_logs",
        null=True,
        blank=True,
    )
    imported_by = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, related_name="import_logs"
    )
    source = models.CharField(max_length=20, choices=ImportSource.choices)
    filename = models.CharField(max_length=255, blank=True)
    rows_total = models.IntegerField(default=0)
    rows_imported = models.IntegerField(default=0)
    rows_overwritten = models.PositiveIntegerField(default=0)
    rows_skipped = models.IntegerField(default=0)
    errors = models.JSONField(default=list)
    warnings = models.JSONField(default=list)
    timestamp_timezone = models.CharField(
        max_length=40,
        blank=True,
        default="",
        help_text=(
            "Zone offset-less timestamps in this batch were read in (Europe/Zurich or UTC). "
            "Empty for imports before ADR 0026, which read them as UTC."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "id"]

    def __str__(self):
        target = self.zev.name if self.zev else "multiple/unknown ZEV"
        return f"Import {self.batch_id} ({self.source}) for {target}"


# ---------------------------------------------------------------------------
# Supplementary energy data (SPEC-2026-supplementary-energy-data, ADR 0030)
#
# Statistics only. Nothing in allocation, tariffs or the invoice engine and
# documents reads these tables; ``MeterReading`` stays the sole billing input.
# ---------------------------------------------------------------------------

SOLAR_MANAGER_ID_RE = re.compile(r"^[A-Za-z0-9]{3,24}$")


class SupplementaryProvider(models.TextChoices):
    SOLAR_MANAGER = "solar_manager", "Solar Manager"
    PUSH = "push", "Push or file upload"


class SupplementaryStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    OK = "ok", "OK"
    ERROR = "error", "Error"
    RECONNECT_REQUIRED = "reconnect_required", "Reconnect required"
    DISABLED = "disabled", "Disabled"


class SupplementarySource(models.Model):
    """One connection between a metering point and a participant's own system.

    The participant is the consenting holder: ingestion is clipped to the
    intervals during which they held the metering point personally.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    metering_point = models.OneToOneField(
        MeteringPoint, on_delete=models.CASCADE, related_name="supplementary_source"
    )
    participant = models.ForeignKey(
        Participant, on_delete=models.CASCADE, related_name="supplementary_sources"
    )
    provider = models.CharField(max_length=20, choices=SupplementaryProvider.choices)
    label = models.CharField(max_length=100, blank=True, default="")
    external_id = models.CharField(
        max_length=64, blank=True, default="", help_text="Solar Manager smId."
    )
    credential_encrypted = models.BinaryField(
        blank=True, default=b"",
        help_text="Fernet ciphertext under INTEGRATION_ENCRYPTION_KEYS (ADR 0031). Never serialized.",
    )
    push_token_prefix = models.CharField(max_length=16, unique=True, null=True, blank=True, default=None)
    push_token_hash = models.CharField(max_length=64, blank=True, default="")
    enabled = models.BooleanField(default=True)
    status = models.CharField(
        max_length=20, choices=SupplementaryStatus.choices, default=SupplementaryStatus.PENDING
    )
    consented_at = models.DateTimeField(default=timezone.now)
    last_sync_at = models.DateTimeField(null=True, blank=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=500, blank=True, default="", help_text="User-safe text only.")
    synced_through = models.DateTimeField(
        null=True, blank=True, help_text="End of the last interval ingested (UTC)."
    )
    covers_from = models.DateTimeField(
        null=True, blank=True, help_text="Start of the earliest stored interval (UTC)."
    )
    reconciliation = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"{self.get_provider_display()} for {self.metering_point_id}"

    # ---- validation ----

    def clean(self):
        errors = {}
        if self.metering_point_id and not self.metering_point.has_behind_meter_generation:
            errors["metering_point"] = (
                "Only metering points with generation behind the meter can have an energy data source."
            )
        if self.participant_id and self.metering_point_id and (
            self.participant.zev_id != self.metering_point.zev_id
        ):
            errors["participant"] = "Participant must belong to the same ZEV as the metering point."
        if self.provider == SupplementaryProvider.SOLAR_MANAGER:
            if not SOLAR_MANAGER_ID_RE.match(self.external_id or ""):
                errors["external_id"] = "A Solar Manager id (3 to 24 letters or digits) is required."
        elif self.external_id:
            errors["external_id"] = "Only Solar Manager sources have an external id."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        # A disabled source is always shown as disabled; re-enabling returns it
        # to ``pending`` until the next sync decides.
        before = self.status
        if not self.enabled and self.status != SupplementaryStatus.DISABLED:
            self.status = SupplementaryStatus.DISABLED
        elif self.enabled and self.status == SupplementaryStatus.DISABLED:
            self.status = SupplementaryStatus.PENDING
        update_fields = kwargs.get("update_fields")
        if self.status != before and update_fields is not None and "status" not in update_fields:
            kwargs["update_fields"] = [*update_fields, "status"]
        return super().save(*args, **kwargs)

    # ---- credential ----

    @property
    def has_credential(self) -> bool:
        return bool(self.credential_encrypted)

    @property
    def credential(self) -> str:
        """The decrypted refresh token, or ``""``. Decrypted on access, never cached."""
        if not self.credential_encrypted:
            return ""
        from .supplementary.crypto import decrypt_secret

        return decrypt_secret(bytes(self.credential_encrypted))

    def set_credential(self, refresh_token: str) -> None:
        """Encrypt and store ``refresh_token`` (not saved).

        Raises ``ValidationError`` when ``INTEGRATION_ENCRYPTION_KEYS`` is empty,
        because a credential that cannot be encrypted must not be stored at all.
        """
        from .supplementary.crypto import IntegrationNotConfigured, encrypt_secret

        try:
            self.credential_encrypted = encrypt_secret(refresh_token)
        except IntegrationNotConfigured as exc:
            raise ValidationError({"api_key": str(exc)}) from exc

    def clear_credential(self) -> None:
        """Drop the credential and any push token (not saved)."""
        self.credential_encrypted = b""
        self.push_token_prefix = None
        self.push_token_hash = ""

    # ---- state transitions (not saved) ----

    def mark_ok(self, *, at=None) -> None:
        at = at or timezone.now()
        self.status = SupplementaryStatus.OK
        self.last_sync_at = at
        self.last_success_at = at
        self.last_error = ""

    def mark_error(self, safe_text: str, *, at=None) -> None:
        self.status = SupplementaryStatus.ERROR
        self.last_sync_at = at or timezone.now()
        self.last_error = safe_text[:500]

    def mark_reconnect_required(self, safe_text: str, *, at=None) -> None:
        self.status = SupplementaryStatus.RECONNECT_REQUIRED
        self.last_sync_at = at or timezone.now()
        self.last_error = safe_text[:500]

    def disconnect(self) -> None:
        """Stop syncing and drop the secrets; the readings are kept (not saved)."""
        self.enabled = False
        self.status = SupplementaryStatus.DISABLED
        self.clear_credential()


class SupplementaryReading(models.Model):
    """One 15-minute interval of a participant's own measurements, in kWh.

    Stored as delivered. Derived figures (self-consumption) are computed at read
    time, because vendors disagree with themselves on their derived fields.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source = models.ForeignKey(SupplementarySource, on_delete=models.CASCADE, related_name="readings")
    metering_point = models.ForeignKey(
        MeteringPoint, on_delete=models.CASCADE, related_name="supplementary_readings"
    )
    timestamp = models.DateTimeField(help_text="Start of the measurement interval (UTC)")
    consumption_kwh = models.DecimalField(max_digits=12, decimal_places=4)
    production_kwh = models.DecimalField(max_digits=12, decimal_places=4)
    import_kwh = models.DecimalField(max_digits=12, decimal_places=4)
    export_kwh = models.DecimalField(max_digits=12, decimal_places=4)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["metering_point", "timestamp", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["metering_point", "timestamp"],
                name="uniq_supplementary_reading_mp_ts",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(consumption_kwh__gte=0)
                    & models.Q(production_kwh__gte=0)
                    & models.Q(import_kwh__gte=0)
                    & models.Q(export_kwh__gte=0)
                ),
                name="supplementary_reading_non_negative",
            ),
        ]

    def __str__(self):
        return f"{self.metering_point_id} {self.timestamp.isoformat()}"
