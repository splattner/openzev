import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone
from zev.models import Zev, Participant
from tariffs.models import TariffCategory


class InvoiceStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    APPROVED = "approved", "Approved"
    SENT = "sent", "Sent"
    PAID = "paid", "Paid"
    CANCELLED = "cancelled", "Cancelled"


class Invoice(models.Model):
    """A billing document for one participant for one period."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # Unique per ZEV, not globally — see the Meta constraint below.
    invoice_number = models.CharField(max_length=50)
    zev = models.ForeignKey(Zev, on_delete=models.PROTECT, related_name="invoices")
    participant = models.ForeignKey(Participant, on_delete=models.CASCADE, related_name="invoices")
    period_start = models.DateField()
    period_end = models.DateField()
    status = models.CharField(max_length=20, choices=InvoiceStatus.choices, default=InvoiceStatus.DRAFT)
    # Totals (computed by engine)
    total_local_kwh = models.DecimalField(max_digits=12, decimal_places=4, default=0)
    total_grid_kwh = models.DecimalField(max_digits=12, decimal_places=4, default=0)
    total_feed_in_kwh = models.DecimalField(max_digits=12, decimal_places=4, default=0)
    subtotal_chf = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    vat_rate = models.DecimalField(max_digits=5, decimal_places=4, default=0)
    vat_chf = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_chf = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    # Document
    pdf_file = models.FileField(upload_to="invoices/pdf/", blank=True, null=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    due_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-period_end", "participant", "id"]
        constraints = [
            # Numbering is per-ZEV: each community counts its invoices from 1,
            # so the number only needs to be unique within the ZEV.
            models.UniqueConstraint(
                fields=["zev", "invoice_number"],
                name="unique_invoice_number_per_zev",
            ),
        ]

    def __str__(self):
        return f"Invoice {self.invoice_number} - {self.participant.full_name} ({self.period_start} – {self.period_end})"


class InvoiceItem(models.Model):
    """A line item on an invoice."""

    class ItemType(models.TextChoices):
        LOCAL_ENERGY = "local_energy", "Local Energy (Solar)"
        GRID_ENERGY = "grid_energy", "Grid Energy (Netzstrom)"
        FEED_IN = "feed_in", "Feed-in Credit"
        FEE = "fee", "Fee"
        CREDIT = "credit", "Credit"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="items")
    item_type = models.CharField(max_length=20, choices=ItemType.choices)
    tariff_category = models.CharField(max_length=20, choices=TariffCategory.choices, default=TariffCategory.ENERGY)
    description = models.CharField(max_length=500)
    quantity_kwh = models.DecimalField(max_digits=12, decimal_places=4, default=0)
    unit = models.CharField(max_length=20, default="kWh")
    unit_price_chf = models.DecimalField(max_digits=8, decimal_places=5, default=0)
    total_chf = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "item_type", "description"]

    def __str__(self):
        return f"{self.description}: {self.quantity_kwh} {self.unit} × {self.unit_price_chf} = {self.total_chf} CHF"


class PdfTemplate(models.Model):
    """
    Customized PDF template stored in the database.

    The on-disk file is the default.  When a user edits a template via the
    admin UI the content is persisted here so it survives container restarts.
    Deleting the row reverts to the on-disk default.
    """

    template_name = models.CharField(max_length=200, unique=True)
    content = models.TextField()
    # Digest of the on-disk default at save time. When the shipped default
    # changes afterwards, the override becomes "stale" (computed on read,
    # never stored as state) so admins can see a customization is based on
    # an older default. Blank on legacy rows kept as unknown provenance.
    default_digest = models.CharField(max_length=64, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return self.template_name


def contract_issue_rendered_on_default():
    """Default ``ContractIssue.rendered_on``: today in Django's configured
    timezone.

    A named module-level function (not a lambda) so ``makemigrations`` can
    serialize it, and never server-local ``date.today``: the issuance machinery
    resolves every date through Django's timezone, and the model default must
    agree with it.
    """
    return timezone.localdate()


class ContractIssue(models.Model):
    """A frozen participation-contract version as actually issued.

    The contract is not a live render of mutable state: every data change
    (tariff, owner address, notes, VAT rate, template) produces a new numbered
    version, while unchanged re-downloads reuse the stored snapshot — so the
    document a participant signed can always be retrieved exactly as issued.
    ``context_hash`` is the sha256 of the rendered HTML and doubles as the
    change detector; re-downloads reproduce the render at ``rendered_on`` (the
    calendar date the document carries) rather than today, so the passing of
    time alone never mints a new version. Snapshots are an immutable archive:
    both foreign keys are ``SET_NULL``, so deleting a participant or ZEV
    retains the issued documents (``document_number`` + audit log keep the
    traceability).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    zev = models.ForeignKey(
        Zev, on_delete=models.SET_NULL, null=True, related_name="contract_issues"
    )
    participant = models.ForeignKey(
        Participant, on_delete=models.SET_NULL, null=True, related_name="contract_issues"
    )
    version = models.PositiveIntegerField()
    document_number = models.CharField(max_length=32)
    language = models.CharField(max_length=2)
    rendered_on = models.DateField(
        default=contract_issue_rendered_on_default,
        help_text="Calendar date the document was rendered with (its issue date)",
    )
    context_hash = models.CharField(max_length=64, help_text="sha256 of the rendered HTML")
    pdf = models.BinaryField(editable=False)
    issued_at = models.DateTimeField(auto_now_add=True)
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )

    class Meta:
        ordering = ["-version"]
        constraints = [
            models.UniqueConstraint(
                fields=["participant", "version"], name="uniq_contract_issue_participant_version"
            ),
        ]

    def save(self, *args, **kwargs):
        # ``zev`` is a denormalized copy of ``participant.zev`` (cascade and
        # per-ZEV queries without a join); derive it so the two never disagree.
        # Archived rows (participant deleted, SET_NULL) keep their stored zev.
        if self.participant_id is not None:
            self.zev = self.participant.zev
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.document_number} v{self.version} ({self.participant_id})"


