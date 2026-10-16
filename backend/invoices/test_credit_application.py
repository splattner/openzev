"""Applying credit notes to the next invoice, and refunding them (#388, phase 3)."""

import threading
import time
from datetime import date, datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from unittest import mock, skipUnless

from django.core import mail
from django.core.files.base import ContentFile
from django.db import connection, connections
from django.db.models import ProtectedError
from django.test import TestCase, TransactionTestCase
from django.test.utils import CaptureQueriesContext, override_settings
from django.utils import timezone as django_timezone
from rest_framework.test import APIClient

from accounts.models import UserRole, VatRate
from audit.models import AuditEvent, AuditEventStatus
from invoices.engine import generate_invoice
from invoices.models import (
    Credit, CreditApplication, CreditKind, CreditStatus, Invoice, InvoiceStatus, Payment,
)
from invoices.pdf import _build_qr_svg
from invoices.tasks import send_invoice_email_task
from invoices.test_helpers import make_invoice, make_participant, make_user, make_zev
from invoices.test_pdf import _render_invoice_markup
from invoices.pdf_translations import INVOICE_TRANSLATIONS
from invoices.workflow import (
    InvoiceWorkflowError,
    apply_open_credits,
    approve_invoice,
    cancel_invoice,
    correct_invoice,
    credit_remaining,
    mark_invoice_paid,
    mark_invoice_sent,
    record_payment,
    refund_credit,
)
from metering.models import MeterReading, ReadingDirection
from tariffs.models import BillingMode, Tariff, TariffCategory
from testing import factories
from testing.helpers import authenticate as auth, clear_vat_rates, create_managed_zev
from zev.models import (
    MeteringPoint, MeteringPointAssignment, MeteringPointType, Participant, VatMode, ZevAccessGrant, ZevAccessRole,
)

INVOICES = "/api/v1/invoices/invoices"
CREDITS = "/api/v1/invoices/credits"
JAN = (date(2026, 1, 1), date(2026, 1, 31))
FEB = (date(2026, 2, 1), date(2026, 2, 28))

_credit_counter = 0


def _credit(zev, participant, amount, *, created_at=None, kind=CreditKind.ADJUSTMENT):
    """A credit note of ``amount``, as a correction would leave it (no source invoice)."""
    global _credit_counter
    _credit_counter += 1
    credit = Credit.objects.create(
        zev=zev, participant=participant, kind=kind, credit_number=f"CN-T{_credit_counter:04d}",
        reason="Test", amount_chf=Decimal(amount), vat_mode=VatMode.NOT_REGISTERED,
    )
    if created_at:
        Credit.objects.filter(pk=credit.pk).update(created_at=created_at)
    return credit


def _invoice(zev, participant, status, *, total="108.10", applied="0.00", period=None):
    invoice = make_invoice(zev, participant, status, period=period)
    Invoice.objects.filter(pk=invoice.pk).update(
        total_chf=Decimal(total), credit_applied_chf=Decimal(applied),
        approved_at=django_timezone.now() if status != InvoiceStatus.DRAFT else None,
        sent_at=django_timezone.now() if status in (InvoiceStatus.SENT, InvoiceStatus.PAID) else None,
    )
    invoice.refresh_from_db()
    return invoice


def _apply(credit, invoice, amount):
    return CreditApplication.objects.create(credit=credit, invoice=invoice, amount_chf=Decimal(amount))


