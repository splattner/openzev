"""Rounding of the payable amounts to 5 Rappen (per-ZEV ``invoice_rounding``)."""

from datetime import date, datetime, timezone as dt_timezone
from decimal import Decimal

from django.test import SimpleTestCase, TestCase
from django.utils import timezone as django_timezone

from accounts.models import UserRole, VatRate
from invoices.credit_pdf import build_credit_context
from invoices.engine import generate_invoice
from invoices.models import Credit, CreditKind, Invoice, InvoiceStatus
from invoices.rounding import FIVE_RAPPEN, round_to_step, rounding_difference
from invoices.test_helpers import make_invoice, make_participant, make_user, make_zev
from invoices.test_pdf import _render_invoice_markup
from invoices.workflow import (
    InvoiceWorkflowError,
    credited_chf,
    correct_invoice,
    mark_invoice_paid,
    record_payment,
)
from metering.models import MeterReading, ReadingDirection
from tariffs.models import BillingMode, Tariff, TariffCategory
from testing import factories
from testing.helpers import clear_vat_rates, create_managed_zev
from zev.models import (
    InvoiceRounding, MeteringPoint, MeteringPointAssignment, MeteringPointType, VatMode,
)

JAN = (date(2026, 1, 1), date(2026, 1, 31))
D = Decimal


class RoundToStepTests(SimpleTestCase):
    def test_every_cent_goes_to_the_nearest_five_rappen(self):
        expected = {
            "10.00": "10.00", "10.01": "10.00", "10.02": "10.00", "10.03": "10.05", "10.04": "10.05",
            "10.05": "10.05", "10.06": "10.05", "10.07": "10.05", "10.08": "10.10", "10.09": "10.10",
        }
        for amount, rounded in expected.items():
            with self.subTest(amount=amount):
                self.assertEqual(round_to_step(D(amount), FIVE_RAPPEN), D(rounded))

    def test_a_payout_rounds_symmetrically(self):
        self.assertEqual(round_to_step(D("-10.02"), FIVE_RAPPEN), D("-10.00"))
        self.assertEqual(round_to_step(D("-10.03"), FIVE_RAPPEN), D("-10.05"))
        self.assertEqual(rounding_difference(D("-10.03"), FIVE_RAPPEN), D("-0.02"))

    def test_no_step_leaves_the_amount_alone(self):
        self.assertEqual(rounding_difference(D("10.03"), None), D("0.00"))
        self.assertEqual(round_to_step(D("10.03"), None), D("10.03"))


