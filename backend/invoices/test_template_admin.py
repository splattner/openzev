"""Coverage for the admin-only template endpoints in ``views_templates``.

The endpoints themselves are old; this module is new because extracting them
from ``InvoiceViewSet`` replaced six hand-written ``if not request.user.is_admin``
checks with a declarative ``IsAdmin`` permission class. Two things had to survive
that swap and were previously untested:

* every one of the six endpoints still refuses a non-admin, and
* the GOVERNANCE audit event written on denial is unchanged.

Both are pinned here so a future change to the permission wiring cannot quietly
drop them.
"""

from django.test import TestCase
from rest_framework.test import APIClient
from weasyprint.urls import URLFetcher

import pytest

from accounts.models import UserRole
from audit.models import AuditActionCategory, AuditEvent, AuditEventStatus
from invoices.contract_pdf import generate_contract_pdf
from invoices.pdf_render import ALLOWED_URL_PROTOCOLS
from invoices.test_helpers import make_participant, make_zev
from testing.helpers import authenticate as auth, make_user

from .models import EMAIL_TEMPLATE_DEFAULTS, EmailTemplate, PdfTemplate
from .views_templates import MAX_TEMPLATE_CHARS

PDF_TEMPLATE_ENDPOINTS = [
    ("pdf-template", "invoices/invoice_pdf.html", "template.invoice_pdf"),
    ("contract-pdf-template", "contracts/participant_contract_pdf.html", "template.contract_pdf"),
    ("annual-statement-pdf-template", "invoices/annual_statement_pdf.html", "template.annual_statement_pdf"),
]

# Every admin-only endpoint in views_templates, as (method, url, payload).
ALL_ENDPOINTS = [
    *[(m, f"/api/v1/invoices/invoices/{path}/", {"content": "<p>x</p>"} if m == "patch" else None)
      for path, _name, _prefix in PDF_TEMPLATE_ENDPOINTS
      for m in ("get", "patch", "delete")],
    ("post", "/api/v1/invoices/invoices/preview-pdf-template/", {"content": "<p>x</p>"}),
    ("get", "/api/v1/invoices/invoices/email-templates/", None),
    ("get", "/api/v1/invoices/invoices/email-template/invoice_email/", None),
    ("patch", "/api/v1/invoices/invoices/email-template/invoice_email/", {"subject": "S", "body": "B"}),
    ("delete", "/api/v1/invoices/invoices/email-template/invoice_email/", None),
]


class TemplateAdminPermissionTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = make_user("tpl_admin", UserRole.ADMIN)
        self.owner = make_user("tpl_owner", UserRole.ZEV_OWNER)
        self.participant = make_user("tpl_participant", UserRole.PARTICIPANT)

    def _call(self, method, url, payload):
        fn = getattr(self.client, method)
        return fn(url, payload, format="json") if payload is not None else fn(url)

    def test_no_endpoint_is_reachable_by_a_non_admin(self):
        """A ZEV owner is the highest non-admin role and must still be refused."""
        for role_name, user in (("owner", self.owner), ("participant", self.participant)):
            for method, url, payload in ALL_ENDPOINTS:
                with self.subTest(role=role_name, method=method, url=url):
                    auth(self.client, user)
                    resp = self._call(method, url, payload)
                    self.assertEqual(resp.status_code, 403)

    def test_no_endpoint_is_reachable_anonymously(self):
        for method, url, payload in ALL_ENDPOINTS:
            with self.subTest(method=method, url=url):
                self.client.credentials()
                resp = self._call(method, url, payload)
                self.assertEqual(resp.status_code, 401)

    def test_anonymous_denial_is_not_audited(self):
        """A 401 is not a governance event — only an authenticated user who lacks admin is."""
        self.client.credentials()
        self.client.get("/api/v1/invoices/invoices/pdf-template/")
        self.assertFalse(AuditEvent.objects.exists())

    def test_non_admin_pdf_template_denial_is_audited(self):
        for path, template_name, action_prefix in PDF_TEMPLATE_ENDPOINTS:
            with self.subTest(template=path):
                AuditEvent.objects.all().delete()
                auth(self.client, self.owner)

                resp = self.client.get(f"/api/v1/invoices/invoices/{path}/")

                self.assertEqual(resp.status_code, 403)
                event = AuditEvent.objects.get()
                self.assertEqual(event.action_category, AuditActionCategory.GOVERNANCE)
                self.assertEqual(event.action_type, f"{action_prefix}.update")
                self.assertEqual(event.status, AuditEventStatus.DENIED)
                self.assertEqual(event.target_type, "invoices.PdfTemplate")
                self.assertEqual(event.target_id, template_name)
                self.assertEqual(
                    event.summary,
                    f"Denied PDF template mutation by non-admin ({template_name}).",
                )

    def test_non_admin_email_template_denial_is_audited(self):
        auth(self.client, self.owner)

        resp = self.client.get("/api/v1/invoices/invoices/email-template/invoice_email/")

        self.assertEqual(resp.status_code, 403)
        event = AuditEvent.objects.get()
        self.assertEqual(event.action_category, AuditActionCategory.GOVERNANCE)
        self.assertEqual(event.action_type, "template.email.update")
        self.assertEqual(event.status, AuditEventStatus.DENIED)
        self.assertEqual(event.target_type, "invoices.EmailTemplate")
        self.assertEqual(event.target_id, "invoice_email")
        self.assertEqual(event.summary, "Denied email template mutation by non-admin.")

    def test_format_suffix_urls_are_served(self):
        """The router used to generate these routes but the action signatures
        rejected the ``format`` kwarg, so every one of them raised a 500."""
        auth(self.client, self.admin)

        self.assertEqual(self.client.get("/api/v1/invoices/invoices/pdf-template.json").status_code, 200)
        self.assertEqual(self.client.get("/api/v1/invoices/invoices/email-templates.json").status_code, 200)


class EmailTemplateAdminTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        auth(self.client, make_user("email_tpl_admin", UserRole.ADMIN))

    def test_list_reports_defaults_until_customised(self):
        resp = self.client.get("/api/v1/invoices/invoices/email-templates/")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual({row["template_key"] for row in resp.data}, set(EMAIL_TEMPLATE_DEFAULTS))
        self.assertTrue(all(row["is_customized"] is False for row in resp.data))

    def test_patch_then_delete_round_trips_to_the_default(self):
        url = "/api/v1/invoices/invoices/email-template/invoice_email/"
        default_subject = EMAIL_TEMPLATE_DEFAULTS["invoice_email"]["subject"]

        patch_resp = self.client.patch(url, {"subject": "Custom", "body": "Body"}, format="json")
        self.assertEqual(patch_resp.status_code, 200)
        self.assertTrue(patch_resp.data["is_customized"])
        self.assertEqual(EmailTemplate.objects.get(template_key="invoice_email").subject, "Custom")

        get_resp = self.client.get(url)
        self.assertEqual(get_resp.data["subject"], "Custom")
        self.assertTrue(get_resp.data["is_customized"])

        delete_resp = self.client.delete(url)
        self.assertEqual(delete_resp.status_code, 200)
        self.assertFalse(delete_resp.data["is_customized"])
        self.assertEqual(delete_resp.data["subject"], default_subject)
        self.assertFalse(EmailTemplate.objects.filter(template_key="invoice_email").exists())

    def test_unknown_template_key_is_404_on_every_method(self):
        url = "/api/v1/invoices/invoices/email-template/not_a_template/"

        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.patch(url, {"subject": "S", "body": "B"}, format="json").status_code, 404)
        self.assertEqual(self.client.delete(url).status_code, 404)

    def test_blank_subject_or_body_is_rejected(self):
        url = "/api/v1/invoices/invoices/email-template/invoice_email/"

        self.assertEqual(self.client.patch(url, {"subject": "  ", "body": "B"}, format="json").status_code, 400)
        self.assertEqual(self.client.patch(url, {"subject": "S", "body": "  "}, format="json").status_code, 400)
        self.assertFalse(EmailTemplate.objects.exists())


class PdfTemplatePreviewTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        auth(self.client, make_user("preview_admin", UserRole.ADMIN))

    def test_each_template_type_renders_its_own_sample_context(self):
        for template_type in ("invoice", "contract", "annual_statement"):
            with self.subTest(template_type=template_type):
                resp = self.client.post(
                    "/api/v1/invoices/invoices/preview-pdf-template/",
                    {"content": "<p>rendered</p>", "template_type": template_type},
                    format="json",
                )
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp.data["html"], "<p>rendered</p>")

    def test_unknown_template_type_is_rejected(self):
        """The preview reads template_type from the request body, so an unknown
        value must 400 rather than silently render the invoice sample context
        (the PATCH save path keeps the helper's fallback; its template_type
        arrives from fixed URL routes)."""
        resp = self.client.post(
            "/api/v1/invoices/invoices/preview-pdf-template/",
            {"content": "{{ invoice.invoice_number }}", "template_type": "nonsense"},
            format="json",
        )

        self.assertEqual(resp.status_code, 400)
        self.assertIn("Unsupported template type", resp.data["error"])

    def test_preview_ignores_external_resource_references(self):
        """Admin-supplied template content must not read local files or make
        network calls during PDF rendering; a rejected resource degrades like
        a missing one instead of failing the render."""
        content = (
            "<html><body>"
            '<img src="file:///etc/passwd">'
            '<img src="http://example.invalid/x.png">'
            "</body></html>"
        )
        resp = self.client.post(
            "/api/v1/invoices/invoices/preview-pdf-template/",
            {"content": content, "output": "pdf"},
            format="json",
        )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")
        self.assertTrue(resp.getvalue().startswith(b"%PDF-"))

    def test_accept_pdf_header_does_not_fail_content_negotiation(self):
        """Regression: the browser client requests previews with
        ``Accept: application/pdf``. The endpoint answers with opaque PDF
        bytes (or JSON errors) — never via a DRF renderer matching that
        media type — so negotiation must fall back instead of answering 406
        before the view body even runs."""
        url = "/api/v1/invoices/invoices/preview-pdf-template/"

        resp = self.client.post(
            url,
            {"content": "<p>rendered</p>", "output": "pdf"},
            format="json",
            HTTP_ACCEPT="application/pdf",
        )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")
        self.assertTrue(resp.getvalue().startswith(b"%PDF-"))

        resp = self.client.post(
            url,
            {"content": "   "},
            format="json",
            HTTP_ACCEPT="application/pdf",
        )

        self.assertEqual(resp.status_code, 400)

    def test_broken_template_returns_400_not_500(self):
        resp = self.client.post(
            "/api/v1/invoices/invoices/preview-pdf-template/",
            {"content": "{% not_a_tag %}"},
            format="json",
        )

        self.assertEqual(resp.status_code, 400)
        self.assertIn("Template rendering error", resp.data["error"])

    def test_blank_content_is_rejected(self):
        resp = self.client.post(
            "/api/v1/invoices/invoices/preview-pdf-template/", {"content": "   "}, format="json"
        )

        self.assertEqual(resp.status_code, 400)

    def test_preview_pdf_output_returns_pdf_bytes(self):
        content = "<html><body><h1>{{ invoice.invoice_number }}</h1></body></html>"
        url = "/api/v1/invoices/invoices/preview-pdf-template/"
        for post_kwargs in (
            {"data": {"content": content, "output": "pdf"}, "format": "json"},
            {"path": url + "?output=pdf", "data": {"content": content}, "format": "json"},
        ):
            with self.subTest(query="output=pdf" in post_kwargs.get("path", "")):
                resp = self.client.post(post_kwargs.get("path", url), **{k: v for k, v in post_kwargs.items() if k != "path"})

                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp["Content-Type"], "application/pdf")
                self.assertTrue(resp["Content-Disposition"].startswith("inline"))
                self.assertTrue(resp.getvalue().startswith(b"%PDF-"))

    def test_preview_pdf_rejects_broken_template_with_400(self):
        for payload in (
            {"content": "{% not_a_tag %}", "output": "pdf"},
            {"content": "{% not_a_tag %}", "output": "html"},
        ):
            with self.subTest(output=payload["output"]):
                resp = self.client.post(
                    "/api/v1/invoices/invoices/preview-pdf-template/", payload, format="json"
                )

                self.assertEqual(resp.status_code, 400)
                self.assertIn("Template rendering error", resp.data["error"])
                self.assertFalse(PdfTemplate.objects.exists())

    def test_preview_rejects_oversized_content(self):
        resp = self.client.post(
            "/api/v1/invoices/invoices/preview-pdf-template/",
            {"content": "x" * (MAX_TEMPLATE_CHARS + 1), "output": "pdf"},
            format="json",
        )

        self.assertEqual(resp.status_code, 400)
        self.assertIn("preview cap", resp.data["error"])

    def test_preview_rejects_unknown_output(self):
        resp = self.client.post(
            "/api/v1/invoices/invoices/preview-pdf-template/",
            {"content": "<p>x</p>", "output": "docx"},
            format="json",
        )

        self.assertEqual(resp.status_code, 400)

    def test_preview_denials_are_not_audit_logged(self):
        """Preview is stateless — unlike the mutation views it has no denial_audit
        override, so a non-admin 403 must not write a GOVERNANCE event."""
        client = APIClient()
        auth(client, make_user("preview_participant", UserRole.PARTICIPANT))
        before = AuditEvent.objects.filter(status=AuditEventStatus.DENIED).count()

        resp = client.post(
            "/api/v1/invoices/invoices/preview-pdf-template/",
            {"content": "<p>x</p>", "output": "pdf"},
            format="json",
        )

        self.assertEqual(resp.status_code, 403)
        self.assertEqual(AuditEvent.objects.filter(status=AuditEventStatus.DENIED).count(), before)


class PdfTemplateAdminTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        auth(self.client, make_user("pdf_tpl_admin", UserRole.ADMIN))

    def test_blank_content_is_rejected_and_nothing_is_stored(self):
        resp = self.client.patch(
            "/api/v1/invoices/invoices/pdf-template/", {"content": "   "}, format="json"
        )

        self.assertEqual(resp.status_code, 400)
        self.assertFalse(PdfTemplate.objects.exists())

    def test_annual_statement_template_round_trips(self):
        """The third PDF template endpoint had no coverage before the split."""
        url = "/api/v1/invoices/invoices/annual-statement-pdf-template/"
        template_name = "invoices/annual_statement_pdf.html"

        get_resp = self.client.get(url)
        self.assertEqual(get_resp.status_code, 200)
        self.assertFalse(get_resp.data["is_customized"])
        default_content = get_resp.data["content"]

        patch_resp = self.client.patch(url, {"content": "<p>custom</p>"}, format="json")
        self.assertEqual(patch_resp.status_code, 200)
        self.assertEqual(PdfTemplate.objects.get(template_name=template_name).content, "<p>custom</p>")

        delete_resp = self.client.delete(url)
        self.assertEqual(delete_resp.status_code, 200)
        self.assertEqual(delete_resp.data["content"], default_content)
        self.assertFalse(PdfTemplate.objects.filter(template_name=template_name).exists())

    def test_update_and_reset_are_audited(self):
        url = "/api/v1/invoices/invoices/pdf-template/"

        self.client.patch(url, {"content": "<p>custom</p>"}, format="json")
        update_event = AuditEvent.objects.get(action_type="template.invoice_pdf.update")
        self.assertEqual(update_event.action_category, AuditActionCategory.GOVERNANCE)
        self.assertEqual(update_event.status, AuditEventStatus.SUCCESS)
        self.assertEqual(update_event.summary, "Updated PDF template invoices/invoice_pdf.html.")

        self.client.delete(url)
        reset_event = AuditEvent.objects.get(action_type="template.invoice_pdf.reset")
        self.assertEqual(reset_event.summary, "Reset PDF template invoices/invoice_pdf.html to default.")


