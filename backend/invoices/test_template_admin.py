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

from accounts.models import UserRole
from audit.models import AuditActionCategory, AuditEvent, AuditEventStatus
from testing.helpers import authenticate as auth, make_user

from .models import EMAIL_TEMPLATE_DEFAULTS, EmailTemplate, PdfTemplate

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

    def test_unknown_template_type_falls_back_to_the_invoice_context(self):
        resp = self.client.post(
            "/api/v1/invoices/invoices/preview-pdf-template/",
            {"content": "{{ invoice.invoice_number }}", "template_type": "nonsense"},
            format="json",
        )

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data["html"].strip())

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