class EngineCreditTests(TestCase):
    """The engine against a real fixture: a CHF 100.00 monthly fee plus 8.1 % VAT = 108.10."""

    def setUp(self):
        clear_vat_rates()
        VatRate.objects.create(rate=Decimal("0.0810"), valid_from=JAN[0])
        self.owner = make_user("ca_engine_owner", UserRole.USER)
        self.zev = create_managed_zev(
            name="Credit Engine ZEV", owner=self.owner, zev_type="vzev", start_date=JAN[0],
            billing_interval="monthly", invoice_prefix="CE",
        )
        self.zev.vat_mode = VatMode.REGISTERED
        self.zev.save(update_fields=["vat_mode"])
        Tariff.objects.create(
            zev=self.zev, name="Basic fee", category=TariffCategory.GRID_FEES,
            billing_mode=BillingMode.MONTHLY_FEE, fixed_price_chf=Decimal("100.00"), valid_from=JAN[0],
        )
        self.participant = self._participant("Carl", "Consumer", "CH-CA-C")
        self.other = self._participant("Olga", "Other", "CH-CA-O")

    def _participant(self, first, last, meter_id):
        participant = factories.ParticipantFactory(
            zev=self.zev, first_name=first, last_name=last, email=f"{first}.{last}@example.com".lower(),
            valid_from=JAN[0],
        )
        point = MeteringPoint.objects.create(
            zev=self.zev, meter_type=MeteringPointType.CONSUMPTION, meter_id=meter_id,
        )
        MeteringPointAssignment.objects.create(metering_point=point, participant=participant, valid_from=JAN[0])
        for month in (1, 2):
            MeterReading.objects.create(
                metering_point=point, timestamp=datetime(2026, month, 5, 12, 0, tzinfo=dt_timezone.utc),
                energy_kwh=Decimal("10"), direction=ReadingDirection.IN,
            )
        return participant

    def _generate(self, period=JAN, participant=None):
        return generate_invoice(participant or self.participant, *period)

    def test_credit_is_applied_after_vat_and_the_lines_stay_unchanged(self):
        credit = _credit(self.zev, self.participant, "50.00")
        invoice = self._generate()
        self.assertEqual(
            (invoice.subtotal_chf, invoice.vat_chf, invoice.total_chf), (Decimal("100.00"), Decimal("8.10"), Decimal("108.10")),
        )
        self.assertEqual(invoice.credit_applied_chf, Decimal("50.00"))
        self.assertEqual(invoice.amount_due_chf, Decimal("58.10"))
        self.assertEqual(sum(item.total_chf for item in invoice.items.all()), Decimal("100.00"))
        application = invoice.credit_applications.get()
        self.assertEqual((application.credit, application.amount_chf), (credit, Decimal("50.00")))
        self.assertIsNone(application.released_at)

    def test_the_amount_due_floors_at_zero_and_the_remainder_carries_forward(self):
        credit = _credit(self.zev, self.participant, "200.00")
        january = self._generate(JAN)
        self.assertEqual((january.credit_applied_chf, january.amount_due_chf), (Decimal("108.10"), Decimal("0.00")))
        self.assertEqual(credit_remaining(credit.pk), Decimal("91.90"))
        february = self._generate(FEB)
        self.assertEqual((february.credit_applied_chf, february.amount_due_chf), (Decimal("91.90"), Decimal("16.20")))
        self.assertEqual(credit_remaining(credit.pk), Decimal("0.00"))
        self.assertEqual(Credit.objects.with_status(CreditStatus.USED).get(), credit)

    def test_several_credits_are_used_oldest_first(self):
        now = django_timezone.now()
        newest = _credit(self.zev, self.participant, "100.00", created_at=now - timedelta(days=1))
        oldest = _credit(self.zev, self.participant, "40.00", created_at=now - timedelta(days=3))
        middle = _credit(self.zev, self.participant, "30.00", created_at=now - timedelta(days=2))
        invoice = self._generate()
        used = {a.credit_id: a.amount_chf for a in invoice.credit_applications.all()}
        self.assertEqual(used, {oldest.pk: Decimal("40.00"), middle.pk: Decimal("30.00"), newest.pk: Decimal("38.10")})
        self.assertEqual(invoice.credit_applied_chf, Decimal("108.10"))
        self.assertEqual(credit_remaining(newest.pk), Decimal("61.90"))

    def test_only_the_participants_own_credit_is_used(self):
        _credit(self.zev, self.other, "50.00")
        invoice = self._generate()
        self.assertEqual(invoice.credit_applied_chf, Decimal("0.00"))
        self.assertFalse(CreditApplication.objects.exists())

    def test_regeneration_releases_the_credit_and_the_replacement_reuses_it(self):
        credit = _credit(self.zev, self.participant, "50.00")
        first = self._generate()
        second = self._generate()
        self.assertFalse(Invoice.objects.filter(pk=first.pk).exists())
        application = CreditApplication.objects.get()
        self.assertEqual((application.invoice, application.amount_chf), (second, Decimal("50.00")))
        self.assertEqual(second.credit_applied_chf, Decimal("50.00"))
        self.assertEqual(credit_remaining(credit.pk), Decimal("0.00"))

    def test_cancellation_releases_the_credit_and_the_next_invoice_reuses_it(self):
        credit = _credit(self.zev, self.participant, "50.00")
        january = self._generate(JAN)
        approve_invoice(january)
        mark_invoice_sent(january)
        cancel_invoice(january)
        application = CreditApplication.objects.get(invoice=january)
        self.assertIsNotNone(application.released_at)
        january.refresh_from_db()
        # Frozen as issued: the cancelled invoice keeps showing what it said.
        self.assertEqual(january.credit_applied_chf, Decimal("50.00"))
        self.assertEqual(credit_remaining(credit.pk), Decimal("50.00"))
        february = self._generate(FEB)
        self.assertEqual(february.credit_applied_chf, Decimal("50.00"))
        self.assertEqual(credit_remaining(credit.pk), Decimal("0.00"))

    def test_a_draft_holds_its_credit_until_it_is_cancelled(self):
        credit = _credit(self.zev, self.participant, "50.00")
        draft = self._generate()
        self.assertEqual(credit_remaining(credit.pk), Decimal("0.00"))
        cancel_invoice(draft)
        self.assertEqual(credit_remaining(credit.pk), Decimal("50.00"))

    def test_nothing_is_applied_to_an_invoice_with_nothing_to_collect(self):
        credit = _credit(self.zev, self.participant, "50.00")
        for total in ("0.00", "-20.00"):
            invoice = _invoice(self.zev, self.participant, InvoiceStatus.DRAFT, total=total)
            self.assertEqual(apply_open_credits(invoice), Decimal("0"))
            self.assertEqual(invoice.amount_due_chf, Decimal(total))
        self.assertFalse(CreditApplication.objects.exists())
        self.assertEqual(credit_remaining(credit.pk), Decimal("50.00"))

    def test_the_participant_with_a_reversed_invoice_gets_the_cash_back_on_the_replacement(self):
        invoice = self._generate()
        approve_invoice(invoice)
        mark_invoice_sent(invoice)
        mark_invoice_paid(invoice)
        credit = correct_invoice(invoice, kind=CreditKind.REVERSAL, reason="Wrong readings")["credit"]
        replacement = self._generate()
        self.assertEqual(replacement.credit_applied_chf, credit.amount_chf)
        self.assertEqual(replacement.amount_due_chf, Decimal("0.00"))


