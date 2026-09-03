import uuid
from datetime import date
from django.core.exceptions import ValidationError
from django.db import models
from zev.models import Zev

from .periods import parse_number_list
from .series import SERIES_FIELDS


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


class SplitKey(models.TextChoices):
    """Which denominator a SHARED_* fee uses.

    Read only for SHARED_MONTHLY_FEE / SHARED_YEARLY_FEE; ignored by every
    other billing mode. Does not apply to community metering points, which
    always allocate by Participant.allocation_weight.
    """

    EQUAL = "equal", "Equal (headcount)"
    WEIGHT = "weight", "Weight"


def _validate_number_list(value: str, *, low: int, high: int, label: str) -> None:
    """Reject anything the engine could not parse back out.

    ``weekdays`` went unvalidated for a long time and the engine parses it with
    a bare ``int()``, so a stray value there is a crash at invoice time rather
    than at entry time. ``months`` arrives with the same shape, so both get the
    same guard.
    """
    if not value:
        return
    for part in value.split(","):
        part = part.strip()
        if not part.isdigit() or not (low <= int(part) <= high):
            raise ValidationError(
                f"{label} must be comma-separated numbers between {low} and {high}, "
                f"or blank for all of them. Got {value!r}."
            )


def validate_weekday_list(value: str) -> None:
    _validate_number_list(value, low=0, high=6, label="Weekdays")


def validate_month_list(value: str) -> None:
    _validate_number_list(value, low=1, high=12, label="Months")


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
    split_key = models.CharField(max_length=10, choices=SplitKey.choices, default=SplitKey.EQUAL)
    valid_from = models.DateField()
    valid_to = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["zev", "category", "name", "-valid_from", "id"]

    def clean(self):
        errors = {}

        if self.valid_to and self.valid_to < self.valid_from:
            errors["valid_to"] = "valid_to must be on or after valid_from."

        if self.billing_mode in {BillingMode.ENERGY, BillingMode.PERCENTAGE_OF_ENERGY} and not self.energy_type:
            errors["energy_type"] = "Energy-based tariffs require an energy type."

        # A ZEV legitimately carries several simultaneous per-kWh components in
        # one category — grid fees are Netznutzung *and* SDL, levies are the
        # Netzzuschlag *and* the cantonal charge — and the engine is built to
        # accumulate them into separate invoice lines. So overlapping windows
        # are only rejected for tariffs sharing a *name*, which is the case that
        # is almost certainly a mistake: a new seasonal version created without
        # closing the previous one, which would double-bill every participant.
        if self.zev_id and self.name and self.valid_from:
            candidate_end = self.valid_to or date.max
            overlaps = Tariff.objects.exclude(pk=self.pk).filter(
                zev_id=self.zev_id,
                name=self.name,
                valid_from__lte=candidate_end,
            ).filter(
                models.Q(valid_to__isnull=True) | models.Q(valid_to__gte=self.valid_from)
            )
            if overlaps.exists():
                errors["valid_from"] = (
                    f'Another tariff named "{self.name}" in this ZEV already covers part of this '
                    "validity period. Close the previous one with a valid_to date, or give this "
                    "one a different name if both should apply at the same time."
                )

            # Tariffs sharing a name are versions of one another, so they must
            # agree on what the tariff *is*. Letting these drift would make the
            # series incoherent: comparing versions would compare a local-energy
            # rate against a grid fee, and the engine would bucket the same
            # "tariff" differently from one year to the next.
            sibling = Tariff.objects.exclude(pk=self.pk).filter(
                zev_id=self.zev_id, name=self.name
            ).first()
            if sibling is not None:
                for field in SERIES_FIELDS:
                    mine, theirs = getattr(self, field), getattr(sibling, field)
                    if mine != theirs:
                        errors[field] = (
                            f'Other versions of "{self.name}" in this ZEV use '
                            f"{field}={theirs!r}. Every version of a tariff must agree on its "
                            "category, billing mode, and energy type — use a different name to "
                            "create a separate tariff instead."
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
    """A price band within a tariff (flat, HT, or NT).

    A band recurs: it applies in certain months, on certain weekdays, between
    certain hours. All three are stored as "blank means every one of them", so
    an unrestricted band is the empty string on every axis and the common case
    stays cheap to read.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tariff = models.ForeignKey(Tariff, on_delete=models.CASCADE, related_name="periods")
    period_type = models.CharField(max_length=10, choices=PeriodType.choices, default=PeriodType.FLAT)
    price_chf_per_kwh = models.DecimalField(max_digits=8, decimal_places=5)
    time_from = models.TimeField(null=True, blank=True, help_text="Start of this period (HH:MM)")
    time_to = models.TimeField(null=True, blank=True, help_text="End of this period (HH:MM)")
    weekdays = models.CharField(
        max_length=20, blank=True,
        validators=[validate_weekday_list],
        help_text="Comma-separated weekday numbers 0-6 (Mon-Sun). Leave blank for all days.",
    )
    # Swiss grid operators commonly price winter and summer differently, and
    # the VSE/AES tariff standard publishes that as a months array per band.
    months = models.CharField(
        max_length=40, blank=True,
        validators=[validate_month_list],
        help_text="Comma-separated month numbers 1-12. Leave blank for all months.",
    )

    class Meta:
        # Unchanged deliberately. Seasonal siblings share a period_type and so
        # fall back to id, which is creation order — for an import that is the
        # order the operator published. Sorting them meaningfully needs
        # time_from, which is nullable and orders NULLs differently on SQLite
        # and Postgres; the frontend sorts for display instead.
        ordering = ["period_type", "id"]

    def clean(self):
        # Nothing else may share a name-and-window with this band's months, but
        # a band that prices no month at all is simply unreachable.
        if self.months and not parse_number_list(self.months):
            raise ValidationError({"months": "Leave months blank to apply in every month."})

    def __str__(self):
        return f"{self.tariff.name} / {self.get_period_type_display()} @ {self.price_chf_per_kwh} CHF/kWh"
