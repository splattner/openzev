"""The participant document inbox (SPEC-2026-11-participant-document-inbox, ADR 0045).

A ``DeliveredDocument`` is a fact: this file reached this participant. Its
content never changes; only ``superseded_*`` and ``withdrawn_*`` are set later.
It is addressed to the participant row, not to an account, so it is there
before anyone logs in and visible as soon as an account is linked.
"""

import io
import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone


class DocumentKind(models.TextChoices):
    INVOICE = "invoice", "Invoice"
    CONTRACT = "contract", "Participation contract"
    ANNUAL_STATEMENT = "annual_statement", "Annual statement"
    FINANCIAL_SUMMARY = "financial_summary", "Financial summary"
    TARIFF_OVERVIEW = "tariff_overview", "Tariff overview"
    CREDIT_NOTE = "credit_note", "Credit note"
    OPERATOR = "operator", "Operator document"


# Kinds that exist once per participant and period: delivering one again
# supersedes the earlier one instead of adding a duplicate.
REPORT_KINDS = (
    DocumentKind.ANNUAL_STATEMENT,
    DocumentKind.FINANCIAL_SUMMARY,
    DocumentKind.TARIFF_OVERVIEW,
)
# The ones keyed by a period (a year); the tariff overview is keyed by participant alone.
PERIOD_REPORT_KINDS = (DocumentKind.ANNUAL_STATEMENT, DocumentKind.FINANCIAL_SUMMARY)


def inbox_upload_to(instance, filename):
    """``inbox/documents/<zev id>/<uuid>.pdf``: a name nobody chooses, so an upload
    can neither collide with nor overwrite another document."""
    return f"inbox/documents/{instance.zev_id or 'none'}/{uuid.uuid4()}.pdf"


class DeliveredDocument(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # A denormalised copy of ``participant.zev`` (see ``save``). CASCADE, unlike
    # ``ContractIssue.zev``: once the ZEV is purged nobody is left who could
    # reach the document, and the purge is meant to erase what is under a ZEV.
    zev = models.ForeignKey("zev.Zev", on_delete=models.CASCADE, related_name="delivered_documents")
    # SET_NULL, never CASCADE: removing a participant must not remove what was
    # delivered to them (#793).
    participant = models.ForeignKey(
        "zev.Participant", on_delete=models.SET_NULL, null=True, related_name="delivered_documents"
    )
    kind = models.CharField(max_length=32, choices=DocumentKind.choices)
    title = models.CharField(max_length=200)
    document_number = models.CharField(max_length=64, blank=True, default="")
    period_start = models.DateField(null=True, blank=True)
    period_end = models.DateField(null=True, blank=True)
    # The stored copy. Empty only for a contract held by reference, whose bytes stay in
    # ``ContractIssue.pdf``.
    file = models.FileField(upload_to=inbox_upload_to, blank=True, max_length=255)
    file_name = models.CharField(max_length=255, blank=True, default="")
    content_type = models.CharField(max_length=100, default="application/pdf")
    size_bytes = models.PositiveBigIntegerField(null=True, blank=True)
    sha256 = models.CharField(max_length=64, blank=True, default="")
    invoice = models.ForeignKey(
        "invoices.Invoice", on_delete=models.SET_NULL, null=True, blank=True, related_name="delivered_documents"
    )
    # PROTECT: a contract row has no file of its own, so a vanished issue would
    # leave a document with no body (and break ``inbox_document_has_one_body``).
    contract_issue = models.ForeignKey(
        "invoices.ContractIssue", on_delete=models.PROTECT, null=True, blank=True,
        related_name="delivered_documents",
    )
    delivered_at = models.DateTimeField(default=timezone.now)
    delivered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    batch_id = models.UUIDField(null=True, blank=True, db_index=True)
    superseded_at = models.DateTimeField(null=True, blank=True)
    superseded_by = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="supersedes"
    )
    withdrawn_at = models.DateTimeField(null=True, blank=True)
    withdrawn_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        ordering = ["-delivered_at", "id"]
        indexes = [
            models.Index(fields=["participant", "-delivered_at"], name="inbox_doc_participant"),
            models.Index(fields=["zev", "kind", "-delivered_at"], name="inbox_doc_zev_kind"),
        ]
        constraints = [
            # A document has exactly one body: a contract held by reference to its
            # ``ContractIssue``, or a file of its own. A contract arriving through a
            # transfer archive has no issue to point at, so it holds a file.
            models.CheckConstraint(
                condition=Q(kind="contract", contract_issue__isnull=False, file="")
                | (Q(contract_issue__isnull=True) & ~Q(file="")),
                name="inbox_document_has_one_body",
            ),
            models.UniqueConstraint(
                fields=["invoice"], condition=Q(invoice__isnull=False), name="inbox_one_per_invoice"
            ),
            # A credit note is keyed by its number, which is unique per ZEV: there is
            # no foreign key to the credit, so the row survives it like any other fact.
            models.UniqueConstraint(
                fields=["zev", "document_number"],
                condition=Q(kind=DocumentKind.CREDIT_NOTE),
                name="inbox_one_per_credit_note",
            ),
            models.UniqueConstraint(
                fields=["contract_issue", "participant"],
                condition=Q(contract_issue__isnull=False),
                name="inbox_one_per_contract_issue",
            ),
            models.UniqueConstraint(
                fields=["participant", "kind", "period_start", "period_end"],
                condition=Q(kind__in=[k.value for k in PERIOD_REPORT_KINDS], superseded_at__isnull=True),
                name="inbox_one_current_report",
            ),
            # NULL periods compare as distinct, so the overview needs its own key.
            models.UniqueConstraint(
                fields=["participant", "kind"],
                condition=Q(kind=DocumentKind.TARIFF_OVERVIEW, superseded_at__isnull=True),
                name="inbox_one_current_tariff_overview",
            ),
        ]

    def save(self, *args, **kwargs):
        # ``zev`` is derived so the two never disagree.
        if self.participant_id is not None:
            self.zev = self.participant.zev
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.kind} {self.title} → {self.participant_id}"

    @property
    def is_current(self) -> bool:
        return self.superseded_at is None and self.withdrawn_at is None

    def open_file(self):
        """A binary file object over the delivered bytes."""
        if self.contract_issue_id is not None:
            return io.BytesIO(bytes(self.contract_issue.pdf))
        return self.file.open("rb")
