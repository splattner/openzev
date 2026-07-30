from datetime import date, datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.utils import timezone

from accounts.models import AppSettings, User, UserRole
from zev.models import Participant, Zev
from tariffs.models import TariffCategory
from .models import Invoice, InvoiceItem
from .pdf import _build_qr_svg, _build_template_context


class InvoicePdfQrTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="pdf_owner",
            password="pass1234",
            role=UserRole.ZEV_OWNER,
        )
        self.zev = Zev.objects.create(
            name="QR ZEV",
            owner=self.owner,
            zev_type="vzev",
            start_date=date(2026, 1, 1),
            billing_interval="monthly",
            invoice_prefix="Q",
            bank_iban="CH9300762011623852957",
        )
        self.owner_participant = Participant.objects.create(
            zev=self.zev,
            user=self.owner,
            first_name="Test",
            last_name="Owner",
            email="owner@example.com",
            address_line1="Bahnhofstrasse 1",
            postal_code="8001",
            city="Zuerich",
            valid_from=date(2026, 1, 1),
        )
        self.participant = Participant.objects.create(
            zev=self.zev,
            first_name="Alice",
            last_name="Muster",
            email="alice@example.com",
            address_line1="Musterweg 3",
            postal_code="3000",
            city="Bern",
            valid_from=date(2026, 1, 1),
        )

    def _invoice(self):
        return Invoice.objects.create(
            invoice_number="Q-00001",
            zev=self.zev,
            participant=self.participant,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            total_chf=Decimal("42.00"),
        )

    def test_build_qr_svg_skips_when_debtor_postal_code_missing(self):
        self.participant.postal_code = ""
        self.participant.save(update_fields=["postal_code"])
        invoice = self._invoice()

        with patch("qrbill.QRBill") as qrbill_cls:
            qr_svg = _build_qr_svg(invoice)

        self.assertIsNone(qr_svg)
        qrbill_cls.assert_not_called()

    def test_build_qr_svg_returns_svg_when_required_data_present(self):
        invoice = self._invoice()

        with patch("qrbill.QRBill") as qrbill_cls:
            bill = MagicMock()
            qrbill_cls.return_value = bill

            def write_svg(output):
                output.write(b"<svg>ok</svg>")

            bill.as_svg.side_effect = write_svg
            qr_svg = _build_qr_svg(invoice)

        self.assertEqual(qr_svg, "<svg>ok</svg>")
        qrbill_cls.assert_called_once()
        kwargs = qrbill_cls.call_args.kwargs
        self.assertEqual(kwargs["debtor"]["pcode"], "3000")
        self.assertEqual(kwargs["creditor"]["pcode"], "8001")

    def test_build_qr_svg_handles_text_writer(self):
        invoice = self._invoice()

        with patch("qrbill.QRBill") as qrbill_cls:
            bill = MagicMock()
            qrbill_cls.return_value = bill

            def write_svg(output):
                output.write("<svg>ok-text</svg>")

            bill.as_svg.side_effect = write_svg
            qr_svg = _build_qr_svg(invoice)

        self.assertEqual(qr_svg, "<svg>ok-text</svg>")
        qrbill_cls.assert_called_once()

    def test_build_qr_svg_skips_when_qrbill_rejects_data(self):
        invoice = self._invoice()

        with patch("qrbill.QRBill", side_effect=ValueError("The debtor address is invalid: Postal code is mandatory")):
            qr_svg = _build_qr_svg(invoice)

        self.assertIsNone(qr_svg)

    def test_template_context_uses_app_date_settings(self):
        invoice = self._invoice()
        invoice.due_date = date(2026, 2, 15)
        invoice.created_at = timezone.make_aware(datetime(2026, 2, 1, 9, 30))
        invoice.save(update_fields=["due_date", "created_at"])

        settings_obj = AppSettings.load()
        settings_obj.date_format_short = AppSettings.SHORT_DATE_YYYY_MM_DD
        settings_obj.save(update_fields=["date_format_short", "updated_at"])

        context = _build_template_context(invoice)

        self.assertEqual(context["formatted_dates"]["invoice_date"], "2026-02-01")
        self.assertEqual(context["formatted_dates"]["period_start"], "2026-01-01")
        self.assertEqual(context["formatted_dates"]["period_end"], "2026-01-31")
        self.assertEqual(context["formatted_dates"]["due_date"], "2026-02-15")
        self.assertEqual(context["creditor_city"], "Zuerich")
        self.assertEqual(context["formatted_dates"]["due_date"], "2026-02-15")

    def test_template_context_strips_repeated_period_from_item_description(self):
        invoice = self._invoice()
        InvoiceItem.objects.create(
            invoice=invoice,
            item_type=InvoiceItem.ItemType.LOCAL_ENERGY,
            tariff_category=TariffCategory.ENERGY,
            description="Solar Work Tariff 2026-01-01 – 2026-01-31",
            quantity_kwh=Decimal("10.00"),
            unit="kWh",
            unit_price_chf=Decimal("0.12345"),
            total_chf=Decimal("1.23"),
        )

        context = _build_template_context(invoice)
        first_group = context["grouped_items"][0]
        first_item = first_group["items"][0]

        self.assertEqual(first_item["description"], "Solar Work Tariff")

    def test_payment_terms_text_follows_the_zevs_configured_term(self):
        """Regression: this line used to always read 'payable within 30 days'
        regardless of Zev.payment_term_days (#365 follow-up)."""
        self.zev.payment_term_days = 45
        self.zev.save(update_fields=["payment_term_days"])
        invoice = self._invoice()

        context = _build_template_context(invoice)

        self.assertEqual(
            context["tr"]["payment_terms_text"],
            "Zahlbar innert 45 Tagen ab Rechnungsdatum",
        )

    def test_payment_terms_text_uses_the_default_thirty_days(self):
        invoice = self._invoice()

        context = _build_template_context(invoice)

        self.assertEqual(
            context["tr"]["payment_terms_text"],
            "Zahlbar innert 30 Tagen ab Rechnungsdatum",
        )

    def test_payment_terms_text_is_grammatically_singular_for_one_day(self):
        self.zev.payment_term_days = 1
        self.zev.save(update_fields=["payment_term_days"])
        invoice = self._invoice()

        context = _build_template_context(invoice)

        self.assertEqual(
            context["tr"]["payment_terms_text"],
            "Zahlbar innert 1 Tag ab Rechnungsdatum",
        )

    def test_payment_terms_text_is_translated_per_zev_invoice_language(self):
        self.zev.payment_term_days = 45
        self.zev.invoice_language = "en"
        self.zev.save(update_fields=["payment_term_days", "invoice_language"])
        invoice = self._invoice()

        context = _build_template_context(invoice)

        self.assertEqual(context["tr"]["payment_terms_text"], "Due within 45 days of invoice date")

    def test_building_one_invoices_context_does_not_leak_into_another(self):
        """The translation dict is a module-level constant shared by every
        invoice; resolving payment_terms_text must copy it, not mutate it in
        place, or one ZEV's term would bleed into every invoice rendered
        afterwards in the same process."""
        self.zev.payment_term_days = 45
        self.zev.save(update_fields=["payment_term_days"])
        first_invoice = self._invoice()
        _build_template_context(first_invoice)

        other_owner = User.objects.create_user(
            username="pdf_owner_other", password="pass1234", role=UserRole.ZEV_OWNER,
        )
        other_zev = Zev.objects.create(
            name="Other ZEV", owner=other_owner, zev_type="vzev",
        )
        other_participant = Participant.objects.create(
            zev=other_zev, first_name="Bob", last_name="Muster",
            email="bob@example.com", address_line1="Weg 1",
            postal_code="4000", city="Basel", valid_from=date(2026, 1, 1),
        )
        second_invoice = Invoice.objects.create(
            invoice_number="Q-00002", zev=other_zev, participant=other_participant,
            period_start=date(2026, 1, 1), period_end=date(2026, 1, 31),
            total_chf=Decimal("10.00"),
        )

        context = _build_template_context(second_invoice)

        self.assertEqual(
            context["tr"]["payment_terms_text"],
            "Zahlbar innert 30 Tagen ab Rechnungsdatum",
        )