class CorrectionWithAppliedCreditTests(TestCase):
    def setUp(self):
        self.owner = make_user("ca_corr_owner", UserRole.USER)
        self.zev = make_zev(self.owner, "Credit Correction ZEV")
        self.participant = make_participant(self.zev)
        self.today = django_timezone.localdate()
        self.earlier = _credit(self.zev, self.participant, "50.00")

    def _part_credit_paid(self):
        """Total 108.10, 50.00 settled by credit, 58.10 paid in cash."""
        invoice = _invoice(self.zev, self.participant, InvoiceStatus.SENT, applied="50.00")
        _apply(self.earlier, invoice, "50.00")
        mark_invoice_paid(invoice)
        return invoice

    def test_a_reversal_releases_the_applications_and_credits_the_cash_only(self):
        invoice = self._part_credit_paid()
        before = correct_invoice(invoice, kind=CreditKind.REVERSAL, reason="Wrong readings")
        self.assertEqual(before["credit"].amount_chf, Decimal("58.10"))
        self.assertEqual(before["released_chf"], Decimal("50.00"))
        self.assertEqual(invoice.status, InvoiceStatus.CANCELLED)
        self.assertIsNotNone(CreditApplication.objects.get(invoice=invoice).released_at)
        # The participant holds the cash credit again and the old credit again.
        self.assertEqual(credit_remaining(self.earlier.pk), Decimal("50.00"))
        self.assertEqual(credit_remaining(before["credit"].pk), Decimal("58.10"))

    def test_the_reversal_of_a_credit_only_invoice_issues_no_credit_note(self):
        invoice = _invoice(self.zev, self.participant, InvoiceStatus.SENT, total="50.00", applied="50.00")
        _apply(self.earlier, invoice, "50.00")
        mark_invoice_paid(invoice)
        self.assertFalse(Payment.objects.filter(invoice=invoice).exists())
        before = correct_invoice(invoice, kind=CreditKind.REVERSAL, reason="Wrong participant")
        self.assertIsNone(before["credit"])
        self.assertEqual(before["released_chf"], Decimal("50.00"))
        self.assertEqual(invoice.status, InvoiceStatus.CANCELLED)
        self.assertEqual(Credit.objects.count(), 1)
        self.assertEqual(credit_remaining(self.earlier.pk), Decimal("50.00"))

    def test_an_adjustment_is_capped_by_the_cash_paid(self):
        invoice = self._part_credit_paid()
        with self.assertRaisesMessage(InvoiceWorkflowError, "creditable amount of CHF 58.10"):
            correct_invoice(invoice, kind=CreditKind.ADJUSTMENT, reason="x", amount_chf=Decimal("58.11"))
        credit = correct_invoice(invoice, kind=CreditKind.ADJUSTMENT, reason="x", amount_chf=Decimal("58.10"))["credit"]
        self.assertEqual(credit.amount_chf, Decimal("58.10"))
        self.assertEqual(invoice.status, InvoiceStatus.PAID)
        self.assertIsNone(CreditApplication.objects.get(invoice=invoice).released_at)

    def test_an_invoice_settled_by_credit_alone_cannot_be_partially_credited(self):
        invoice = _invoice(self.zev, self.participant, InvoiceStatus.SENT, total="50.00", applied="50.00")
        _apply(self.earlier, invoice, "50.00")
        mark_invoice_paid(invoice)
        with self.assertRaisesMessage(InvoiceWorkflowError, "creditable amount of CHF 0.00"):
            correct_invoice(invoice, kind=CreditKind.ADJUSTMENT, reason="x", amount_chf=Decimal("5.00"))

    def test_a_reversal_with_nothing_to_give_back_is_still_refused(self):
        invoice = _invoice(self.zev, self.participant, InvoiceStatus.SENT)
        record_payment(invoice, amount_chf=Decimal("108.10"), paid_on=self.today)
        correct_invoice(invoice, kind=CreditKind.ADJUSTMENT, reason="a", amount_chf=Decimal("108.10"))
        with self.assertRaisesMessage(InvoiceWorkflowError, "already been credited"):
            correct_invoice(invoice, kind=CreditKind.REVERSAL, reason="b")

    def test_the_audit_metadata_names_the_released_credit(self):
        client = APIClient()
        auth(client, self.owner)
        invoice = _invoice(self.zev, self.participant, InvoiceStatus.SENT, total="50.00", applied="50.00")
        _apply(self.earlier, invoice, "50.00")
        mark_invoice_paid(invoice)
        response = client.post(f"{INVOICES}/{invoice.pk}/correct/", {"kind": "reversal", "reason": "x"}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertIsNone(response.data["credit"])
        self.assertEqual(response.data["invoice"]["status"], InvoiceStatus.CANCELLED)
        event = AuditEvent.objects.get(action_type="invoice.correct", target_id=str(invoice.pk))
        self.assertEqual(event.metadata_json["released_chf"], "50.00")
        self.assertIsNone(event.metadata_json["credit_id"])
        self.assertIsNone(event.metadata_json["credit_number"])


class PaymentWithAppliedCreditTests(TestCase):
    def setUp(self):
        self.owner = make_user("ca_pay_owner", UserRole.USER)
        self.zev = make_zev(self.owner, "Credit Pay ZEV")
        self.participant = make_participant(self.zev)
        self.today = django_timezone.localdate()

    def test_record_payment_is_limited_to_the_amount_due(self):
        invoice = _invoice(self.zev, self.participant, InvoiceStatus.SENT, applied="50.00")
        with self.assertRaisesMessage(InvoiceWorkflowError, "outstanding amount of CHF 58.10"):
            record_payment(invoice, amount_chf=Decimal("58.11"), paid_on=self.today)
        record_payment(invoice, amount_chf=Decimal("20.00"), paid_on=self.today)
        record_payment(invoice, amount_chf=Decimal("38.10"), paid_on=self.today)
        self.assertEqual(invoice.status, InvoiceStatus.PAID)

    def test_a_credit_covered_invoice_takes_no_payment_but_can_be_marked_paid(self):
        invoice = _invoice(self.zev, self.participant, InvoiceStatus.SENT, total="50.00", applied="50.00")
        with self.assertRaisesMessage(InvoiceWorkflowError, "credit applied covers this invoice"):
            record_payment(invoice, amount_chf=Decimal("1.00"), paid_on=self.today)
        before = mark_invoice_paid(invoice)
        self.assertIsNone(before["payment"])
        self.assertEqual(invoice.status, InvoiceStatus.PAID)
        self.assertFalse(Payment.objects.exists())

    def test_mark_paid_books_the_rest_of_the_amount_due(self):
        invoice = _invoice(self.zev, self.participant, InvoiceStatus.SENT, applied="50.00")
        record_payment(invoice, amount_chf=Decimal("10.00"), paid_on=self.today)
        before = mark_invoice_paid(invoice)
        self.assertEqual(before["payment"].amount_chf, Decimal("48.10"))

    def test_a_payout_keeps_the_existing_message(self):
        invoice = _invoice(self.zev, self.participant, InvoiceStatus.SENT, total="-20.00")
        with self.assertRaisesMessage(InvoiceWorkflowError, "nothing to collect"):
            record_payment(invoice, amount_chf=Decimal("1.00"), paid_on=self.today)

    def test_the_amount_due_is_derived_from_the_total(self):
        invoice = _invoice(self.zev, self.participant, InvoiceStatus.DRAFT, total="30.00", applied="50.00")
        self.assertEqual(invoice.amount_due_chf, Decimal("0"))
        invoice.total_chf = Decimal("200.00")
        self.assertEqual(invoice.amount_due_chf, Decimal("150.00"))
        invoice.total_chf = Decimal("-5.00")
        self.assertEqual(invoice.amount_due_chf, Decimal("-5.00"))


class RefundWorkflowTests(TestCase):
    def setUp(self):
        self.owner = make_user("ca_refund_owner", UserRole.USER)
        self.zev = make_zev(self.owner, "Credit Refund ZEV")
        self.participant = make_participant(self.zev)
        self.today = django_timezone.localdate()

    def test_refunding_books_the_remainder(self):
        credit = _credit(self.zev, self.participant, "100.00")
        _apply(credit, _invoice(self.zev, self.participant, InvoiceStatus.SENT, total="30.00", applied="30.00"), "30.00")
        booked = refund_credit(credit, refunded_on=self.today, note=" IBAN CH93 ", user=self.owner)
        self.assertEqual(booked["amount"], Decimal("70.00"))
        credit.refresh_from_db()
        self.assertEqual(
            (credit.refunded_chf, credit.refunded_on, credit.refund_note),
            (Decimal("70.00"), self.today, "IBAN CH93"),
        )
        self.assertEqual(credit_remaining(credit.pk), Decimal("0.00"))
        self.assertEqual(Credit.objects.with_status(CreditStatus.REFUNDED).get(), credit)
        self.assertFalse(Credit.objects.with_status(CreditStatus.OPEN).exists())

    def test_nothing_remains_to_refund_twice(self):
        credit = _credit(self.zev, self.participant, "100.00")
        refund_credit(credit, refunded_on=self.today)
        with self.assertRaisesMessage(InvoiceWorkflowError, "Nothing remains to refund."):
            refund_credit(credit, refunded_on=self.today)

    def test_the_refund_date_cannot_be_in_the_future(self):
        credit = _credit(self.zev, self.participant, "100.00")
        with self.assertRaisesMessage(InvoiceWorkflowError, "cannot be in the future"):
            refund_credit(credit, refunded_on=self.today + timedelta(days=1))
        credit.refresh_from_db()
        self.assertEqual(credit.refunded_chf, Decimal("0.00"))

    def test_credit_held_by_a_draft_is_not_refundable_until_the_draft_is_gone(self):
        credit = _credit(self.zev, self.participant, "50.00")
        draft = _invoice(self.zev, self.participant, InvoiceStatus.DRAFT, total="80.00", applied="50.00")
        _apply(credit, draft, "50.00")
        with self.assertRaisesMessage(InvoiceWorkflowError, "Nothing remains to refund."):
            refund_credit(credit, refunded_on=self.today)
        draft.delete()
        self.assertEqual(refund_credit(credit, refunded_on=self.today)["amount"], Decimal("50.00"))

    def test_a_partly_used_credit_reads_open_until_refunded(self):
        credit = _credit(self.zev, self.participant, "100.00")
        _apply(credit, _invoice(self.zev, self.participant, InvoiceStatus.SENT, total="30.00", applied="30.00"), "30.00")
        self.assertEqual(Credit.objects.with_status(CreditStatus.OPEN).get(), credit)
        self.assertEqual(credit.status, CreditStatus.OPEN)
        self.assertEqual(credit.remaining(), Decimal("70.00"))


class RefundAndCreditApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = make_user("ca_api_owner", UserRole.USER)
        self.admin = make_user("ca_api_admin", UserRole.ADMIN)
        self.zev = make_zev(self.owner, "Credit Refund API ZEV")
        self.tenant = make_user("ca_api_tenant", UserRole.USER)
        self.participant = make_participant(self.zev, user=self.tenant)
        self.credit = _credit(self.zev, self.participant, "100.00")
        self.today = django_timezone.localdate().isoformat()
        auth(self.client, self.owner)

    def _refund(self, credit=None, **body):
        body.setdefault("refunded_on", self.today)
        return self.client.post(f"{CREDITS}/{(credit or self.credit).pk}/refund/", body, format="json")

    def test_a_manager_refunds_the_remainder(self):
        invoice = _invoice(self.zev, self.participant, InvoiceStatus.SENT, total="30.00", applied="30.00")
        _apply(self.credit, invoice, "30.00")
        response = self._refund(note="Bank transfer")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["remaining_chf"], "0.00")
        self.assertEqual(response.data["status"], "refunded")
        self.assertEqual(response.data["refunded_chf"], "70.00")
        self.assertEqual(response.data["refunded_on"], self.today)
        self.assertEqual(response.data["refund_note"], "Bank transfer")
        self.assertEqual(
            [(a["invoice_number"], a["amount_chf"]) for a in response.data["applications"]],
            [(invoice.invoice_number, "30.00")],
        )
        event = AuditEvent.objects.get(action_type="credit.refund", target_id=str(self.credit.pk))
        self.assertEqual(event.status, AuditEventStatus.SUCCESS)
        self.assertEqual(event.target_type, "invoices.Credit")
        self.assertEqual(event.metadata_json, {"amount_chf": "70.00", "refunded_on": self.today})

    def test_nothing_remains_returns_400_and_audits_the_denial(self):
        self.assertEqual(self._refund().status_code, 200)
        response = self._refund()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"], "Nothing remains to refund.")
        denied = AuditEvent.objects.filter(action_type="credit.refund", status=AuditEventStatus.DENIED)
        self.assertEqual(denied.count(), 1)

    def test_the_body_is_validated(self):
        response = self.client.post(f"{CREDITS}/{self.credit.pk}/refund/", {}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self._refund(refunded_on="2999-01-01").status_code, 400)
        self.credit.refresh_from_db()
        self.assertEqual(self.credit.refunded_chf, Decimal("0.00"))

    def test_a_viewer_cannot_refund(self):
        viewer = make_user("ca_api_viewer", UserRole.USER)
        ZevAccessGrant.objects.create(zev=self.zev, user=viewer, role=ZevAccessRole.VIEWER, valid_from=date(2026, 1, 1))
        auth(self.client, viewer)
        self.assertIn(self._refund().status_code, (403, 404))
        self.assertEqual(self.client.get(f"{CREDITS}/{self.credit.pk}/").status_code, 200)
        self.credit.refresh_from_db()
        self.assertEqual(self.credit.refunded_chf, Decimal("0.00"))

    def test_a_participant_cannot_refund_their_own_credit(self):
        auth(self.client, self.tenant)
        self.assertIn(self._refund().status_code, (403, 404))
        self.credit.refresh_from_db()
        self.assertEqual(self.credit.refunded_chf, Decimal("0.00"))

    def test_a_disabled_zev_refuses_non_admins_but_not_admins(self):
        self.zev.disabled_at = django_timezone.now()
        self.zev.save(update_fields=["disabled_at"])
        response = self._refund()
        self.assertEqual(response.status_code, 400)
        self.assertIn("disabled", response.data["error"])
        self.assertTrue(AuditEvent.objects.filter(action_type="credit.refund", status=AuditEventStatus.DENIED).exists())
        auth(self.client, self.admin)
        self.assertEqual(self._refund().status_code, 200)

    def test_the_credit_list_filters_by_status(self):
        used = _credit(self.zev, self.participant, "20.00")
        _apply(used, _invoice(self.zev, self.participant, InvoiceStatus.SENT, total="20.00", applied="20.00"), "20.00")
        refunded = _credit(self.zev, self.participant, "10.00")
        self.assertEqual(self._refund(refunded).status_code, 200)

        def ids(status):
            response = self.client.get(f"{CREDITS}/", {"status": status})
            self.assertEqual(response.status_code, 200, response.data)
            rows = response.data["results"] if isinstance(response.data, dict) else response.data
            return {row["id"] for row in rows}

        self.assertEqual(ids("open"), {str(self.credit.pk)})
        self.assertEqual(ids("used"), {str(used.pk)})
        self.assertEqual(ids("refunded"), {str(refunded.pk)})
        self.assertEqual(self.client.get(f"{CREDITS}/", {"status": "bogus"}).status_code, 400)

    def test_the_credit_shows_where_it_was_applied(self):
        invoice = _invoice(self.zev, self.participant, InvoiceStatus.SENT, total="30.00", applied="30.00")
        _apply(self.credit, invoice, "30.00")
        data = self.client.get(f"{CREDITS}/{self.credit.pk}/").data
        self.assertEqual(data["remaining_chf"], "70.00")
        self.assertEqual(data["status"], "open")
        self.assertEqual(data["applications"][0]["invoice"], invoice.pk)
        self.assertEqual(data["applications"][0]["invoice_number"], invoice.invoice_number)
        self.assertIsNone(data["applications"][0]["released_at"])


class InvoiceSerializerTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = make_user("ca_ser_owner", UserRole.USER)
        self.zev = make_zev(self.owner, "Credit Serializer ZEV")
        self.tenant = make_user("ca_ser_tenant", UserRole.USER)
        self.participant = make_participant(self.zev, user=self.tenant)
        self.credit = _credit(self.zev, self.participant, "50.00")
        self.invoice = _invoice(self.zev, self.participant, InvoiceStatus.SENT, applied="50.00")
        _apply(self.credit, self.invoice, "50.00")

    def test_list_and_detail_carry_the_amount_due(self):
        auth(self.client, self.owner)
        row = self.client.get(f"{INVOICES}/").data
        row = (row["results"] if isinstance(row, dict) else row)[0]
        self.assertEqual((row["total_chf"], row["credit_applied_chf"], row["amount_due_chf"]), ("108.10", "50.00", "58.10"))
        self.assertEqual(row["outstanding_chf"], "58.10")
        self.assertNotIn("credit_applications", row)
        detail = self.client.get(f"{INVOICES}/{self.invoice.pk}/").data
        self.assertEqual(detail["amount_due_chf"], "58.10")
        self.assertEqual(
            [(a["credit"], a["credit_number"], a["amount_chf"], a["released_at"]) for a in detail["credit_applications"]],
            [(self.credit.pk, self.credit.credit_number, "50.00", None)],
        )

    def test_the_participant_sees_the_credit_applied_to_their_invoice(self):
        auth(self.client, self.tenant)
        detail = self.client.get(f"{INVOICES}/{self.invoice.pk}/").data
        self.assertEqual(detail["credit_applications"][0]["credit_number"], self.credit.credit_number)
        self.assertEqual(detail["amount_due_chf"], "58.10")
        self.assertIsNone(detail["payments"])

    def test_an_application_names_the_invoice_its_credit_came_from(self):
        source = _invoice(self.zev, self.participant, InvoiceStatus.CANCELLED, period=(date(2025, 1, 1), date(2025, 1, 31)))
        Credit.objects.filter(pk=self.credit.pk).update(source_invoice=source)
        auth(self.client, self.owner)
        application = self.client.get(f"{INVOICES}/{self.invoice.pk}/").data["credit_applications"][0]
        self.assertEqual(
            (application["credit_source_invoice"], application["credit_source_invoice_number"]),
            (str(source.pk), source.invoice_number),
        )

    def test_an_application_without_a_source_invoice_says_so(self):
        auth(self.client, self.owner)
        application = self.client.get(f"{INVOICES}/{self.invoice.pk}/").data["credit_applications"][0]
        self.assertIsNone(application["credit_source_invoice"])
        self.assertIsNone(application["credit_source_invoice_number"])

    def test_a_released_application_stays_visible_as_released(self):
        cancel_invoice_target = _invoice(self.zev, self.participant, InvoiceStatus.DRAFT, total="10.00", applied="10.00")
        other = _credit(self.zev, self.participant, "10.00")
        _apply(other, cancel_invoice_target, "10.00")
        cancel_invoice(cancel_invoice_target)
        auth(self.client, self.owner)
        detail = self.client.get(f"{INVOICES}/{cancel_invoice_target.pk}/").data
        self.assertIsNotNone(detail["credit_applications"][0]["released_at"])
        self.assertEqual(detail["credit_applied_chf"], "10.00")
        self.assertEqual(detail["outstanding_chf"], "0.00")

    def test_the_list_query_count_does_not_grow_with_invoices(self):
        auth(self.client, self.owner)

        def queries():
            with CaptureQueriesContext(connection) as captured:
                self.assertEqual(self.client.get(f"{INVOICES}/").status_code, 200)
            return len(captured)

        baseline = queries()
        for index in range(4):
            other = _credit(self.zev, self.participant, "5.00")
            extra = _invoice(self.zev, self.participant, InvoiceStatus.SENT, total="20.00", applied="5.00")
            _apply(other, extra, "5.00")
        self.assertEqual(queries(), baseline)

    def test_the_public_payload_carries_the_amount_due(self):
        from invoices.views_public import _serialize

        payload = _serialize(self.invoice)
        self.assertEqual((payload["total_chf"], payload["credit_applied_chf"], payload["amount_due_chf"]),
                         ("108.10", "50.00", "58.10"))


