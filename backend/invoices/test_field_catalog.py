"""Check catalog paths, template coverage, and API payloads."""

import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from invoices.field_catalog import (
    EMAIL_FIELD_CATALOGS,
    EMAIL_SAMPLE_CONTEXTS,
    PDF_FIELD_CATALOGS,
    PDF_SAMPLE_CONTEXTS,
    _resolve_sample_path,
    email_field_catalog,
    pdf_field_catalog,
)


PDF_TEMPLATE_PATHS = {
    "invoice": "invoices/invoice_pdf.html",
    "contract": "contracts/participant_contract_pdf.html",
    "annual_statement": "invoices/annual_statement_pdf.html",
}

# Template-local bindings are not context fields or independent insertions.
DEFAULT_TEMPLATE_LOCAL_OUTPUTS = {
    "invoice": {"item_count"},
    "contract": {"item", "category", "period"},
    "annual_statement": set(),
}


def _template_translation_keys(template_type):
    template_path = Path(settings.BASE_DIR) / "templates" / PDF_TEMPLATE_PATHS[template_type]
    template = template_path.read_text(encoding="utf-8")
    return set(re.findall(r"\{\{\s*tr\.([A-Za-z_][A-Za-z0-9_]*)\b[^}]*\}\}", template))


def _entries(catalog):
    for group in catalog:
        for entry in group["fields"]:
            yield entry


def _normalized_variable_key(variable):
    kind = "output" if variable.startswith("{{") else "block" if variable.startswith("{%") else "email"
    opening = 2 if kind in {"output", "block"} else 1
    closing = 2 if variable.endswith(("}}", "%}")) else 1
    inner = variable[opening:-closing].split("|", 1)[0]
    return kind, "".join(inner.split())


class PdfCatalogResolutionTests(SimpleTestCase):
    def test_every_sample_path_resolves_against_its_context(self):
        for template_type, groups in PDF_FIELD_CATALOGS.items():
            context = PDF_SAMPLE_CONTEXTS[template_type]()
            with self.subTest(template_type=template_type):
                for entry in _entries(groups):
                    with self.subTest(variable=entry["variable"]):
                        value = _resolve_sample_path(entry["sample_path"], context)
                        # SVG samples may be None; other fields need examples.
                        if "|safe" not in entry["variable"]:
                            self.assertIsNotNone(value, "sample context value must be non-None")

    def test_resolved_examples_are_computed_not_hand_typed(self):
        for template_type, groups in PDF_FIELD_CATALOGS.items():
            with self.subTest(template_type=template_type):
                for entry in _entries(groups):
                    self.assertNotIn("example", entry)

    def test_variables_are_unique_within_a_catalog(self):
        for template_type, groups in PDF_FIELD_CATALOGS.items():
            variables = [entry["variable"] for entry in _entries(groups)]
            with self.subTest(template_type=template_type):
                self.assertEqual(len(variables), len(set(variables)))
                normalized = [_normalized_variable_key(variable) for variable in variables]
                self.assertEqual(len(normalized), len(set(normalized)))

    def test_catalog_covers_concrete_translation_tokens_in_default_templates(self):
        for template_type, groups in PDF_FIELD_CATALOGS.items():
            catalog_variables = {entry["variable"] for entry in _entries(groups)}
            catalog_translation_variables = {
                variable.removeprefix("{{ ").removesuffix(" }}")
                for variable in catalog_variables
                if variable.startswith("{{ tr.")
            }
            with self.subTest(template_type=template_type):
                template_keys = _template_translation_keys(template_type)
                self.assertEqual(
                    {f"tr.{key}" for key in template_keys},
                    catalog_translation_variables,
                )

    def test_catalog_covers_default_template_output_tokens(self):
        for template_type, groups in PDF_FIELD_CATALOGS.items():
            template_path = Path(settings.BASE_DIR) / "templates" / PDF_TEMPLATE_PATHS[template_type]
            template = template_path.read_text(encoding="utf-8")
            output_tokens = {
                expression.split("|", 1)[0].strip()
                for expression in re.findall(r"\{\{\s*([^}]+?)\s*\}\}", template)
            }
            catalog_tokens = {
                entry["variable"].removeprefix("{{").removesuffix("}}").split("|", 1)[0].strip()
                for entry in _entries(groups)
                if entry["variable"].startswith("{{")
            }
            with self.subTest(template_type=template_type):
                self.assertEqual(
                    output_tokens - DEFAULT_TEMPLATE_LOCAL_OUTPUTS[template_type] - catalog_tokens,
                    set(),
                )

    def test_catalog_contains_the_newer_contract_fields(self):
        variables = {entry["variable"] for entry in _entries(PDF_FIELD_CATALOGS["contract"])}
        for variable in (
            "{{ participation_start }}",
            "{{ document_id }}",
            "{{ vat_rate_display }}",
            "{{ tariff_rule }}",
            "{{ tariff_pct_line }}",
            "{{ tariff_reference_product }}",
            "{{ row.validity }}",
            "{{ row.rate_note }}",
            "{{ local_tariff_rows.0.name }}",
            "{{ local_tariff_rows.0.rate_rp }}",
            "{{ local_tariff_rows.0.unit }}",
            "{{ zev.payment_term_days }}",
        ):
            with self.subTest(variable=variable):
                self.assertIn(variable, variables)

    def test_catalog_contains_newer_invoice_fields(self):
        variables = {entry["variable"] for entry in _entries(PDF_FIELD_CATALOGS["invoice"])}
        for variable in (
            "{{ invoice.zev.invoice_language|default:'de' }}",
            "{{ access_qr_svg|safe }}",
        ):
            with self.subTest(variable=variable):
                self.assertIn(variable, variables)


