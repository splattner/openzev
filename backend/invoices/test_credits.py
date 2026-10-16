"""Credit notes and the correction of paid invoices (#388, ADR 0037)."""

from datetime import date
from decimal import Decimal
from unittest import mock

from django.core.files.base import ContentFile
from django.test import TestCase
from django.utils import timezone as django_timezone
from rest_framework.test import APIClient

from accounts.models import UserRole
from audit.models import AuditEvent, AuditEventStatus
from invoices.annual_statement import generate_annual_statement_pdf
from invoices.credit_pdf import build_credit_context
from invoices.models import Credit, CreditKind, Invoice, InvoicePdfStatus, InvoiceStatus
from invoices.tasks import generate_credit_pdf_task
from invoices.test_helpers import make_invoice, make_participant, make_user, make_zev
from invoices.workflow import (
    InvoiceWorkflowError,
    cancel_invoice,
    correct_invoice,
    credit_vat_split,
    delete_payment,
    invoice_vat_mode,
    mark_invoice_paid,
    record_payment,
)
from testing.helpers import authenticate as auth
from zev.models import VatMode, ZevAccessGrant, ZevAccessRole

INVOICES = "/api/v1/invoices/invoices"
CREDITS = "/api/v1/invoices/credits"


def _issued(zev, participant, status, total="108.10", vat_mode=VatMode.REGISTERED, **kwargs):
    """An invoice of ``total`` in the given VAT mode (registered: 8.1 % on 100.00)."""
    invoice = make_invoice(zev, participant, status, **kwargs)
    fields = {"total_chf": Decimal(total), "approved_at": django_timezone.now(), "sent_at": django_timezone.now()}
    if vat_mode == VatMode.REGISTERED:
        fields.update(
            subtotal_chf=Decimal("100.00"), vat_rate=Decimal("0.0810"), vat_base_chf=Decimal("100.00"),
            vat_chf=Decimal("8.10"),
        )
    elif vat_mode == VatMode.INCLUSIVE:
        fields.update(subtotal_chf=Decimal(total), embedded_vat_chf=Decimal("8.10"))
    else:
        fields.update(subtotal_chf=Decimal(total))
    Invoice.objects.filter(pk=invoice.pk).update(**fields)
    invoice.refresh_from_db()
    return invoice


def _paid(zev, participant, **kwargs):
    invoice = _issued(zev, participant, InvoiceStatus.SENT, **kwargs)
    mark_invoice_paid(invoice)
    return invoice


