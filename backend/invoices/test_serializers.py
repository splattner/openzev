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
        self.log = EmailLog.objects.create(
            invoice=self.invoice,
            recipient="list@example.com",
            subject="Invoice",
            status=EmailLog.Status.SENT,
        )
        # A second invoice with **no** email logs: an annotated null must not
        # be mistaken for a missing annotation (that would send each such
        # invoice back to the database — the per-row N+1 this shape exists to
        # avoid).
        self.no_log_participant = make_participant(self.zev, first="No", last="Logs")
        self.no_log_invoice = make_invoice(
            self.zev, self.no_log_participant, InvoiceStatus.SENT
        )

    def _client(self):
        client = APIClient()
        client.force_authenticate(self.owner)
        return client

    @staticmethod
    def _standalone_email_log_queries(captured) -> list[str]:
        """Queries reading ``invoices_emaillog`` outside the list annotation.

        The annotation is part of the invoice SELECT (… AS
        "last_email_status"); any other query touching the email-log table is
        the per-row fallback firing. Matching is case- and quote-insensitive
        so a renamed/uppercased SQL dialect cannot silently pass."""
        return [
            q["sql"]
            for q in captured
            if "INVOICES_EMAILLOG" in q["sql"].upper()
            and "LAST_EMAIL_STATUS" not in q["sql"].upper()
        ]

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
        by_participant = {r["participant_name"]: r["invoice"] for r in rows}
        # The no-log invoice row exists too: an invoice stays reachable even
        # without its own assignment (attention links land on a non-empty
        # table), so the row with the log is found by participant, not order.
        self.assertEqual(by_participant[self.participant.full_name]["email_logs"][0]["status"], "sent")
        self.assertEqual(len(by_participant[self.participant.full_name]["items"]), 1)
        self.assertIsNone(by_participant[self.no_log_participant.full_name]["last_email_status"])

    def test_list_does_not_query_the_tables_it_no_longer_serializes(self):
        """The prefetch is dropped along with the fields it fed. Asserting on
        the tables touched rather than a query count: the count alone would
        also pass with the prefetch in place, since prefetching is a fixed two
        extra queries regardless of how many invoices come back.

        Since the nav-regroup readiness work the list does carry
        ``last_email_status``, but via a subquery annotation inside the one
        SELECT — never a separate per-row query. The captured SQL must not
        contain a standalone FROM invoices_emaillog outside the subselect,
        and the page must stay at a constant query count when rows grow."""
        with CaptureQueriesContext(connection) as ctx:
            resp = self._client().get("/api/v1/invoices/invoices/")

        self.assertEqual(resp.status_code, 200)
        touched = " ".join(q["sql"] for q in ctx.captured_queries)
        self.assertNotIn("invoices_invoiceitem", touched)
        # The annotation rides inside the invoice SELECT (… AS "last_email_status");
        # a prefetch would instead show as its own query with FROM invoices_emaillog.
        subquery = "LAST_EMAIL_STATUS" in touched.upper()
        standalone = self._standalone_email_log_queries(ctx.captured_queries)
        self.assertTrue(
            subquery,
            "list must annotate last_email_status instead of reading email logs separately",
        )
        self.assertEqual(
            standalone,
            [],
            "list must not query invoices_emaillog outside the annotation subquery",
        )
        # Phase 3 (email-retry tab): the same subquery also feeds
        # last_email_log_id, so it must ride the same single SELECT too.
        self.assertIn(
            'AS "last_email_log_id"',
            touched,
            "list must annotate last_email_log_id in the same invoice SELECT",
        )
        # Rows are ordered by (-period_end, participant), so the logged and
        # the no-log invoice can land in either order — find them by id, not
        # by position (the period-overview test above pins the same rule).
        by_id = {r["id"]: r for r in resp.data["results"]}
        self.assertEqual(
            by_id[str(self.invoice.id)]["last_email_log_id"], str(self.log.pk)
        )
        self.assertIsNone(by_id[str(self.no_log_invoice.id)]["last_email_log_id"])

    def test_annotated_null_row_stays_constant_query_count(self):
        """Invoices without email logs must not trigger a per-row fallback
        query: the annotated null is a value, not a missing annotation. The
        page costs the same number of queries whether it carries one invoice
        without logs or many (regression: the fallback fired per no-log
        invoice, an N+1 that only shows on mixed lists)."""
        def capture():
            with CaptureQueriesContext(connection) as ctx:
                resp = self._client().get("/api/v1/invoices/invoices/")
            self.assertEqual(resp.status_code, 200)
            rows = resp.json()["results"]
            self.assertEqual(
                self._standalone_email_log_queries(ctx.captured_queries),
                [],
                "no-log invoices must not trigger standalone email-log queries",
            )
            return len(ctx.captured_queries), rows

        base_queries, rows = capture()
        by_id = {row["id"]: row for row in rows}
        self.assertEqual(
            by_id[str(self.no_log_invoice.id)]["last_email_status"], None
        )
        self.assertEqual(by_id[str(self.invoice.id)]["last_email_status"], "sent")

        # Grow the number of no-log invoices — the query count must not move.
        for i in range(3):
            participant = make_participant(self.zev, first=f"Grow{i}", last="Logs")
            make_invoice(self.zev, participant, InvoiceStatus.SENT)
        grown_queries, _ = capture()
        self.assertEqual(grown_queries, base_queries)

    def test_retrieve_still_prefetches_the_nested_relations(self):
        """The detail read renders them, so it must still fetch them — the
        list-only narrowing must not turn detail into an N+1."""
        with CaptureQueriesContext(connection) as ctx:
            resp = self._client().get(f"/api/v1/invoices/invoices/{self.invoice.pk}/")

        self.assertEqual(resp.status_code, 200)
        touched = " ".join(q["sql"] for q in ctx.captured_queries)
        self.assertIn("invoices_invoiceitem", touched)
        self.assertIn("invoices_emaillog", touched)
        self.assertEqual(len(self._standalone_email_log_queries(ctx.captured_queries)), 1)
        self.assertEqual(resp.data["last_email_log_id"], str(self.log.pk))

    def test_prefetched_latest_email_fields_do_not_query_and_agree_on_ties(self):
        from invoices.models import Invoice

        newer = EmailLog.objects.create(
            invoice=self.invoice, recipient="new@example.com", subject="Retry", status="failed",
        )
        EmailLog.objects.filter(pk=newer.pk).update(created_at=self.log.created_at)
        latest = max((self.log, newer), key=lambda log: log.id)
        for invoice_id, expected in ((self.invoice.pk, latest), (self.no_log_invoice.pk, None)):
            invoice = Invoice.objects.prefetch_related("email_logs").get(pk=invoice_id)
            serializer = InvoiceSerializer()
            with self.assertNumQueries(0):
                self.assertEqual(serializer.get_last_email_status(invoice), expected.status if expected else None)
                self.assertEqual(serializer.get_last_email_log_id(invoice), str(expected.pk) if expected else None)
