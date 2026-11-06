"""The live invoice endpoints are for managers and admins (#862, phase 6).

A participant reads what was delivered to them from the document inbox, so the
invoice list is empty for them and detail, PDF, annual statement and financial
summary answer 404, whatever the invoice's status and whether or not they still
take part. Owners and admins are not narrowed. Which invoices reach the inbox is
tested in ``inbox`` (an invoice is delivered when it is sent, #861).
"""

from datetime import date
from unittest import mock

from django.core.files.base import ContentFile
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import UserRole
from invoices.annual_statement import generate_annual_statement_pdf
from invoices.models import Invoice, InvoiceStatus
from invoices.test_helpers import make_invoice, make_participant, make_zev
from zev.models import Participant
from testing.helpers import authenticate as auth, make_user

INVOICES = "/api/v1/invoices/invoices/"
ANNUAL_STATEMENT = "/api/v1/invoices/invoices/annual-statement/"
FINANCIAL_SUMMARY = "/api/v1/invoices/invoices/financial-summary/"


class ParticipantInvoiceVisibilityTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = make_user("vis_owner", UserRole.USER)
        self.tenant = make_user("vis_tenant", UserRole.USER)
        self.zev = make_zev(self.owner)
        self.participant = make_participant(self.zev, user=self.tenant)
        self.draft = self._invoice(InvoiceStatus.DRAFT, month=1)
        self.approved = self._invoice(InvoiceStatus.APPROVED, month=2)
        self.sent = self._invoice(InvoiceStatus.SENT, month=3, sent=True)
        self.paid = self._invoice(InvoiceStatus.PAID, month=4, sent=True)
        self.cancelled_after_sending = self._invoice(InvoiceStatus.CANCELLED, month=5, sent=True)
        self.cancelled_draft = self._invoice(InvoiceStatus.CANCELLED, month=6)

    def _invoice(self, inv_status, *, month, sent=False):
        invoice = make_invoice(
            self.zev, self.participant, inv_status=inv_status,
            period=(date(2026, month, 1), date(2026, month, 28)),
        )
        if sent:
            invoice.sent_at = timezone.now()
            invoice.save(update_fields=["sent_at"])
        return invoice

    def _listed_ids(self, user):
        auth(self.client, user)
        response = self.client.get(INVOICES)
        self.assertEqual(response.status_code, 200, response.content)
        return {row["id"] for row in response.json()["results"]}

    def test_participant_list_is_empty(self):
        self.assertEqual(self._listed_ids(self.tenant), set())

    def test_owner_list_is_not_narrowed(self):
        self.assertEqual(
            self._listed_ids(self.owner),
            {str(invoice.id) for invoice in Invoice.objects.filter(zev=self.zev)},
        )

    def test_participant_cannot_open_any_invoice(self):
        auth(self.client, self.tenant)
        for invoice in (self.draft, self.approved, self.sent, self.paid, self.cancelled_after_sending):
            with self.subTest(status=invoice.status):
                self.assertEqual(self.client.get(f"{INVOICES}{invoice.id}/").status_code, 404)

    def test_participant_cannot_download_a_sent_invoice_pdf(self):
        self.sent.pdf_file.save("sent.pdf", ContentFile(b"%PDF-1.4 sent"), save=True)
        auth(self.client, self.tenant)
        self.assertEqual(self.client.get(f"{INVOICES}{self.sent.id}/pdf/").status_code, 404)

    def test_a_former_participant_reaches_nothing_either(self):
        Participant.objects.filter(pk=self.participant.pk).update(valid_to=date(2026, 4, 30))
        self.assertEqual(self._listed_ids(self.tenant), set())
        auth(self.client, self.tenant)
        self.assertEqual(self.client.get(f"{INVOICES}{self.sent.id}/").status_code, 404)

    def test_the_owner_still_opens_and_downloads(self):
        self.sent.pdf_file.save("sent.pdf", ContentFile(b"%PDF-1.4 sent"), save=True)
        auth(self.client, self.owner)
        self.assertEqual(self.client.get(f"{INVOICES}{self.sent.id}/").status_code, 200)
        self.assertEqual(self.client.get(f"{INVOICES}{self.sent.id}/pdf/").status_code, 200)

    def test_a_manager_who_rents_elsewhere_gets_no_live_invoice_there(self):
        other_owner = make_user("vis_other_owner", UserRole.USER)
        other_zev = make_zev(other_owner, "Elsewhere")
        rented = make_invoice(other_zev, make_participant(other_zev, user=self.owner), inv_status=InvoiceStatus.SENT)
        Invoice.objects.filter(pk=rented.pk).update(sent_at=timezone.now())
        self.assertNotIn(str(rented.id), self._listed_ids(self.owner))
        auth(self.client, self.owner)
        self.assertEqual(self.client.get(f"{INVOICES}{rented.id}/").status_code, 404)