class EmailCatalogResolutionTests(SimpleTestCase):
    def test_every_sample_path_resolves_against_its_context(self):
        for template_key, groups in EMAIL_FIELD_CATALOGS.items():
            context = EMAIL_SAMPLE_CONTEXTS[template_key]()
            with self.subTest(template_key=template_key):
                for entry in _entries(groups):
                    with self.subTest(variable=entry["variable"]):
                        value = _resolve_sample_path(entry["sample_path"], context)
                        self.assertIsNotNone(value, "sample context value must be non-None")

    def test_email_catalog_covers_the_send_time_contexts(self):
        """Email catalog entries must match the shared send-time format keys."""
        self.assertEqual(set(EMAIL_SAMPLE_CONTEXTS), set(EMAIL_FIELD_CATALOGS))
        for template_key, context_builder in EMAIL_SAMPLE_CONTEXTS.items():
            context = context_builder()
            variables = [entry["variable"] for entry in _entries(EMAIL_FIELD_CATALOGS[template_key])]
            expected = sorted("{" + key + "}" for key in context)
            with self.subTest(template_key=template_key):
                self.assertEqual(sorted(variables), expected)


class CatalogPayloadShapeTests(SimpleTestCase):
    def test_pdf_catalog_payload_has_the_ui_shape(self):
        for template_type in ("invoice", "contract", "annual_statement"):
            with self.subTest(template_type=template_type):
                for group in pdf_field_catalog(template_type):
                    self.assertIn("group_key", group)
                    self.assertIn("group_title_key", group)
                    self.assertIn("fields", group)
                    for entry in group["fields"]:
                        self.assertIn("variable", entry)
                        self.assertIn("description_key", entry)
                        self.assertIn("example", entry)
                        self.assertNotIn("sample_path", entry)
                        self.assertTrue(entry["description_key"].startswith("admin."))

    def test_email_catalog_payload_has_the_ui_shape(self):
        for template_key in ("invoice_email", "participant_onboarding", "email_verification", "participant_magic_link"):
            with self.subTest(template_key=template_key):
                for group in email_field_catalog(template_key):
                    self.assertIsNone(group["group_title_key"])
                    for entry in group["fields"]:
                        self.assertIn("example", entry)
                        self.assertNotIn("sample_path", entry)
                        self.assertTrue(entry["description_key"].startswith("admin."))

    def test_unknown_template_type_returns_empty_catalog(self):
        self.assertEqual(pdf_field_catalog("nonsense"), [])
        self.assertEqual(email_field_catalog("nonsense"), [])

    def test_example_values_match_the_preview(self):
        catalog = {entry["variable"]: entry for entry in _entries(pdf_field_catalog("invoice"))}
        self.assertEqual(catalog["{{ participant.full_name }}"]["example"], "Hans Beispiel")
        self.assertEqual(catalog["{{ invoice.total_chf }}"]["example"], "486.45")
        self.assertEqual(catalog["{{ savings_data.saved_chf }}"]["example"], "12.82")

    def test_svg_and_translation_examples_are_null(self):
        catalog = {entry["variable"]: entry for entry in _entries(pdf_field_catalog("annual_statement"))}
        self.assertIsNone(catalog["{{ monthly_chart_svg|safe }}"]["example"])
        variables = [entry["variable"] for entry in _entries(pdf_field_catalog("contract"))]
        self.assertTrue(any(variable.startswith("{{ tr.") for variable in variables))
        for entry in _entries(pdf_field_catalog("contract")):
            if entry["variable"].startswith("{{ tr."):
                self.assertIsNone(entry["example"])
