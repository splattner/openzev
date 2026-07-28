"""
RBAC and billing integration tests for the invoice endpoints.

Tests that:
- Admin can access and action all invoices.
- ZEV owner can only access invoices for their own ZEVs.
- Participant can only read their own invoices and cannot perform actions.
- Billing generation creates draft invoices with expected local/grid totals.
"""
from datetime import date, datetime, timezone
from decimal import Decimal

from django.conf import settings
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import UserRole
from invoices.models import Invoice, InvoiceStatus, PdfTemplate
from invoices.test_helpers import make_invoice, make_participant, make_user, make_zev
from metering.models import MeterReading, ReadingDirection, ReadingResolution
from tariffs.models import BillingMode, EnergyType, Tariff, TariffCategory, TariffPeriod
from testing.helpers import authenticate as auth
from zev.models import MeteringPoint, MeteringPointAssignment, MeteringPointType


# ---------------------------------------------------------------------------
# RBAC: list/read access
# ---------------------------------------------------------------------------

class InvoiceRBACTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = make_user("rbac_admin", UserRole.ADMIN)
        self.owner1 = make_user("rbac_owner1", UserRole.ZEV_OWNER)
        self.owner2 = make_user("rbac_owner2", UserRole.ZEV_OWNER)
        self.puser = make_user("rbac_participant", UserRole.PARTICIPANT)

        self.zev1 = make_zev(self.owner1, "ZEV-1")
        self.zev2 = make_zev(self.owner2, "ZEV-2")

        self.p1 = make_participant(self.zev1, user=self.puser, first="Alice")
        self.p2 = make_participant(self.zev2, first="Bob")

        self.inv1 = make_invoice(self.zev1, self.p1)
        self.inv2 = make_invoice(self.zev2, self.p2)

    def _list(self):
        resp = self.client.get("/api/v1/invoices/invoices/")
        return resp.status_code, {str(inv["id"]) for inv in resp.data.get("results", [])}

    def test_admin_sees_all_invoices(self):
        auth(self.client, self.admin)
        status_code, ids = self._list()
        self.assertEqual(status_code, 200)
        self.assertIn(str(self.inv1.pk), ids)
        self.assertIn(str(self.inv2.pk), ids)

    def test_owner1_sees_only_own_zev_invoices(self):
        auth(self.client, self.owner1)
        status_code, ids = self._list()
        self.assertEqual(status_code, 200)
        self.assertIn(str(self.inv1.pk), ids)
        self.assertNotIn(str(self.inv2.pk), ids)

    def test_participant_sees_only_own_invoices(self):
        auth(self.client, self.puser)
        status_code, ids = self._list()
        self.assertEqual(status_code, 200)
        self.assertIn(str(self.inv1.pk), ids)
        self.assertNotIn(str(self.inv2.pk), ids)

    def test_participant_cannot_approve(self):
        auth(self.client, self.puser)
        resp = self.client.post(f"/api/v1/invoices/invoices/{self.inv1.pk}/approve/")
        self.assertEqual(resp.status_code, 403)

    def test_participant_cannot_cancel(self):
        auth(self.client, self.puser)
        resp = self.client.post(f"/api/v1/invoices/invoices/{self.inv1.pk}/cancel/")
        self.assertEqual(resp.status_code, 403)

    def test_unauthenticated_is_rejected(self):
        self.client.credentials()
        resp = self.client.get("/api/v1/invoices/invoices/")
        self.assertEqual(resp.status_code, 401)

    def test_admin_can_read_pdf_template(self):
        auth(self.client, self.admin)
        resp = self.client.get("/api/v1/invoices/invoices/pdf-template/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("content", resp.data)

    def test_owner_cannot_read_pdf_template(self):
        auth(self.client, self.owner1)
        resp = self.client.get("/api/v1/invoices/invoices/pdf-template/")
        self.assertEqual(resp.status_code, 403)

    def test_owner_can_download_financial_summary_pdf(self):
        # Owner needs a participant record to download their own summary
        owner_participant = make_participant(self.zev1, user=self.owner1, first="Owner", last="One")
        make_invoice(self.zev1, owner_participant, InvoiceStatus.PAID)
        auth(self.client, self.owner1)

        resp = self.client.get(
            "/api/v1/invoices/invoices/financial-summary/",
            {"zev_id": str(self.zev1.pk), "year": 2026},
        )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")
        self.assertIn("financial-summary-2026", resp["Content-Disposition"])

    def test_owner_financial_summary_requires_year_and_zev_id(self):
        auth(self.client, self.owner1)

        resp = self.client.get("/api/v1/invoices/invoices/financial-summary/")

        self.assertEqual(resp.status_code, 400)

    def test_participant_can_download_own_financial_summary_pdf(self):
        make_invoice(self.zev1, self.p1, InvoiceStatus.PAID)
        auth(self.client, self.puser)

        resp = self.client.get(
            "/api/v1/invoices/invoices/financial-summary/",
            {"year": 2026},
        )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")
        self.assertIn("financial-summary-2026", resp["Content-Disposition"])

    def test_owner_can_download_financial_summary_for_participant(self):
        make_invoice(self.zev1, self.p1, InvoiceStatus.PAID)
        auth(self.client, self.owner1)

        resp = self.client.get(
            "/api/v1/invoices/invoices/financial-summary/",
            {"zev_id": str(self.zev1.pk), "year": 2026, "participant_id": str(self.p1.pk)},
        )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")

    def test_admin_can_update_pdf_template(self):
        auth(self.client, self.admin)
        template_path = settings.BASE_DIR / "templates" / "invoices" / "invoice_pdf.html"
        original = template_path.read_text(encoding="utf-8")
        updated = original + "\n<!-- test marker -->\n"
        resp = self.client.patch(
            "/api/v1/invoices/invoices/pdf-template/",
            {"content": updated},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("detail", resp.data)
        self.assertTrue(resp.data["is_customized"])

        record = PdfTemplate.objects.get(template_name="invoices/invoice_pdf.html")
        self.assertEqual(record.content, updated)
        # On-disk file remains the immutable default.
        self.assertEqual(template_path.read_text(encoding="utf-8"), original)

    def test_admin_can_reset_pdf_template_to_default(self):
        auth(self.client, self.admin)
        template_name = "invoices/invoice_pdf.html"
        default_content = (settings.BASE_DIR / "templates" / template_name).read_text(encoding="utf-8")
        PdfTemplate.objects.create(template_name=template_name, content="<html>custom</html>")

        resp = self.client.delete("/api/v1/invoices/invoices/pdf-template/")

        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.data["is_customized"])
        self.assertEqual(resp.data["content"], default_content)
        self.assertFalse(PdfTemplate.objects.filter(template_name=template_name).exists())

    def test_admin_can_read_and_update_contract_pdf_template(self):
        auth(self.client, self.admin)
        get_resp = self.client.get("/api/v1/invoices/invoices/contract-pdf-template/")
        self.assertEqual(get_resp.status_code, 200)
        self.assertIn("content", get_resp.data)
        self.assertFalse(get_resp.data["is_customized"])

        updated = get_resp.data["content"] + "\n<!-- contract marker -->\n"
        patch_resp = self.client.patch(
            "/api/v1/invoices/invoices/contract-pdf-template/",
            {"content": updated},
            format="json",
        )
        self.assertEqual(patch_resp.status_code, 200)
        self.assertTrue(patch_resp.data["is_customized"])
        record = PdfTemplate.objects.get(template_name="contracts/participant_contract_pdf.html")
        self.assertEqual(record.content, updated)

    def test_owner_cannot_read_contract_pdf_template(self):
        auth(self.client, self.owner1)
        resp = self.client.get("/api/v1/invoices/invoices/contract-pdf-template/")
        self.assertEqual(resp.status_code, 403)

    def test_generic_update_is_not_allowed(self):
        # Invoices must only be mutated through the dedicated, audited
        # workflow actions (generate/approve/mark-sent/mark-paid/cancel) —
        # not the generic PUT/PATCH endpoint, which would bypass those
        # permission checks and leave no audit trail.
        inv = make_invoice(self.zev1, self.p1, InvoiceStatus.DRAFT)
        auth(self.client, self.admin)

        put_resp = self.client.put(
            f"/api/v1/invoices/invoices/{inv.pk}/",
            {"status": InvoiceStatus.PAID},
            format="json",
        )
        self.assertEqual(put_resp.status_code, 405)

        patch_resp = self.client.patch(
            f"/api/v1/invoices/invoices/{inv.pk}/",
            {"status": InvoiceStatus.PAID},
            format="json",
        )
        self.assertEqual(patch_resp.status_code, 405)

        inv.refresh_from_db()
        self.assertEqual(inv.status, InvoiceStatus.DRAFT)

    def test_admin_can_delete_paid_invoice(self):
        inv = make_invoice(self.zev1, self.p1, InvoiceStatus.PAID)
        auth(self.client, self.admin)

        resp = self.client.delete(f"/api/v1/invoices/invoices/{inv.pk}/")

        self.assertEqual(resp.status_code, 204)
        self.assertFalse(Invoice.objects.filter(pk=inv.pk).exists())

    def test_admin_can_delete_sent_invoice(self):
        inv = make_invoice(self.zev1, self.p1, InvoiceStatus.SENT)
        auth(self.client, self.admin)

        resp = self.client.delete(f"/api/v1/invoices/invoices/{inv.pk}/")

        self.assertEqual(resp.status_code, 204)
        self.assertFalse(Invoice.objects.filter(pk=inv.pk).exists())

    def test_owner_cannot_delete_paid_invoice(self):
        inv = make_invoice(self.zev1, self.p1, InvoiceStatus.PAID)
        auth(self.client, self.owner1)

        resp = self.client.delete(f"/api/v1/invoices/invoices/{inv.pk}/")

        self.assertEqual(resp.status_code, 400)
        self.assertTrue(Invoice.objects.filter(pk=inv.pk).exists())

    def test_generic_create_returns_405(self):
        """The generic POST create endpoint is removed; only generate() creates invoices."""
        auth(self.client, self.admin)
        resp = self.client.post(
            "/api/v1/invoices/invoices/",
            {"zev": str(self.zev1.pk), "participant": str(self.p1.pk)},
        )
        self.assertEqual(resp.status_code, 405)

    def test_participant_cannot_create_invoice_via_generic_endpoint(self):
        """Participants get 405 (endpoint doesn't exist) rather than a 403."""
        auth(self.client, self.puser)
        resp = self.client.post(
            "/api/v1/invoices/invoices/",
            {"zev": str(self.zev1.pk), "participant": str(self.p1.pk)},
        )
        self.assertEqual(resp.status_code, 405)

    def test_serializer_ignores_forged_billing_fields(self):
        """Defense-in-depth: billing/workflow fields are read-only on the serializer."""
        from invoices.serializers import InvoiceSerializer

        s = InvoiceSerializer(
            data={
                "zev": str(self.zev1.pk),
                "participant": str(self.p1.pk),
                "status": InvoiceStatus.PAID,
                "total_chf": "9999.99",
                "subtotal_chf": "9999.99",
                "vat_chf": "0.00",
                "period_start": "2026-01-01",
                "period_end": "2026-01-31",
                "notes": "legit note",
            }
        )
        self.assertTrue(s.is_valid(), s.errors)
        for field in (
            "zev",
            "participant",
            "status",
            "total_chf",
            "subtotal_chf",
            "vat_chf",
            "period_start",
            "period_end",
        ):
            self.assertNotIn(field, s.validated_data)
        self.assertEqual(s.validated_data.get("notes"), "legit note")

class InvoiceBillingIntegrationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = make_user("billing_owner", UserRole.ZEV_OWNER)
        self.zev = make_zev(self.owner, "Billing ZEV")
        self.participant = make_participant(self.zev, first="Bill", last="Ing")

        self.consumption_mp = MeteringPoint.objects.create(
            zev=self.zev,
            meter_id="CH-BILL-CONS-1",
            meter_type=MeteringPointType.CONSUMPTION,
        )
        self.production_mp = MeteringPoint.objects.create(
            zev=self.zev,
            meter_id="CH-BILL-PROD-1",
            meter_type=MeteringPointType.PRODUCTION,
        )
        MeteringPointAssignment.objects.create(
            metering_point=self.consumption_mp,
            participant=self.participant,
            valid_from=date(2026, 1, 1),
        )
        MeteringPointAssignment.objects.create(
            metering_point=self.production_mp,
            participant=self.participant,
            valid_from=date(2026, 1, 1),
        )

        local_tariff = Tariff.objects.create(
            zev=self.zev,
            name="Local Energy",
            category=TariffCategory.ENERGY,
            billing_mode=BillingMode.ENERGY,
            energy_type=EnergyType.LOCAL,
            valid_from=date(2026, 1, 1),
        )
        TariffPeriod.objects.create(
            tariff=local_tariff,
            period_type="flat",
            price_chf_per_kwh=Decimal("0.10000"),
        )

        grid_tariff = Tariff.objects.create(
            zev=self.zev,
            name="Grid Energy",
            category=TariffCategory.ENERGY,
            billing_mode=BillingMode.ENERGY,
            energy_type=EnergyType.GRID,
            valid_from=date(2026, 1, 1),
        )
        TariffPeriod.objects.create(
            tariff=grid_tariff,
            period_type="flat",
            price_chf_per_kwh=Decimal("0.30000"),
        )

        ts = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        MeterReading.objects.create(
            metering_point=self.consumption_mp,
            timestamp=ts,
            energy_kwh=Decimal("10.0000"),
            direction=ReadingDirection.IN,
            resolution=ReadingResolution.FIFTEEN_MIN,
        )
        MeterReading.objects.create(
            metering_point=self.production_mp,
            timestamp=ts,
            energy_kwh=Decimal("6.0000"),
            direction=ReadingDirection.OUT,
            resolution=ReadingResolution.FIFTEEN_MIN,
        )

        auth(self.client, self.owner)

    def test_end_to_end_billing_generation_workflow_and_dashboard_consistency(self):
        generate_resp = self.client.post(
            "/api/v1/invoices/invoices/generate/",
            {
                "participant_id": str(self.participant.id),
                "period_start": "2026-01-01",
                "period_end": "2026-01-31",
            },
        )
        self.assertEqual(generate_resp.status_code, 201)

        invoice_id = generate_resp.data["id"]
        invoice = Invoice.objects.get(pk=invoice_id)

        self.assertEqual(invoice.status, InvoiceStatus.DRAFT)
        self.assertEqual(invoice.total_local_kwh, Decimal("6.0000"))
        self.assertEqual(invoice.total_grid_kwh, Decimal("4.0000"))





