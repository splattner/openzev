import uuid
from django.db import models
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
    invoice_number = models.CharField(max_length=50, unique=True)
    zev = models.ForeignKey(Zev, on_delete=models.PROTECT, related_name="invoices")
    participant = models.ForeignKey(Participant, on_delete=models.PROTECT, related_name="invoices")
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
        ordering = ["-period_end", "participant"]

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


class EmailLog(models.Model):
    """Audit log for invoice emails."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="email_logs")
    recipient = models.EmailField()
    subject = models.CharField(max_length=500)
    status = models.CharField(max_length=20, default="pending")  # pending / sent / failed
    error_message = models.TextField(blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
