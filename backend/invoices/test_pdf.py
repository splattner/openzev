import io
import re
from datetime import date, datetime
from datetime import timezone as dt_timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

from accounts.models import AppSettings, User, UserRole
from django.conf import settings
from django.test import TestCase
from django.utils import timezone
from tariffs.models import TariffCategory
from metering.models import MeterReading, ReadingDirection
from testing.helpers import make_named_participant
from zev.models import MeteringPoint, MeteringPointAssignment, MeteringPointType, Participant, Zev

from .models import Invoice, InvoiceItem, InvoiceStatus
from .pdf import (
    _build_qr_svg,
    _build_template_context,
    _count_qr_slips,
    _find_qr_clip_rect,
    _render_template,
    generate_pdf,
)
from .pdf_charts import (
    _CHART_BG,
    _CHART_INK,
    _CHART_LABEL,
    _CHART_MUTED,
    _build_energy_chart_svg,
    _build_energy_flow_svg,
    _build_hourly_profile_chart_svg,
)
from .pdf_stats import _build_energy_summary, _build_savings_data
from .pdf_translations import INVOICE_TRANSLATIONS
from .template_context import build_sample_invoice_context


_STYLE_BLOCK_RE = re.compile(r"<style>.*?</style>", re.DOTALL)


def _render_invoice_markup(invoice):
    """Render the invoice template to markup, stylesheet removed.

    The ``<style>`` block renders on every invoice, so a bare class name found
    in the full HTML may be nothing but a CSS selector. Asserting against the
    markup alone keeps a structural check from passing on the stylesheet while
    the element it names is gone (#427).
    """
    from .pdf import TEMPLATE_NAME
    html = _render_template(TEMPLATE_NAME, _build_template_context(invoice))
    return _STYLE_BLOCK_RE.sub("", html)


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

    def test_build_qr_svg_builds_in_all_four_languages(self):
        for i, lang in enumerate(("de", "fr", "it", "en"), start=1):
            with self.subTest(lang=lang):
                self.zev.invoice_language = lang
                self.zev.save(update_fields=["invoice_language"])
                invoice = Invoice.objects.create(
                    invoice_number=f"QL-{i:05d}",
                    zev=self.zev,
                    participant=self.participant,
                    period_start=date(2026, 1, 1),
                    period_end=date(2026, 1, 31),
                    total_chf=Decimal("42.00"),
                )

                with patch("qrbill.QRBill") as qrbill_cls:
                    bill = MagicMock()
                    qrbill_cls.return_value = bill

                    def write_svg(output):
                        output.write(b"<svg>ok</svg>")

                    bill.as_svg.side_effect = write_svg
                    qr_svg = _build_qr_svg(invoice)

                self.assertIsNotNone(qr_svg, f"QR SVG should not be None for lang={lang}")
                kwargs = qrbill_cls.call_args.kwargs
                self.assertEqual(kwargs["language"], lang)

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

    def test_invoice_number_split_at_last_hyphen(self):
        invoice = self._invoice()
        context = _build_template_context(invoice)
        self.assertEqual(context["invoice_number_prefix"], "Q-")
        self.assertEqual(context["invoice_number_suffix"], "00001")

    def test_invoice_number_split_long_prefix(self):
        invoice = self._invoice()
        invoice.invoice_number = "INV-2026-001"
        invoice.save(update_fields=["invoice_number"])
        context = _build_template_context(invoice)
        self.assertEqual(context["invoice_number_prefix"], "INV-2026-")
        self.assertEqual(context["invoice_number_suffix"], "001")

    def test_invoice_number_split_no_hyphen(self):
        invoice = self._invoice()
        invoice.invoice_number = "FLATNUM"
        invoice.save(update_fields=["invoice_number"])
        context = _build_template_context(invoice)
        self.assertEqual(context["invoice_number_prefix"], "FLATNUM")
        self.assertEqual(context["invoice_number_suffix"], "")

    def test_template_context_does_not_mutate_shared_translations(self):
        invoice = self._invoice()

        context = _build_template_context(invoice)

        self.assertNotIn("{email}", context["tr"]["notes_question"])
        self.assertIn(settings.DEFAULT_FROM_EMAIL, context["tr"]["notes_question"])
        # The module-level dict must keep its raw placeholder across renders.
        self.assertIn("{email}", INVOICE_TRANSLATIONS["de"]["notes_question"])

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

    def test_energy_comparison_is_rendered_without_a_prior_period(self):
        invoice = self._invoice()
        invoice.total_local_kwh = Decimal("10.00")
        invoice.total_grid_kwh = Decimal("20.00")
        invoice.save(update_fields=["total_local_kwh", "total_grid_kwh"])

        chart = _build_energy_chart_svg(invoice, INVOICE_TRANSLATIONS["de"])

        self.assertIsNotNone(chart)
        self.assertTrue(chart.startswith("<svg"))
        self.assertIn("<rect", chart)  # bars exist
        self.assertIn("<text", chart)  # labels exist

    def test_energy_comparison_is_rendered_when_a_prior_period_exists(self):
        Invoice.objects.create(
            invoice_number="Q-00000",
            zev=self.zev,
            participant=self.participant,
            period_start=date(2025, 1, 1),
            period_end=date(2025, 1, 31),
            total_local_kwh=Decimal("8.00"),
            total_grid_kwh=Decimal("22.00"),
            total_chf=Decimal("42.00"),
            status=InvoiceStatus.PAID,
        )
        invoice = self._invoice()
        invoice.total_local_kwh = Decimal("10.00")
        invoice.total_grid_kwh = Decimal("20.00")
        invoice.save(update_fields=["total_local_kwh", "total_grid_kwh"])

        chart = _build_energy_chart_svg(invoice, INVOICE_TRANSLATIONS["de"])

        self.assertIsNotNone(chart)
        self.assertTrue(chart.startswith("<svg"))
        self.assertIn("<rect", chart)
        self.assertIn("<text", chart)
        self.assertIn("2025", chart)  # prior year label proves comparison data is rendered

    def test_energy_comparison_excludes_draft_prior_invoices(self):
        Invoice.objects.create(
            invoice_number="Q-00000",
            zev=self.zev,
            participant=self.participant,
            period_start=date(2025, 1, 1),
            period_end=date(2025, 1, 31),
            total_local_kwh=Decimal("8.00"),
            total_grid_kwh=Decimal("22.00"),
            total_chf=Decimal("42.00"),
            status=InvoiceStatus.DRAFT,
        )
        invoice = self._invoice()
        invoice.total_local_kwh = Decimal("10.00")
        invoice.total_grid_kwh = Decimal("20.00")
        invoice.save(update_fields=["total_local_kwh", "total_grid_kwh"])

        chart = _build_energy_chart_svg(invoice, INVOICE_TRANSLATIONS["de"])

        self.assertIsNotNone(chart)
        self.assertNotIn("2025", chart)  # draft prior invoice must be excluded

    def test_default_template_uses_dedicated_invoice_and_payment_layouts(self):
        """Verify structural properties of the rendered PDF instead of CSS text."""
        from pypdf import PdfReader

        owner = User.objects.create_user(
            username="struct_owner", password="pass1234", role=UserRole.ZEV_OWNER,
        )
        zev = Zev.objects.create(
            name="Struct ZEV", owner=owner, zev_type="vzev",
            start_date=date(2026, 1, 1), billing_interval="monthly",
            invoice_prefix="Q", bank_iban="CH9300762011623852957",
            invoice_language="de",
        )
        participant = Participant.objects.create(
            zev=zev, user=owner, first_name="Test", last_name="Owner",
            email="owner@example.com", address_line1="Bahnhofstrasse 1",
            postal_code="8001", city="Zuerich", valid_from=date(2026, 1, 1),
        )
        invoice = Invoice.objects.create(
            invoice_number="Q-00010", zev=zev, participant=participant,
            period_start=date(2026, 1, 1), period_end=date(2026, 1, 31),
            total_local_kwh=Decimal("100.00"), total_grid_kwh=Decimal("50.00"),
            total_chf=Decimal("42.00"),
        )
        InvoiceItem.objects.create(
            invoice=invoice, item_type=InvoiceItem.ItemType.LOCAL_ENERGY,
            tariff_category=TariffCategory.ENERGY, description="Solar energy",
            quantity_kwh=Decimal("100.00"), unit="kWh",
            unit_price_chf=Decimal("0.15"), total_chf=Decimal("15.00"),
        )
        # Grid item at a higher rate so savings_data (and the savings card) renders
        InvoiceItem.objects.create(
            invoice=invoice, item_type=InvoiceItem.ItemType.GRID_ENERGY,
            tariff_category=TariffCategory.ENERGY, description="Grid energy",
            quantity_kwh=Decimal("50.00"), unit="kWh",
            unit_price_chf=Decimal("0.32"), total_chf=Decimal("16.00"),
        )

        pdf_bytes = generate_pdf(invoice)
        reader = PdfReader(io.BytesIO(pdf_bytes))
        self.assertGreaterEqual(len(reader.pages), 2)  # invoice + insights at minimum

        markup = _render_invoice_markup(invoice)
        # Structural checks on the rendered markup
        self.assertIn('class="line-items"', markup)
        self.assertIn('quantity-cell', markup)
        self.assertNotIn('<th>{{ tr.unit }}</th>', markup)  # unit merged into quantity
        self.assertIn('savings-breakdown', markup)  # savings card variant renders

    def test_structural_markers_are_absent_when_their_element_does_not_render(self):
        """Guards the assertions above.

        Both markers also exist as CSS selectors, and the stylesheet renders on
        every invoice — so asserting them against the full HTML passed even with
        the elements deleted from the template (#427). An invoice with no items
        has no line-item table and no savings card; if these markers still turn
        up, the structural checks have stopped proving anything again.
        """
        markup = _render_invoice_markup(self._invoice())

        self.assertNotIn('savings-breakdown', markup)
        self.assertNotIn('quantity-cell', markup)

    def test_template_context_enables_inline_qr_payment_for_small_invoices(self):
        invoice = self._invoice()
        InvoiceItem.objects.create(
            invoice=invoice,
            item_type=InvoiceItem.ItemType.LOCAL_ENERGY,
            tariff_category=TariffCategory.ENERGY,
            description="Solar Work Tariff",
            quantity_kwh=Decimal("10.00"),
            unit="kWh",
            unit_price_chf=Decimal("0.12345"),
            total_chf=Decimal("1.23"),
        )

        context = _build_template_context(invoice)

        self.assertTrue(context["inline_qr_payment"])

    def test_hourly_profile_buckets_by_stored_hour_not_localtime(self):
        """Readings are stored as wall-clock UTC; bucket by ts.hour directly."""
        from metering.models import MeterReading, ReadingDirection, ReadingResolution
        from zev.models import MeteringPoint, MeteringPointAssignment, MeteringPointType

        invoice = self._invoice()
        invoice.total_local_kwh = Decimal("10.00")
        invoice.total_grid_kwh = Decimal("20.00")
        invoice.save(update_fields=["total_local_kwh", "total_grid_kwh"])

        mp = MeteringPoint.objects.create(
            zev=self.zev,
            meter_id="CH00000000000000000000000000TEST01",
            meter_type=MeteringPointType.CONSUMPTION,
        )
        MeteringPointAssignment.objects.create(
            metering_point=mp,
            participant=self.participant,
            valid_from=date(2026, 1, 1),
        )

        # Create a production metering point for ZEV-level aggregation
        prod_mp = MeteringPoint.objects.create(
            zev=self.zev,
            meter_id="CH00000000000000000000000000TEST02",
            meter_type=MeteringPointType.PRODUCTION,
        )
        MeteringPointAssignment.objects.create(
            metering_point=prod_mp,
            participant=self.participant,
            valid_from=date(2026, 1, 1),
        )

        # 23:30 UTC — stored as wall-clock 23:30, should bucket into hour 23
        ts_utc = datetime(2026, 1, 15, 23, 30, tzinfo=dt_timezone.utc)
        MeterReading.objects.create(
            metering_point=mp,
            timestamp=ts_utc,
            energy_kwh=Decimal("5.0000"),
            direction=ReadingDirection.IN,
            resolution=ReadingResolution.HOURLY,
        )
        MeterReading.objects.create(
            metering_point=prod_mp,
            timestamp=ts_utc,
            energy_kwh=Decimal("3.0000"),
            direction=ReadingDirection.OUT,
            resolution=ReadingResolution.HOURLY,
        )

        chart = _build_hourly_profile_chart_svg(invoice, INVOICE_TRANSLATIONS["de"])

        self.assertIsNotNone(chart)
        # The 23:30 UTC reading must land in the hour-23 bucket (stored hour),
        # and no other hour may have a bar.
        hours_with_bars = set(re.findall(r'data-hour="(\d+)"', chart))
        self.assertEqual(hours_with_bars, {"23"})

    def test_hourly_profile_skips_readings_outside_the_assignment_window(self):
        """A mid-period transfer must not let the new holder's profile absorb
        readings from before their assignment started (ADR 0013)."""
        from metering.models import MeterReading, ReadingDirection, ReadingResolution
        from zev.models import MeteringPoint, MeteringPointAssignment, MeteringPointType

        invoice = self._invoice()
        invoice.total_local_kwh = Decimal("10.00")
        invoice.total_grid_kwh = Decimal("20.00")
        invoice.save(update_fields=["total_local_kwh", "total_grid_kwh"])

        mp = MeteringPoint.objects.create(
            zev=self.zev,
            meter_id="CH00000000000000000000000000TEST03",
            meter_type=MeteringPointType.CONSUMPTION,
        )
        # The participant only holds the point from Jan 16 onward.
        MeteringPointAssignment.objects.create(
            metering_point=mp,
            participant=self.participant,
            valid_from=date(2026, 1, 16),
        )
        prod_mp = MeteringPoint.objects.create(
            zev=self.zev,
            meter_id="CH00000000000000000000000000TEST04",
            meter_type=MeteringPointType.PRODUCTION,
        )
        MeteringPointAssignment.objects.create(
            metering_point=prod_mp,
            participant=self.participant,
            valid_from=date(2026, 1, 1),
        )
        # One reading before the assignment (must be skipped), one after.
        early = datetime(2026, 1, 15, 10, 0, tzinfo=dt_timezone.utc)
        late = datetime(2026, 1, 20, 10, 0, tzinfo=dt_timezone.utc)
        for ts in (early, late):
            MeterReading.objects.create(
                metering_point=mp, timestamp=ts, energy_kwh=Decimal("5.0000"),
                direction=ReadingDirection.IN, resolution=ReadingResolution.HOURLY,
            )
            MeterReading.objects.create(
                metering_point=prod_mp, timestamp=ts, energy_kwh=Decimal("9.0000"),
                direction=ReadingDirection.OUT, resolution=ReadingResolution.HOURLY,
            )

        chart = _build_hourly_profile_chart_svg(invoice, INVOICE_TRANSLATIONS["de"])

        self.assertIsNotNone(chart)
        # Only the post-assignment reading contributes: exactly one bar at
        # hour 10 (local), and no grid bar — the pre-assignment 5 kWh would
        # otherwise produce a second, orange (grid) bar there.
        self.assertIn('data-hour="10"', chart)
        self.assertEqual(chart.count('data-hour="10"'), 1)
        self.assertNotIn('fill="#c9891a" data-hour', chart)

    def test_hourly_profile_reaches_a_community_only_participant(self):
        """A participant with no personally-held meter — their only stake in
        the ZEV is a community share — must still get a chart. Before the fix
        (shared metering points, docs/specs/2026-08-shared-metering-points.md
        §7.7), consumption_mps was scoped to literal holders only, so this
        participant's readings queryset was empty and the function returned
        None before ever reaching the attribution logic."""
        from metering.models import MeterReading, ReadingDirection, ReadingResolution
        from zev.models import AllocationMode, MeteringPoint, MeteringPointAssignment, MeteringPointType

        holder = Participant.objects.create(
            zev=self.zev, first_name="Hans", last_name="Halter",
            email="hans@example.com", valid_from=date(2026, 1, 1),
            allocation_weight=Decimal("3"),
        )
        self.participant.allocation_weight = Decimal("1")
        self.participant.save(update_fields=["allocation_weight"])

        invoice = self._invoice()
        invoice.total_local_kwh = Decimal("10.00")
        invoice.total_grid_kwh = Decimal("20.00")
        invoice.save(update_fields=["total_local_kwh", "total_grid_kwh"])

        community_mp = MeteringPoint.objects.create(
            zev=self.zev, meter_id="CH00000000000000000000000000TEST05",
            meter_type=MeteringPointType.CONSUMPTION,
        )
        MeteringPointAssignment.objects.create(
            metering_point=community_mp, participant=holder,
            valid_from=date(2026, 1, 1), allocation_mode=AllocationMode.COMMUNITY,
        )
        MeterReading.objects.create(
            metering_point=community_mp,
            timestamp=datetime(2026, 1, 15, 9, 0, tzinfo=dt_timezone.utc),
            energy_kwh=Decimal("5.0000"), direction=ReadingDirection.IN,
            resolution=ReadingResolution.HOURLY,
        )

        chart = _build_hourly_profile_chart_svg(invoice, INVOICE_TRANSLATIONS["de"])

        self.assertIsNotNone(chart)
        self.assertIn('data-hour="9"', chart)

    def test_period_window_uses_utc_not_local_tz(self):
        """pdf_stats and pdf_charts must query the same UTC range as the engine."""
        from datetime import timedelta

        from .engine import _period_to_dt

        period_start = date(2026, 4, 1)
        period_end = date(2026, 6, 30)

        start_dt = _period_to_dt(period_start)
        end_dt = _period_to_dt(period_end) + timedelta(days=1)

        self.assertEqual(start_dt.tzinfo, dt_timezone.utc)
        self.assertEqual(start_dt, datetime(2026, 4, 1, 0, 0, tzinfo=dt_timezone.utc))
        self.assertEqual(end_dt, datetime(2026, 7, 1, 0, 0, tzinfo=dt_timezone.utc))

    def test_sample_invoice_context_has_all_template_keys(self):
        invoice = self._invoice()
        InvoiceItem.objects.create(
            invoice=invoice,
            item_type=InvoiceItem.ItemType.LOCAL_ENERGY,
            tariff_category=TariffCategory.ENERGY,
            description="Solar Work Tariff",
            quantity_kwh=Decimal("10.00"),
            unit="kWh",
            unit_price_chf=Decimal("0.12345"),
            total_chf=Decimal("1.23"),
        )

        real_keys = set(_build_template_context(invoice).keys())
        sample_keys = set(build_sample_invoice_context().keys())

        missing = real_keys - sample_keys - {"invoice"}
        self.assertEqual(missing, set(), f"Sample context is missing keys: {missing}")

        real_tr_keys = set(_build_template_context(invoice)["tr"].keys())
        sample_tr_keys = set(build_sample_invoice_context()["tr"].keys())
        missing_tr = real_tr_keys - sample_tr_keys
        self.assertEqual(missing_tr, set(), f"Sample tr is missing keys: {missing_tr}")

    def test_savings_data_returns_none_when_no_local_energy(self):
        invoice = self._invoice()
        invoice.total_local_kwh = Decimal("0")
        invoice.total_grid_kwh = Decimal("20.00")
        invoice.save(update_fields=["total_local_kwh", "total_grid_kwh"])

        result = _build_savings_data(invoice, INVOICE_TRANSLATIONS["de"])

        self.assertIsNone(result)

    def test_savings_data_returns_none_when_local_rate_exceeds_grid(self):
        invoice = self._invoice()
        invoice.total_local_kwh = Decimal("10.00")
        invoice.total_grid_kwh = Decimal("10.00")
        invoice.save(update_fields=["total_local_kwh", "total_grid_kwh"])

        # Local rate (30 rp/kWh) > Grid rate (20 rp/kWh)
        InvoiceItem.objects.create(
            invoice=invoice,
            item_type=InvoiceItem.ItemType.LOCAL_ENERGY,
            tariff_category=TariffCategory.ENERGY,
            description="Local energy",
            quantity_kwh=Decimal("10.00"),
            unit="kWh",
            unit_price_chf=Decimal("0.30"),
            total_chf=Decimal("3.00"),
        )
        InvoiceItem.objects.create(
            invoice=invoice,
            item_type=InvoiceItem.ItemType.GRID_ENERGY,
            tariff_category=TariffCategory.GRID_FEES,
            description="Grid energy",
            quantity_kwh=Decimal("10.00"),
            unit="kWh",
            unit_price_chf=Decimal("0.20"),
            total_chf=Decimal("2.00"),
        )

        result = _build_savings_data(invoice, INVOICE_TRANSLATIONS["de"])

        self.assertIsNone(result)

    def test_savings_data_computes_bar_percentages(self):
        invoice = self._invoice()
        invoice.total_local_kwh = Decimal("10.00")
        invoice.total_grid_kwh = Decimal("10.00")
        invoice.save(update_fields=["total_local_kwh", "total_grid_kwh"])

        # Local rate (15 rp/kWh) < Grid rate (20 rp/kWh)
        InvoiceItem.objects.create(
            invoice=invoice,
            item_type=InvoiceItem.ItemType.LOCAL_ENERGY,
            tariff_category=TariffCategory.ENERGY,
            description="Local energy",
            quantity_kwh=Decimal("10.00"),
            unit="kWh",
            unit_price_chf=Decimal("0.15"),
            total_chf=Decimal("1.50"),
        )
        InvoiceItem.objects.create(
            invoice=invoice,
            item_type=InvoiceItem.ItemType.GRID_ENERGY,
            tariff_category=TariffCategory.GRID_FEES,
            description="Grid energy",
            quantity_kwh=Decimal("10.00"),
            unit="kWh",
            unit_price_chf=Decimal("0.20"),
            total_chf=Decimal("2.00"),
        )

        result = _build_savings_data(invoice, INVOICE_TRANSLATIONS["de"])

        self.assertIsNotNone(result)
        bar_pct = float(result["bar_pct"])
        savings_bar_pct = float(result["savings_bar_pct"])
        self.assertAlmostEqual(bar_pct + savings_bar_pct, 100.0, places=1)

    def test_energy_flow_svg_returns_none_when_no_readings(self):
        invoice = self._invoice()

        result = _build_energy_flow_svg(invoice, INVOICE_TRANSLATIONS["de"])

        self.assertIsNone(result)

    def test_energy_flow_svg_renders_with_valid_data(self):
        from metering.models import MeterReading, ReadingDirection, ReadingResolution
        from zev.models import MeteringPoint, MeteringPointAssignment, MeteringPointType

        invoice = self._invoice()
        invoice.total_local_kwh = Decimal("10.00")
        invoice.total_grid_kwh = Decimal("20.00")
        invoice.save(update_fields=["total_local_kwh", "total_grid_kwh"])

        cons_mp = MeteringPoint.objects.create(
            zev=self.zev,
            meter_id="CH00000000000000000000000000FLOW01",
            meter_type=MeteringPointType.CONSUMPTION,
        )
        MeteringPointAssignment.objects.create(
            metering_point=cons_mp,
            participant=self.participant,
            valid_from=date(2026, 1, 1),
        )
        prod_mp = MeteringPoint.objects.create(
            zev=self.zev,
            meter_id="CH00000000000000000000000000FLOW02",
            meter_type=MeteringPointType.PRODUCTION,
        )

        ts = datetime(2026, 1, 15, 12, 0, tzinfo=dt_timezone.utc)
        MeterReading.objects.create(
            metering_point=cons_mp, timestamp=ts,
            energy_kwh=Decimal("5.0000"), direction=ReadingDirection.IN,
            resolution=ReadingResolution.DAILY,
        )
        MeterReading.objects.create(
            metering_point=prod_mp, timestamp=ts,
            energy_kwh=Decimal("8.0000"), direction=ReadingDirection.OUT,
            resolution=ReadingResolution.DAILY,
        )

        result = _build_energy_flow_svg(invoice, INVOICE_TRANSLATIONS["de"])

        self.assertIsNotNone(result)
        self.assertIn("<svg", result)

    def test_energy_summary_computes_local_share(self):
        invoice = self._invoice()
        invoice.total_local_kwh = Decimal("60.00")
        invoice.total_grid_kwh = Decimal("40.00")
        invoice.save(update_fields=["total_local_kwh", "total_grid_kwh"])

        result = _build_energy_summary(invoice)

        self.assertIsNotNone(result)
        self.assertEqual(result["local_kwh"], "60.0")
        self.assertEqual(result["grid_kwh"], "40.0")
        self.assertEqual(result["total_kwh"], "100.0")
        self.assertEqual(result["local_share_pct"], "60")

    def test_energy_summary_returns_none_when_no_energy(self):
        invoice = self._invoice()
        invoice.total_local_kwh = Decimal("0")
        invoice.total_grid_kwh = Decimal("0")
        invoice.save(update_fields=["total_local_kwh", "total_grid_kwh"])

        result = _build_energy_summary(invoice)

        self.assertIsNone(result)

    def test_hourly_profile_returns_none_for_daily_only_resolution(self):
        from metering.models import MeterReading, ReadingDirection, ReadingResolution
        from zev.models import MeteringPoint, MeteringPointAssignment, MeteringPointType

        invoice = self._invoice()
        invoice.total_local_kwh = Decimal("10.00")
        invoice.total_grid_kwh = Decimal("20.00")
        invoice.save(update_fields=["total_local_kwh", "total_grid_kwh"])

        mp = MeteringPoint.objects.create(
            zev=self.zev,
            meter_id="CH00000000000000000000000000DAILY01",
            meter_type=MeteringPointType.CONSUMPTION,
        )
        MeteringPointAssignment.objects.create(
            metering_point=mp, participant=self.participant, valid_from=date(2026, 1, 1),
        )

        ts = datetime(2026, 1, 15, 0, 0, tzinfo=dt_timezone.utc)
        MeterReading.objects.create(
            metering_point=mp, timestamp=ts,
            energy_kwh=Decimal("10.0000"), direction=ReadingDirection.IN,
            resolution=ReadingResolution.DAILY,
        )

        result = _build_hourly_profile_chart_svg(invoice, INVOICE_TRANSLATIONS["de"])

        self.assertIsNone(result)

    def test_inline_qr_disabled_for_long_invoice(self):
        invoice = self._invoice()
        # Create 5 categories x 3 items = 15 items = 25 table rows (> 12)
        for i in range(15):
            InvoiceItem.objects.create(
                invoice=invoice,
                item_type=InvoiceItem.ItemType.LOCAL_ENERGY,
                tariff_category=TariffCategory.ENERGY,
                description=f"Item {i}",
                quantity_kwh=Decimal("1.00"),
                unit="kWh",
                unit_price_chf=Decimal("0.10"),
                total_chf=Decimal("0.10"),
            )

        context = _build_template_context(invoice)

        self.assertFalse(context["inline_qr_payment"])

    def test_inline_qr_disabled_when_notes_present(self):
        invoice = self._invoice()
        invoice.notes = "Custom notes"
        invoice.save(update_fields=["notes"])
        InvoiceItem.objects.create(
            invoice=invoice,
            item_type=InvoiceItem.ItemType.LOCAL_ENERGY,
            tariff_category=TariffCategory.ENERGY,
            description="Solar Work Tariff",
            quantity_kwh=Decimal("10.00"),
            unit="kWh",
            unit_price_chf=Decimal("0.12345"),
            total_chf=Decimal("1.23"),
        )

        context = _build_template_context(invoice)

        self.assertFalse(context["inline_qr_payment"])

    def test_inline_qr_disabled_when_no_bank_iban(self):
        invoice = self._invoice()
        invoice.zev.bank_iban = ""
        invoice.zev.save(update_fields=["bank_iban"])

        context = _build_template_context(invoice)

        self.assertFalse(context["inline_qr_payment"])

    def test_due_date_empty_when_not_set(self):
        invoice = self._invoice()
        invoice.due_date = None
        invoice.save(update_fields=["due_date"])

        context = _build_template_context(invoice)

        self.assertEqual(context["formatted_dates"]["due_date"], "")


