import uuid
from datetime import date
from decimal import Decimal
from django.db import models, transaction
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.utils import timezone

from allocation.validity import active_during
from .iban import INVALID_IBAN_MESSAGE, is_valid_iban, normalize_iban

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
    # Postal code of the grid connection (not a participant's address — a ZEV
    # has one ``grid_connection_point``, so one site postal code). Used only to
    # look up a grid-operator suggestion from the ElCom register
    # (``zev.grid_operators.grid_operators_for_postal_code``); never
    # validated, since a ZEV with no resolvable operator must stay enterable.
    postal_code = models.CharField(max_length=10, blank=True)
    grid_operator = models.CharField(max_length=200, blank=True, help_text="Name of the VNB (Verteilnetzbetreiber)")
    # Set when the name was chosen from the official ElCom list, null when it
    # was typed. Deliberately not a foreign key: the list is a suggestion
    # source, and an operator missing from ElCom's tariff cube must still be
    # enterable (see zev.grid_operators).
    grid_operator_elcom_id = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="ElCom operator id, when the grid operator was picked from the official list",
    )
    # Every operator hosts its own address rather than publishing through a
    # central portal, so this is stored per ZEV and reused for next year's
    # refresh. ElCom's register catalogues where to find it (see
    # ``grid_operators_for_postal_code``), but that catalogue entry is a
    # suggestion only — see the long comment in ``zev.grid_operators`` on why
    # it is never trusted enough to write here without a validating fetch.
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
    # Prints a QR on the invoice that opens that invoice without a login. Off
    # by default and no migration opts anyone in: it changes a document
    # participants receive and exposes figures without authentication, which is
    # an operator's decision to take rather than one to inherit on upgrade.
    participant_invoice_access = models.BooleanField(
        default=False,
        help_text="Print a QR on invoices letting participants view them without an account.",
    )
    # Off by default: turning it on changes how every subsequent invoice reads,
    # and an operator who never set it should keep the output they know.
    itemize_tariff_bands = models.BooleanField(
        default=False,
        help_text=(
            "Show each price band of a multi-band tariff as its own invoice "
            "line, instead of one line at the blended average rate."
        ),
    )
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
    # A retired ZEV, not a deleted one: nothing under it is touched. A
    # timestamp rather than a boolean because *when* is what retention, the
    # admin list and the audit trail all need, and it is the field a future
    # purge guardrail keys off ("disabled for at least N days"). Null means
    # active. Never set directly through ``ZevSerializer`` (see its
    # ``read_only_fields``) — only through ``ZevViewSet.disable``/``enable``,
    # so the admin-only rule on ``enable`` cannot be bypassed with a PATCH.
    disabled_at = models.DateTimeField(
        null=True, blank=True, db_index=True,
        help_text="When this ZEV was disabled. Null means active.",
    )
    disabled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="+",
        help_text="Who disabled this ZEV (its owner or an admin).",
    )
    disabled_reason = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "id"]

    def __str__(self):
        return f"{self.name} ({self.get_zev_type_display()})"

    @property
    def is_disabled(self) -> bool:
        return self.disabled_at is not None

    def clean(self):
        if self.bank_iban:
            self.bank_iban = normalize_iban(self.bank_iban)
            if not is_valid_iban(self.bank_iban):
                raise ValidationError({"bank_iban": INVALID_IBAN_MESSAGE})
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


class ParticipantManager(models.Manager):
    """Participants always come with their party: almost every read of a
    participant reads its name or address (ADR 0028)."""

    def get_queryset(self):
        return super().get_queryset().select_related("party")


class PartyKind(models.TextChoices):
    PERSON = "person", "Person"
    ORGANISATION = "organisation", "Organisation"


class PartyTitle(models.TextChoices):
    MR = "mr", "Mr."
    MRS = "mrs", "Mrs."
    MS = "ms", "Ms."
    DR = "dr", "Dr."
    PROF = "prof", "Prof."


# A party's names, contact data and address: the fields Participant reads
# through to (its facade, ADR 0028).
PARTY_FACADE_FIELDS = (
    "kind",
    "title",
    "first_name",
    "last_name",
    "organisation_name",
    "name_addition",
    "email",
    "phone",
    "address_line1",
    "address_line2",
    "postal_code",
    "city",
)

# The party fields a name is built from (display_name, name_lines).
PARTY_NAME_FIELDS = ("kind", "title", "first_name", "last_name", "organisation_name", "name_addition")

QR_NAME_MAX_LENGTH = 70