class RoundingEngineTests(TestCase):
    """A CHF 99.99 monthly fee plus 8.1 % VAT (8.10) is 108.09, asked for as 108.10."""

    def setUp(self):
        clear_vat_rates()
        VatRate.objects.create(rate=D("0.0810"), valid_from=JAN[0])
        self.owner = make_user("rnd_engine_owner", UserRole.USER)
        self.zev = create_managed_zev(
            name="Rounding ZEV", owner=self.owner, zev_type="vzev", start_date=JAN[0],
            billing_interval="monthly", invoice_prefix="RN",
        )
        self.zev.vat_mode = VatMode.REGISTERED
        self.zev.save(update_fields=["vat_mode"])
        Tariff.objects.create(
            zev=self.zev, name="Basic fee", category=TariffCategory.GRID_FEES,
            billing_mode=BillingMode.MONTHLY_FEE, fixed_price_chf=D("99.99"), valid_from=JAN[0],
        )
        self.participant = factories.ParticipantFactory(
            zev=self.zev, first_name="Rita", last_name="Round", email="rita@example.com", valid_from=JAN[0],
        )
        point = MeteringPoint.objects.create(zev=self.zev, meter_type=MeteringPointType.CONSUMPTION, meter_id="CH-RND")
        MeteringPointAssignment.objects.create(metering_point=point, participant=self.participant, valid_from=JAN[0])
        MeterReading.objects.create(
            metering_point=point, timestamp=datetime(2026, 1, 5, 12, 0, tzinfo=dt_timezone.utc),
            energy_kwh=D("10"), direction=ReadingDirection.IN,
        )

    def _enable(self):
        self.zev.invoice_rounding = InvoiceRounding.FIVE_RAPPEN
        self.zev.save(update_fields=["invoice_rounding"])

    def test_off_by_default_the_total_is_exact(self):
        invoice = generate_invoice(self.participant, *JAN)
        self.assertEqual((invoice.vat_chf, invoice.rounding_chf, invoice.total_chf), (D("8.10"), D("0.00"), D("108.09")))
        self.assertEqual(invoice.amount_due_chf, D("108.09"))

    def test_the_total_is_rounded_and_lines_and_vat_are_untouched(self):
        self._enable()
        invoice = generate_invoice(self.participant, *JAN)
        self.assertEqual(invoice.subtotal_chf, D("99.99"))
        self.assertEqual(invoice.vat_chf, D("8.10"))
        self.assertEqual(invoice.rounding_chf, D("0.01"))
        self.assertEqual(invoice.total_chf, D("108.10"))
        self.assertEqual(invoice.amount_due_chf, D("108.10"))
        self.assertEqual(sum(item.total_chf for item in invoice.items.all()), D("99.99"))

    def test_the_amount_due_after_credit_is_rounded_too(self):
        self._enable()
        Credit.objects.create(
            zev=self.zev, participant=self.participant, kind=CreditKind.ADJUSTMENT, credit_number="CN-R1",
            reason="Test", amount_chf=D("12.33"), vat_mode=VatMode.NOT_REGISTERED,
        )
        invoice = generate_invoice(self.participant, *JAN)
        # 108.10 - 12.33 = 95.77, asked for as 95.75.
        self.assertEqual(invoice.credit_applied_chf, D("12.33"))
        self.assertEqual(invoice.due_rounding_chf, D("-0.02"))
        self.assertEqual(invoice.amount_due_chf, D("95.75"))
        self.assertEqual(invoice.total_chf, D("108.10"))

    def test_a_credit_that_keeps_the_remainder_on_the_grid_adds_no_rounding(self):
        self._enable()
        Credit.objects.create(
            zev=self.zev, participant=self.participant, kind=CreditKind.ADJUSTMENT, credit_number="CN-R2",
            reason="Test", amount_chf=D("10.00"), vat_mode=VatMode.NOT_REGISTERED,
        )
        invoice = generate_invoice(self.participant, *JAN)
        self.assertEqual((invoice.due_rounding_chf, invoice.amount_due_chf), (D("0.00"), D("98.10")))

    def test_switching_the_setting_off_leaves_issued_invoices_alone(self):
        self._enable()
        invoice = generate_invoice(self.participant, *JAN)
        self.zev.invoice_rounding = InvoiceRounding.NONE
        self.zev.save(update_fields=["invoice_rounding"])
        invoice.refresh_from_db()
        self.assertEqual((invoice.rounding_chf, invoice.total_chf), (D("0.01"), D("108.10")))

    def test_the_pdf_shows_the_rounding_lines_only_when_there_are_some(self):
        plain = _render_invoice_markup(generate_invoice(self.participant, *JAN))
        self.assertNotIn("Rundung", plain)
        Invoice.objects.filter(participant=self.participant).delete()
        self._enable()
        Credit.objects.create(
            zev=self.zev, participant=self.participant, kind=CreditKind.ADJUSTMENT, credit_number="CN-R3",
            reason="Test", amount_chf=D("12.33"), vat_mode=VatMode.NOT_REGISTERED,
        )
        markup = _render_invoice_markup(generate_invoice(self.participant, *JAN))
        self.assertEqual(markup.count("Rundung"), 2)
        self.assertIn("CHF 0.01", markup)
        self.assertIn("CHF -0.02", markup)


class RoundingPaymentTests(TestCase):
    def setUp(self):
        self.owner = make_user("rnd_pay_owner", UserRole.USER)
        self.zev = make_zev(self.owner, "Rounding Pay ZEV")
        self.participant = make_participant(self.zev)

    def _sent(self, total, *, applied="0.00", due_rounding="0.00"):
        invoice = make_invoice(self.zev, self.participant, InvoiceStatus.SENT)
        Invoice.objects.filter(pk=invoice.pk).update(
            total_chf=D(total), credit_applied_chf=D(applied), due_rounding_chf=D(due_rounding),
            approved_at=django_timezone.now(), sent_at=django_timezone.now(),
        )
        invoice.refresh_from_db()
        return invoice

    def test_the_rounded_amount_due_is_what_has_to_be_paid(self):
        invoice = self._sent("108.10", applied="12.33", due_rounding="-0.02")
        self.assertEqual(invoice.amount_due_chf, D("95.75"))
        with self.assertRaises(InvoiceWorkflowError):
            record_payment(invoice, amount_chf=D("95.77"), paid_on=django_timezone.localdate())
        record_payment(invoice, amount_chf=D("95.75"), paid_on=django_timezone.localdate())
        self.assertEqual(invoice.status, InvoiceStatus.PAID)

    def test_mark_paid_books_the_rounded_amount(self):
        invoice = self._sent("108.10", applied="12.33", due_rounding="-0.02")
        result = mark_invoice_paid(invoice)
        self.assertEqual(result["payment"].amount_chf, D("95.75"))


