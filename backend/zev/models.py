import uuid
from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone

DEFAULT_EMAIL_SUBJECT_TEMPLATE = "Invoice {invoice_number} \u2013 {zev_name}"
DEFAULT_EMAIL_BODY_TEMPLATE = (
    "Dear {participant_name},\n\n"
    "Please find your energy invoice for the period "
    "{period_start} to {period_end} attached.\n\n"
    "Total: CHF {total_chf}\n\n"
    "Kind regards,\n{zev_name}"
)



class BillingInterval(models.TextChoices):
    MONTHLY = "monthly", "Monthly"
    QUARTERLY = "quarterly", "Quarterly"
    SEMI_ANNUAL = "semi_annual", "Semi-Annual"
    ANNUAL = "annual", "Annual"


class ZevType(models.TextChoices):
    ZEV = "zev", "ZEV (Zusammenschluss zum Eigenverbrauch)"
    VZEV = "vzev", "vZEV (Virtueller Zusammenschluss zum Eigenverbrauch)"


class Zev(models.Model):
    """Represents a ZEV or vZEV community."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    start_date = models.DateField(default=timezone.localdate)
    zev_type = models.CharField(max_length=10, choices=ZevType.choices, default=ZevType.VZEV)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="owned_zevs",
    )
    grid_operator = models.CharField(max_length=200, blank=True, help_text="Name of the VNB (Verteilnetzbetreiber)")
    grid_connection_point = models.CharField(max_length=200, blank=True, help_text="Verknüpfungspunkt / EAN")
    address_line1 = models.CharField(max_length=200, blank=True)
    address_line2 = models.CharField(max_length=200, blank=True)
    postal_code = models.CharField(max_length=10, blank=True)
    billing_interval = models.CharField(
        max_length=20, choices=BillingInterval.choices, default=BillingInterval.MONTHLY
    )
    invoice_prefix = models.CharField(max_length=10, default="INV", help_text="Prefix for invoice numbers")
    invoice_counter = models.PositiveIntegerField(default=1, help_text="Auto-incremented invoice number")
    bank_iban = models.CharField(max_length=34, blank=True, help_text="IBAN for QR-Rechnung")
    bank_name = models.CharField(max_length=200, blank=True)
    vat_number = models.CharField(max_length=50, blank=True)
    notes = models.TextField(blank=True)
    email_subject_template = models.CharField(
        max_length=500,
        default="",
        blank=True,
        help_text=(
            "Subject line template for invoice emails. "
            "Leave blank to use the system default. "
            "Available variables: {invoice_number}, {zev_name}, {participant_name}, "
            "{period_start}, {period_end}, {total_chf}."
        ),
    )
    email_body_template = models.TextField(
        default="",
        blank=True,
        help_text=(
            "Body template for invoice emails. "
            "Leave blank to use the system default. "
            "Available variables: {invoice_number}, {zev_name}, {participant_name}, "
            "{period_start}, {period_end}, {total_chf}."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.get_zev_type_display()})"

    def next_invoice_number(self):
        num = f"{self.invoice_prefix}-{self.invoice_counter:05d}"
        Zev.objects.filter(pk=self.pk).update(invoice_counter=models.F("invoice_counter") + 1)
        self.refresh_from_db()
        return num


class Participant(models.Model):
    """A person or entity participating in a ZEV."""

    class Title(models.TextChoices):
        MR = "mr", "Mr."
        MRS = "mrs", "Mrs."
        MS = "ms", "Ms."
        DR = "dr", "Dr."
        PROF = "prof", "Prof."

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    zev = models.ForeignKey(Zev, on_delete=models.CASCADE, related_name="participants")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="participations",
        help_text="Linked user account (optional)",
    )
    title = models.CharField(max_length=10, choices=Title.choices, blank=True)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    address_line1 = models.CharField(max_length=200, blank=True)
    address_line2 = models.CharField(max_length=200, blank=True)
    postal_code = models.CharField(max_length=10, blank=True)
    city = models.CharField(max_length=100, blank=True)
    valid_from = models.DateField()
    valid_to = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["last_name", "first_name"]

    @property
    def full_name(self):
        title_display = self.get_title_display() if self.title else ""
        return f"{title_display} {self.first_name} {self.last_name}".strip()

    def __str__(self):
        return f"{self.full_name} ({self.zev.name})"


class MeteringPointType(models.TextChoices):
    CONSUMPTION = "consumption", "Consumption"
    PRODUCTION = "production", "Production"
    BIDIRECTIONAL = "bidirectional", "Bidirectional (Consumption + Production)"


class MeteringPoint(models.Model):
    """A smart meter / metering point that belongs to a ZEV and can be assigned to participants over time."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    zev = models.ForeignKey(Zev, on_delete=models.CASCADE, related_name="metering_points")
    participant = models.ForeignKey(
        Participant,
        on_delete=models.SET_NULL,
        related_name="metering_points",
        null=True,
        blank=True,
        help_text="Deprecated direct link. Use assignments for temporal participant ownership.",
    )
    meter_id = models.CharField(max_length=100, help_text="Messpunktnummer / Meter ID (e.g. CH9876543210987000000000044440859)")
    meter_type = models.CharField(
        max_length=20, choices=MeteringPointType.choices, default=MeteringPointType.CONSUMPTION
    )
    is_active = models.BooleanField(default=True)
    valid_from = models.DateField()
    valid_to = models.DateField(null=True, blank=True)
    location_description = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["meter_id"]

    def __str__(self):
        if self.participant:
            return f"{self.meter_id} ({self.participant.full_name})"
        return f"{self.meter_id} (unassigned)"


class MeteringPointAssignment(models.Model):
    """Temporal assignment of a metering point to a participant."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    metering_point = models.ForeignKey(
        MeteringPoint,
        on_delete=models.CASCADE,
        related_name="assignments",
    )
    participant = models.ForeignKey(
        Participant,
        on_delete=models.CASCADE,
        related_name="metering_point_assignments",
    )
    valid_from = models.DateField()
    valid_to = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-valid_from", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["metering_point", "participant", "valid_from"],
                name="uniq_metering_point_assignment_start",
            )
        ]

    def clean(self):
        if self.participant.zev_id != self.metering_point.zev_id:
            raise ValidationError("Participant must belong to the same ZEV as the metering point.")
        if self.valid_to and self.valid_to < self.valid_from:
            raise ValidationError("valid_to must be on or after valid_from.")

    def __str__(self):
        valid_to = self.valid_to.isoformat() if self.valid_to else "open"
        return f"{self.metering_point.meter_id} → {self.participant.full_name} ({self.valid_from} - {valid_to})"