class AmountDueDocumentTests(TestCase):
    """The QR bill, the PDF and the email ask for the amount due, not the total."""

    def setUp(self):
        self.owner = make_user("ca_doc_owner", UserRole.USER)
        self.zev = create_managed_zev(
            name="Credit Doc ZEV", owner=self.owner, zev_type="vzev", start_date=JAN[0],
            billing_interval="monthly", invoice_prefix="Q", bank_iban="CH9300762011623852957",
        )
        owner_participant = Participant.objects.create(
            zev=self.zev, user=self.owner, first_name="Test", last_name="Owner", email="owner@example.com",
            address_line1="Bahnhofstrasse 1", postal_code="8001", city="Zuerich", valid_from=JAN[0],
        )
        from zev.parties import ensure_initial_roles
        ensure_initial_roles(owner_participant.zev, owner_participant.party, owner_participant.valid_from)
        self.participant = Participant.objects.create(
            zev=self.zev, first_name="Alice", last_name="Muster", email="alice@example.com",
            address_line1="Musterweg 3", postal_code="3000", city="Bern", valid_from=JAN[0],
        )
        self.credit = _credit(self.zev, self.participant, "50.00")

    def _qr_amount(self, invoice):
        with mock.patch("qrbill.QRBill") as qrbill_cls:
            qrbill_cls.return_value.as_svg.side_effect = lambda output: output.write(b"<svg/>")
            svg = _build_qr_svg(invoice)
        return svg, (qrbill_cls.call_args.kwargs["amount"] if qrbill_cls.called else None)

    def test_the_qr_amount_is_the_amount_due(self):
        invoice = _invoice(self.zev, self.participant, InvoiceStatus.APPROVED, applied="50.00")
        svg, amount = self._qr_amount(invoice)
        self.assertEqual(svg, "<svg/>")
        self.assertEqual(amount, "58.10")

    def test_there_is_no_qr_slip_when_the_credit_covers_the_invoice(self):
        invoice = _invoice(self.zev, self.participant, InvoiceStatus.APPROVED, total="50.00", applied="50.00")
        svg, amount = self._qr_amount(invoice)
        self.assertIsNone(svg)
        self.assertIsNone(amount)

    def test_the_pdf_lists_the_credit_and_the_amount_due(self):
        invoice = _invoice(self.zev, self.participant, InvoiceStatus.APPROVED, applied="50.00")
        _apply(self.credit, invoice, "50.00")
        tr = INVOICE_TRANSLATIONS["de"]
        markup = _render_invoice_markup(invoice)
        self.assertIn(tr["credit_applied"].format(number=self.credit.credit_number), markup)
        self.assertIn("CHF -50.00", markup)
        self.assertIn(tr["amount_due"], markup)
        self.assertIn("CHF 58.10", markup)

    def test_the_pdf_has_no_credit_lines_without_credit(self):
        invoice = _invoice(self.zev, self.participant, InvoiceStatus.APPROVED)
        markup = _render_invoice_markup(invoice)
        self.assertNotIn(INVOICE_TRANSLATIONS["de"]["amount_due"], markup)

    def test_the_credit_lines_are_translated(self):
        for lang in ("de", "fr", "it", "en"):
            self.assertIn("{number}", INVOICE_TRANSLATIONS[lang]["credit_applied"])
            self.assertTrue(INVOICE_TRANSLATIONS[lang]["amount_due"])

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_the_email_variable_is_the_amount_due(self):
        self.zev.email_body_template = "total={total_chf} due={amount_due_chf}"
        self.zev.save(update_fields=["email_body_template"])
        invoice = _invoice(self.zev, self.participant, InvoiceStatus.APPROVED, applied="50.00")
        invoice.pdf_file.save("invoice_test.pdf", ContentFile(b"PDF"), save=True)
        send_invoice_email_task.run(str(invoice.pk), "recipient@example.com")
        self.assertEqual(mail.outbox[-1].body, "total=108.10 due=58.10")

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_the_default_email_asks_for_the_amount_due(self):
        invoice = _invoice(self.zev, self.participant, InvoiceStatus.APPROVED, applied="50.00")
        invoice.pdf_file.save("invoice_test.pdf", ContentFile(b"PDF"), save=True)
        send_invoice_email_task.run(str(invoice.pk), "recipient@example.com")
        self.assertIn("CHF 58.10", mail.outbox[-1].body)
        self.assertNotIn("108.10", mail.outbox[-1].body)


