"""The invoice actions offered to a user (``Invoice.allowed_actions``) by
status, approval, payments, credits, a disabled ZEV and role, checked against
the write endpoints they stand for.
"""

from datetime import date, timedelta
from itertools import count
from decimal import Decimal
from unittest import mock

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import UserRole
from invoices.models import Credit, CreditApplication, CreditKind, Invoice, InvoiceStatus, Payment
from invoices.serializers import CreditSerializer
from invoices.test_helpers import make_invoice, make_participant, make_user, make_zev
from invoices.views import InvoiceViewSet
from invoices.workflow import allowed_actions, credit_allowed_actions
from testing.helpers import authenticate
from zev.models import VatMode, ZevAccessGrant, ZevAccessRole

INVOICES = "/api/v1/invoices/invoices"

SEND = {"send_email", "mark_paid", "record_payment"}
CORRECT = {"correct", "adjust"}


class _Fixture(TestCase):
    def setUp(self):
        self.manager = make_user("aa_manager", UserRole.USER)
        self.admin = make_user("aa_admin", UserRole.ADMIN)
        self.viewer = make_user("aa_viewer", UserRole.USER)
        self.member = make_user("aa_participant", UserRole.USER)
        self.zev = make_zev(self.manager, "Allowed Actions ZEV")
        ZevAccessGrant.objects.create(zev=self.zev, user=self.viewer, role=ZevAccessRole.VIEWER, valid_from=date(2026, 1, 1))
        self.participant = make_participant(self.zev, user=self.member)
        self._periods = count()

    def invoice(self, status, *, approved=None, total="42.00", paid=None, credited=None, applied=None):
        """An invoice in ``status``; ``approved`` defaults to "issued" for every
        status past draft. ``paid``/``credited``/``applied`` book a payment, a
        credit note issued for it and credit set against it."""
        # One period each: the period overview shows the newest invoice per period.
        start = date(2026, 1, 1) + timedelta(days=2 * next(self._periods))
        invoice = make_invoice(self.zev, self.participant, status, period=(start, start))
        if approved is None:
            approved = status != InvoiceStatus.DRAFT
        Invoice.objects.filter(pk=invoice.pk).update(
            total_chf=Decimal(total), approved_at=timezone.now() if approved else None,
            credit_applied_chf=Decimal(applied or "0"),
        )
        if paid:
            Payment.objects.create(invoice=invoice, amount_chf=Decimal(paid), paid_on=date(2026, 3, 1))
        if credited:
            self.credit(credited, source=invoice)
        if applied:
            CreditApplication.objects.create(credit=self.credit(applied), invoice=invoice, amount_chf=Decimal(applied))
        invoice.refresh_from_db()
        return invoice

    def credit(self, amount, *, source=None):
        return Credit.objects.create(
            zev=self.zev, participant=self.participant, kind=CreditKind.ADJUSTMENT, source_invoice=source,
            credit_number=f"CN-AA{Credit.objects.count() + 1:03d}", reason="Test",
            amount_chf=Decimal(amount), vat_mode=VatMode.NOT_REGISTERED,
        )

    def disable_zev(self):
        self.zev.disabled_at = timezone.now()
        self.zev.save(update_fields=["disabled_at"])

    def actions(self, invoice, user):
        # A fresh row each time: no annotation or prefetch, the fallback path.
        return set(allowed_actions(Invoice.objects.select_related("zev").get(pk=invoice.pk), user))

    def client_for(self, user):
        client = APIClient()
        authenticate(client, user)
        return client


