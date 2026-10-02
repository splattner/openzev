"""The invoice's copy of who it is from and to (#761, invoices.document_parties).

A draft follows today's data; from approval on the copy is frozen, so an
approved, sent or paid invoice renders the same document whatever changes
later — the owner's address, the ZEV's IBAN, the participant's address.
"""

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from rest_framework.test import APIClient

from accounts.models import UserRole
from testing.helpers import authenticate, make_user
from zev.models import Participant, Zev

from . import workflow
from .document_parties import build_copy, copy_for_render, template_parties
from .models import Invoice, InvoiceStatus
from .pdf import _build_qr_svg, _build_template_context


class InvoiceCopyTestCase(TestCase):
    def setUp(self):
        self.owner = make_user("copy_owner", UserRole.USER)
        self.zev = Zev.objects.create(
            name="Copy ZEV", owner=self.owner, zev_type="vzev", start_date=date(2026, 1, 1),
            invoice_prefix="C", bank_iban="CH9300762011623852957", bank_name="First Bank",
            vat_number="CHE-111.111.111",
        )
        self.owner_row = Participant.objects.create(
            zev=self.zev, user=self.owner, first_name="Olga", last_name="Owner", email="olga@example.com",
            address_line1="Bahnhofstrasse 1", postal_code="8001", city="Zuerich", valid_from=date(2026, 1, 1),
        )
        self.tenant = Participant.objects.create(
            zev=self.zev, first_name="Alice", last_name="Muster", email="alice@example.com",
            address_line1="Musterweg 3", postal_code="3000", city="Bern", valid_from=date(2026, 1, 1),
        )

    def invoice(self, **over):
        fields = dict(
            invoice_number="C-00001", zev=self.zev, participant=self.tenant,
            period_start=date(2026, 1, 1), period_end=date(2026, 1, 31), total_chf=Decimal("42.00"),
        )
        fields.update(over)
        invoice = Invoice.objects.create(**fields)
        invoice.issuer, invoice.recipient = build_copy(invoice).values()
        invoice.save(update_fields=["issuer", "recipient"])
        return invoice

    def change_everything(self):
        """Move the owner, switch the ZEV's bank, and move the tenant."""
        self.owner_row.address_line1 = "Neue Strasse 9"
        self.owner_row.save(update_fields=["address_line1"])
        self.zev.bank_iban = "CH5604835012345678009"
        self.zev.vat_number = "CHE-222.222.222"
        self.zev.save(update_fields=["bank_iban", "vat_number"])
        self.tenant.address_line1 = "Umzugsweg 7"
        self.tenant.save(update_fields=["address_line1"])


class CopyContentTests(InvoiceCopyTestCase):
    def test_the_copy_holds_the_issuer_and_recipient(self):
        copy = build_copy(self.invoice())
        self.assertEqual(copy["issuer"]["name"], "Olga Owner")
        self.assertEqual(copy["issuer"]["address_line1"], "Bahnhofstrasse 1")
        self.assertEqual(copy["issuer"]["iban"], "CH9300762011623852957")
        self.assertEqual(copy["issuer"]["vat_number"], "CHE-111.111.111")
        self.assertIs(copy["issuer"]["from_participant"], True)
        self.assertEqual(copy["recipient"]["name"], "Alice Muster")
        self.assertEqual(copy["recipient"]["address_line1"], "Musterweg 3")

    def test_without_an_owner_row_the_issuer_is_the_zev_name(self):
        self.owner_row.delete()
        copy = build_copy(self.invoice())
        self.assertEqual(copy["issuer"]["name"], "Copy ZEV")
        self.assertIs(copy["issuer"]["from_participant"], False)
        self.assertIsNone(template_parties(self.invoice(invoice_number="C-2"), **copy)["owner_participant"])