class InvoicePdfRenderingTests(TestCase):
    """Integration tests that render actual PDFs and verify page counts."""

    def setUp(self):
        self.owner = User.objects.create_user(
            username="render_owner", password="pass1234", role=UserRole.ZEV_OWNER,
        )
        self.zev = Zev.objects.create(
            name="Render ZEV", owner=self.owner, zev_type="vzev",
            start_date=date(2026, 1, 1), billing_interval="monthly",
            invoice_prefix="Q", bank_iban="CH9300762011623852957",
            invoice_language="de",
        )
        self.owner_participant = Participant.objects.create(
            zev=self.zev, user=self.owner, first_name="Test", last_name="Owner",
            email="owner@example.com", address_line1="Bahnhofstrasse 1",
            postal_code="8001", city="Zuerich", valid_from=date(2026, 1, 1),
        )
        self.participant = Participant.objects.create(
            zev=self.zev, first_name="Alice", last_name="Muster",
            email="alice@example.com", address_line1="Musterweg 3",
            postal_code="3000", city="Bern", valid_from=date(2026, 1, 1),
        )

    def _invoice(self, **kwargs):
        defaults = dict(
            invoice_number="Q-00001", zev=self.zev, participant=self.participant,
            period_start=date(2026, 1, 1), period_end=date(2026, 1, 31),
            total_chf=Decimal("42.00"), total_local_kwh=Decimal("10.00"),
            total_grid_kwh=Decimal("20.00"),
        )
        defaults.update(kwargs)
        return Invoice.objects.create(**defaults)

    def _page_count(self, pdf_bytes: bytes) -> int:
        from pypdf import PdfReader
        return len(PdfReader(io.BytesIO(pdf_bytes)).pages)

    def _make_items(self, invoice, count, category=TariffCategory.ENERGY):
        for i in range(count):
            InvoiceItem.objects.create(
                invoice=invoice, item_type=InvoiceItem.ItemType.LOCAL_ENERGY,
                tariff_category=category, description=f"Item {i}",
                quantity_kwh=Decimal("10.00"), unit="kWh",
                unit_price_chf=Decimal("0.12"), total_chf=Decimal("1.20"),
            )

    def test_short_invoice_renders_two_pages(self):
        """Short invoice: page 1 = invoice+inline QR, page 2 = insights."""
        invoice = self._invoice()
        self._make_items(invoice, 3)

        pdf = generate_pdf(invoice)

        self.assertEqual(self._page_count(pdf), 2)

    def test_long_invoice_forces_three_pages(self):
        """Long invoice: page 1 = invoice, page 2 = insights, page 3 = payment+QR."""
        invoice = self._invoice()
        self._make_items(invoice, 10)

        pdf = generate_pdf(invoice)

        self.assertEqual(self._page_count(pdf), 3)

    def test_invoice_with_savings_and_many_items_forces_three_pages(self):
        invoice = self._invoice(
            total_local_kwh=Decimal("100.00"),
            total_grid_kwh=Decimal("50.00"),
        )
        # Local energy item
        InvoiceItem.objects.create(
            invoice=invoice, item_type=InvoiceItem.ItemType.LOCAL_ENERGY,
            tariff_category=TariffCategory.ENERGY, description="Local solar",
            quantity_kwh=Decimal("100.00"), unit="kWh",
            unit_price_chf=Decimal("0.15"), total_chf=Decimal("15.00"),
        )
        # Grid energy item
        InvoiceItem.objects.create(
            invoice=invoice, item_type=InvoiceItem.ItemType.GRID_ENERGY,
            tariff_category=TariffCategory.GRID_FEES, description="Grid import",
            quantity_kwh=Decimal("50.00"), unit="kWh",
            unit_price_chf=Decimal("0.22"), total_chf=Decimal("11.00"),
        )
        # Additional items to push over the limit
        self._make_items(invoice, 6, TariffCategory.LEVIES)

        pdf = generate_pdf(invoice)

        self.assertEqual(self._page_count(pdf), 3)

    def test_realistic_many_levies_invoice_paginates_with_single_slip(self):
        """Maintainer concern: an EVU-style invoice with ~5 Abgaben no longer
        fits on one page. The layout must paginate the line items across pages
        while keeping exactly one QR-Rechnung slip on the final payment page."""
        invoice = self._invoice(
            invoice_number="Q-00030",
            period_start=date(2026, 1, 1),
            period_end=date(2026, 3, 31),
            total_local_kwh=Decimal("120.00"),
            total_grid_kwh=Decimal("150.00"),
            subtotal_chf=Decimal("120.00"),
            vat_rate=Decimal("8.1000"),
            vat_chf=Decimal("9.72"),
            total_chf=Decimal("129.72"),
        )

        def add(item_type, category, description, qty, unit, price, total):
            InvoiceItem.objects.create(
                invoice=invoice, item_type=item_type, tariff_category=category,
                description=description, quantity_kwh=Decimal(qty), unit=unit,
                unit_price_chf=Decimal(price), total_chf=Decimal(total),
            )

        add(InvoiceItem.ItemType.LOCAL_ENERGY, TariffCategory.ENERGY,
            "Local Solar Energy", "120.00", "kWh", "0.18000", "21.60")
        add(InvoiceItem.ItemType.GRID_ENERGY, TariffCategory.ENERGY,
            "Grid Energy HT/NT", "150.00", "kWh", "0.29500", "44.25")
        add(InvoiceItem.ItemType.FEE, TariffCategory.GRID_FEES,
            "Netznutzung", "150.00", "kWh", "0.07500", "11.25")
        for name, price, total in [
            ("Bundesabgaben", "0.02300", "3.45"),
            ("Stromreserve", "0.00410", "0.62"),
            ("Solidarisierte Kosten", "0.00050", "0.08"),
            ("Förderung Energieeffizienz", "0.00160", "0.24"),
            ("Konzessionsabgabe", "0.00300", "0.45"),
        ]:
            add(InvoiceItem.ItemType.FEE, TariffCategory.LEVIES,
                name, "150.00", "kWh", price, total)
        add(InvoiceItem.ItemType.FEE, TariffCategory.METERING,
            "Metering Service Fee (3 Monate)", "3.00", "Monat", "8.50000", "25.50")

        # All four cost categories render as separate groups.
        context = _build_template_context(invoice)
        self.assertEqual(
            {group["key"] for group in context["grouped_items"]},
            {TariffCategory.ENERGY, TariffCategory.GRID_FEES,
             TariffCategory.LEVIES, TariffCategory.METERING},
        )
        # Too tall for the inline single-page layout.
        self.assertFalse(context["inline_qr_payment"])

        pdf = generate_pdf(invoice)
        self.assertGreaterEqual(self._page_count(pdf), 3)
        self.assertEqual(
            _count_qr_slips(pdf), 1,
            "Many-line invoice must carry exactly one QR-Rechnung slip",
        )

    def test_all_four_languages_render_without_error(self):
        for lang in ("de", "fr", "it", "en"):
            self.zev.invoice_language = lang
            self.zev.save(update_fields=["invoice_language"])
            invoice = self._invoice(invoice_number=f"Q-{lang.upper()}")
            self._make_items(invoice, 3)

            pdf = generate_pdf(invoice)

            self.assertGreater(len(pdf), 1000, f"PDF for {lang} is too small")
            self.assertEqual(self._page_count(pdf), 2, f"PDF for {lang} should be 2 pages (invoice + insights)")

    def test_shared_lines_render_with_marker(self):
        """A community-allocated line item's marker text must actually reach
        the rendered PDF, in every invoice language (§7.6) — not just the
        description string the engine builds (covered in
        ``test_shared_metering.py``)."""
        from pypdf import PdfReader

        markers = {
            "de": "Gemeinschaftsanteil",
            "fr": "Part communautaire",
            "it": "Quota comunitaria",
            "en": "Community share",
        }
        for lang, marker in markers.items():
            with self.subTest(lang=lang):
                self.zev.invoice_language = lang
                self.zev.save(update_fields=["invoice_language"])
                invoice = self._invoice(invoice_number=f"Q-SHARED-{lang.upper()}")
                InvoiceItem.objects.create(
                    invoice=invoice, item_type=InvoiceItem.ItemType.GRID_ENERGY,
                    tariff_category=TariffCategory.ENERGY,
                    description=f"Netzenergie ({marker})",
                    quantity_kwh=Decimal("5.00"), unit="kWh",
                    unit_price_chf=Decimal("0.20000"), total_chf=Decimal("1.00"),
                )

                pdf = generate_pdf(invoice)
                reader = PdfReader(io.BytesIO(pdf))
                text = "\n".join(page.extract_text() for page in reader.pages)

                self.assertIn(marker, text)

    # ── QR-Rechnung placement tests ──────────────────────────────────────
    # The Swiss payment slip must be exactly 106 mm tall and flush with the
    # page bottom.  We verify this by parsing the PDF content stream for the
    # clip rect (re + W) that defines the QR section area.

    _QR_HEIGHT_MM = 106
    _QR_HEIGHT_CSS = _QR_HEIGHT_MM * 96 / 25.4  # ≈ 400.6 CSS px
    _TOLERANCE_MM = 1.5  # accounts for WeasyPrint sub-pixel rounding (~0.7 mm inline gap)
    _TOLERANCE_CSS = _TOLERANCE_MM * 96 / 25.4  # ≈ 5.7 CSS px

    def _find_payment_slip_rect(self, reader):
        """Return the QR slip clip rect from whichever page carries it.

        The insights page is appended *after* the dedicated payment page, so
        the slip is not necessarily on the last page; locate it by scanning.
        """
        for page in reader.pages:
            rect = _find_qr_clip_rect(page)
            if rect is not None:
                return rect
        return None

    def test_inline_qr_is_106mm_high(self):
        """Short invoice: inline QR section must be 106 mm tall."""
        from pypdf import PdfReader

        invoice = self._invoice()
        self._make_items(invoice, 3)

        pdf = generate_pdf(invoice)
        reader = PdfReader(io.BytesIO(pdf))
        rect = _find_qr_clip_rect(reader.pages[0])

        self.assertIsNotNone(rect, "QR clip rect not found on page 0")
        _, height_css, _ = rect
        self.assertAlmostEqual(
            height_css, self._QR_HEIGHT_CSS, delta=self._TOLERANCE_CSS,
            msg=f"QR height should be ~106 mm, got {height_css * 25.4 / 96:.1f} mm",
        )

    def test_inline_qr_bottom_aligns_with_page_bottom(self):
        """Short invoice: inline QR bottom edge must reach the page bottom."""
        from pypdf import PdfReader

        invoice = self._invoice()
        self._make_items(invoice, 3)

        pdf = generate_pdf(invoice)
        reader = PdfReader(io.BytesIO(pdf))
        rect = _find_qr_clip_rect(reader.pages[0])

        self.assertIsNotNone(rect, "QR clip rect not found on page 0")
        top_y, height_css, page_h = rect
        bottom = top_y + height_css
        gap = page_h - bottom
        self.assertLessEqual(
            gap, self._TOLERANCE_CSS,
            msg=f"QR bottom is {gap * 25.4 / 96:.1f} mm from page bottom, "
                f"must be ≤ {self._TOLERANCE_MM} mm",
        )

    def test_separate_payment_qr_is_106mm_high(self):
        """Long invoice: payment page QR section must be 106 mm tall."""
        from pypdf import PdfReader

        invoice = self._invoice()
        self._make_items(invoice, 10)

        pdf = generate_pdf(invoice)
        reader = PdfReader(io.BytesIO(pdf))
        # The insights page follows the payment page, so locate the slip by
        # scanning rather than assuming a fixed page index.
        rect = self._find_payment_slip_rect(reader)

        self.assertIsNotNone(rect, "QR clip rect not found on payment page")
        _, height_css, _ = rect
        self.assertAlmostEqual(
            height_css, self._QR_HEIGHT_CSS, delta=self._TOLERANCE_CSS,
            msg=f"QR height should be ~106 mm, got {height_css * 25.4 / 96:.1f} mm",
        )

    def test_separate_payment_qr_bottom_aligns_with_page_bottom(self):
        """Long invoice: payment page QR bottom edge must reach page bottom."""
        from pypdf import PdfReader

        invoice = self._invoice()
        self._make_items(invoice, 10)

        pdf = generate_pdf(invoice)
        reader = PdfReader(io.BytesIO(pdf))
        # The insights page follows the payment page, so locate the slip by
        # scanning rather than assuming a fixed page index.
        rect = self._find_payment_slip_rect(reader)

        self.assertIsNotNone(rect, "QR clip rect not found on payment page")
        top_y, height_css, page_h = rect
        bottom = top_y + height_css
        gap = page_h - bottom
        self.assertLessEqual(
            gap, self._TOLERANCE_CSS,
            msg=f"QR bottom is {gap * 25.4 / 96:.1f} mm from page bottom, "
                f"must be ≤ {self._TOLERANCE_MM} mm",
        )

    def test_qr_clip_rect_not_found_on_insights_page(self):
        """Insights page must not contain a QR clip rect."""
        from pypdf import PdfReader

        invoice = self._invoice()
        self._make_items(invoice, 3)

        pdf = generate_pdf(invoice)
        reader = PdfReader(io.BytesIO(pdf))
        # 2-page inline QR: page 0 = invoice, page 1 = insights
        rect = _find_qr_clip_rect(reader.pages[1])

        self.assertIsNone(rect, "Insights page should not have a QR clip rect")

    # A description long enough to wrap onto three lines in the 48% column.
    _WRAPPING_DESC = (
        "Solar energy local consumption tariff for the shared photovoltaic "
        "installation on the rooftop including winter reserve adjustment"
    )

    def _make_wrapping_items(self, invoice, count):
        for i in range(count):
            InvoiceItem.objects.create(
                invoice=invoice, item_type=InvoiceItem.ItemType.LOCAL_ENERGY,
                tariff_category=TariffCategory.ENERGY,
                description=f"{self._WRAPPING_DESC} {i}",
                quantity_kwh=Decimal("10.00"), unit="kWh",
                unit_price_chf=Decimal("0.12"), total_chf=Decimal("1.20"),
            )

    def test_wrapping_descriptions_do_not_duplicate_qr(self):
        """Regression: wrapping rows that overflow the inline estimate must
        not render the payment slip on more than one page.  The fast estimate
        still flags these as inline, so the render-time guard must downgrade
        them to the dedicated payment page (exactly one slip)."""
        invoice = self._invoice()
        self._make_wrapping_items(invoice, 9)

        # The estimate (pre-filter) thinks this fits inline ...
        self.assertTrue(_build_template_context(invoice)["inline_qr_payment"])

        pdf = generate_pdf(invoice)

        # ... but the real layout must carry a single slip.
        self.assertEqual(
            _count_qr_slips(pdf), 1,
            "QR-Rechnung must appear on exactly one page even when line "
            "items wrap and overflow the inline height estimate",
        )

    def test_many_rows_render_single_qr_on_final_page(self):
        """A long invoice (dedicated payment page) must carry exactly one
        slip, flush with the bottom of its page."""
        from pypdf import PdfReader

        invoice = self._invoice()
        self._make_items(invoice, 30)

        pdf = generate_pdf(invoice)

        self.assertEqual(_count_qr_slips(pdf), 1)
        reader = PdfReader(io.BytesIO(pdf))
        rect = self._find_payment_slip_rect(reader)
        self.assertIsNotNone(rect, "Slip must be on the payment page")
        top_y, height_css, page_h = rect
        self.assertLessEqual(
            page_h - (top_y + height_css), self._TOLERANCE_CSS,
            msg="Slip on the payment page must be bottom-aligned",
        )