# ── Email template defaults ─────────────────────────────────────────────

DEFAULT_INVOICE_EMAIL_SUBJECT = "Invoice {invoice_number} – {zev_name}"
DEFAULT_INVOICE_EMAIL_BODY = (
    "Dear {participant_name},\n\n"
    "Please find your energy invoice for the period "
    "{period_start} to {period_end} attached.\n\n"
    "Total: CHF {total_chf}\n\n"
    "Kind regards,\n{zev_name}"
)

DEFAULT_INVITATION_EMAIL_SUBJECT = "Invitation to OpenZEV for {zev_name}"
DEFAULT_INVITATION_EMAIL_BODY = (
    "Hello {participant_name},\n\n"
    "{inviter_name} invited you to access your OpenZEV participant account for {zev_name}.\n\n"
    "Login username: {username}\n"
    "Temporary password: {temporary_password}\n\n"
    "Please sign in and change your password after your first login.\n\n"
    "Best regards,\nOpenZEV"
)

DEFAULT_VERIFICATION_EMAIL_SUBJECT = "Verify your OpenZEV account"
DEFAULT_VERIFICATION_EMAIL_BODY = (
    "Hello,\n\n"
    "Thank you for registering with OpenZEV.\n"
    "Please verify your email address by clicking the link below:\n\n"
    "{verify_url}\n\n"
    "This link is valid for 24 hours.\n\n"
    "If you did not register for OpenZEV, please ignore this email.\n\n"
    "Best regards,\nOpenZEV"
)

EMAIL_TEMPLATE_DEFAULTS = {
    "invoice_email": {
        "subject": DEFAULT_INVOICE_EMAIL_SUBJECT,
        "body": DEFAULT_INVOICE_EMAIL_BODY,
    },
    "participant_invitation": {
        "subject": DEFAULT_INVITATION_EMAIL_SUBJECT,
        "body": DEFAULT_INVITATION_EMAIL_BODY,
    },
    "email_verification": {
        "subject": DEFAULT_VERIFICATION_EMAIL_SUBJECT,
        "body": DEFAULT_VERIFICATION_EMAIL_BODY,
    },
}


class EmailTemplate(models.Model):
    """
    Admin-customizable email template stored in the database.

    Each template_key maps to a specific email type (invoice_email,
    participant_invitation, email_verification).  Hardcoded defaults
    are defined in EMAIL_TEMPLATE_DEFAULTS.  Deleting the DB row
    reverts to the hardcoded default.
    """

    template_key = models.CharField(max_length=100, unique=True)
    subject = models.CharField(max_length=500)
    body = models.TextField()
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return self.template_key


class EmailLog(models.Model):
    """Audit log for invoice emails."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="email_logs")
    recipient = models.EmailField()
    subject = models.CharField(max_length=500)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    error_message = models.TextField(blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