class DashboardRevenueTests(TestCase):
    def test_revenue_is_billed_less_partial_credits(self):
        admin = make_user("ca_dash_admin", UserRole.ADMIN)
        owner = make_user("ca_dash_owner", UserRole.USER)
        zev = make_zev(owner, "Credit Dashboard ZEV")
        participant = make_participant(zev)
        _invoice(zev, participant, InvoiceStatus.DRAFT, total="1000.00")  # never issued
        _invoice(zev, participant, InvoiceStatus.APPROVED, total="10.00")
        cancelled = _invoice(zev, participant, InvoiceStatus.SENT, total="500.00")
        cancel_invoice(cancelled)
        paid = _invoice(zev, participant, InvoiceStatus.SENT, total="100.00")
        mark_invoice_paid(paid)
        correct_invoice(paid, kind=CreditKind.ADJUSTMENT, reason="x", amount_chf=Decimal("15.00"))
        reversed_invoice = _invoice(zev, participant, InvoiceStatus.SENT, total="200.00")
        mark_invoice_paid(reversed_invoice)
        correct_invoice(reversed_invoice, kind=CreditKind.REVERSAL, reason="x")
        client = APIClient()
        auth(client, admin)
        response = client.get("/api/v1/invoices/invoices/dashboard/")
        self.assertEqual(response.status_code, 200)
        # 10 approved + 100 paid - 15 adjustment; the reversed and cancelled ones are out.
        self.assertEqual(response.data["invoices"]["total_revenue"], 95.0)


