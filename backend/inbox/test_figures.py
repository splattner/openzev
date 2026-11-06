"""The live figures an invoice or credit note row carries (spec §5.1, phase 6).

The delivered file is a copy and never changes; what a participant owes and where it
stands does. The row reads those from the invoice or credit, so the pages that used to
list live invoices keep their amounts and payment state without a live endpoint.
"""

from datetime import date
from decimal import Decimal

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from accounts.models import UserRole
from inbox.models import DocumentKind
from inbox.producers import deliver_credit_document, deliver_invoice_document
from inbox.test_helpers import PDF, deliver_operator_document
from invoices.models import Credit, CreditApplication, CreditKind, Invoice, InvoiceReadingImpact, InvoiceStatus
from invoices.workflow import record_payment
from invoices.test_helpers import make_invoice, make_participant, make_zev
from testing.helpers import authenticate as auth, make_user
from zev.models import VatMode

DOCS = "/api/v1/inbox/documents/"


def rows(response):
    assert response.status_code == 200, response.content
    return response.json()["results"]


class FiguresBase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = make_user("inbox_fig_owner", UserRole.USER)
        self.tenant = make_user("inbox_fig_tenant", UserRole.USER)
        self.zev = make_zev(self.owner)
        self.participant = make_participant(self.zev, user=self.tenant)

    def invoice(self, *, status=InvoiceStatus.SENT, total="108.10", applied="0.00", month=1):
        invoice = make_invoice(
            self.zev, self.participant, status, period=(date(2026, month, 1), date(2026, month, 28))
        )
        Invoice.objects.filter(pk=invoice.pk).update(total_chf=Decimal(total), credit_applied_chf=Decimal(applied))
        invoice.refresh_from_db()
        deliver_invoice_document(invoice, PDF)
        return invoice

    def credit(self, amount="50.00"):
        credit = Credit.objects.create(
            zev=self.zev, participant=self.participant, kind=CreditKind.ADJUSTMENT,
            credit_number=f"CN-{Credit.objects.count() + 1:05d}", reason="x", amount_chf=Decimal(amount),
            vat_mode=VatMode.NOT_REGISTERED,
        )
        deliver_credit_document(credit, PDF)
        return credit

    def row_of(self, **match):
        auth(self.client, self.tenant)
        return next(row for row in rows(self.client.get(DOCS)) if all(str(row[k]) == str(v) for k, v in match.items()))


class InvoiceFiguresTests(FiguresBase):
    def test_an_invoice_row_carries_what_is_owed_and_where_it_stands(self):
        invoice = self.invoice(total="108.10", applied="50.00")
        record_payment(invoice, amount_chf=Decimal("10.00"), paid_on=date(2026, 2, 1))

        figures = self.row_of(invoice=invoice.pk)["invoice_figures"]

        self.assertEqual(figures["status"], "sent")
        self.assertEqual(figures["total_chf"], "108.10")
        self.assertEqual(figures["credit_applied_chf"], "50.00")
        self.assertEqual(figures["amount_due_chf"], "58.10")
        self.assertEqual(figures["paid_chf"], "10.00")
        self.assertEqual(figures["outstanding_chf"], "48.10")
        self.assertEqual(figures["open_data_impact_count"], 0)

    def test_the_figures_are_read_live_while_the_file_stays_as_delivered(self):
        invoice = self.invoice()
        before = self.row_of(invoice=invoice.pk)
        record_payment(invoice, amount_chf=Decimal("108.10"), paid_on=date(2026, 2, 1))

        after = self.row_of(invoice=invoice.pk)

        self.assertEqual(before["invoice_figures"]["paid_chf"], "0.00")
        self.assertEqual(after["invoice_figures"]["paid_chf"], "108.10")
        self.assertEqual(after["invoice_figures"]["outstanding_chf"], "0.00")
        self.assertEqual(after["sha256"], before["sha256"])

    def test_a_cancelled_invoice_owes_nothing(self):
        invoice = self.invoice()
        Invoice.objects.filter(pk=invoice.pk).update(status=InvoiceStatus.CANCELLED)

        figures = self.row_of(invoice=invoice.pk)["invoice_figures"]

        self.assertEqual((figures["status"], figures["outstanding_chf"]), ("cancelled", "0.00"))

    def test_open_reading_corrections_are_counted_without_their_evidence(self):
        invoice = self.invoice()
        InvoiceReadingImpact.objects.create(invoice=invoice, evidence={"source": "sdat-import"})
        InvoiceReadingImpact.objects.create(
            invoice=invoice, evidence={}, resolved_at=invoice.created_at, resolution="cancelled"
        )

        row = self.row_of(invoice=invoice.pk)

        self.assertEqual(row["invoice_figures"]["open_data_impact_count"], 1)
        self.assertNotIn("data_impacts", row["invoice_figures"])

    def test_other_kinds_carry_no_figures(self):
        document = deliver_operator_document(self.participant, "Rules")
        row = self.row_of(id=document.pk)
        self.assertEqual((row["invoice_figures"], row["credit_figures"]), (None, None))


class CreditFiguresTests(FiguresBase):
    def test_a_credit_note_row_carries_its_balance(self):
        credit = self.credit("50.00")
        invoice = self.invoice(applied="20.00")
        CreditApplication.objects.create(credit=credit, invoice=invoice, amount_chf=Decimal("20.00"))

        row = self.row_of(kind=DocumentKind.CREDIT_NOTE)

        self.assertIsNone(row["invoice_figures"])
        self.assertEqual(row["credit_figures"], {
            "amount_chf": "50.00", "remaining_chf": "30.00", "status": "open", "source_invoice_number": None,
            "applied_to": [{"invoice_number": invoice.invoice_number, "amount_chf": "20.00"}],
        })

    def test_a_released_application_is_not_listed(self):
        credit = self.credit("50.00")
        invoice = self.invoice()
        CreditApplication.objects.create(
            credit=credit, invoice=invoice, amount_chf=Decimal("20.00"), released_at=invoice.created_at
        )

        figures = self.row_of(kind=DocumentKind.CREDIT_NOTE)["credit_figures"]

        self.assertEqual((figures["remaining_chf"], figures["applied_to"]), ("50.00", []))

    def test_a_note_names_the_invoice_it_corrects(self):
        invoice = self.invoice(status=InvoiceStatus.CANCELLED)
        credit = self.credit()
        Credit.objects.filter(pk=credit.pk).update(source_invoice=invoice)

        figures = self.row_of(kind=DocumentKind.CREDIT_NOTE)["credit_figures"]

        self.assertEqual(figures["source_invoice_number"], invoice.invoice_number)

    def test_the_detail_route_carries_them_too(self):
        credit = self.credit("50.00")
        document = deliver_credit_document(credit, PDF)[0]
        auth(self.client, self.tenant)

        body = self.client.get(f"{DOCS}{document.pk}/").json()

        self.assertEqual(body["credit_figures"]["remaining_chf"], "50.00")


class QueryCountTests(FiguresBase):
    def count_queries(self):
        auth(self.client, self.tenant)
        with CaptureQueriesContext(connection) as queries:
            self.assertEqual(self.client.get(DOCS).status_code, 200)
        return len(queries)

    def test_the_number_of_queries_does_not_grow_with_the_rows(self):
        for month in (1, 2):
            self.invoice(month=month)
            self.credit()
        few = self.count_queries()
        for month in (3, 4, 5, 6):
            self.invoice(month=month)
            self.credit()

        self.assertEqual(self.count_queries(), few)
