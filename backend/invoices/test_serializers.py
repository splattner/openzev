from decimal import Decimal

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from accounts.models import UserRole
from invoices.models import EmailLog, InvoiceItem, InvoiceStatus
from invoices.serializers import InvoiceSerializer
from invoices.test_helpers import make_invoice, make_participant, make_user, make_zev
from tariffs.models import TariffCategory
from testing.factories import assignment_for


class InvoiceDescriptionSerializationTests(TestCase):
    def test_serializer_strips_period_suffix_for_legacy_item_descriptions(self):
        owner = make_user("desc_owner", UserRole.ZEV_OWNER)
        zev = make_zev(owner, "Description ZEV")
        participant = make_participant(zev, first="Des", last="Crip")
        invoice = make_invoice(zev, participant, InvoiceStatus.DRAFT)

        InvoiceItem.objects.create(
            invoice=invoice,
            item_type=InvoiceItem.ItemType.GRID_ENERGY,
            tariff_category=TariffCategory.GRID_FEES,
            description="Grid usage fee 2026-01-01 – 2026-01-31",
            quantity_kwh=Decimal("4.0000"),
            unit="kWh",
            unit_price_chf=Decimal("0.05000"),
            total_chf=Decimal("0.20"),
        )

        serialized = InvoiceSerializer(invoice).data

        self.assertEqual(serialized["items"][0]["description"], "Grid usage fee")


class InvoiceListPayloadTests(TestCase):
    """The list endpoint drops the nested ``items``/``email_logs``; detail
    reads and the period overview keep them (#488).

    The admin invoice view walks every invoice in the instance, so a nested
    array on the list serializer is paid for once per invoice across the whole
    dataset. No list consumer reads them.
    """

    def setUp(self):
        self.owner = make_user("list_payload_owner", UserRole.ZEV_OWNER)
        self.zev = make_zev(self.owner, "List Payload ZEV")
        self.participant = make_participant(self.zev, first="List", last="Payload")
        self.invoice = make_invoice(self.zev, self.participant, InvoiceStatus.DRAFT)
        InvoiceItem.objects.create(
            invoice=self.invoice,
            item_type=InvoiceItem.ItemType.GRID_ENERGY,
            tariff_category=TariffCategory.GRID_FEES,
            description="Grid usage fee",
            quantity_kwh=Decimal("4.0000"),
            unit="kWh",
            unit_price_chf=Decimal("0.05000"),
            total_chf=Decimal("0.20"),
        )
        EmailLog.objects.create(
            invoice=self.invoice,
            recipient="list@example.com",
            subject="Invoice",
            status=EmailLog.Status.SENT,
        )

    def _client(self):
        client = APIClient()
        client.force_authenticate(self.owner)
        return client

    def test_list_omits_the_nested_items_and_email_logs(self):
        resp = self._client().get("/api/v1/invoices/invoices/")

        self.assertEqual(resp.status_code, 200)
        row = resp.json()["results"][0]
        self.assertNotIn("items", row)
        self.assertNotIn("email_logs", row)

    def test_list_keeps_every_field_its_consumers_read(self):
        """AdminInvoicesPage and DashboardPage columns — dropping any of these
        would blank a column rather than just shrink the payload."""
        resp = self._client().get("/api/v1/invoices/invoices/")

        row = resp.json()["results"][0]
        for field in (
            "id",
            "invoice_number",
            "zev_name",
            "participant_name",
            "period_start",
            "period_end",
            "total_chf",
            "status",
            "pdf_url",
            "due_date",
        ):
            self.assertIn(field, row, f"list row lost {field}")

    def test_retrieve_still_returns_items_and_email_logs(self):
        resp = self._client().get(f"/api/v1/invoices/invoices/{self.invoice.pk}/")

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(len(body["items"]), 1)
        self.assertEqual(len(body["email_logs"]), 1)

    def test_period_overview_still_returns_email_logs(self):
        """InvoicePeriodRowsTable renders the email-log count and failure
        badge off this payload, which builds InvoiceSerializer directly."""
        # The overview only lists participants with an assignment active in
        # the period, so give this one a metering point.
        assignment_for(self.participant)

        resp = self._client().get(
            "/api/v1/invoices/invoices/period-overview/",
            {
                "zev_id": str(self.zev.id),
                "period_start": "2026-01-01",
                "period_end": "2026-01-31",
            },
        )

        self.assertEqual(resp.status_code, 200)
        rows = [r for r in resp.json()["rows"] if r["invoice"]]
        self.assertTrue(rows, "expected the period overview to carry an invoice")
        self.assertEqual(len(rows[0]["invoice"]["email_logs"]), 1)
        self.assertEqual(len(rows[0]["invoice"]["items"]), 1)

    def test_list_does_not_query_the_tables_it_no_longer_serializes(self):
        """The prefetch is dropped along with the fields it fed. Asserting on
        the tables touched rather than a query count: the count alone would
        also pass with the prefetch in place, since prefetching is a fixed two
        extra queries regardless of how many invoices come back."""
        with CaptureQueriesContext(connection) as ctx:
            resp = self._client().get("/api/v1/invoices/invoices/")

        self.assertEqual(resp.status_code, 200)
        touched = " ".join(q["sql"] for q in ctx.captured_queries)
        self.assertNotIn("invoices_invoiceitem", touched)
        self.assertNotIn("invoices_emaillog", touched)

    def test_retrieve_still_prefetches_the_nested_relations(self):
        """The detail read renders them, so it must still fetch them — the
        list-only narrowing must not turn detail into an N+1."""
        with CaptureQueriesContext(connection) as ctx:
            resp = self._client().get(f"/api/v1/invoices/invoices/{self.invoice.pk}/")

        self.assertEqual(resp.status_code, 200)
        touched = " ".join(q["sql"] for q in ctx.captured_queries)
        self.assertIn("invoices_invoiceitem", touched)
        self.assertIn("invoices_emaillog", touched)
