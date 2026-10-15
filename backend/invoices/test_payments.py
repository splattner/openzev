"""Payments, approval stamps and the retention rule (#388, ADR 0037)."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.utils import timezone as django_timezone
from rest_framework.test import APIClient

from accounts.models import UserRole
from audit.models import AuditEvent
from invoices.models import Invoice, InvoiceStatus, Payment
from invoices.test_helpers import make_invoice, make_participant, make_user, make_zev
from invoices.workflow import (
    InvoiceWorkflowError,
    approve_invoice,
    delete_payment,
    mark_invoice_paid,
    record_payment,
)
from testing.helpers import authenticate as auth
from zev.models import ZevAccessGrant, ZevAccessRole

INVOICES = "/api/v1/invoices/invoices"


def _sent(zev, participant, total="100.00", **kwargs):
    invoice = make_invoice(zev, participant, InvoiceStatus.SENT, **kwargs)
    Invoice.objects.filter(pk=invoice.pk).update(total_chf=Decimal(total))
    invoice.refresh_from_db()
    return invoice


class PaymentWorkflowTests(TestCase):
    def setUp(self):
        self.owner = make_user("pay_owner", UserRole.USER)
        self.zev = make_zev(self.owner, "Pay ZEV")
        self.participant = make_participant(self.zev)
        self.today = django_timezone.localdate()

    def test_record_partial_payment_keeps_invoice_sent(self):
        invoice = _sent(self.zev, self.participant)
        record_payment(invoice, amount_chf=Decimal("40.00"), paid_on=self.today)
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, InvoiceStatus.SENT)
        self.assertEqual(invoice.payments.get().amount_chf, Decimal("40.00"))

    def test_payments_covering_total_mark_invoice_paid(self):
        invoice = _sent(self.zev, self.participant)
        record_payment(invoice, amount_chf=Decimal("40.00"), paid_on=self.today)
        before = record_payment(invoice, amount_chf=Decimal("60.00"), paid_on=self.today)
        self.assertEqual(before["status"], InvoiceStatus.SENT)
        self.assertEqual(invoice.status, InvoiceStatus.PAID)
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, InvoiceStatus.PAID)

    def test_payment_above_outstanding_is_refused(self):
        invoice = _sent(self.zev, self.participant)
        record_payment(invoice, amount_chf=Decimal("90.00"), paid_on=self.today)
        with self.assertRaisesMessage(InvoiceWorkflowError, "outstanding amount of CHF 10.00"):
            record_payment(invoice, amount_chf=Decimal("10.01"), paid_on=self.today)
        self.assertEqual(invoice.payments.count(), 1)

    def test_payment_on_approved_or_draft_is_refused(self):
        for status in (InvoiceStatus.DRAFT, InvoiceStatus.APPROVED, InvoiceStatus.CANCELLED):
            invoice = make_invoice(self.zev, self.participant, status)
            with self.assertRaisesMessage(InvoiceWorkflowError, "Only sent invoices can receive payments."):
                record_payment(invoice, amount_chf=Decimal("1.00"), paid_on=self.today)
            self.assertFalse(invoice.payments.exists())

    def test_payment_in_the_future_or_not_positive_is_refused(self):
        invoice = _sent(self.zev, self.participant)
        with self.assertRaisesMessage(InvoiceWorkflowError, "cannot be in the future"):
            record_payment(invoice, amount_chf=Decimal("1.00"), paid_on=self.today + timedelta(days=1))
        with self.assertRaisesMessage(InvoiceWorkflowError, "must be positive"):
            record_payment(invoice, amount_chf=Decimal("-1.00"), paid_on=self.today)
        self.assertFalse(invoice.payments.exists())

    def test_mark_paid_records_the_outstanding_amount(self):
        invoice = _sent(self.zev, self.participant)
        record_payment(invoice, amount_chf=Decimal("30.00"), paid_on=self.today)
        before = mark_invoice_paid(invoice, paid_on=date(2026, 3, 2))
        self.assertEqual(before["payment"].amount_chf, Decimal("70.00"))
        self.assertEqual(before["payment"].source, Payment.Source.MARK_PAID)
        self.assertEqual(before["payment"].paid_on, date(2026, 3, 2))
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, InvoiceStatus.PAID)

    def test_mark_paid_on_payout_invoice_records_negative_payment(self):
        # A producer whose feed-in credit outweighs consumption is paid out.
        invoice = _sent(self.zev, self.participant, total="-40.00")
        with self.assertRaisesMessage(InvoiceWorkflowError, "nothing to collect"):
            record_payment(invoice, amount_chf=Decimal("40.00"), paid_on=self.today)
        mark_invoice_paid(invoice)
        self.assertEqual(invoice.payments.get().amount_chf, Decimal("-40.00"))
        self.assertEqual(invoice.status, InvoiceStatus.PAID)

    def test_mark_paid_zero_total_has_no_payment(self):
        invoice = _sent(self.zev, self.participant, total="0.00")
        before = mark_invoice_paid(invoice)
        self.assertIsNone(before["payment"])
        self.assertFalse(invoice.payments.exists())
        self.assertEqual(invoice.status, InvoiceStatus.PAID)

    def test_delete_payment_reverts_paid_to_sent(self):
        invoice = _sent(self.zev, self.participant)
        mark_invoice_paid(invoice)
        payment = invoice.payments.get()
        before = delete_payment(payment)
        self.assertEqual(before["status"], InvoiceStatus.PAID)
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, InvoiceStatus.SENT)
        self.assertFalse(invoice.payments.exists())

    def test_approve_stamps_approved_at(self):
        invoice = make_invoice(self.zev, self.participant, InvoiceStatus.DRAFT)
        approve_invoice(invoice)
        invoice.refresh_from_db()
        self.assertIsNotNone(invoice.approved_at)


class PaymentApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = make_user("payapi_owner", UserRole.USER)
        self.zev = make_zev(self.owner, "Pay API ZEV")
        self.tenant = make_user("payapi_tenant", UserRole.USER)
        self.participant = make_participant(self.zev, user=self.tenant)
        auth(self.client, self.owner)

    def test_record_payment_returns_updated_invoice(self):
        invoice = _sent(self.zev, self.participant)
        response = self.client.post(
            f"{INVOICES}/{invoice.pk}/payments/",
            {"amount_chf": "25.00", "paid_on": "2026-02-10", "note": "E-Banking"},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["status"], InvoiceStatus.SENT)
        self.assertEqual(response.data["paid_chf"], "25.00")
        self.assertEqual(response.data["outstanding_chf"], "75.00")
        self.assertEqual([p["note"] for p in response.data["payments"]], ["E-Banking"])

    def test_record_payment_above_outstanding_returns_400(self):
        invoice = _sent(self.zev, self.participant)
        response = self.client.post(f"{INVOICES}/{invoice.pk}/payments/", {"amount_chf": "100.01"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("outstanding", response.data["error"])

    def test_mark_paid_accepts_a_date(self):
        invoice = _sent(self.zev, self.participant)
        response = self.client.post(f"{INVOICES}/{invoice.pk}/mark-paid/", {"paid_on": "2026-02-20"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["status"], InvoiceStatus.PAID)
        self.assertEqual(response.data["outstanding_chf"], "0.00")
        self.assertEqual(invoice.payments.get().paid_on, date(2026, 2, 20))
        event = AuditEvent.objects.get(action_type="invoice.mark_paid", target_id=str(invoice.pk))
        self.assertEqual(event.metadata_json["amount_chf"], "100.00")

    def test_list_shows_paid_and_outstanding(self):
        invoice = _sent(self.zev, self.participant)
        record_payment(invoice, amount_chf=Decimal("12.50"), paid_on=date(2026, 2, 1))
        response = self.client.get(f"{INVOICES}/", {"zev_id": str(self.zev.pk)})
        row = next(r for r in response.data["results"] if r["id"] == str(invoice.pk))
        self.assertEqual(row["paid_chf"], "12.50")
        self.assertEqual(row["outstanding_chf"], "87.50")

    def test_remove_payment(self):
        invoice = _sent(self.zev, self.participant)
        mark_invoice_paid(invoice)
        payment = invoice.payments.get()
        response = self.client.delete(f"{INVOICES}/{invoice.pk}/payments/{payment.pk}/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["status"], InvoiceStatus.SENT)
        self.assertTrue(
            AuditEvent.objects.filter(action_type="invoice.payment_delete", target_id=str(invoice.pk)).exists()
        )

    def test_remove_unknown_payment_returns_404(self):
        invoice = _sent(self.zev, self.participant)
        response = self.client.delete(f"{INVOICES}/{invoice.pk}/payments/not-a-uuid/")
        self.assertEqual(response.status_code, 404)

    def test_payment_audit_event(self):
        invoice = _sent(self.zev, self.participant)
        self.client.post(f"{INVOICES}/{invoice.pk}/payments/", {"amount_chf": "10.00"}, format="json")
        event = AuditEvent.objects.get(action_type="invoice.payment_record", target_id=str(invoice.pk))
        self.assertEqual(event.metadata_json["amount_chf"], "10.00")

    def test_cancel_refuses_invoice_with_payments(self):
        invoice = _sent(self.zev, self.participant)
        record_payment(invoice, amount_chf=Decimal("10.00"), paid_on=date(2026, 2, 1))
        response = self.client.post(f"{INVOICES}/{invoice.pk}/cancel/")
        self.assertEqual(response.status_code, 400)
        self.assertIn("payments", response.data["error"])
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, InvoiceStatus.SENT)

    def test_viewer_cannot_record_payment(self):
        viewer = make_user("payapi_viewer", UserRole.USER)
        ZevAccessGrant.objects.create(zev=self.zev, user=viewer, role=ZevAccessRole.VIEWER, valid_from=date(2026, 1, 1))
        invoice = _sent(self.zev, self.participant)
        auth(self.client, viewer)
        self.assertEqual(self.client.get(f"{INVOICES}/{invoice.pk}/payments/").status_code, 200)
        response = self.client.post(f"{INVOICES}/{invoice.pk}/payments/", {"amount_chf": "1.00"}, format="json")
        self.assertIn(response.status_code, (403, 404))
        self.assertFalse(invoice.payments.exists())

    def test_participant_sees_totals_but_not_payment_rows(self):
        invoice = _sent(self.zev, self.participant)
        record_payment(invoice, amount_chf=Decimal("10.00"), paid_on=date(2026, 2, 1))
        auth(self.client, self.tenant)
        detail = self.client.get(f"{INVOICES}/{invoice.pk}/")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.data["paid_chf"], "10.00")
        self.assertIsNone(detail.data["payments"])
        self.assertEqual(self.client.get(f"{INVOICES}/{invoice.pk}/payments/").status_code, 403)

    def test_disabled_zev_refuses_payment_for_non_admin(self):
        invoice = _sent(self.zev, self.participant)
        self.zev.disabled_at = django_timezone.now()
        self.zev.save(update_fields=["disabled_at"])
        response = self.client.post(f"{INVOICES}/{invoice.pk}/payments/", {"amount_chf": "1.00"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(invoice.payments.exists())

    def test_approve_all_stamps_approved_at(self):
        invoice = make_invoice(self.zev, self.participant, InvoiceStatus.DRAFT)
        response = self.client.post(f"{INVOICES}/approve-all/", {
            "zev_id": str(self.zev.pk), "period_start": "2026-01-01", "period_end": "2026-01-31",
        }, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        invoice.refresh_from_db()
        self.assertIsNotNone(invoice.approved_at)


class RetentionTests(TestCase):
    """An invoice that was ever approved keeps its number for good (ADR 0037)."""

    def setUp(self):
        self.client = APIClient()
        self.owner = make_user("ret_owner", UserRole.USER)
        self.admin = make_user("ret_admin", UserRole.ADMIN)
        self.zev = make_zev(self.owner, "Retention ZEV")
        self.participant = make_participant(self.zev)
        auth(self.client, self.owner)

    def _cancelled(self, *, issued):
        invoice = make_invoice(self.zev, self.participant, InvoiceStatus.CANCELLED)
        if issued:
            Invoice.objects.filter(pk=invoice.pk).update(approved_at=django_timezone.now())
        return invoice

    def _generate(self):
        return self.client.post(f"{INVOICES}/generate/", {
            "participant_id": str(self.participant.pk),
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
        })

    def test_regeneration_keeps_issued_cancelled_invoice(self):
        original = self._cancelled(issued=True)
        response = self._generate()
        self.assertEqual(response.status_code, 201, response.data)
        self.assertTrue(Invoice.objects.filter(pk=original.pk).exists())
        self.assertEqual(Invoice.objects.filter(participant=self.participant).count(), 2)

    def test_regeneration_deletes_never_issued_cancelled_invoice(self):
        original = self._cancelled(issued=False)
        response = self._generate()
        self.assertEqual(response.status_code, 201, response.data)
        self.assertFalse(Invoice.objects.filter(pk=original.pk).exists())

    def test_owner_cannot_delete_issued_cancelled_invoice(self):
        invoice = self._cancelled(issued=True)
        response = self.client.delete(f"{INVOICES}/{invoice.pk}/")
        self.assertEqual(response.status_code, 400)
        self.assertTrue(Invoice.objects.filter(pk=invoice.pk).exists())

    def test_owner_can_delete_never_issued_cancelled_invoice(self):
        invoice = self._cancelled(issued=False)
        self.assertEqual(self.client.delete(f"{INVOICES}/{invoice.pk}/").status_code, 204)

    def test_admin_cannot_delete_invoice_with_payments(self):
        invoice = _sent(self.zev, self.participant)
        record_payment(invoice, amount_chf=Decimal("1.00"), paid_on=date(2026, 2, 1))
        auth(self.client, self.admin)
        response = self.client.delete(f"{INVOICES}/{invoice.pk}/")
        self.assertEqual(response.status_code, 400)
        self.assertTrue(Invoice.objects.filter(pk=invoice.pk).exists())

    def test_period_overview_prefers_replacement_over_cancelled_original(self):
        self._cancelled(issued=True)
        self.assertEqual(self._generate().status_code, 201)
        replacement = Invoice.objects.exclude(status=InvoiceStatus.CANCELLED).get(participant=self.participant)
        response = self.client.get(f"{INVOICES}/period-overview/", {
            "zev_id": str(self.zev.pk), "period_start": "2026-01-01", "period_end": "2026-01-31",
        })
        self.assertEqual(response.status_code, 200, response.data)
        rows = [row for row in response.data["rows"] if row["participant_id"] == str(self.participant.pk)]
        self.assertEqual(rows[0]["invoice"]["id"], str(replacement.pk))


    def test_readiness_ignores_retained_cancelled_invoice(self):
        from invoices.readiness import compute_readiness

        self._cancelled(issued=True)
        make_invoice(self.zev, self.participant, InvoiceStatus.DRAFT)
        steps = {step["key"]: step for step in compute_readiness(self.zev, date(2026, 1, 1), date(2026, 1, 31))["steps"]}
        self.assertEqual((steps["approved"]["count"], steps["approved"]["total"]), (1, 1))


class BillingRuleTests(TestCase):
    """The reports count issued, uncancelled invoices (``billed_invoices``)."""

    def test_billed_invoices_excludes_drafts_and_cancelled(self):
        from invoices.models import billed_invoices

        owner = make_user("rule_owner", UserRole.USER)
        zev = make_zev(owner, "Rule ZEV")
        participant = make_participant(zev)
        months = iter(range(1, 13))

        def invoice(status, approved_at=None):
            month = next(months)
            row = make_invoice(zev, participant, status, period=(date(2026, month, 1), date(2026, month, 28)))
            if approved_at:
                Invoice.objects.filter(pk=row.pk).update(approved_at=approved_at)
            return row

        invoice(InvoiceStatus.DRAFT)
        invoice(InvoiceStatus.CANCELLED, approved_at=django_timezone.now())
        expected = {
            invoice(InvoiceStatus.APPROVED).pk,
            invoice(InvoiceStatus.SENT).pk,
            invoice(InvoiceStatus.PAID).pk,
        }
        billed = billed_invoices(zev, date(2026, 1, 1), date(2026, 12, 31), participant)
        self.assertEqual(set(billed.values_list("pk", flat=True)), expected)


class BackfillMigrationTests(TransactionTestCase):
    BEFORE = [("invoices", "0022_invoice_payments_and_approved_at")]
    AFTER = [("invoices", "0023_backfill_payments_and_approved_at")]

    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def setUp(self):
        self.tearDown()

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())

    def test_backfill_payments_and_approved_at(self):
        owner = make_user("bf_pay_owner", UserRole.USER)
        zev = make_zev(owner, "Backfill Pay ZEV")
        participant = make_participant(zev)
        old = self.migrate(self.BEFORE)
        OldInvoice = old.get_model("invoices", "Invoice")

        def create(number, status, total="50.00", sent_at=None):
            return OldInvoice.objects.create(
                invoice_number=number, zev_id=zev.pk, participant_id=participant.pk, status=status,
                period_start=date(2026, 1, 1), period_end=date(2026, 1, 31),
                total_chf=Decimal(total), sent_at=sent_at,
            )

        sent_at = datetime(2026, 2, 3, 9, tzinfo=timezone.utc)
        paid = create("BF-P", "paid", sent_at=sent_at)
        zero = create("BF-Z", "paid", total="0.00", sent_at=sent_at)
        draft = create("BF-D", "draft")
        sent_cancelled = create("BF-SC", "cancelled", sent_at=sent_at)
        draft_cancelled = create("BF-DC", "cancelled")
        marked_at = datetime(2026, 2, 28, 23, 30, tzinfo=timezone.utc)  # 1 March in Zurich
        # The audit app stays at its latest state, so its live model will do.
        event = AuditEvent.objects.create(
            action_category="invoice", action_type="invoice.mark_paid", target_type="invoices.Invoice",
            target_id=str(paid.pk), status="success",
        )
        AuditEvent.objects.filter(pk=event.pk).update(created_at=marked_at)

        new = self.migrate(self.AFTER)
        Invoice_ = new.get_model("invoices", "Invoice")
        Payment_ = new.get_model("invoices", "Payment")

        payment = Payment_.objects.get(invoice_id=paid.pk)
        self.assertEqual(payment.amount_chf, Decimal("50.00"))
        self.assertEqual(payment.paid_on, date(2026, 3, 1))
        self.assertEqual(payment.source, "backfill")
        self.assertFalse(Payment_.objects.filter(invoice_id=zero.pk).exists())
        self.assertEqual(Invoice_.objects.get(pk=paid.pk).approved_at, sent_at)
        self.assertEqual(Invoice_.objects.get(pk=sent_cancelled.pk).approved_at, sent_at)
        self.assertIsNone(Invoice_.objects.get(pk=draft.pk).approved_at)
        self.assertIsNone(Invoice_.objects.get(pk=draft_cancelled.pk).approved_at)