class ParticipantDeletionTests(TestCase):
    """Pins what happens when a participant with credits is deleted (out of scope to redesign)."""

    def test_a_participant_with_credit_notes_cannot_be_deleted(self):
        owner = make_user("ca_del_owner", UserRole.USER)
        zev = make_zev(owner, "Credit Delete ZEV")
        participant = make_participant(zev)
        invoice = _invoice(zev, participant, InvoiceStatus.SENT)
        mark_invoice_paid(invoice)
        correct_invoice(invoice, kind=CreditKind.ADJUSTMENT, reason="x", amount_chf=Decimal("5.00"))
        with self.assertRaises(ProtectedError):
            participant.delete()


@skipUnless(connection.vendor == "postgresql", "needs row locks, which SQLite does not have")
class ConcurrentApplicationTests(TransactionTestCase):
    def test_two_generations_do_not_use_one_credit_twice(self):
        owner = make_user("ca_conc_owner", UserRole.USER)
        zev = make_zev(owner, "Credit Concurrency ZEV")
        participant = make_participant(zev)
        credit = _credit(zev, participant, "100.00")
        first = _invoice(zev, participant, InvoiceStatus.DRAFT, total="80.00", period=JAN)
        second = _invoice(zev, participant, InvoiceStatus.DRAFT, total="80.00", period=FEB)
        holding = threading.Event()
        errors = []

        def run_first():
            try:
                from django.db import transaction
                with transaction.atomic():
                    apply_open_credits(Invoice.objects.get(pk=first.pk))
                    holding.set()
                    time.sleep(1.0)  # the credit stays locked until this commits
            except Exception as exc:  # pragma: no cover - surfaced below
                errors.append(exc)
                holding.set()
            finally:
                connections.close_all()

        def run_second():
            try:
                from django.db import transaction
                holding.wait(10)
                with transaction.atomic():
                    apply_open_credits(Invoice.objects.get(pk=second.pk))
            except Exception as exc:  # pragma: no cover
                errors.append(exc)
            finally:
                connections.close_all()

        threads = [threading.Thread(target=run_first), threading.Thread(target=run_second)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(30)
        self.assertEqual(errors, [])
        applied = sum(a.amount_chf for a in CreditApplication.objects.filter(credit=credit))
        self.assertEqual(applied, Decimal("100.00"))
        self.assertEqual(credit_remaining(credit.pk), Decimal("0.00"))
        by_invoice = {a.invoice_id: a.amount_chf for a in CreditApplication.objects.all()}
        self.assertEqual(by_invoice, {first.pk: Decimal("80.00"), second.pk: Decimal("20.00")})