class FreezeTests(InvoiceCopyTestCase):
    def test_a_draft_follows_todays_data(self):
        invoice = self.invoice()
        self.change_everything()

        context = _build_template_context(invoice)

        self.assertEqual(context["issuer"]["address_line1"], "Neue Strasse 9")
        self.assertEqual(context["participant"].address_line1, "Umzugsweg 7")
        self.assertEqual(context["zev"].vat_number, "CHE-222.222.222")
        invoice.refresh_from_db()
        self.assertEqual(invoice.recipient["address_line1"], "Umzugsweg 7")

    def test_an_approved_invoice_keeps_its_copy(self):
        invoice = self.invoice()
        self.change_everything()
        workflow.approve_invoice(invoice)
        frozen = (dict(invoice.issuer), dict(invoice.recipient))
        # Approval wrote today's data a last time …
        self.assertEqual(frozen[0]["address_line1"], "Neue Strasse 9")

        # … and nothing after it reaches the document.
        self.owner_row.address_line1 = "Später 1"
        self.owner_row.save(update_fields=["address_line1"])
        self.zev.bank_iban = "CH4431999123000889012"
        self.zev.save(update_fields=["bank_iban"])
        self.tenant.address_line1 = "Später 2"
        self.tenant.save(update_fields=["address_line1"])
        invoice.refresh_from_db()

        context = _build_template_context(invoice)
        self.assertEqual(context["owner_participant"].address_line1, "Neue Strasse 9")
        self.assertEqual(context["participant"].address_line1, "Umzugsweg 7")
        self.assertEqual(context["zev"].bank_iban, "CH5604835012345678009")
        invoice.refresh_from_db()
        self.assertEqual((invoice.issuer, invoice.recipient), frozen)

    def test_a_sent_invoice_renders_the_same_qr_bill(self):
        invoice = self.invoice()
        workflow.approve_invoice(invoice)
        workflow.mark_invoice_sent(invoice)
        self.change_everything()
        invoice.refresh_from_db()

        with patch("qrbill.QRBill") as qrbill_cls:
            bill = MagicMock()
            qrbill_cls.return_value = bill
            bill.as_svg.side_effect = lambda output: output.write(b"<svg/>")
            _build_qr_svg(invoice)

        kwargs = qrbill_cls.call_args.kwargs
        self.assertEqual(kwargs["account"], "CH9300762011623852957")
        self.assertEqual(kwargs["creditor"]["street"], "Bahnhofstrasse 1")
        self.assertEqual(kwargs["debtor"]["street"], "Musterweg 3")

    def test_an_invoice_without_a_copy_gets_one_once(self):
        invoice = Invoice.objects.create(
            invoice_number="C-00009", zev=self.zev, participant=self.tenant, status=InvoiceStatus.SENT,
            period_start=date(2026, 1, 1), period_end=date(2026, 1, 31), total_chf=Decimal("1.00"),
        )
        copy_for_render(invoice)
        invoice.refresh_from_db()
        self.assertEqual(invoice.recipient["address_line1"], "Musterweg 3")

        self.change_everything()
        copy_for_render(invoice)
        invoice.refresh_from_db()
        self.assertEqual(invoice.recipient["address_line1"], "Musterweg 3")

    def test_a_render_racing_an_approval_keeps_the_approved_copy(self):
        invoice = self.invoice()
        stale = Invoice.objects.get(pk=invoice.pk)  # still a draft in memory
        workflow.approve_invoice(invoice)
        self.change_everything()

        issuer, recipient = copy_for_render(stale)

        self.assertEqual(recipient["address_line1"], "Musterweg 3")
        invoice.refresh_from_db()
        self.assertEqual(invoice.recipient["address_line1"], "Musterweg 3")

    def test_the_template_still_reaches_live_fields_the_copy_does_not_hold(self):
        invoice = self.invoice()
        context = _build_template_context(invoice)
        self.assertEqual(context["participant"].pk, self.tenant.pk)
        self.assertEqual(context["zev"].invoice_language, self.zev.invoice_language)


class BatchApprovalTests(InvoiceCopyTestCase):
    def test_approve_all_writes_the_copy(self):
        invoice = self.invoice()
        self.change_everything()
        admin = make_user("copy_admin", UserRole.ADMIN)
        client = APIClient()
        authenticate(client, admin)

        response = client.post("/api/v1/invoices/invoices/approve-all/", {
            "zev_id": str(self.zev.pk), "period_start": "2026-01-01", "period_end": "2026-01-31",
        }, format="json")

        self.assertEqual((response.status_code, response.json()["approved"]), (200, 1))
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, InvoiceStatus.APPROVED)
        self.assertEqual(invoice.recipient["address_line1"], "Umzugsweg 7")
        self.assertEqual(invoice.issuer["iban"], "CH5604835012345678009")


class BackfillMigrationTests(TransactionTestCase):
    # The other apps stay at their latest state; only the invoices app moves.
    BEFORE = [
        ("invoices", "0018_dynamic_source_evidence"),
        ("zev", "0031_zev_access_grant"),
        ("accounts", "0021_collapse_user_role"),
    ]
    AFTER = [("invoices", "0019_invoice_issuer_recipient_copy")]

    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())

    def test_existing_invoices_get_todays_issuer_and_recipient(self):
        old = self.migrate(self.BEFORE)
        owner = make_user("bf_owner")
        zev = old.get_model("zev", "Zev").objects.create(
            name="Backfill ZEV", owner_id=owner.pk, bank_iban="CH9300762011623852957",
        )
        Participant = old.get_model("zev", "Participant")
        Participant.objects.create(
            zev=zev, user_id=owner.pk, first_name="Olga", last_name="Owner", address_line1="Hof 1",
            postal_code="8001", city="Zuerich", valid_from=date(2026, 1, 1),
        )
        tenant = Participant.objects.create(
            zev=zev, title="ms", first_name="Alice", last_name="Muster", address_line1="Weg 3",
            postal_code="3000", city="Bern", valid_from=date(2026, 1, 1),
        )
        old.get_model("invoices", "Invoice").objects.create(
            invoice_number="BF-1", zev=zev, participant=tenant, status="sent",
            period_start=date(2026, 1, 1), period_end=date(2026, 1, 31),
        )

        new = self.migrate(self.AFTER)
        invoice = new.get_model("invoices", "Invoice").objects.get(invoice_number="BF-1")

        self.assertEqual(invoice.issuer["name"], "Olga Owner")
        self.assertEqual(invoice.issuer["iban"], "CH9300762011623852957")
        self.assertEqual(invoice.recipient["name"], "Ms. Alice Muster")
        self.assertEqual(invoice.recipient["address_line1"], "Weg 3")