class ParticipantAnnualStatementTests(TestCase):
    def setUp(self):
        self.owner = make_user("stmt_owner", UserRole.USER)
        self.tenant = make_user("stmt_tenant", UserRole.USER)
        self.zev = make_zev(self.owner)
        self.participant = make_participant(self.zev, user=self.tenant)
        self.draft = make_invoice(
            self.zev, self.participant, inv_status=InvoiceStatus.DRAFT,
            period=(date(2026, 1, 1), date(2026, 1, 31)),
        )
        self.sent = make_invoice(
            self.zev, self.participant, inv_status=InvoiceStatus.SENT,
            period=(date(2026, 2, 1), date(2026, 2, 28)),
        )

    def _rendered_invoice_numbers(self, **kwargs):
        with mock.patch("invoices.annual_statement._render_template", return_value="<html></html>") as render, \
                mock.patch("invoices.annual_statement.render_pdf", return_value=b"%PDF-stub"):
            generate_annual_statement_pdf(self.participant, self.zev, 2026, **kwargs)
        context = render.call_args.args[1]
        return {row["invoice_number"] for row in context["invoices"]}

    def test_sent_only_leaves_out_unsent_invoices(self):
        self.assertEqual(self._rendered_invoice_numbers(sent_only=True), {self.sent.invoice_number})

    def test_default_keeps_every_issued_invoice(self):
        # The owner's statement counts what was billed (#388): approved and
        # sent invoices, not the draft still being worked on.
        approved = make_invoice(
            self.zev, self.participant, inv_status=InvoiceStatus.APPROVED,
            period=(date(2026, 3, 1), date(2026, 3, 31)),
        )
        self.assertEqual(
            self._rendered_invoice_numbers(),
            {approved.invoice_number, self.sent.invoice_number},
        )

    def test_participant_download_is_refused_and_renders_nothing(self):
        client = APIClient()
        auth(client, self.tenant)
        with mock.patch("invoices.views_reports.generate_annual_statement_pdf") as generate:
            response = client.get(ANNUAL_STATEMENT, {"year": 2026})
        self.assertEqual(response.status_code, 404)
        generate.assert_not_called()

    def test_participant_cannot_name_ids_to_get_around_it(self):
        client = APIClient()
        auth(client, self.tenant)
        with mock.patch("invoices.views_reports.generate_annual_statement_pdf") as generate:
            response = client.get(
                ANNUAL_STATEMENT,
                {"year": 2026, "zev_id": str(self.zev.id), "participant_id": str(self.participant.id)},
            )
        self.assertEqual(response.status_code, 404)
        generate.assert_not_called()

    def test_participant_financial_summary_is_refused(self):
        client = APIClient()
        auth(client, self.tenant)
        with mock.patch("invoices.views_reports.generate_financial_summary_pdf") as generate:
            response = client.get(FINANCIAL_SUMMARY, {"year": 2026})
        self.assertEqual(response.status_code, 404)
        generate.assert_not_called()

    def test_owner_download_is_not_narrowed(self):
        client = APIClient()
        auth(client, self.owner)
        with mock.patch(
            "invoices.views_reports.generate_annual_statement_pdf", return_value=b"%PDF-stub"
        ) as generate:
            response = client.get(
                ANNUAL_STATEMENT,
                {"year": 2026, "zev_id": str(self.zev.id), "participant_id": str(self.participant.id)},
            )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("sent_only", generate.call_args.kwargs)
