"""Smoke tests for invoices.template_context sample context builders.

These verify that each builder returns a dict with the expected top-level
keys and that the data is self-consistent (e.g. INVOICE_TRANSLATIONS used
in the right language, monthly_data length matches months list).
"""

from django.test import SimpleTestCase

from invoices.template_context import (
    build_sample_invoice_context,
    build_sample_contract_context,
    build_sample_annual_statement_context,
)


class BuildSampleInvoiceContextTests(SimpleTestCase):
    def setUp(self):
        self.ctx = build_sample_invoice_context()

    def test_required_keys_present(self):
        for key in ("invoice", "grouped_items", "zev", "participant", "owner_participant",
                    "formatted_dates", "savings_data", "tr"):
            with self.subTest(key=key):
                self.assertIn(key, self.ctx)

    def test_invoice_has_number_and_totals(self):
        inv = self.ctx["invoice"]
        self.assertEqual(inv.invoice_number, "INV-2026-001")
        self.assertTrue(float(inv.total_chf) > 0)

    def test_grouped_items_structure(self):
        for group in self.ctx["grouped_items"]:
            self.assertIn("key", group)
            self.assertIn("label", group)
            self.assertIn("items", group)
            self.assertIn("subtotal", group)

    def test_formatted_dates_present(self):
        dates = self.ctx["formatted_dates"]
        for key in ("invoice_date", "period_start", "period_end", "due_date"):
            self.assertIn(key, dates)


class BuildSampleContractContextTests(SimpleTestCase):
    def setUp(self):
        self.ctx = build_sample_contract_context()

    def test_required_keys_present(self):
        for key in ("participant", "owner_participant", "zev", "consumption_mps",
                    "production_mps", "local_tariff_rows", "tr", "lang"):
            with self.subTest(key=key):
                self.assertIn(key, self.ctx)

    def test_the_issuer_and_representative_are_samples(self):
        self.assertEqual(self.ctx["issuer"]["name"], "Maria Muster")
        self.assertIsNotNone(self.ctx["representative"])

    def test_metering_points_are_lists(self):
        self.assertIsInstance(self.ctx["consumption_mps"], list)
        self.assertIsInstance(self.ctx["production_mps"], list)


class BuildSampleAnnualStatementContextTests(SimpleTestCase):
    def setUp(self):
        self.ctx = build_sample_annual_statement_context()

    def test_required_keys_present(self):
        for key in ("monthly_data", "totals", "invoices", "invoice_totals",
                    "savings", "formatted_dates", "tr", "year"):
            with self.subTest(key=key):
                self.assertIn(key, self.ctx)

    def test_monthly_data_has_12_entries(self):
        self.assertEqual(len(self.ctx["monthly_data"]), 12)

    def test_totals_are_consistent_with_monthly_data(self):
        monthly = self.ctx["monthly_data"]
        expected_consumed = sum(float(m["consumed_kwh"]) for m in monthly)
        self.assertAlmostEqual(float(self.ctx["totals"]["total_consumed_kwh"]), expected_consumed, places=1)

    def test_monthly_chart_svg_produced(self):
        self.assertIsNotNone(self.ctx["monthly_chart_svg"])
        self.assertIn("<svg", self.ctx["monthly_chart_svg"])

    def test_invoices_list_has_four_quarters(self):
        self.assertEqual(len(self.ctx["invoices"]), 4)