class TranslationParityTests(TestCase):
    def test_all_locales_have_identical_keys_with_nonempty_values(self):
        locales = list(INVOICE_TRANSLATIONS.values())
        key_sets = [sorted(d.keys()) for d in locales]
        self.assertEqual(len(set(map(tuple, key_sets))), 1, "All locales must define the same keys")
        for locale_name, keys in zip(INVOICE_TRANSLATIONS.keys(), key_sets):
            for key in keys:
                val = INVOICE_TRANSLATIONS[locale_name][key]
                if isinstance(val, dict):
                    for sub_key, sub_val in val.items():
                        self.assertIsInstance(sub_val, str, f"{locale_name}.{key}.{sub_key} must be a string")
                        self.assertTrue(sub_val.strip(), f"{locale_name}.{key}.{sub_key} must be non-empty")
                    continue
                self.assertIsInstance(val, str, f"{locale_name}.{key} must be a string")
                self.assertTrue(val.strip(), f"{locale_name}.{key} must be non-empty")

    def test_all_locales_have_identical_status_values_keys(self):
        key_sets = {
            tuple(sorted(d["status_values"].keys()))
            for d in INVOICE_TRANSLATIONS.values()
        }
        self.assertEqual(len(key_sets), 1, "All locales must define the same status_values keys")


