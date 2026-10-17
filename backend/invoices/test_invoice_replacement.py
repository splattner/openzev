"""Which invoice replaced which (#388): a correction or a cancel-and-regenerate
leaves a cancelled invoice behind, and the invoice that took its place, for the
same participant and period, names it (``replaces``) and vice versa
(``replaced_by``)."""

from datetime import date, datetime, timedelta, timezone

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from accounts.models import UserRole
from invoices.models import Invoice, InvoiceStatus
from invoices.test_helpers import make_invoice, make_participant, make_user, make_zev
from testing.helpers import authenticate as auth

INVOICES = "/api/v1/invoices/invoices"
_T0 = datetime(2026, 2, 1, 8, 0, tzinfo=timezone.utc)


def _invoice(zev, participant, status, minutes, period=None):
    """An invoice created ``minutes`` after a fixed instant, so the order is explicit."""
    invoice = make_invoice(zev, participant, status, period=period)
    Invoice.objects.filter(pk=invoice.pk).update(created_at=_T0 + timedelta(minutes=minutes))
    invoice.refresh_from_db()
    return invoice


class InvoiceReplacementTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = make_user("replace_owner", UserRole.USER)
        self.zev = make_zev(self.owner, "Replacement ZEV")
        self.participant = make_participant(self.zev)
        # First issued, then corrected twice: A and B cancelled, C current.
        self.first = _invoice(self.zev, self.participant, InvoiceStatus.CANCELLED, 0)
        self.second = _invoice(self.zev, self.participant, InvoiceStatus.CANCELLED, 10)
        self.current = _invoice(self.zev, self.participant, InvoiceStatus.DRAFT, 20)
        auth(self.client, self.owner)

    def _detail(self, invoice):
        return self.client.get(f"{INVOICES}/{invoice.pk}/").data

    def test_the_current_invoice_lists_what_it_replaces_newest_first(self):
        detail = self._detail(self.current)
        self.assertEqual(
            detail["replaces"],
            [
                {"id": str(self.second.pk), "invoice_number": self.second.invoice_number},
                {"id": str(self.first.pk), "invoice_number": self.first.invoice_number},
            ],
        )
        self.assertIsNone(detail["replaced_by"])

    def test_a_cancelled_invoice_points_to_the_newest_one(self):
        detail = self._detail(self.first)
        self.assertEqual(detail["replaced_by"], {"id": str(self.current.pk), "invoice_number": self.current.invoice_number})
        self.assertEqual(detail["replaces"], [])
        self.assertEqual(
            self._detail(self.second)["replaces"],
            [{"id": str(self.first.pk), "invoice_number": self.first.invoice_number}],
        )

    def test_a_cancelled_invoice_not_yet_replaced_says_so(self):
        Invoice.objects.filter(pk=self.current.pk).delete()
        self.assertIsNone(self._detail(self.second)["replaced_by"])

    def test_other_periods_and_participants_are_not_related(self):
        other = make_participant(self.zev, first="Other", last="Person")
        _invoice(self.zev, other, InvoiceStatus.CANCELLED, 5)
        _invoice(self.zev, self.participant, InvoiceStatus.CANCELLED, 5, period=(date(2026, 2, 1), date(2026, 2, 28)))
        self.assertEqual(len(self._detail(self.current)["replaces"]), 2)

    def test_the_period_overview_row_carries_the_replaced_invoices(self):
        params = {"zev_id": str(self.zev.id), "period_start": "2026-01-01", "period_end": "2026-01-31"}
        rows = self.client.get(f"{INVOICES}/period-overview/", params).data["rows"]
        self.assertEqual(rows[0]["invoice"]["id"], str(self.current.pk))
        self.assertEqual(
            [ref["invoice_number"] for ref in rows[0]["invoice"]["replaces"]],
            [self.second.invoice_number, self.first.invoice_number],
        )

    def test_the_period_overview_does_not_query_per_replaced_invoice(self):
        params = {"zev_id": str(self.zev.id), "period_start": "2026-01-01", "period_end": "2026-01-31"}
        with CaptureQueriesContext(connection) as before:
            self.client.get(f"{INVOICES}/period-overview/", params)
        for minutes in (1, 2, 3):
            _invoice(self.zev, self.participant, InvoiceStatus.CANCELLED, minutes)
        with CaptureQueriesContext(connection) as after:
            rows = self.client.get(f"{INVOICES}/period-overview/", params).data["rows"]
        self.assertEqual(len(rows[0]["invoice"]["replaces"]), 5)
        self.assertEqual(len(after), len(before))