class PdfTemplateOverrideIntegrityTests(TestCase):
    """The whole-document override path is validated at the door and
    provenance-aware: broken templates are rejected on save (never stored to
    fail at document-render time), staleness against a changed on-disk default
    is surfaced on read, and the shared-base include keeps working through the
    DB override render path."""

    def setUp(self):
        self.client = APIClient()
        auth(self.client, make_user("override_admin", UserRole.ADMIN))
        self.owner = make_user("override_owner", UserRole.ZEV_OWNER)

    def test_broken_override_is_rejected_and_nothing_is_stored(self):
        url = "/api/v1/invoices/invoices/contract-pdf-template/"

        resp = self.client.patch(url, {"content": "{% not_a_tag %}"}, format="json")

        self.assertEqual(resp.status_code, 400)
        self.assertIn("Template rendering error", resp.data["error"])
        self.assertFalse(PdfTemplate.objects.exists())

    def test_oversized_override_is_rejected_and_nothing_is_stored(self):
        """The save path enforces the same content cap as the preview, because
        a stored override renders through the same WeasyPrint pipeline."""
        url = "/api/v1/invoices/invoices/contract-pdf-template/"

        resp = self.client.patch(
            url, {"content": "x" * (MAX_TEMPLATE_CHARS + 1)}, format="json"
        )

        self.assertEqual(resp.status_code, 400)
        self.assertIn("cap", resp.data["error"])
        self.assertFalse(PdfTemplate.objects.exists())

    def test_valid_override_is_stored_with_default_digest_and_not_stale(self):
        url = "/api/v1/invoices/invoices/contract-pdf-template/"

        resp = self.client.patch(url, {"content": "<p>custom</p>"}, format="json")

        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.data["is_stale"])
        record = PdfTemplate.objects.get(template_name="contracts/participant_contract_pdf.html")
        self.assertEqual(record.content, "<p>custom</p>")
        self.assertTrue(record.default_digest)

    def test_get_flags_override_saved_against_an_older_default_as_stale(self):
        url = "/api/v1/invoices/invoices/pdf-template/"
        PdfTemplate.objects.create(
            template_name="invoices/invoice_pdf.html",
            content="<p>old override</p>",
            default_digest="0" * 64,  # a digest that can never match a real file
        )

        resp = self.client.get(url)

        self.assertTrue(resp.data["is_customized"])
        self.assertTrue(resp.data["is_stale"])

    def test_override_without_digest_provenance_is_never_stale(self):
        """A legacy override with a blank digest (migration 0009 backfills
        those, but a row may still lack provenance) must not alarm."""
        url = "/api/v1/invoices/invoices/pdf-template/"
        PdfTemplate.objects.create(
            template_name="invoices/invoice_pdf.html",
            content="<p>legacy override</p>",
        )

        resp = self.client.get(url)

        self.assertTrue(resp.data["is_customized"])
        self.assertFalse(resp.data["is_stale"])

    def test_patch_rejects_unknown_template_variables(self):
        """Django renders unknown variables as an empty string by default, so a
        typo like ``{{ participant.emali }}`` would silently produce a broken
        PDF. Save-time validation must reject it."""
        url = "/api/v1/invoices/invoices/contract-pdf-template/"
        resp = self.client.patch(
            url,
            {"content": "<p>Contact: {{ participant.emali }}</p>"},
            format="json",
        )

        self.assertEqual(resp.status_code, 400)
        self.assertIn("participant.emali", resp.data["error"])
        self.assertFalse(PdfTemplate.objects.exists())

    def test_default_template_is_never_stale(self):
        resp = self.client.get("/api/v1/invoices/invoices/pdf-template/")

        self.assertFalse(resp.data["is_customized"])
        self.assertFalse(resp.data["is_stale"])

    def _contract_participant(self):
        zev = make_zev(self.owner, "Override ZEV")
        return make_participant(zev, first="Override", last="Participant")

    @pytest.mark.slow
    def test_override_with_shared_base_include_renders_through_the_real_path(self):
        """The current default already includes the shared design base; stored
        as an override it must keep resolving it via the engine loaders, so the
        two sources of design truth stay aligned."""
        url = "/api/v1/invoices/invoices/contract-pdf-template/"
        default_content = self.client.get(url).data["content"]

        resp = self.client.patch(url, {"content": default_content}, format="json")
        self.assertEqual(resp.status_code, 200)

        participant = self._contract_participant()
        pdf = generate_contract_pdf(participant)
        self.assertTrue(pdf.startswith(b"%PDF"))

        from django.template.loader import render_to_string
        from invoices.contract_pdf import CONTRACT_TEMPLATE_NAME, _build_contract_context
        html = render_to_string(CONTRACT_TEMPLATE_NAME, _build_contract_context(participant))
        self.assertIn("running(footer-meta)", html)  # shared-base CSS survived
        self.assertIn("document-header", html)

    @pytest.mark.slow
    def test_legacy_override_without_include_still_renders(self):
        """Overrides saved before the redesign carry their own full markup and
        no shared-base include; they must still render without error."""
        url = "/api/v1/invoices/invoices/contract-pdf-template/"
        legacy = (
            "<!DOCTYPE html><html><body><h1>Legacy contract</h1>"
            "<p>{{ participant.full_name }}</p></body></html>"
        )

        resp = self.client.patch(url, {"content": legacy}, format="json")
        self.assertEqual(resp.status_code, 200)

        pdf = generate_contract_pdf(self._contract_participant())
        self.assertTrue(pdf.startswith(b"%PDF"))