class RoundingCreditNoteTests(TestCase):
    def setUp(self):
        self.owner = make_user("rnd_cn_owner", UserRole.USER)
        self.zev = make_zev(self.owner, "Rounding Credit ZEV")
        self.zev.vat_mode = VatMode.REGISTERED
        self.zev.invoice_rounding = InvoiceRounding.FIVE_RAPPEN
        self.zev.save(update_fields=["vat_mode", "invoice_rounding"])
        self.participant = make_participant(self.zev)

    def _paid(self, total="108.10"):
        invoice = make_invoice(self.zev, self.participant, InvoiceStatus.SENT)
        Invoice.objects.filter(pk=invoice.pk).update(
            total_chf=D(total), subtotal_chf=D("100.00"), vat_chf=D("8.10"), vat_rate=D("0.0810"),
            vat_base_chf=D("100.00"), approved_at=django_timezone.now(), sent_at=django_timezone.now(),
        )
        invoice.refresh_from_db()
        mark_invoice_paid(invoice)
        return invoice

    def test_an_adjustment_is_rounded_and_the_vat_is_worked_out_on_the_exact_amount(self):
        invoice = self._paid()
        credit = correct_invoice(invoice, kind=CreditKind.ADJUSTMENT, reason="Overcharge", amount_chf=D("12.33"))["credit"]
        self.assertEqual((credit.amount_chf, credit.rounding_chf), (D("12.35"), D("0.02")))
        self.assertEqual(credit.vat_chf, D("0.92"))  # 12.33 * 0.081 / 1.081
        context = build_credit_context(credit)
        self.assertEqual(context["net_chf"], D("11.41"))

    def test_the_rounding_does_not_eat_into_what_is_still_creditable(self):
        invoice = self._paid()
        correct_invoice(invoice, kind=CreditKind.ADJUSTMENT, reason="One", amount_chf=D("12.33"))
        self.assertEqual(credited_chf(invoice.pk), D("12.33"))
        # 108.10 - 12.33 = 95.77 is still creditable, to the Rappen.
        correct_invoice(invoice, kind=CreditKind.ADJUSTMENT, reason="Two", amount_chf=D("95.77"))
        with self.assertRaises(InvoiceWorkflowError):
            correct_invoice(invoice, kind=CreditKind.ADJUSTMENT, reason="Three", amount_chf=D("0.05"))

    def test_a_credit_that_rounds_to_nothing_is_refused(self):
        invoice = self._paid()
        with self.assertRaises(InvoiceWorkflowError) as raised:
            correct_invoice(invoice, kind=CreditKind.ADJUSTMENT, reason="Tiny", amount_chf=D("0.02"))
        self.assertIn("rounds to CHF 0.00", raised.exception.user_message)

    def test_a_reversal_credits_what_was_paid_rounded(self):
        invoice = make_invoice(self.zev, self.participant, InvoiceStatus.SENT)
        Invoice.objects.filter(pk=invoice.pk).update(
            total_chf=D("108.10"), approved_at=django_timezone.now(), sent_at=django_timezone.now(),
        )
        invoice.refresh_from_db()
        record_payment(invoice, amount_chf=D("50.03"), paid_on=django_timezone.localdate())
        credit = correct_invoice(invoice, kind=CreditKind.REVERSAL, reason="Wrong tenant")["credit"]
        self.assertEqual((credit.amount_chf, credit.rounding_chf), (D("50.05"), D("0.02")))
        self.assertEqual(invoice.status, InvoiceStatus.CANCELLED)

    def test_a_zev_without_rounding_issues_exact_credit_notes(self):
        self.zev.invoice_rounding = InvoiceRounding.NONE
        self.zev.save(update_fields=["invoice_rounding"])
        invoice = self._paid()
        credit = correct_invoice(invoice, kind=CreditKind.ADJUSTMENT, reason="Overcharge", amount_chf=D("12.33"))["credit"]
        self.assertEqual((credit.amount_chf, credit.rounding_chf), (D("12.33"), D("0.00")))

    def test_the_credit_note_pdf_lists_the_rounding(self):
        from invoices.credit_pdf import CREDIT_NOTE_TEMPLATE
        from invoices.pdf import _render_template

        invoice = self._paid()
        credit = correct_invoice(invoice, kind=CreditKind.ADJUSTMENT, reason="Overcharge", amount_chf=D("12.33"))["credit"]
        html = _render_template(CREDIT_NOTE_TEMPLATE, build_credit_context(credit))
        self.assertIn("Rundung", html)
        self.assertIn("CHF 12.35", html)