class PaletteConsistencyTests(TestCase):
    """Python chart palette constants must match the CSS :root custom properties."""

    # Expected mappings: Python constant → CSS variable name → hex value
    _MAPPINGS = {
        "_CHART_INK": "#0f172a",     # --ink
        "_CHART_MUTED": "#64748b",   # --muted
        "_CHART_LABEL": "#334155",   # --ink-soft
        "_CHART_BG": "#fbfcfb",      # --chart-surface
    }

    def test_chart_constants_match_css_variables(self):
        actual = {
            "_CHART_INK": _CHART_INK,
            "_CHART_MUTED": _CHART_MUTED,
            "_CHART_LABEL": _CHART_LABEL,
            "_CHART_BG": _CHART_BG,
        }
        for name, expected_hex in self._MAPPINGS.items():
            self.assertEqual(
                actual[name], expected_hex,
                f"{name} = {actual[name]} does not match expected {expected_hex}",
            )


class StatusTranslationTests(TestCase):
    """Status pill must use translated status, not Django's English get_status_display."""

    def test_status_display_is_translated_in_context(self):
        """_build_template_context includes a translated status_display key."""
        owner = User.objects.create_user(
            username="status_owner",
            password="pass1234",
            role=UserRole.ZEV_OWNER,
        )
        zev = Zev.objects.create(
            name="Status ZEV",
            owner=owner,
            zev_type="vzev",
            start_date=date(2026, 1, 1),
            billing_interval="monthly",
            invoice_prefix="S",
            invoice_language="de",
        )
        participant = Participant.objects.create(
            zev=zev,
            first_name="Alice",
            last_name="Muster",
            email="alice@example.com",
            address_line1="Musterweg 3",
            postal_code="3000",
            city="Bern",
            valid_from=date(2026, 1, 1),
        )
        invoice = Invoice.objects.create(
            invoice_number="S-00001",
            zev=zev,
            participant=participant,
            period_start=date(2025, 1, 1),
            period_end=date(2025, 3, 31),
            status="sent",
        )
        ctx = _build_template_context(invoice)

        # Must have a status_display key that is not the English label
        self.assertIn("status_display", ctx)
        self.assertNotEqual(ctx["status_display"], "Sent",
                            "status_display should be translated, not English")
        self.assertEqual(ctx["status_display"], "Versendet")



