"""A populated instance for backup tests.

Not named ``test_*`` so pytest does not collect it. Builds on
``zev.test_transfer.build_populated_zev`` (one of everything the transfer
archive carries) and adds what a *backup* must carry and a transfer must not:
accounts, invoice PDFs, issued contracts, audit rows, and the rows that outlive
a deleted community.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.core.files.base import ContentFile

from accounts.models import FeatureFlag, OAuthProvider, UserRole, VatRate
from audit.models import AuditActionCategory, AuditEvent
from audit.services import record_audit_event
from invoices.models import ContractIssue, EmailLog, Invoice, InvoiceAccessToken
from metering.models import ImportLog
from tariffs.dynamic.models import DynamicPricePoint, DynamicTariffSource
from testing.helpers import make_user
from zev.models import Participant, ParticipantOnboardingToken
from zev.test_transfer import build_populated_zev

PDF_BYTES = b"%PDF-1.4 fake invoice pdf \x00\xff binary tail"


@dataclass
class World:
    admin: object
    owner: object
    member: object
    alpha: object
    beta: object
    alpha_invoice: Invoice


def build_world() -> World:
    admin = make_user("bk_admin", UserRole.ADMIN)
    owner = make_user("bk_owner", UserRole.ZEV_OWNER)
    member = make_user("bk_member", UserRole.PARTICIPANT)

    alpha = build_populated_zev(owner, name="Alpha", meter_prefix="ALPHA")
    beta = build_populated_zev(owner, name="Beta", meter_prefix="BETA")
    owner.preferred_zev = alpha
    owner.save()

    alice = Participant.objects.get(zev=alpha, first_name="Alice")
    alice.user = member
    alice.save()

    invoice = Invoice.objects.get(zev=alpha)
    invoice.pdf_file.save("alpha-invoice.pdf", ContentFile(PDF_BYTES), save=True)
    beta_invoice = Invoice.objects.get(zev=beta)
    beta_invoice.pdf_file.save("beta-invoice.pdf", ContentFile(PDF_BYTES + b"beta"), save=True)

    EmailLog.objects.create(invoice=invoice, recipient="alice@example.com", subject="Invoice", status="sent")
    InvoiceAccessToken.objects.create(invoice=invoice, prefix="acc-alpha", secret="s" * 32)
    ParticipantOnboardingToken.objects.create(participant=alice, prefix="onb-alpha", secret="o" * 32)
    ImportLog.objects.create(zev=alpha, imported_by=owner, source="csv", filename="alpha.csv", rows_total=3)
    ContractIssue.objects.create(
        zev=alpha, participant=alice, version=1, document_number="C-ALPHA-1", language="de",
        context_hash="a" * 64, pdf=b"%PDF-contract-bytes", issued_by=owner,
    )
    record_audit_event(
        action_category=AuditActionCategory.INVOICE, action_type="invoice.sent",
        target_type="invoices.Invoice", target=invoice, target_id=str(invoice.pk),
        summary="Alpha invoice sent.", user=owner, zev=alpha,
    )

    # Instance-wide rows.
    # Rates may not overlap and migrations seed the current one, so use a closed
    # range far in the past.
    VatRate.objects.create(rate=Decimal("0.0650"), valid_from=date(1999, 1, 1), valid_to=date(1999, 12, 31))
    FeatureFlag.objects.get_or_create(name="bk-flag", defaults={"description": "test", "enabled": True})
    OAuthProvider.objects.create(
        name="idp", display_name="IdP", client_id="cid", client_secret="plaintext-client-secret",
        authorization_url="https://idp.test/auth", token_url="https://idp.test/token",
        userinfo_url="https://idp.test/userinfo", redirect_url="https://app.test/cb",
    )
    source = DynamicTariffSource.objects.create(
        label="Grid", url="https://prices.test/v2", api_version="v1_0_5", tariff_type="grid", tariff_name="vario",
    )
    DynamicPricePoint.objects.create(
        source=source, valid_from="2026-01-01T00:00:00Z", valid_to="2026-01-01T00:15:00Z",
        price_chf_per_kwh=Decimal("0.21000"),
    )

    # Rows that outlive a deleted community: no ZEV, but they must survive a
    # restore of the instance.
    record_audit_event(
        action_category=AuditActionCategory.GOVERNANCE, action_type="settings.updated",
        target_type="accounts.AppSettings", summary="Instance-level change.", user=admin,
    )
    orphan = ContractIssue.objects.create(
        zev=beta, participant=Participant.objects.get(zev=beta, first_name="Alice"),
        version=1, document_number="C-ORPHAN-1", language="de", context_hash="b" * 64,
        pdf=b"%PDF-orphaned-contract", issued_by=admin,
    )
    ContractIssue.objects.filter(pk=orphan.pk).update(zev=None, participant=None)
    ImportLog.objects.create(zev=None, imported_by=admin, source="csv", filename="unscoped.csv")

    assert AuditEvent.objects.filter(zev__isnull=True).exists()
    return World(admin=admin, owner=owner, member=member, alpha=alpha, beta=beta, alpha_invoice=invoice)