class CreditWorkflowTests(TestCase):
    def setUp(self):
        self.owner = make_user("cr_owner", UserRole.USER)
        self.zev = make_zev(self.owner, "Credit ZEV")
        self.participant = make_participant(self.zev)
        self.today = django_timezone.localdate()

    def test_reversal_of_paid_invoice_cancels_it_and_credits_what_was_paid(self):
        invoice = _paid(self.zev, self.participant)
        before = correct_invoice(invoice, kind=CreditKind.REVERSAL, reason="Wrong readings", user=self.owner)
        credit = before["credit"]
        self.assertEqual(before["status"], InvoiceStatus.PAID)
        self.assertEqual(invoice.status, InvoiceStatus.CANCELLED)
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, InvoiceStatus.CANCELLED)
        self.assertEqual(credit.amount_chf, Decimal("108.10"))
        self.assertEqual(credit.kind, CreditKind.REVERSAL)
        self.assertEqual(credit.source_invoice, invoice)
        self.assertEqual(credit.participant, self.participant)
        self.assertEqual(credit.reason, "Wrong readings")
        self.assertEqual(credit.created_by, self.owner)
        self.assertEqual(credit.pdf_status, InvoicePdfStatus.PENDING)

    def test_credit_numbers_use_their_own_sequence(self):
        first = _paid(self.zev, self.participant)
        second = _paid(self.zev, self.participant)
        counter_before = Invoice.objects.count()
        a = correct_invoice(first, kind=CreditKind.REVERSAL, reason="x")["credit"]
        b = correct_invoice(second, kind=CreditKind.REVERSAL, reason="x")["credit"]
        self.assertEqual((a.credit_number, b.credit_number), ("CN-00001", "CN-00002"))
        self.zev.refresh_from_db()
        self.assertEqual(self.zev.credit_note_counter, 3)
        self.assertEqual(self.zev.invoice_counter, 1)
        self.assertEqual(Invoice.objects.count(), counter_before)

    def test_credit_note_prefix_is_configurable(self):
        self.zev.credit_note_prefix = "GS"
        self.zev.save(update_fields=["credit_note_prefix"])
        credit = correct_invoice(_paid(self.zev, self.participant), kind=CreditKind.REVERSAL, reason="x")["credit"]
        self.assertEqual(credit.credit_number, "GS-00001")

    def test_reversal_of_underpaid_sent_invoice_credits_the_payments_and_scales_vat(self):
        invoice = _issued(self.zev, self.participant, InvoiceStatus.SENT)
        record_payment(invoice, amount_chf=Decimal("54.05"), paid_on=self.today)
        credit = correct_invoice(invoice, kind=CreditKind.REVERSAL, reason="Moved out")["credit"]
        self.assertEqual(invoice.status, InvoiceStatus.CANCELLED)
        self.assertEqual(credit.amount_chf, Decimal("54.05"))
        # 54.05 * 0.081 / 1.081 = 4.05
        self.assertEqual(credit.vat_chf, Decimal("4.05"))
        self.assertEqual(credit.vat_mode, VatMode.REGISTERED)

    def test_full_reversal_copies_the_vat_exactly(self):
        invoice = _paid(self.zev, self.participant)
        credit = correct_invoice(invoice, kind=CreditKind.REVERSAL, reason="x")["credit"]
        self.assertEqual(credit.vat_chf, Decimal("8.10"))
        self.assertEqual(credit.vat_rate, Decimal("0.0810"))
        self.assertIsNone(credit.embedded_vat_chf)

    def test_full_reversal_copies_the_embedded_vat_of_an_inclusive_invoice(self):
        invoice = _paid(self.zev, self.participant, total="108.10", vat_mode=VatMode.INCLUSIVE)
        credit = correct_invoice(invoice, kind=CreditKind.REVERSAL, reason="x")["credit"]
        self.assertEqual(credit.vat_mode, VatMode.INCLUSIVE)
        self.assertEqual(credit.vat_chf, Decimal("0"))
        self.assertEqual(credit.embedded_vat_chf, Decimal("8.10"))

    def test_vat_split_per_mode_for_a_partial_amount(self):
        registered = _issued(self.zev, self.participant, InvoiceStatus.PAID)
        inclusive = _issued(self.zev, self.participant, InvoiceStatus.PAID, vat_mode=VatMode.INCLUSIVE)
        plain = _issued(self.zev, self.participant, InvoiceStatus.PAID, vat_mode=VatMode.NOT_REGISTERED)
        amount = Decimal("54.05")
        self.assertEqual(invoice_vat_mode(registered), VatMode.REGISTERED)
        self.assertEqual(invoice_vat_mode(inclusive), VatMode.INCLUSIVE)
        self.assertEqual(invoice_vat_mode(plain), VatMode.NOT_REGISTERED)
        self.assertEqual(credit_vat_split(registered, amount)["vat_chf"], Decimal("4.05"))
        split = credit_vat_split(inclusive, amount)
        self.assertEqual((split["vat_chf"], split["embedded_vat_chf"]), (Decimal("0"), Decimal("4.05")))
        split = credit_vat_split(plain, amount)
        self.assertEqual((split["vat_chf"], split["embedded_vat_chf"]), (Decimal("0"), None))

    def test_the_vat_mode_comes_from_the_invoice_not_from_the_zev(self):
        invoice = _paid(self.zev, self.participant, vat_mode=VatMode.NOT_REGISTERED)
        self.zev.vat_mode = VatMode.INCLUSIVE
        self.zev.save(update_fields=["vat_mode"])
        credit = correct_invoice(invoice, kind=CreditKind.ADJUSTMENT, reason="x", amount_chf=Decimal("10.00"))["credit"]
        self.assertEqual(credit.vat_mode, VatMode.NOT_REGISTERED)
        self.assertIsNone(credit.embedded_vat_chf)

    def test_adjustment_within_the_cap_keeps_the_invoice(self):
        invoice = _paid(self.zev, self.participant)
        credit = correct_invoice(
            invoice, kind=CreditKind.ADJUSTMENT, reason="Overcharged", amount_chf=Decimal("20.00"),
        )["credit"]
        self.assertEqual(invoice.status, InvoiceStatus.PAID)
        invoice.refresh_from_db()
        self.assertEqual((invoice.status, invoice.total_chf), (InvoiceStatus.PAID, Decimal("108.10")))
        self.assertEqual(credit.amount_chf, Decimal("20.00"))
        self.assertEqual(credit.vat_chf, Decimal("1.50"))  # 20 * 0.081 / 1.081

    def test_adjustments_are_capped_by_what_was_paid_less_earlier_credits(self):
        invoice = _paid(self.zev, self.participant)
        correct_invoice(invoice, kind=CreditKind.ADJUSTMENT, reason="a", amount_chf=Decimal("100.00"))
        with self.assertRaisesMessage(InvoiceWorkflowError, "creditable amount of CHF 8.10"):
            correct_invoice(invoice, kind=CreditKind.ADJUSTMENT, reason="b", amount_chf=Decimal("8.11"))
        correct_invoice(invoice, kind=CreditKind.ADJUSTMENT, reason="b", amount_chf=Decimal("8.10"))
        self.assertEqual(Credit.objects.filter(source_invoice=invoice).count(), 2)

    def test_adjustment_needs_a_positive_amount(self):
        invoice = _paid(self.zev, self.participant)
        for amount in (None, Decimal("0"), Decimal("-1.00")):
            with self.assertRaisesMessage(InvoiceWorkflowError, "must be positive"):
                correct_invoice(invoice, kind=CreditKind.ADJUSTMENT, reason="x", amount_chf=amount)
        self.assertFalse(Credit.objects.exists())

    def test_reversal_after_an_adjustment_credits_the_rest(self):
        invoice = _paid(self.zev, self.participant)
        correct_invoice(invoice, kind=CreditKind.ADJUSTMENT, reason="a", amount_chf=Decimal("30.00"))
        credit = correct_invoice(invoice, kind=CreditKind.REVERSAL, reason="b")["credit"]
        self.assertEqual(credit.amount_chf, Decimal("78.10"))
        self.assertEqual(invoice.status, InvoiceStatus.CANCELLED)
        # Not the invoice's full total: the VAT is scaled, not copied.
        self.assertEqual(credit.vat_chf, Decimal("5.85"))

    def test_nothing_left_to_reverse_is_refused(self):
        invoice = _paid(self.zev, self.participant)
        correct_invoice(invoice, kind=CreditKind.ADJUSTMENT, reason="a", amount_chf=Decimal("108.10"))
        with self.assertRaisesMessage(InvoiceWorkflowError, "already been credited"):
            correct_invoice(invoice, kind=CreditKind.REVERSAL, reason="b")
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, InvoiceStatus.PAID)

    def test_payout_invoices_are_refused(self):
        invoice = _issued(self.zev, self.participant, InvoiceStatus.SENT, total="-40.00", vat_mode=VatMode.NOT_REGISTERED)
        mark_invoice_paid(invoice)
        with self.assertRaisesMessage(InvoiceWorkflowError, "payouts"):
            correct_invoice(invoice, kind=CreditKind.REVERSAL, reason="x")
        self.assertFalse(Credit.objects.exists())

    def test_sent_invoice_without_payments_is_refused(self):
        invoice = _issued(self.zev, self.participant, InvoiceStatus.SENT)
        with self.assertRaisesMessage(InvoiceWorkflowError, "Cancel a sent invoice that has no payments instead"):
            correct_invoice(invoice, kind=CreditKind.REVERSAL, reason="x")

    def test_other_statuses_are_refused(self):
        for status in (InvoiceStatus.DRAFT, InvoiceStatus.APPROVED, InvoiceStatus.CANCELLED):
            invoice = make_invoice(self.zev, self.participant, status)
            with self.assertRaises(InvoiceWorkflowError):
                correct_invoice(invoice, kind=CreditKind.REVERSAL, reason="x")
        self.assertFalse(Credit.objects.exists())

    def test_a_reason_is_required(self):
        invoice = _paid(self.zev, self.participant)
        with self.assertRaisesMessage(InvoiceWorkflowError, "reason is required"):
            correct_invoice(invoice, kind=CreditKind.REVERSAL, reason="   ")

    def test_a_correction_is_not_repeatable_after_a_reversal(self):
        invoice = _paid(self.zev, self.participant)
        correct_invoice(invoice, kind=CreditKind.REVERSAL, reason="x")
        with self.assertRaisesMessage(InvoiceWorkflowError, "already cancelled"):
            correct_invoice(invoice, kind=CreditKind.REVERSAL, reason="x")
        self.assertEqual(Credit.objects.count(), 1)

    def test_delete_payment_is_refused_once_a_credit_exists(self):
        invoice = _paid(self.zev, self.participant)
        correct_invoice(invoice, kind=CreditKind.ADJUSTMENT, reason="x", amount_chf=Decimal("5.00"))
        with self.assertRaisesMessage(InvoiceWorkflowError, "credit notes"):
            delete_payment(invoice.payments.get())
        self.assertTrue(invoice.payments.exists())

    def test_cancel_points_to_the_correction(self):
        invoice = _issued(self.zev, self.participant, InvoiceStatus.SENT)
        record_payment(invoice, amount_chf=Decimal("10.00"), paid_on=self.today)
        with self.assertRaisesMessage(InvoiceWorkflowError, "cannot be cancelled. Correct the invoice instead"):
            cancel_invoice(invoice)
        paid = _paid(self.zev, self.participant)
        with self.assertRaisesMessage(InvoiceWorkflowError, "cannot be cancelled. Correct the invoice instead"):
            cancel_invoice(paid)

    def test_the_credit_amount_must_be_positive_in_the_database(self):
        invoice = _paid(self.zev, self.participant)
        credit = correct_invoice(invoice, kind=CreditKind.ADJUSTMENT, reason="x", amount_chf=Decimal("1.00"))["credit"]
        from django.db import IntegrityError, transaction
        with self.assertRaises(IntegrityError), transaction.atomic():
            Credit.objects.filter(pk=credit.pk).update(amount_chf=Decimal("0"))


class CreditApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = make_user("crapi_owner", UserRole.USER)
        self.admin = make_user("crapi_admin", UserRole.ADMIN)
        self.zev = make_zev(self.owner, "Credit API ZEV")
        self.tenant = make_user("crapi_tenant", UserRole.USER)
        self.participant = make_participant(self.zev, user=self.tenant)
        auth(self.client, self.owner)

    def _correct(self, invoice, **body):
        return self.client.post(f"{INVOICES}/{invoice.pk}/correct/", body, format="json")

    def test_correct_returns_the_invoice_and_the_credit(self):
        invoice = _paid(self.zev, self.participant)
        response = self._correct(invoice, kind="reversal", reason="Wrong readings")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["invoice"]["status"], InvoiceStatus.CANCELLED)
        credit = response.data["credit"]
        self.assertEqual(credit["amount_chf"], "108.10")
        self.assertEqual(credit["credit_number"], "CN-00001")
        self.assertEqual(credit["status"], "open")
        self.assertEqual(credit["remaining_chf"], "108.10")
        self.assertEqual(credit["source_invoice_number"], invoice.invoice_number)
        self.assertEqual([c["id"] for c in response.data["invoice"]["credits"]], [credit["id"]])

    def test_correct_validates_the_body(self):
        invoice = _paid(self.zev, self.participant)
        self.assertEqual(self._correct(invoice, kind="reversal").status_code, 400)
        self.assertEqual(self._correct(invoice, kind="nonsense", reason="x").status_code, 400)
        self.assertEqual(self._correct(invoice, kind="adjustment", reason="x").status_code, 400)
        self.assertFalse(Credit.objects.exists())

    def test_guard_failure_returns_400_and_audits_the_denial(self):
        invoice = _issued(self.zev, self.participant, InvoiceStatus.SENT)
        response = self._correct(invoice, kind="reversal", reason="x")
        self.assertEqual(response.status_code, 400)
        self.assertIn("no payments", response.data["error"])
        event = AuditEvent.objects.get(action_type="invoice.correct", target_id=str(invoice.pk))
        self.assertEqual(event.status, AuditEventStatus.DENIED)

    def test_audit_event_carries_the_credit(self):
        invoice = _paid(self.zev, self.participant)
        response = self._correct(invoice, kind="adjustment", reason="Overcharged", amount_chf="10.00")
        self.assertEqual(response.status_code, 201, response.data)
        event = AuditEvent.objects.get(action_type="invoice.correct", target_id=str(invoice.pk))
        self.assertEqual(event.status, AuditEventStatus.SUCCESS)
        self.assertEqual(event.metadata_json, {
            "kind": "adjustment", "credit_id": response.data["credit"]["id"], "credit_number": "CN-00001",
            "amount_chf": "10.00", "reason": "Overcharged",
        })

    def test_viewer_cannot_correct(self):
        viewer = make_user("crapi_viewer", UserRole.USER)
        ZevAccessGrant.objects.create(zev=self.zev, user=viewer, role=ZevAccessRole.VIEWER, valid_from=date(2026, 1, 1))
        invoice = _paid(self.zev, self.participant)
        auth(self.client, viewer)
        self.assertIn(self._correct(invoice, kind="reversal", reason="x").status_code, (403, 404))
        self.assertFalse(Credit.objects.exists())

    def test_participant_cannot_correct(self):
        invoice = _paid(self.zev, self.participant)
        auth(self.client, self.tenant)
        self.assertIn(self._correct(invoice, kind="reversal", reason="x").status_code, (403, 404))
        self.assertFalse(Credit.objects.exists())

    def test_disabled_zev_refuses_non_admins_but_not_admins(self):
        invoice = _paid(self.zev, self.participant)
        self.zev.disabled_at = django_timezone.now()
        self.zev.save(update_fields=["disabled_at"])
        self.assertEqual(self._correct(invoice, kind="reversal", reason="x").status_code, 400)
        self.assertFalse(Credit.objects.exists())
        auth(self.client, self.admin)
        self.assertEqual(self._correct(invoice, kind="reversal", reason="x").status_code, 201)

    def test_admin_delete_is_refused_once_a_credit_exists(self):
        invoice = _paid(self.zev, self.participant)
        self._correct(invoice, kind="reversal", reason="x")
        auth(self.client, self.admin)
        response = self.client.delete(f"{INVOICES}/{invoice.pk}/")
        self.assertEqual(response.status_code, 400)
        self.assertIn("credit notes", response.data["error"])
        self.assertTrue(Invoice.objects.filter(pk=invoice.pk).exists())

    def test_removing_a_payment_is_refused_once_a_credit_exists(self):
        invoice = _paid(self.zev, self.participant)
        self._correct(invoice, kind="adjustment", reason="x", amount_chf="5.00")
        payment = invoice.payments.get()
        response = self.client.delete(f"{INVOICES}/{invoice.pk}/payments/{payment.pk}/")
        self.assertEqual(response.status_code, 400)

    def test_regeneration_after_a_reversal_keeps_the_cancelled_original(self):
        invoice = _paid(self.zev, self.participant)
        self.assertEqual(self._correct(invoice, kind="reversal", reason="x").status_code, 201)
        response = self.client.post(f"{INVOICES}/generate/", {
            "participant_id": str(self.participant.pk), "period_start": "2026-01-01", "period_end": "2026-01-31",
        })
        self.assertEqual(response.status_code, 201, response.data)
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, InvoiceStatus.CANCELLED)
        self.assertEqual(Invoice.objects.filter(participant=self.participant).count(), 2)
        self.assertEqual(invoice.credits.count(), 1)

    def test_credit_list_is_scoped_and_filterable(self):
        mine = correct_invoice(_paid(self.zev, self.participant), kind=CreditKind.REVERSAL, reason="x")["credit"]
        other_participant = make_participant(self.zev, first="Max", last="Muster")
        theirs = correct_invoice(_paid(self.zev, other_participant), kind=CreditKind.REVERSAL, reason="x")["credit"]
        other_zev = make_zev(make_user("crapi_other", UserRole.USER), "Elsewhere")
        stranger = correct_invoice(
            _paid(other_zev, make_participant(other_zev)), kind=CreditKind.REVERSAL, reason="x",
        )["credit"]

        def ids(**params):
            response = self.client.get(f"{CREDITS}/", params)
            self.assertEqual(response.status_code, 200, response.data)
            return {row["id"] for row in response.data["results"]}

        self.assertEqual(ids(), {str(mine.pk), str(theirs.pk)})
        self.assertEqual(ids(participant_id=str(self.participant.pk)), {str(mine.pk)})
        self.assertEqual(ids(source_invoice_id=str(theirs.source_invoice_id)), {str(theirs.pk)})
        self.assertEqual(ids(zev_id=str(self.zev.pk)), {str(mine.pk), str(theirs.pk)})
        self.assertEqual(self.client.get(f"{CREDITS}/{stranger.pk}/").status_code, 404)
        self.assertEqual(self.client.get(f"{CREDITS}/", {"participant_id": "nope"}).status_code, 400)
        auth(self.client, self.admin)
        self.assertEqual(ids(), {str(mine.pk), str(theirs.pk), str(stranger.pk)})

    def test_participant_sees_only_their_own_credits(self):
        mine = correct_invoice(_paid(self.zev, self.participant), kind=CreditKind.REVERSAL, reason="x")["credit"]
        other_participant = make_participant(self.zev, first="Max", last="Muster")
        theirs = correct_invoice(_paid(self.zev, other_participant), kind=CreditKind.REVERSAL, reason="x")["credit"]
        auth(self.client, self.tenant)
        response = self.client.get(f"{CREDITS}/")
        self.assertEqual({row["id"] for row in response.data["results"]}, {str(mine.pk)})
        self.assertEqual(self.client.get(f"{CREDITS}/{theirs.pk}/").status_code, 404)
        self.assertEqual(self.client.get(f"{CREDITS}/{mine.pk}/").status_code, 200)

    def test_participant_sees_the_credits_on_their_invoice(self):
        invoice = _paid(self.zev, self.participant)
        credit = correct_invoice(invoice, kind=CreditKind.ADJUSTMENT, reason="x", amount_chf=Decimal("5.00"))["credit"]
        auth(self.client, self.tenant)
        detail = self.client.get(f"{INVOICES}/{invoice.pk}/")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual([c["id"] for c in detail.data["credits"]], [str(credit.pk)])
        self.assertIsNone(detail.data["payments"])

    def test_credit_pdf_is_404_before_the_render_and_served_after(self):
        credit = correct_invoice(_paid(self.zev, self.participant), kind=CreditKind.REVERSAL, reason="x")["credit"]
        self.assertEqual(self.client.get(f"{CREDITS}/{credit.pk}/pdf/").status_code, 404)
        credit.pdf_file.save("c.pdf", ContentFile(b"%PDF-1.7 stub"), save=False)
        Credit.objects.filter(pk=credit.pk).update(pdf_file=credit.pdf_file.name, pdf_status=InvoicePdfStatus.READY)
        response = self.client.get(f"{CREDITS}/{credit.pk}/pdf/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("CN-00001.pdf", response["Content-Disposition"])
        auth(self.client, self.tenant)
        self.assertEqual(self.client.get(f"{CREDITS}/{credit.pk}/pdf/").status_code, 200)

    def test_generate_pdf_queues_a_render_for_managers_only(self):
        credit = correct_invoice(_paid(self.zev, self.participant), kind=CreditKind.REVERSAL, reason="x")["credit"]
        auth(self.client, self.tenant)
        self.assertIn(self.client.post(f"{CREDITS}/{credit.pk}/generate-pdf/").status_code, (403, 404))
        auth(self.client, self.owner)
        with mock.patch("invoices.views.generate_credit_pdf_task.delay") as queued:
            response = self.client.post(f"{CREDITS}/{credit.pk}/generate-pdf/")
        self.assertEqual(response.status_code, 202)
        queued.assert_called_once_with(str(credit.pk))

    def test_credits_are_read_only(self):
        credit = correct_invoice(_paid(self.zev, self.participant), kind=CreditKind.REVERSAL, reason="x")["credit"]
        self.assertEqual(self.client.delete(f"{CREDITS}/{credit.pk}/").status_code, 405)
        self.assertEqual(self.client.patch(f"{CREDITS}/{credit.pk}/", {"reason": "y"}, format="json").status_code, 405)


class CreditPdfTests(TestCase):
    def setUp(self):
        self.owner = make_user("crpdf_owner", UserRole.USER)
        self.zev = make_zev(self.owner, "Credit PDF ZEV")
        self.participant = make_participant(self.zev)

    def _credit(self, **kwargs):
        invoice = _paid(self.zev, self.participant)
        return correct_invoice(invoice, kind=CreditKind.REVERSAL, reason="Wrong readings", **kwargs)["credit"]

    def test_task_renders_and_stores_the_pdf(self):
        credit = self._credit()
        generate_credit_pdf_task(str(credit.pk))
        credit.refresh_from_db()
        self.assertEqual(credit.pdf_status, InvoicePdfStatus.READY)
        with credit.pdf_file.open("rb") as handle:
            self.assertTrue(handle.read().startswith(b"%PDF"))

    def test_rendering_again_replaces_the_stored_file(self):
        credit = self._credit()
        generate_credit_pdf_task(str(credit.pk))
        credit.refresh_from_db()
        first = credit.pdf_file.name
        generate_credit_pdf_task(str(credit.pk))
        credit.refresh_from_db()
        self.assertEqual(credit.pdf_status, InvoicePdfStatus.READY)
        self.assertFalse(credit.pdf_file.storage.exists(first) and first != credit.pdf_file.name)

    def test_a_failed_render_is_recorded(self):
        credit = self._credit()
        with mock.patch("invoices.credit_pdf.render_pdf", side_effect=RuntimeError("boom")):
            generate_credit_pdf_task(str(credit.pk))
        credit.refresh_from_db()
        self.assertEqual(credit.pdf_status, InvoicePdfStatus.FAILED)
        self.assertFalse(credit.pdf_file)
        self.assertTrue(AuditEvent.objects.filter(
            action_type="credit.generate_pdf", target_id=str(credit.pk), status=AuditEventStatus.FAILED,
        ).exists())

    def test_the_context_names_the_invoice_the_reason_and_the_vat(self):
        credit = self._credit()
        context = build_credit_context(credit)
        self.assertIn(credit.source_invoice.invoice_number, context["credit_for_invoice"])
        self.assertTrue(context["show_vat"])
        self.assertEqual(context["net_chf"], Decimal("100.00"))
        self.assertEqual(context["credit_number_prefix"], "CN-")
        self.assertEqual(context["credit_number_suffix"], "00001")
        self.assertEqual(context["kind_display"], "Gutschrift" if False else context["tr"]["kind_values"]["reversal"])

    def test_no_vat_breakdown_unless_the_invoice_was_registered(self):
        invoice = _paid(self.zev, self.participant, vat_mode=VatMode.NOT_REGISTERED)
        credit = correct_invoice(invoice, kind=CreditKind.REVERSAL, reason="x")["credit"]
        self.assertFalse(build_credit_context(credit)["show_vat"])

    def test_the_document_is_in_the_invoice_language(self):
        self.zev.invoice_language = "fr"
        self.zev.save(update_fields=["invoice_language"])
        credit = self._credit()
        html = None
        with mock.patch("invoices.credit_pdf.render_pdf", side_effect=lambda h: b"%PDF") as render:
            from invoices.credit_pdf import generate_credit_pdf
            generate_credit_pdf(credit)
            html = render.call_args.args[0]
        self.assertIn("Note de crédit", html)
        self.assertIn("Wrong readings", html)
        self.assertIn(credit.credit_number.split("-")[0] + "-", html)

    def test_the_template_is_editable_and_previewable_by_admins(self):
        admin = make_user("crpdf_admin", UserRole.ADMIN)
        client = APIClient()
        auth(client, admin)
        url = "/api/v1/invoices/invoices/credit-note-pdf-template/"
        response = client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["is_customized"])
        self.assertIn("{{ credit.credit_number }}", response.data["content"])
        self.assertTrue(response.data["fields"])
        preview = client.post(
            "/api/v1/invoices/invoices/preview-pdf-template/",
            {"content": response.data["content"], "template_type": "credit_note"}, format="json",
        )
        self.assertEqual(preview.status_code, 200, preview.data)
        self.assertIn("CN-", preview.data["html"])
        patched = client.patch(url, {"content": response.data["content"]}, format="json")
        self.assertEqual(patched.status_code, 200, patched.data)
        self.assertTrue(client.get(url).data["is_customized"])