class Party(models.Model):
    """A person or organisation of a ZEV (#761, ADR 0028).

    Whoever the ZEV deals with is a party: its participants (each participation
    is a ``Participant`` row of a party), the issuer of its invoices, its
    representative toward the grid operator, its landowners — and contacts that
    are none of these yet. A party belongs to one ZEV; the same company in two
    ZEVs is two parties.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    zev = models.ForeignKey("Zev", on_delete=models.CASCADE, related_name="parties")
    kind = models.CharField(max_length=20, choices=PartyKind.choices, default=PartyKind.PERSON)
    title = models.CharField(max_length=10, choices=PartyTitle.choices, blank=True)
    first_name = models.CharField(max_length=100, blank=True)
    last_name = models.CharField(max_length=100, blank=True)
    organisation_name = models.CharField(max_length=200, blank=True)
    # A second name line: another member of the household, "c/o …".
    name_addition = models.CharField(max_length=200, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    address_line1 = models.CharField(max_length=200, blank=True)
    address_line2 = models.CharField(max_length=200, blank=True)
    postal_code = models.CharField(max_length=10, blank=True)
    city = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    # The party's own login, for a party that is not a participant (a property
    # manager, an outside representative). A participant's account stays on its
    # participation (``Participant.user``); ``zev.access.party_accounts`` reads
    # both. An account linked here gets no rights by itself: the issuer and
    # representative roles make it a manager (ADR 0028, amended), a grant gives
    # anything else.
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="parties",
        help_text="The party's own account, when it is not a participant",
    )
    # What lists sort by: the organisation's name or the person's last name.
    sort_name = models.CharField(max_length=200, blank=True, editable=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_name", "first_name", "id"]
        verbose_name_plural = "parties"

    def clean(self):
        super().clean()
        if self.kind == PartyKind.ORGANISATION and not self.organisation_name.strip():
            raise ValidationError({"organisation_name": "An organisation needs a name."})
        if self.kind == PartyKind.PERSON and not self.last_name.strip():
            raise ValidationError({"last_name": "A person needs a last name."})

    def save(self, *args, **kwargs):
        self.sort_name = self.compute_sort_name()
        update_fields = kwargs.get("update_fields")
        if update_fields is not None and "sort_name" not in update_fields:
            kwargs["update_fields"] = [*update_fields, "sort_name"]
        super().save(*args, **kwargs)

    def compute_sort_name(self) -> str:
        if self.kind == PartyKind.ORGANISATION:
            return self.organisation_name.strip()
        return self.last_name.strip()

    @property
    def person_name(self) -> str:
        title_display = self.get_title_display() if self.title else ""
        return f"{title_display} {self.first_name} {self.last_name}".strip()

    @property
    def display_name(self) -> str:
        if self.kind == PartyKind.ORGANISATION:
            return self.organisation_name.strip()
        return self.person_name

    @property
    def name_lines(self) -> list[str]:
        lines = [self.display_name]
        if self.name_addition.strip():
            lines.append(self.name_addition.strip())
        return lines

    @property
    def qr_name(self) -> str:
        """The name on a QR bill: one line of at most 70 characters."""
        return " ".join(self.name_lines)[:QR_NAME_MAX_LENGTH].strip()

    def __str__(self):
        return self.display_name


def _facade_property(name):
    """A Participant attribute that reads and writes its party's field ``name``.

    A write is staged on the participant and lands on the party when the
    participant is saved, so ``Participant(first_name=…)`` and
    ``participant.city = …; participant.save()`` keep working.
    """

    def getter(self):
        pending = self.__dict__.get("_party_pending", {})
        if name in pending:
            return pending[name]
        party = self._party_or_none()
        if party is not None:
            return getattr(party, name)
        return Party._meta.get_field(name).get_default()

    def setter(self, value):
        self.__dict__.setdefault("_party_pending", {})[name] = value

    return property(getter, setter, doc=f"The party's ``{name}`` (read through, ADR 0028).")


class Participant(models.Model):
    """A party's billing relationship with a ZEV (#761, ADR 0028).

    What is about being billed lives here: the dates, the allocation weight,
    the meter assignments and invoices, the account link. Names, contact data
    and the address belong to the ``party``; the attributes of the same names
    on a participant read and write through to it (``PARTY_FACADE_FIELDS``).
    ORM lookups go through ``party__…``. Several participations may share one
    party — someone moving within a ZEV, a flat plus a business unit.
    """

    Title = PartyTitle

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    zev = models.ForeignKey(Zev, on_delete=models.CASCADE, related_name="participants")
    party = models.ForeignKey(Party, on_delete=models.RESTRICT, related_name="participations")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="participations",
        help_text="Linked user account (optional)",
    )
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

    objects = ParticipantManager()

    class Meta:
        ordering = ["party__sort_name", "party__first_name", "id"]
        base_manager_name = "objects"

    for _name in PARTY_FACADE_FIELDS:
        locals()[_name] = _facade_property(_name)
    del _name

    def _party_or_none(self):
        if self.party_id is None:
            return None
        return self.party

    def get_title_display(self):
        title = self.title
        return PartyTitle(title).label if title in PartyTitle.values else title

    @property
    def full_name(self) -> str:
        """The name the participant is billed under (the party's display name)."""
        party = self._party_or_none()
        if party is None or self.__dict__.get("_party_pending"):
            return self._staged_party().display_name
        return party.display_name

    @property
    def display_name(self) -> str:
        return self.full_name

    @property
    def name_lines(self) -> list[str]:
        party = self._party_or_none()
        if party is None or self.__dict__.get("_party_pending"):
            return self._staged_party().name_lines
        return party.name_lines

    def _staged_party(self) -> Party:
        """An unsaved party with the current values, staged ones applied."""
        values = {name: getattr(self, name) for name in PARTY_FACADE_FIELDS}
        return Party(zev_id=self.zev_id, **values)

    def clean(self):
        super().clean()
        if self.party_id is not None and self.zev_id is not None and self.party.zev_id != self.zev_id:
            raise ValidationError({"party": "The party belongs to another ZEV."})

    def save(self, *args, **kwargs):
        pending = self.__dict__.pop("_party_pending", {})
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            # Facade names are party fields: written to the party below.
            facade = [name for name in update_fields if name in PARTY_FACADE_FIELDS]
            kwargs["update_fields"] = [name for name in update_fields if name not in PARTY_FACADE_FIELDS]
            for name in facade:
                pending.setdefault(name, getattr(self._party_or_none(), name, ""))
        with transaction.atomic():
            if self.party_id is None:
                party = Party(zev_id=self.zev_id, **pending)
                party.save()
                self.party = party
                if kwargs.get("update_fields") is not None:
                    kwargs["update_fields"] = [*kwargs["update_fields"], "party"]
            elif pending:
                party = self.party
                for name, value in pending.items():
                    setattr(party, name, value)
                party.save(update_fields=[*pending, "updated_at"])
            if kwargs.get("update_fields") == []:
                return
            super().save(*args, **kwargs)

    def refresh_from_db(self, using=None, fields=None, from_queryset=None):
        if fields is None:
            self.__dict__.pop("_party_pending", None)
        else:
            facade = [name for name in fields if name in PARTY_FACADE_FIELDS]
            fields = [name for name in fields if name not in PARTY_FACADE_FIELDS]
            if facade and self.party_id is not None:
                self.party.refresh_from_db(using=using, fields=facade)
            if not fields:
                return
        super().refresh_from_db(using=using, fields=fields, from_queryset=from_queryset)
        if fields is None and self.party_id is not None and "party" in self._state.fields_cache:
            self.party.refresh_from_db(using=using)

    def __str__(self):
        return f"{self.full_name} ({self.zev.name})"


class ParticipantOnboardingToken(models.Model):
    """A reusable per-participant bearer link, valid for 30 days.

    Lets the mailed link double as the participant's way back in until they
    set a password of their own, which revokes it. Prefix and secret are
    stored in clear for the same reason ``InvoiceAccessToken.secret`` is:
    whoever can read this row can already read the participant it protects,
    so revocation — not secrecy of storage — is the control.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    participant = models.ForeignKey(
        Participant, on_delete=models.CASCADE, related_name="onboarding_tokens",
    )
    prefix = models.CharField(max_length=32, unique=True, db_index=True)
    secret = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField()

    class Meta:
        ordering = ["-created_at", "id"]
        constraints = [
            # One usable link per participant: concurrent copy/send requests
            # must serialize on this rather than minting two live links.
            models.UniqueConstraint(
                fields=["participant"],
                condition=models.Q(revoked_at__isnull=True),
                name="one_unrevoked_onboarding_token_per_participant",
            ),
        ]

    def __str__(self):
        return f"{self.prefix} ({self.participant.full_name})"

    @property
    def is_expired(self) -> bool:
        return self.expires_at <= timezone.now()

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None and not self.is_expired


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
    has_behind_meter_generation = models.BooleanField(
        default=False,
        help_text=(
            "Generation (e.g. PV) sits behind this meter, so it records only the "
            "surplus fed in and the residual grid draw (net / surplus metering)."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["meter_id"]

    def __str__(self):
        return self.meter_id

    def clean(self):
        if self.has_behind_meter_generation and self.meter_type not in (
            MeteringPointType.BIDIRECTIONAL,
            MeteringPointType.PRODUCTION,
        ):
            raise ValidationError(
                {
                    "has_behind_meter_generation": (
                        "Only bidirectional or production metering points can have "
                        "generation behind the meter."
                    )
                }
            )


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


class ZevAccessRole(models.TextChoices):
    MANAGER = "manager", "Manager"
    VIEWER = "viewer", "Viewer"


class ZevAccessGrant(models.Model):
    """An account's right to manage or view one ZEV, for a dated window (#761).

    Replaces the platform-wide ``zev_owner`` role and the former ``Zev.owner`` as the
    answer to "may this account act on this ZEV" (ADR 0027). A ``manager`` has
    today's owner rights; a ``viewer`` sees everything a manager sees and
    changes nothing. The window is inclusive at both ends, like
    ``MeteringPointAssignment`` (ADR 0001); ``valid_to`` null is open-ended.
    Revoking ends the window yesterday (or deletes a grant that never took
    effect), and a role change ends one grant and opens another, so the rows
    are the history of who could act on the ZEV and when. Read through
    ``zev.access``, never directly by views.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    zev = models.ForeignKey(Zev, on_delete=models.CASCADE, related_name="access_grants")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="zev_grants")
    role = models.CharField(max_length=10, choices=ZevAccessRole.choices)
    valid_from = models.DateField(default=timezone.localdate)
    valid_to = models.DateField(null=True, blank=True)
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="+",
        help_text="Who granted it; empty for grants created by migration or by owning the ZEV.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["zev_id", "role", "user_id", "valid_from", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["zev", "user"],
                condition=models.Q(valid_to__isnull=True),
                name="one_open_zev_grant_per_user",
            ),
            models.CheckConstraint(
                condition=models.Q(valid_to__isnull=True) | models.Q(valid_to__gte=models.F("valid_from")),
                name="zev_grant_valid_window",
            ),
        ]
        indexes = [models.Index(fields=["user", "valid_to"], name="zev_grant_user_valid_to")]

    def __str__(self):
        return f"{self.user} {self.role} {self.zev.name}"


