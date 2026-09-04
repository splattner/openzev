import uuid
from datetime import date
from decimal import Decimal
from django.db import models, transaction
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.utils import timezone

from allocation.validity import active_during

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


class InvoiceLanguage(models.TextChoices):
    DE = "de", "Deutsch"
    FR = "fr", "Français"
    IT = "it", "Italiano"
    EN = "en", "English"


class VatMode(models.TextChoices):
    """How VAT is treated when billing participants.

    - ``NOT_REGISTERED``: the ZEV is not VAT-registered. Tariff prices are
      billed exactly as entered — whatever they are is the final amount, and
      no VAT line appears.
    - ``REGISTERED``: the ZEV is VAT-registered. Tariff prices are net; the
      engine adds the active ``VatRate`` on top of the subtotal and the
      invoice shows a VAT line. The ZEV reclaims its input VAT upstream.
    - ``INCLUSIVE``: the ZEV is not registered but the costs it buys in (grid
      energy, grid fees, levies, metering) reach it with VAT it cannot
      reclaim. Tariff prices stay net (as published / imported); the engine
      grosses the VAT-bearing lines by the active rate at invoice time. No
      VAT line appears — a non-registered issuer must not show one — but the
      amounts billed are gross. See ``Invoice.embedded_vat_chf``.
    """

    NOT_REGISTERED = "not_registered", "Not VAT-registered (prices are final as entered)"
    REGISTERED = "registered", "VAT-registered (VAT added on top of net prices)"
    INCLUSIVE = "inclusive", "Not registered — upstream VAT folded into prices"


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
    # Set when the name was chosen from the official ElCom list, null when it
    # was typed. Deliberately not a foreign key: the list is a suggestion
    # source, and an operator missing from ElCom's tariff cube must still be
    # enterable (see zev.grid_operators).
    grid_operator_elcom_id = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="ElCom operator id, when the grid operator was picked from the official list",
    )
    # Where this operator publishes its machine-readable tariffs (Art. 7b
    # StromVV). There is no central registry — every operator hosts its own
    # address — so it is stored per ZEV and reused for next year's refresh.
    tariff_source_url = models.URLField(
        max_length=500, blank=True,
        help_text="URL of the grid operator's machine-readable tariff publication (VSE/AES standard)",
    )
    grid_connection_point = models.CharField(max_length=200, blank=True, help_text="Verknüpfungspunkt / EAN")
    billing_interval = models.CharField(
        max_length=20, choices=BillingInterval.choices, default=BillingInterval.MONTHLY
    )
    invoice_prefix = models.CharField(max_length=10, default="INV", help_text="Prefix for invoice numbers")
    invoice_counter = models.PositiveIntegerField(default=1, help_text="Auto-incremented invoice number")
    contract_counter = models.PositiveIntegerField(
        default=1, help_text="Auto-incremented participation-contract document number"
    )
    invoice_language = models.CharField(
        max_length=2,
        choices=InvoiceLanguage.choices,
        default=InvoiceLanguage.DE,
        help_text="Language used when generating invoice PDFs",
    )
    payment_term_days = models.PositiveIntegerField(
        default=30,
        validators=[MinValueValidator(1), MaxValueValidator(365)],
        help_text="Number of days after invoice generation (issue date) until payment is due",
    )
    bank_iban = models.CharField(max_length=34, blank=True, help_text="IBAN for QR-Rechnung")
    bank_name = models.CharField(max_length=200, blank=True)
    vat_mode = models.CharField(
        max_length=20,
        choices=VatMode.choices,
        default=VatMode.NOT_REGISTERED,
        help_text="How VAT is applied when billing participants.",
    )
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
            "{period_start}, {period_end}, {due_date}, {total_chf}."
        ),
    )
    email_body_template = models.TextField(
        default="",
        blank=True,
        help_text=(
            "Body template for invoice emails. "
            "Leave blank to use the system default. "
            "Available variables: {invoice_number}, {zev_name}, {participant_name}, "
            "{period_start}, {period_end}, {due_date}, {total_chf}."
        ),
    )
    local_tariff_notes = models.TextField(
        blank=True,
        help_text=(
            "Free-text conditions for the local ZEV tariff in following years. "
            "Shown on the participation contract PDF."
        ),
    )
    additional_contract_notes = models.TextField(
        blank=True,
        help_text="Additional agreements shown in the participation contract PDF.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "id"]

    def __str__(self):
        return f"{self.name} ({self.get_zev_type_display()})"

    def clean(self):
        # A VAT-registered ZEV shows its UID on every invoice and contract, so
        # the number is not optional in that mode. The other two modes are for
        # entities that have no UID, so a number stored against them is almost
        # certainly a leftover — flag it rather than silently print it.
        if self.vat_mode == VatMode.REGISTERED and not self.vat_number:
            raise ValidationError(
                {"vat_number": "A VAT-registered ZEV must have a VAT number (UID)."}
            )
        if self.vat_mode != VatMode.REGISTERED and self.vat_number:
            raise ValidationError(
                {"vat_number": "Only a VAT-registered ZEV carries a VAT number. "
                 "Clear it, or set the VAT mode to registered."}
            )

    def next_invoice_number(self):
        num = f"{self.invoice_prefix}-{self.invoice_counter:05d}"
        Zev.objects.filter(pk=self.pk).update(invoice_counter=models.F("invoice_counter") + 1)
        self.refresh_from_db()
        return num

    def next_contract_number(self, year: int | None = None) -> str:
        """Next participation-contract document number (per-ZEV sequence).

        Format ``CTR-YYYY-NNNN``. The counter is read and incremented under a
        ``select_for_update`` row lock, so two concurrent issuances cannot
        derive the same number from a stale counter value. Pass ``year`` to
        pin the year (used by the contract service so its patched clock and
        the rendered document agree). Safe to call inside an outer
        ``transaction.atomic()`` (the contract service does): the inner
        atomic block becomes a savepoint, so the bump rolls back with the
        caller's transaction. Standalone callers get their own transaction.
        """
        year = year or timezone.localdate().year
        with transaction.atomic():
            locked = Zev.objects.select_for_update().get(pk=self.pk)
            num = f"CTR-{year}-{locked.contract_counter:04d}"
            Zev.objects.filter(pk=locked.pk).update(
                contract_counter=models.F("contract_counter") + 1
            )
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
    allocation_weight = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        default=Decimal("1"),
        validators=[MinValueValidator(Decimal("0.0001"))],
        help_text=(
            "Unitless relative weight for splitting community-meter costs. "
            "Not a percentage, per-mille, or Wertquote."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["last_name", "first_name", "id"]

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
    meter_id = models.CharField(max_length=100, unique=True, help_text="Messpunktnummer / Meter ID (e.g. CH9876543210987000000000044440859)")
    meter_type = models.CharField(
        max_length=20, choices=MeteringPointType.choices, default=MeteringPointType.CONSUMPTION
    )
    is_active = models.BooleanField(default=True)
    location_description = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["meter_id"]

    def __str__(self):
        return self.meter_id


class AllocationMode(models.TextChoices):
    """Whether an assignment's costs go to its holder alone or are split.

    ``COMMUNITY`` does not change who holds the metering point — the
    assignment's ``participant`` stays the holder of record for provenance,
    UI, and data-quality purposes (see ``AssignmentWindows.participant_on``).
    It changes only who pays: billing distributes the meter's costs across
    every eligible participant by ``Participant.allocation_weight`` instead
    of attributing them to the holder.
    """

    PERSONAL = "personal", "Personal"
    COMMUNITY = "community", "Community"


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
    allocation_mode = models.CharField(
        max_length=10,
        choices=AllocationMode.choices,
        default=AllocationMode.PERSONAL,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-valid_from", "-created_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["metering_point", "participant", "valid_from"],
                name="uniq_metering_point_assignment_start",
            )
        ]

    def clean(self):
        if not self.participant_id or not self.metering_point_id or not self.valid_from:
            return

        errors = {}

        if self.participant.zev_id != self.metering_point.zev_id:
            errors["participant"] = "Participant must belong to the same ZEV as the metering point."
        if self.valid_to and self.valid_to < self.valid_from:
            errors["valid_to"] = "valid_to must be on or after valid_from."

        if self.valid_from < self.participant.valid_from:
            errors["valid_from"] = (
                f"Assignment valid_from cannot be before the participant's "
                f"valid_from ({self.participant.valid_from})."
            )
        if self.valid_to and self.participant.valid_to and self.valid_to > self.participant.valid_to:
            errors["valid_to"] = (
                f"Assignment valid_to cannot be after the participant's "
                f"valid_to ({self.participant.valid_to})."
            )

        if errors:
            raise ValidationError(errors)

        self._validate_no_overlap()

    def _validate_no_overlap(self):
        """Reject assignment windows that overlap another assignment of the
        same metering point.

        Called from ``clean()`` (full validation on the API/admin paths) and
        from ``save()`` (single-object ORM writes). Overlapping windows would
        make per-timestamp holder attribution ambiguous, so they are rejected
        at write time rather than left for the allocation runtime to refuse
        (ADR 0013).
        """
        if not self.metering_point_id or not self.valid_from:
            return
        existing = MeteringPointAssignment.objects.filter(metering_point=self.metering_point)
        if self.pk:
            existing = existing.exclude(pk=self.pk)
        overlap_exists = active_during(
            existing, self.valid_from, self.valid_to or date.max
        ).exists()
        if overlap_exists:
            raise ValidationError("A metering point can only have one active assignment at a time.")

    def save(self, *args, **kwargs):
        """Enforce the non-overlap rule on single-object ORM writes.

        Only the overlap rule runs here: the other ``clean()`` rules
        (cross-ZEV participant, participant validity containment,
        ``valid_to >= valid_from``) still require ``full_clean()``, so they
        are enforced on the API/admin paths.
        """
        self._validate_no_overlap()
        super().save(*args, **kwargs)

    def __str__(self):
        valid_to = self.valid_to.isoformat() if self.valid_to else "open"
        return f"{self.metering_point.meter_id} → {self.participant.full_name} ({self.valid_from} - {valid_to})"