class PdfRenderFetchPolicyTests(TestCase):
    """render_pdf's fetch policy: embedded data: URIs only.

    Every shipped template is fully inline, so no legitimate render needs
    another protocol; the allowlist is the boundary that keeps admin-editable
    template content from reading local files or reaching the network.
    """

    def test_rejects_file_http_and_ftp_urls(self):
        fetcher = URLFetcher(allowed_protocols=ALLOWED_URL_PROTOCOLS)
        for url in (
            "file:///etc/passwd",
            "http://example.com/x.png",
            "https://example.com/a.css",
            "ftp://example.com/f",
        ):
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    fetcher(url)

    def test_allows_data_uris(self):
        fetcher = URLFetcher(allowed_protocols=ALLOWED_URL_PROTOCOLS)

        response = fetcher("data:text/plain,hello")

        # urllib assigns no HTTP status to data: responses; the body is the proof.
        self.assertEqual(response.read(), b"hello")

class InvoicePdfDownloadTests(TestCase):
    def setUp(self):
        from invoices.test_helpers import make_invoice

        self.client = APIClient()
        self.owner = make_user("pdfdl_owner", UserRole.ZEV_OWNER)
        self.participant_user = make_user("pdfdl_participant", UserRole.PARTICIPANT)
        self.stranger = make_user("pdfdl_stranger", UserRole.ZEV_OWNER)
        self.zev = make_zev(self.owner, "PDF DL ZEV")
        self.participant = make_participant(self.zev, user=self.participant_user,
                                            first="Pdf", last="Downloader")
        self.invoice = make_invoice(self.zev, self.participant)

    def _attach_pdf(self, invoice):
        from django.core.files.base import ContentFile
        invoice.pdf_file.save("test.pdf", ContentFile(b"%PDF-1.4 fake"), save=True)

    def _url(self, invoice):
        return f"/api/v1/invoices/invoices/{invoice.pk}/pdf/"

    def test_pdf_returns_200_pdf_for_owner(self):
        self._attach_pdf(self.invoice)
        auth(self.client, self.owner)
        resp = self.client.get(self._url(self.invoice))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")
        self.assertTrue(b"".join(resp.streaming_content).startswith(b"%PDF"))

    def test_pdf_returns_200_for_own_participant(self):
        self._attach_pdf(self.invoice)
        auth(self.client, self.participant_user)
        resp = self.client.get(self._url(self.invoice))
        self.assertEqual(resp.status_code, 200)

    def test_pdf_returns_404_when_no_pdf_file(self):
        auth(self.client, self.owner)
        resp = self.client.get(self._url(self.invoice))
        self.assertEqual(resp.status_code, 404)

    def test_pdf_returns_404_for_out_of_scope(self):
        self._attach_pdf(self.invoice)
        auth(self.client, self.stranger)
        resp = self.client.get(self._url(self.invoice))
        self.assertEqual(resp.status_code, 404)

    def test_pdf_returns_401_for_anonymous(self):
        self._attach_pdf(self.invoice)
        resp = self.client.get(self._url(self.invoice))
        self.assertEqual(resp.status_code, 401)
