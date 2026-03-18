import uuid
from django.db import models
from zev.models import MeteringPoint


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
        ordering = ["metering_point", "timestamp"]
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
    rows_skipped = models.IntegerField(default=0)
    errors = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        target = self.zev.name if self.zev else "multiple/unknown ZEV"
        return f"Import {self.batch_id} ({self.source}) for {target}"