class AnnualStatementCreditTests(TestCase):
    def setUp(self):
        self.owner = make_user("crst_owner", UserRole.USER)
        self.zev = make_zev(self.owner, "Statement ZEV")
        self.participant = make_participant(self.zev)

    def _statement(self):
        with mock.patch("invoices.annual_statement._render_template", return_value="<html></html>") as render, \
                mock.patch("invoices.annual_statement.render_pdf", return_value=b"%PDF-stub"):
            generate_annual_statement_pdf(self.participant, self.zev, 2026)
        return render.call_args.args[1]

    def test_an_adjustment_is_a_negative_row_and_reduces_the_totals(self):
        invoice = _paid(self.zev, self.participant)
        credit = correct_invoice(invoice, kind=CreditKind.ADJUSTMENT, reason="x", amount_chf=Decimal("20.00"))["credit"]
        context = self._statement()
        rows = {row["invoice_number"]: row for row in context["invoices"]}
        self.assertEqual(set(rows), {invoice.invoice_number, credit.credit_number})
        row = rows[credit.credit_number]
        self.assertEqual((row["subtotal_chf"], row["vat_chf"], row["total_chf"]), ("-18.50", "-1.50", "-20.00"))
        self.assertEqual(context["invoice_totals"]["total_chf"], "88.10")
        self.assertEqual(context["invoice_totals"]["vat_chf"], "6.60")
        self.assertEqual(context["invoice_totals"]["subtotal_chf"], "81.50")

    def test_a_reversal_is_not_listed_and_leaves_no_trace_in_the_totals(self):
        invoice = _paid(self.zev, self.participant)
        correct_invoice(invoice, kind=CreditKind.REVERSAL, reason="x")
        context = self._statement()
        self.assertEqual(context["invoices"], [])
        self.assertEqual(context["invoice_totals"]["total_chf"], "0.00")

    def test_an_adjustment_on_an_invoice_reversed_later_is_dropped_with_it(self):
        invoice = _paid(self.zev, self.participant)
        correct_invoice(invoice, kind=CreditKind.ADJUSTMENT, reason="x", amount_chf=Decimal("20.00"))
        correct_invoice(invoice, kind=CreditKind.REVERSAL, reason="y")
        self.assertEqual(self._statement()["invoices"], [])

    def test_an_adjustment_outside_the_year_is_not_listed(self):
        invoice = _paid(self.zev, self.participant, period=(date(2025, 1, 1), date(2025, 1, 31)))
        correct_invoice(invoice, kind=CreditKind.ADJUSTMENT, reason="x", amount_chf=Decimal("20.00"))
        self.assertEqual(self._statement()["invoices"], [])
