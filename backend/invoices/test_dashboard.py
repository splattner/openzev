"""Coverage for the admin dashboard statistics endpoint.

The endpoint is old but had no tests at all — the one test whose name mentions
it (``test_end_to_end_billing_generation_workflow_and_dashboard_consistency``)
never actually calls it. That mattered, because admin-only access rested
entirely on a hand-written ``if not request.user.is_admin`` and this endpoint
reports across *every* tenant: a ZEV owner reaching it would see every other
owner's revenue.
"""

from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import UserRole
from testing.helpers import authenticate as auth, make_user

from .models import EmailLog, InvoiceStatus
from .test_helpers import make_invoice, make_participant, make_zev

URL = "/api/v1/invoices/invoices/dashboard/"


class DashboardPermissionTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_admin_is_allowed(self):
        auth(self.client, make_user("dash_admin", UserRole.ADMIN))

        self.assertEqual(self.client.get(URL).status_code, 200)

    def test_non_admins_are_refused(self):
        """This endpoint aggregates across all tenants, so the permission check
        is the only thing keeping one owner out of another owner's figures."""
        for role in (UserRole.ZEV_OWNER, UserRole.PARTICIPANT):
            with self.subTest(role=role):
                auth(self.client, make_user(f"dash_{role}", role))
                self.assertEqual(self.client.get(URL).status_code, 403)

    def test_anonymous_is_refused(self):
        self.client.credentials()

        self.assertEqual(self.client.get(URL).status_code, 401)


class DashboardStatisticsTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = make_user("dash_stats_owner", UserRole.ZEV_OWNER)
        self.zev = make_zev(self.owner, "Dash ZEV")
        self.participant = make_participant(self.zev, first="Dana")
        auth(self.client, make_user("dash_stats_admin", UserRole.ADMIN))

    def _get(self):
        resp = self.client.get(URL)
        self.assertEqual(resp.status_code, 200)
        return resp.data

    def test_empty_database_reports_zeroes_not_nulls(self):
        data = self._get()

        self.assertEqual(data["invoices"]["draft"], 0)
        self.assertEqual(data["invoices"]["total_revenue"], 0)
        self.assertEqual(data["emails"]["total"], 0)
        self.assertEqual(data["recent_invoices"], [])

    def test_counts_are_reported_per_status(self):
        for st in (InvoiceStatus.DRAFT, InvoiceStatus.DRAFT, InvoiceStatus.APPROVED,
                   InvoiceStatus.SENT, InvoiceStatus.PAID):
            make_invoice(self.zev, self.participant, st)

        data = self._get()

        self.assertEqual(data["invoices"]["draft"], 2)
        self.assertEqual(data["invoices"]["approved"], 1)
        self.assertEqual(data["invoices"]["sent"], 1)
        self.assertEqual(data["invoices"]["paid"], 1)

    def test_revenue_counts_sent_and_paid_only(self):
        make_invoice(self.zev, self.participant, InvoiceStatus.SENT)
        make_invoice(self.zev, self.participant, InvoiceStatus.PAID)
        make_invoice(self.zev, self.participant, InvoiceStatus.DRAFT)
        make_invoice(self.zev, self.participant, InvoiceStatus.CANCELLED)
        per_invoice = float(make_invoice(self.zev, self.participant, InvoiceStatus.DRAFT).total_chf)

        data = self._get()

        self.assertEqual(data["invoices"]["total_revenue"], per_invoice * 2)

    def test_zev_and_participant_totals(self):
        make_participant(self.zev, first="Second")

        data = self._get()

        self.assertEqual(data["zevs"]["total"], 1)
        self.assertEqual(data["participants"]["total"], 2)

    def test_email_statistics_are_grouped_by_status(self):
        invoice = make_invoice(self.zev, self.participant)
        for st in (EmailLog.Status.SENT, EmailLog.Status.SENT,
                   EmailLog.Status.FAILED, EmailLog.Status.PENDING):
            EmailLog.objects.create(invoice=invoice, recipient="x@example.com", status=st)

        data = self._get()

        self.assertEqual(data["emails"], {"total": 4, "sent": 2, "failed": 1, "pending": 1})

    def test_recent_invoices_are_capped_at_ten_newest_first(self):
        created = [make_invoice(self.zev, self.participant) for _ in range(12)]

        data = self._get()

        self.assertEqual(len(data["recent_invoices"]), 10)
        self.assertEqual(data["recent_invoices"][0]["invoice_number"], created[-1].invoice_number)

    def test_recent_invoice_rows_carry_denormalised_names(self):
        invoice = make_invoice(self.zev, self.participant, InvoiceStatus.PAID)

        row = self._get()["recent_invoices"][0]

        self.assertEqual(row["invoice_number"], invoice.invoice_number)
        self.assertEqual(row["participant_name"], self.participant.full_name)
        self.assertEqual(row["zev_name"], self.zev.name)
        self.assertEqual(row["status"], InvoiceStatus.PAID)
        self.assertEqual(Decimal(str(row["total_chf"])), invoice.total_chf)

    def test_statistics_span_every_tenant(self):
        other_zev = make_zev(make_user("dash_other_owner", UserRole.ZEV_OWNER), "Other ZEV")
        make_invoice(other_zev, make_participant(other_zev, first="Otto"), InvoiceStatus.DRAFT)
        make_invoice(self.zev, self.participant, InvoiceStatus.DRAFT)

        data = self._get()

        self.assertEqual(data["zevs"]["total"], 2)
        self.assertEqual(data["invoices"]["draft"], 2)

    def test_cancelled_invoices_are_counted(self):
        """The aggregate used to run over a queryset that had already excluded
        cancelled invoices, so this count was unconditionally 0."""
        make_invoice(self.zev, self.participant, InvoiceStatus.CANCELLED)
        make_invoice(self.zev, self.participant, InvoiceStatus.CANCELLED)
        make_invoice(self.zev, self.participant, InvoiceStatus.DRAFT)

        data = self._get()

        self.assertEqual(data["invoices"]["cancelled"], 2)
        self.assertEqual(data["invoices"]["draft"], 1)