class AllowedActionsMatrixTests(_Fixture):
    def test_manager_and_admin_by_state(self):
        S = InvoiceStatus
        cases = [
            # (label, invoice kwargs, manager actions, admin actions)
            ("draft", dict(status=S.DRAFT), {"approve", "delete"}, {"approve", "delete"}),
            ("approved", dict(status=S.APPROVED), {"mark_sent", "send_email"}, {"mark_sent", "send_email", "delete"}),
            ("sent", dict(status=S.SENT), SEND, SEND | {"delete"}),
            ("sent, part paid", dict(status=S.SENT, paid="10.00"), SEND | CORRECT, SEND | CORRECT),
            ("sent, payout", dict(status=S.SENT, total="-40.00"), {"send_email", "mark_paid"},
             {"send_email", "mark_paid", "delete"}),
            ("paid", dict(status=S.PAID, paid="42.00"), CORRECT, CORRECT),
            ("paid, fully credited", dict(status=S.PAID, paid="42.00", credited="42.00"), set(), set()),
            ("paid, part credited", dict(status=S.PAID, paid="42.00", credited="10.00"), CORRECT, CORRECT),
            # Credit set against an invoice is not a credit note issued for it:
            # the admin may still delete it (the application cascades away).
            ("paid by credit alone", dict(status=S.PAID, applied="42.00"), {"correct"}, {"correct", "delete"}),
            ("paid payout", dict(status=S.PAID, total="-40.00", paid="-40.00"), set(), set()),
            ("cancelled, never issued", dict(status=S.CANCELLED, approved=False), {"delete"}, {"delete"}),
            ("cancelled, issued", dict(status=S.CANCELLED), set(), {"delete"}),
            ("cancelled, credited", dict(status=S.CANCELLED, paid="42.00", credited="42.00"), set(), set()),
        ]
        for label, kwargs, manager, admin in cases:
            invoice = self.invoice(**kwargs)
            with self.subTest(label, user="manager"):
                self.assertEqual(self.actions(invoice, self.manager), manager)
            with self.subTest(label, user="admin"):
                self.assertEqual(self.actions(invoice, self.admin), admin)
            with self.subTest(label, user="viewer"):
                self.assertEqual(self.actions(invoice, self.viewer), set())
            with self.subTest(label, user="participant"):
                self.assertEqual(self.actions(invoice, self.member), set())

    def test_disabled_zev_leaves_admins_the_state_eligible_actions(self):
        draft = self.invoice(InvoiceStatus.DRAFT)
        sent = self.invoice(InvoiceStatus.SENT, paid="10.00")
        self.disable_zev()
        self.assertEqual(self.actions(draft, self.manager), set())
        self.assertEqual(self.actions(sent, self.manager), set())
        self.assertEqual(self.actions(draft, self.admin), {"approve", "delete"})
        self.assertEqual(self.actions(sent, self.admin), SEND | CORRECT)

    def test_without_a_request_nothing_is_allowed(self):
        from invoices.serializers import InvoiceSerializer

        self.assertEqual(InvoiceSerializer(self.invoice(InvoiceStatus.DRAFT)).data["allowed_actions"], [])

    def test_list_detail_and_period_overview_agree_with_the_predicate(self):
        invoices = [
            self.invoice(InvoiceStatus.DRAFT),
            self.invoice(InvoiceStatus.SENT, paid="10.00"),
            self.invoice(InvoiceStatus.PAID, paid="42.00", credited="10.00"),
            self.invoice(InvoiceStatus.PAID, applied="42.00"),
            self.invoice(InvoiceStatus.CANCELLED),
        ]
        for user in (self.manager, self.admin):
            client = self.client_for(user)
            listed = {row["id"]: set(row["allowed_actions"]) for row in client.get(f"{INVOICES}/").json()["results"]}
            for invoice in invoices:
                expected = self.actions(invoice, user)
                with self.subTest(user=user.username, status=invoice.status):
                    self.assertEqual(listed[str(invoice.pk)], expected)
                    detail = client.get(f"{INVOICES}/{invoice.pk}/").json()
                    self.assertEqual(set(detail["allowed_actions"]), expected)
                    overview = client.get(
                        f"{INVOICES}/period-overview/",
                        {"zev_id": str(self.zev.pk), "period_start": invoice.period_start.isoformat(),
                         "period_end": invoice.period_end.isoformat()},
                    ).json()
                    row = next(r["invoice"] for r in overview["rows"] if r["invoice"])
                    self.assertEqual(set(row["allowed_actions"]), expected)

    def test_viewer_reads_the_field_empty(self):
        invoice = self.invoice(InvoiceStatus.DRAFT)
        response = self.client_for(self.viewer).get(f"{INVOICES}/{invoice.pk}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["allowed_actions"], [])

    def test_a_workflow_response_carries_the_new_actions(self):
        invoice = self.invoice(InvoiceStatus.DRAFT)
        response = self.client_for(self.manager).post(f"{INVOICES}/{invoice.pk}/approve/")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(set(response.json()["allowed_actions"]), {"mark_sent", "send_email"})


class DestroyHonoursThePredicateTests(_Fixture):
    def test_delete_succeeds_exactly_when_allowed(self):
        S = InvoiceStatus
        states = [
            dict(status=S.DRAFT), dict(status=S.APPROVED), dict(status=S.SENT),
            dict(status=S.SENT, paid="10.00"), dict(status=S.PAID, paid="42.00"),
            dict(status=S.PAID, applied="42.00"), dict(status=S.CANCELLED, approved=False),
            dict(status=S.CANCELLED), dict(status=S.CANCELLED, paid="42.00", credited="42.00"),
        ]
        for disabled in (False, True):
            if disabled:
                self.disable_zev()
            for user in (self.manager, self.admin, self.viewer):
                for kwargs in states:
                    invoice = self.invoice(**kwargs)
                    allowed = "delete" in self.actions(invoice, user)
                    response = self.client_for(user).delete(f"{INVOICES}/{invoice.pk}/")
                    with self.subTest(user=user.username, disabled=disabled, **kwargs):
                        self.assertEqual(response.status_code == 204, allowed, response.content)
                        self.assertEqual(Invoice.objects.filter(pk=invoice.pk).exists(), not allowed)

    def test_guards_are_rechecked_on_the_locked_row(self):
        """An approval that lands between the view loading the invoice and
        deleting it is seen: the guard reads the locked row, not the stale one."""
        invoice = self.invoice(InvoiceStatus.DRAFT)
        load = InvoiceViewSet.get_object

        def approved_meanwhile(view):
            stale = load(view)
            Invoice.objects.filter(pk=stale.pk).update(status=InvoiceStatus.APPROVED, approved_at=timezone.now())
            return stale

        with mock.patch.object(InvoiceViewSet, "get_object", approved_meanwhile):
            response = self.client_for(self.manager).delete(f"{INVOICES}/{invoice.pk}/")
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("never approved", response.json()["error"])
        self.assertTrue(Invoice.objects.filter(pk=invoice.pk).exists())

    def test_a_row_deleted_meanwhile_is_a_404(self):
        invoice = self.invoice(InvoiceStatus.DRAFT)
        load = InvoiceViewSet.get_object

        def deleted_meanwhile(view):
            stale = load(view)
            Invoice.objects.filter(pk=stale.pk).delete()
            return stale

        with mock.patch.object(InvoiceViewSet, "get_object", deleted_meanwhile):
            response = self.client_for(self.manager).delete(f"{INVOICES}/{invoice.pk}/")
        self.assertEqual(response.status_code, 404, response.content)

    def test_delete_takes_the_row_lock(self):
        invoice = self.invoice(InvoiceStatus.DRAFT)
        with CaptureQueriesContext(connection) as ctx:
            response = self.client_for(self.manager).delete(f"{INVOICES}/{invoice.pk}/")
        self.assertEqual(response.status_code, 204, response.content)
        if connection.features.has_select_for_update:
            self.assertTrue(any("FOR UPDATE" in q["sql"] for q in ctx.captured_queries))


class CorrectionEndpointTests(_Fixture):
    """``correct``/``adjust`` are offered exactly where ``POST correct/`` accepts them."""

    def correct(self, invoice, kind):
        body = {"kind": kind, "reason": "Test"} | ({"amount_chf": "5.00"} if kind == "adjustment" else {})
        return self.client_for(self.manager).post(f"{INVOICES}/{invoice.pk}/correct/", body, format="json")

    def test_offered_and_withheld_corrections_match_the_endpoint(self):
        S = InvoiceStatus
        cases = [
            ("sent, part paid", dict(status=S.SENT, paid="10.00"), "adjustment"),
            ("paid by credit alone", dict(status=S.PAID, applied="42.00"), "adjustment"),
            ("paid by credit alone", dict(status=S.PAID, applied="42.00"), "reversal"),
            ("paid, fully credited", dict(status=S.PAID, paid="42.00", credited="42.00"), "reversal"),
            ("sent, unpaid", dict(status=S.SENT), "reversal"),
        ]
        for label, kwargs, kind in cases:
            invoice = self.invoice(**kwargs)
            offered = ("adjust" if kind == "adjustment" else "correct") in self.actions(invoice, self.manager)
            response = self.correct(invoice, kind)
            with self.subTest(label, kind=kind):
                self.assertEqual(response.status_code == 201, offered, response.content)


class ListQueryCountTests(_Fixture):
    def test_allowed_actions_do_not_query_per_row(self):
        client = self.client_for(self.manager)

        def queries():
            with CaptureQueriesContext(connection) as ctx:
                response = client.get(f"{INVOICES}/")
            self.assertEqual(response.status_code, 200)
            return len(ctx.captured_queries)

        self.invoice(InvoiceStatus.PAID, paid="42.00", credited="10.00")
        base = queries()
        self.invoice(InvoiceStatus.SENT, paid="10.00")
        self.invoice(InvoiceStatus.PAID, applied="42.00")
        self.invoice(InvoiceStatus.PAID, paid="42.00", credited="42.00")
        self.invoice(InvoiceStatus.DRAFT)
        self.assertEqual(queries(), base)


class CreditAllowedActionsTests(_Fixture):
    def test_refund_is_offered_to_the_manager_of_an_open_credit(self):
        credit = self.credit("10.00")
        self.assertEqual(credit_allowed_actions(credit, self.manager), ["refund"])
        self.assertEqual(credit_allowed_actions(credit, self.admin), ["refund"])
        self.assertEqual(credit_allowed_actions(credit, self.viewer), [])
        self.assertEqual(credit_allowed_actions(credit, self.member), [])

    def test_not_for_a_used_or_refunded_credit(self):
        used = self.credit("10.00")
        CreditApplication.objects.create(credit=used, invoice=self.invoice(InvoiceStatus.DRAFT), amount_chf=Decimal("10.00"))
        refunded = self.credit("10.00")
        Credit.objects.filter(pk=refunded.pk).update(refunded_chf=Decimal("10.00"))
        for credit in (used, refunded):
            fresh = Credit.objects.select_related("zev").prefetch_related("applications").get(pk=credit.pk)
            self.assertEqual(credit_allowed_actions(fresh, self.manager), [])

    def test_not_for_the_manager_of_a_disabled_zev(self):
        credit = self.credit("10.00")
        self.disable_zev()
        credit.zev.refresh_from_db()
        self.assertEqual(credit_allowed_actions(credit, self.manager), [])
        self.assertEqual(credit_allowed_actions(credit, self.admin), ["refund"])

    def test_the_serializer_and_the_nested_credits_carry_it(self):
        invoice = self.invoice(InvoiceStatus.PAID, paid="42.00", credited="10.00")
        client = self.client_for(self.manager)
        nested = client.get(f"{INVOICES}/{invoice.pk}/").json()["credits"]
        self.assertEqual(nested[0]["allowed_actions"], ["refund"])
        listed = client.get("/api/v1/invoices/credits/").json()["results"]
        self.assertEqual(listed[0]["allowed_actions"], ["refund"])
        self.assertEqual(CreditSerializer(Credit.objects.get()).data["allowed_actions"], [])
