"""``?status=`` filter on GET /invoices/: comma-separated values, list-only, never widening scoping."""

from datetime import date
from unittest.mock import patch

from django.test import TestCase
from rest_framework.pagination import PageNumberPagination
from rest_framework.test import APIClient

from accounts.models import UserRole
from invoices.models import Invoice, InvoiceStatus
from invoices.views import InvoiceViewSet
from testing.helpers import authenticate as auth, make_user
from zev.models import Participant, Zev

INVOICES = "/api/v1/invoices/invoices/"


class _PageSizeTwo(PageNumberPagination):
    page_size = 2


def _rows(response):
    body = response.json()
    return body.get("results", body)


class _TwoPopulatedCommunitiesMixin:
    """Two communities whose members each hold one invoice per status."""

    def setUp(self):
        super().setUp()
        self.admin = make_user("isf_admin", UserRole.ADMIN)
        self.owner_a = make_user("isf_owner_a", UserRole.ZEV_OWNER)
        self.owner_b = make_user("isf_owner_b", UserRole.ZEV_OWNER)
        self.zev_a = Zev.objects.create(name="Community A", owner=self.owner_a, invoice_prefix="AAA")
        self.zev_b = Zev.objects.create(name="Community B", owner=self.owner_b, invoice_prefix="BBB")

        self.participant_a = self._populate(self.zev_a, "A")
        self.participant_b = self._populate(self.zev_b, "B")

        self.client = self._as(self.admin)

    def _as(self, user):
        client = APIClient()
        auth(client, user)
        return client

    def _populate(self, zev, tag):
        participant = Participant.objects.create(
            zev=zev, first_name=tag, last_name="Member",
            email=f"{tag.lower()}@example.com", valid_from=date(2026, 1, 1),
        )
        for status in InvoiceStatus.values:
            Invoice.objects.create(
                zev=zev, participant=participant, invoice_number=f"{tag}-{status}",
                period_start=date(2026, 1, 1), period_end=date(2026, 1, 31),
                status=status,
            )
        return participant


class InvoiceStatusFilterTests(_TwoPopulatedCommunitiesMixin, TestCase):
    def test_no_status_param_returns_everything(self):
        response = self.client.get(INVOICES)
        self.assertEqual(response.status_code, 200, response.content)
        expected = 2 * len(InvoiceStatus.values)
        self.assertEqual(len(_rows(response)), expected)

    def test_comma_separated_statuses_return_only_matching(self):
        response = self.client.get(INVOICES, {"status": "approved,sent"})
        self.assertEqual(response.status_code, 200, response.content)
        rows = _rows(response)
        self.assertEqual(len(rows), 4)
        self.assertEqual({row["status"] for row in rows}, {"approved", "sent"})

    def test_repeated_status_params_are_combined(self):
        response = self.client.get(INVOICES, {"status": ["approved", "sent"]})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(len(_rows(response)), 4)

    def test_single_status_value(self):
        response = self.client.get(INVOICES, {"status": "sent"})
        self.assertEqual(response.status_code, 200, response.content)
        rows = _rows(response)
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row["status"] == "sent" for row in rows))

    def test_whitespace_around_values_is_tolerated(self):
        response = self.client.get(INVOICES, {"status": " approved , sent "})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(len(_rows(response)), 4)

    def test_empty_status_param_is_treated_as_absent(self):
        # ?status= means "no filter", not "empty status".
        response = self.client.get(INVOICES, {"status": ""})
        self.assertEqual(response.status_code, 200)
        expected = 2 * len(InvoiceStatus.values)
        self.assertEqual(len(_rows(response)), expected)

    def test_unknown_status_returns_400(self):
        response = self.client.get(INVOICES, {"status": "bogus"})
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("status", response.json())

    def test_partially_unknown_status_returns_400(self):
        response = self.client.get(INVOICES, {"status": "approved,bogus"})
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("status", response.json())

    def test_multiple_unknown_statuses_all_reported(self):
        response = self.client.get(INVOICES, {"status": "bogus,other"})
        self.assertEqual(response.status_code, 400, response.content)
        message = response.json()["status"][0]
        self.assertIn("'bogus'", message)
        self.assertIn("'other'", message)

    @patch.object(InvoiceViewSet, "pagination_class", _PageSizeTwo)
    def test_filter_composes_with_pagination(self):
        # The whole point of the server-side filter: with a small page size the
        # matches spill onto later pages, and each page must keep carrying the
        # status filter (the frontend walker then collects them all).
        page1 = self.client.get(INVOICES, {"status": "approved,sent"})
        self.assertEqual(page1.status_code, 200, page1.content)
        self.assertEqual(page1.json()["count"], 4)
        self.assertEqual(len(_rows(page1)), 2)
        self.assertIn("status=", page1.json()["next"])
        page2 = self.client.get(page1.json()["next"])
        self.assertEqual(page2.status_code, 200, page2.content)
        self.assertIsNone(page2.json()["next"])
        rows = _rows(page1) + _rows(page2)
        self.assertEqual(len(rows), 4)
        self.assertEqual({row["status"] for row in rows}, {"approved", "sent"})


class InvoiceStatusFilterScopingTests(_TwoPopulatedCommunitiesMixin, TestCase):
    def test_admin_combines_zev_id_and_status(self):
        response = self.client.get(INVOICES, {"zev_id": str(self.zev_a.id), "status": "paid"})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual([row["invoice_number"] for row in _rows(response)], ["A-paid"])

    def test_owner_filters_own_zev_by_status(self):
        response = self._as(self.owner_a).get(INVOICES, {"zev_id": str(self.zev_a.id), "status": "approved,sent"})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            {row["invoice_number"] for row in _rows(response)}, {"A-approved", "A-sent"}
        )

    def test_owner_naming_another_zev_gets_nothing(self):
        response = self._as(self.owner_a).get(INVOICES, {"zev_id": str(self.zev_b.id), "status": "approved,sent"})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(_rows(response), [])

    def test_participant_sees_only_their_own_open_invoices(self):
        response = self._as_participant_a().get(INVOICES, {"status": "approved,sent"})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            {row["invoice_number"] for row in _rows(response)}, {"A-approved", "A-sent"}
        )

    def test_participant_naming_a_foreign_zev_gets_nothing(self):
        response = self._as_participant_a().get(INVOICES, {"zev_id": str(self.zev_b.id), "status": "approved,sent"})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(_rows(response), [])

    def test_status_param_is_ignored_on_retrieve(self):
        # ?status= must not leak into detail routes through get_object().
        sent_id = Invoice.objects.get(invoice_number="A-sent").id
        response = self.client.get(f"{INVOICES}{sent_id}/?status=bogus")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["invoice_number"], "A-sent")

    def test_status_param_is_ignored_on_approve(self):
        draft_id = Invoice.objects.get(invoice_number="A-draft").id
        response = self.client.post(f"{INVOICES}{draft_id}/approve/?status=sent")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["status"], "approved")

    def test_status_param_is_ignored_on_pdf(self):
        # Detail routes reuse get_object(), so ?status= must not be validated
        # there: expect the pdf route's own 404, not a 400 from the filter.
        sent_id = Invoice.objects.get(invoice_number="A-sent").id
        response = self.client.get(f"{INVOICES}{sent_id}/pdf/?status=bogus")
        self.assertEqual(response.status_code, 404, response.content)

    def _as_participant_a(self):
        member = make_user("isf_member", UserRole.PARTICIPANT)
        self.participant_a.user = member
        self.participant_a.save(update_fields=["user"])
        return self._as(member)
