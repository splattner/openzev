import uuid
from datetime import date
from django.core.exceptions import ValidationError
from django.db import models
from zev.models import Zev


class EnergyType(models.TextChoices):
    LOCAL = "local", "Local (Solar/ZEV)"
    GRID = "grid", "Grid (Netzstrom)"
    FEED_IN = "feed_in", "Feed-in (Einspeisung)"


class TariffCategory(models.TextChoices):
    ENERGY = "energy", "Energy"
    GRID_FEES = "grid_fees", "Grid Fees"
    LEVIES = "levies", "Levies"
    METERING = "metering", "Metering Tariff"


class BillingMode(models.TextChoices):
    ENERGY = "energy", "By energy"
    PERCENTAGE_OF_ENERGY = "percentage_of_energy", "Percentage of energy tariffs"
    MONTHLY_FEE = "monthly_fee", "Monthly fee"
    YEARLY_FEE = "yearly_fee", "Yearly fee"
    PER_METERING_POINT_MONTHLY_FEE = "per_metering_point_monthly_fee", "Per metering point monthly fee"
    PER_METERING_POINT_YEARLY_FEE = "per_metering_point_yearly_fee", "Per metering point yearly fee"
    # For the two shared modes ``fixed_price_chf`` is the amount the *community*
    # pays per month (or per year), not the amount each participant pays: it is
    # divided by the number of participants active in each billed month.
    SHARED_MONTHLY_FEE = "shared_monthly_fee", "Shared monthly fee (split across participants)"
    SHARED_YEARLY_FEE = "shared_yearly_fee", "Shared yearly fee (split across participants)"


class PeriodType(models.TextChoices):
    FLAT = "flat", "Flat rate (all hours)"
    HIGH = "high", "High tariff (HT)"
    LOW = "low", "Low tariff (NT)"


class Tariff(models.Model):
    """Tariff definition for a ZEV with a validity period."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    zev = models.ForeignKey(Zev, on_delete=models.CASCADE, related_name="tariffs")
    name = models.CharField(max_length=200)
    category = models.CharField(max_length=20, choices=TariffCategory.choices, default=TariffCategory.ENERGY)
    billing_mode = models.CharField(max_length=40, choices=BillingMode.choices, default=BillingMode.ENERGY)
    energy_type = models.CharField(max_length=20, choices=EnergyType.choices, null=True, blank=True)
    fixed_price_chf = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    percentage = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
        help_text="Percentage of all energy tariffs (same energy type) used as the effective price. "
                  "Only applicable for billing_mode=percentage_of_energy.",
    )
    valid_from = models.DateField()
    valid_to = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["zev", "category", "name", "-valid_from"]

    def clean(self):
        errors = {}

        if self.valid_to and self.valid_to < self.valid_from:
            errors["valid_to"] = "valid_to must be on or after valid_from."

        if self.billing_mode in {BillingMode.ENERGY, BillingMode.PERCENTAGE_OF_ENERGY} and not self.energy_type:
            errors["energy_type"] = "Energy-based tariffs require an energy type."

        if (
            self.zev_id
            and self.energy_type
            and self.valid_from
            and self.billing_mode in {BillingMode.ENERGY, BillingMode.PERCENTAGE_OF_ENERGY}
        ):
            candidate_end = self.valid_to or date.max
            overlaps = Tariff.objects.exclude(pk=self.pk).filter(
                zev_id=self.zev_id,
                category=self.category,
                billing_mode=self.billing_mode,
                energy_type=self.energy_type,
                valid_from__lte=candidate_end,
            ).filter(
                models.Q(valid_to__isnull=True) | models.Q(valid_to__gte=self.valid_from)
            )
            if overlaps.exists():
                errors["valid_from"] = (
                    "Overlapping tariff windows are not allowed for the same ZEV, category, billing mode, and energy type."
                )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        descriptor = self.get_energy_type_display() if self.energy_type else self.get_billing_mode_display()
        return f"{self.name} ({descriptor}) from {self.valid_from}"


class TariffPeriod(models.Model):
    """A price band within a tariff (flat, HT, or NT)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tariff = models.ForeignKey(Tariff, on_delete=models.CASCADE, related_name="periods")
    period_type = models.CharField(max_length=10, choices=PeriodType.choices, default=PeriodType.FLAT)
    price_chf_per_kwh = models.DecimalField(max_digits=8, decimal_places=5)
    time_from = models.TimeField(null=True, blank=True, help_text="Start of this period (HH:MM)")
    time_to = models.TimeField(null=True, blank=True, help_text="End of this period (HH:MM)")
    weekdays = models.CharField(
        max_length=20, blank=True,
        help_text="Comma-separated weekday numbers 0-6 (Mon-Sun). Leave blank for all days.",
    )

    class Meta:
        ordering = ["period_type"]

    def __str__(self):
        return f"{self.tariff.name} / {self.get_period_type_display()} @ {self.price_chf_per_kwh} CHF/kWh"
