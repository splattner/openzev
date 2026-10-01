"""A participant sees an invoice only once it has been sent to them (#861).

Drafts are the operator's working state and approved invoices are final but
undelivered, so neither reaches the participant through the invoice list,
detail, PDF download or their own annual statement. Owners and admins are not
narrowed.
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
from testing.helpers import authenticate as auth, make_user

INVOICES = "/api/v1/invoices/invoices/"
ANNUAL_STATEMENT = "/api/v1/invoices/invoices/annual-statement/"


class ParticipantInvoiceVisibilityTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = make_user("vis_owner", UserRole.ZEV_OWNER)
        self.tenant = make_user("vis_tenant", UserRole.PARTICIPANT)
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

    def test_participant_list_shows_only_sent_invoices(self):
        self.assertEqual(
            self._listed_ids(self.tenant),
            {str(self.sent.id), str(self.paid.id), str(self.cancelled_after_sending.id)},
        )

    def test_owner_list_is_not_narrowed(self):
        self.assertEqual(
            self._listed_ids(self.owner),
            {str(invoice.id) for invoice in Invoice.objects.filter(zev=self.zev)},
        )

    def test_participant_cannot_open_an_unsent_invoice(self):
        auth(self.client, self.tenant)
        for invoice in (self.draft, self.approved, self.cancelled_draft):
            with self.subTest(status=invoice.status):
                response = self.client.get(f"{INVOICES}{invoice.id}/")
                self.assertEqual(response.status_code, 404)

    def test_participant_opens_a_sent_invoice(self):
        auth(self.client, self.tenant)
        response = self.client.get(f"{INVOICES}{self.sent.id}/")
        self.assertEqual(response.status_code, 200, response.content)

    def test_participant_cannot_download_an_unsent_pdf(self):
        self.draft.pdf_file.save("draft.pdf", ContentFile(b"%PDF-1.4 draft"), save=True)
        auth(self.client, self.tenant)
        response = self.client.get(f"{INVOICES}{self.draft.id}/pdf/")
        self.assertEqual(response.status_code, 404)

    def test_sent_status_without_sent_at_stays_visible(self):
        # A sent/paid row whose sent_at was never stamped (older data) must not
        # disappear from the participant's list.
        Invoice.objects.filter(pk__in=[self.sent.pk, self.paid.pk]).update(sent_at=None)
        listed = self._listed_ids(self.tenant)
        self.assertIn(str(self.sent.id), listed)
        self.assertIn(str(self.paid.id), listed)


class ParticipantAnnualStatementSentOnlyTests(TestCase):
    def setUp(self):
        self.owner = make_user("stmt_owner", UserRole.ZEV_OWNER)
        self.tenant = make_user("stmt_tenant", UserRole.PARTICIPANT)
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

    def test_default_keeps_every_uncancelled_invoice(self):
        self.assertEqual(
            self._rendered_invoice_numbers(),
            {self.draft.invoice_number, self.sent.invoice_number},
        )

    def test_participant_download_asks_for_sent_only(self):
        client = APIClient()
        auth(client, self.tenant)
        with mock.patch(
            "invoices.views_reports.generate_annual_statement_pdf", return_value=b"%PDF-stub"
        ) as generate:
            response = client.get(ANNUAL_STATEMENT, {"year": 2026})
        self.assertEqual(response.status_code, 200)
        self.assertIs(generate.call_args.kwargs["sent_only"], True)

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
        self.assertIs(generate.call_args.kwargs["sent_only"], False)