class PeriodParticipantStatsTests(TestCase):
    """``_compute_period_participant_stats`` attributes readings per timestamp
    (ADR 0013) and must not double-count readings across assignments."""

    PERIOD_START = date(2026, 1, 1)
    PERIOD_END = date(2026, 1, 31)

    def setUp(self):
        self.zev = Zev.objects.create(
            name="Stats ZEV",
            owner=User.objects.create_user(
                username="stats_owner", password="pass1234", role=UserRole.ZEV_OWNER),
            zev_type="vzev",
            start_date=self.PERIOD_START,
            billing_interval="monthly",
            invoice_prefix="ST",
        )
        self.zev.refresh_from_db()

    def _reading(self, metering_point, day, kwh):
        return MeterReading.objects.create(
            metering_point=metering_point,
            timestamp=datetime(day.year, day.month, day.day, 12, 0, tzinfo=dt_timezone.utc),
            energy_kwh=Decimal(kwh),
            direction=ReadingDirection.IN,
        )

    def _stats(self):
        from .pdf_stats import _compute_period_participant_stats
        invoice = Invoice.objects.create(
            invoice_number=f"ST-{Invoice.objects.count() + 1:05d}",
            zev=self.zev,
            participant=self.participant,
            period_start=self.PERIOD_START,
            period_end=self.PERIOD_END,
            status=InvoiceStatus.DRAFT,
        )
        return _compute_period_participant_stats(invoice)

    def test_mid_period_transfer_is_attributed_per_reading(self):
        """A metering point handed over mid-period attributes each reading to
        its holder without double-counting (join fan-out regression)."""
        alice = make_named_participant(self.zev, "Alice Muster", self.PERIOD_START, date(2026, 1, 15))
        bob = make_named_participant(self.zev, "Bob Beispiel", date(2026, 1, 16))
        self.participant = alice
        metering_point = MeteringPoint.objects.create(
            zev=self.zev, meter_type=MeteringPointType.CONSUMPTION)
        MeteringPointAssignment.objects.create(
            metering_point=metering_point, participant=alice,
            valid_from=self.PERIOD_START, valid_to=date(2026, 1, 15))
        MeteringPointAssignment.objects.create(
            metering_point=metering_point, participant=bob,
            valid_from=date(2026, 1, 16), valid_to=None)
        self._reading(metering_point, date(2026, 1, 5), "4")
        self._reading(metering_point, date(2026, 1, 20), "6")

        _, stats = self._stats()
        by_name = {s["participant_name"]: s for s in stats}

        assert by_name["Alice Muster"]["total_consumed_kwh"] == 4.0
        assert by_name["Bob Beispiel"]["total_consumed_kwh"] == 6.0

    def test_readings_in_an_assignment_gap_appear_in_no_participants_stats(self):
        alice = make_named_participant(self.zev, "Alice Muster", self.PERIOD_START, date(2026, 1, 10))
        bob = make_named_participant(self.zev, "Bob Beispiel", date(2026, 1, 20))
        self.participant = alice
        metering_point = MeteringPoint.objects.create(
            zev=self.zev, meter_type=MeteringPointType.CONSUMPTION)
        MeteringPointAssignment.objects.create(
            metering_point=metering_point, participant=alice,
            valid_from=self.PERIOD_START, valid_to=date(2026, 1, 10))
        MeteringPointAssignment.objects.create(
            metering_point=metering_point, participant=bob,
            valid_from=date(2026, 1, 20), valid_to=None)
        self._reading(metering_point, date(2026, 1, 5), "2")
        self._reading(metering_point, date(2026, 1, 15), "3")  # gap

        _, stats = self._stats()
        by_name = {s["participant_name"]: s for s in stats}

        # The gap reading never lands on anyone.
        assert by_name["Alice Muster"]["total_consumed_kwh"] == 2.0
        assert "Bob Beispiel" not in by_name

    def test_a_holder_who_left_the_zev_keeps_their_name_in_the_period_stats(self):
        """The stats are a historical document: a participant who held a meter
        during the billed period but has since left the ZEV must still be
        named — the lookup is keyed off the assignment windows, not the
        current participant list."""
        alice = make_named_participant(self.zev, "Alice Muster", self.PERIOD_START)
        bob = make_named_participant(self.zev, "Bob Beispiel", self.PERIOD_START)
        self.participant = bob
        metering_point = MeteringPoint.objects.create(
            zev=self.zev, meter_type=MeteringPointType.CONSUMPTION)
        MeteringPointAssignment.objects.create(
            metering_point=metering_point, participant=alice,
            valid_from=self.PERIOD_START, valid_to=date(2026, 1, 15))
        MeteringPointAssignment.objects.create(
            metering_point=metering_point, participant=bob,
            valid_from=date(2026, 1, 16), valid_to=None)
        self._reading(metering_point, date(2026, 1, 5), "4")
        self._reading(metering_point, date(2026, 1, 20), "6")

        # Alice leaves the ZEV after the period: her assignments stay with the
        # metering point, but she is no longer in zev.participants.
        other_zev = Zev.objects.create(
            name="Other ZEV",
            owner=User.objects.create_user(
                username="other_owner", password="pass1234", role=UserRole.ZEV_OWNER),
            zev_type="vzev",
            start_date=self.PERIOD_START,
            billing_interval="monthly",
            invoice_prefix="OT",
        )
        alice.zev = other_zev
        alice.save()

        _, stats = self._stats()
        by_id = {s["participant_id"]: s for s in stats}

        assert by_id[str(alice.id)]["participant_name"] == "Alice Muster"
        assert by_id[str(alice.id)]["total_consumed_kwh"] == 4.0
        assert by_id[str(bob.id)]["participant_name"] == "Bob Beispiel"

    def test_stats_reconcile_with_the_engine_for_full_period_assignments(self):
        """For unchanged data the PDF stats split matches the billed invoice
        totals exactly."""
        from .engine import generate_invoice
        alice = make_named_participant(self.zev, "Alice Muster", self.PERIOD_START)
        self.participant = alice
        metering_point = MeteringPoint.objects.create(
            zev=self.zev, meter_type=MeteringPointType.CONSUMPTION)
        MeteringPointAssignment.objects.create(
            metering_point=metering_point, participant=alice,
            valid_from=self.PERIOD_START, valid_to=None)
        for day in (5, 15, 25):
            self._reading(metering_point, date(2026, 1, day), "2")

        invoice = generate_invoice(alice, self.PERIOD_START, self.PERIOD_END)
        _, stats = self._stats()
        row = next(s for s in stats if s["participant_name"] == "Alice Muster")

        assert float(invoice.total_local_kwh) == row["from_zev_kwh"]
        assert float(invoice.total_grid_kwh) == row["from_grid_kwh"]