class PartyRole(models.TextChoices):
    ISSUER = "issuer", "Issuer"
    REPRESENTATIVE = "representative", "Representative"
    LANDOWNER = "landowner", "Landowner"


# Roles held by at most one party on any day.
SINGLE_HOLDER_ROLES = (PartyRole.ISSUER, PartyRole.REPRESENTATIVE)

# Roles whose holder manages the ZEV in OpenZEV while it holds them (ADR 0028,
# amended): the party's accounts get manager rights, derived in ``zev.access``
# rather than stored as grants. A landowner gets nothing by its role.
MANAGING_ROLES = (PartyRole.ISSUER, PartyRole.REPRESENTATIVE)


class ZevPartyRole(models.Model):
    """A party's role in a ZEV for a dated window (#761, ADR 0028).

    ``issuer``: whom the ZEV's documents are from (name and address on
    invoices, the QR creditor, the contract's counterparty); ``representative``:
    who acts for the ZEV toward the grid operator; ``landowner``: an owner of
    the land or building. Issuer and representative have at most one holder on
    any day, landowners any number. The window is inclusive at both ends, as in
    ADR 0001; ``valid_to`` null is open-ended. Holding a role grants nothing in
    OpenZEV — accounts act through ``ZevAccessGrant``. Written through
    ``zev.parties``, which keeps the windows of a single-holder role apart.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    zev = models.ForeignKey(Zev, on_delete=models.CASCADE, related_name="party_roles")
    party = models.ForeignKey(Party, on_delete=models.CASCADE, related_name="roles")
    role = models.CharField(max_length=20, choices=PartyRole.choices)
    valid_from = models.DateField()
    valid_to = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["role", "-valid_from", "id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(valid_to__isnull=True) | models.Q(valid_to__gte=models.F("valid_from")),
                name="party_role_window_order",
            ),
            models.UniqueConstraint(
                fields=["zev", "role"],
                condition=models.Q(valid_to__isnull=True, role__in=["issuer", "representative"]),
                name="one_open_single_holder_role",
            ),
            models.UniqueConstraint(
                fields=["zev", "party", "role"],
                condition=models.Q(valid_to__isnull=True),
                name="one_open_role_per_party",
            ),
        ]

    def clean(self):
        super().clean()
        if self.party_id and self.zev_id and self.party.zev_id != self.zev_id:
            raise ValidationError({"party": "The party belongs to another ZEV."})

    def __str__(self):
        return f"{self.party} {self.role} {self.valid_from}–{self.valid_to or ''}"
