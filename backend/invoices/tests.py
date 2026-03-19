"""
RBAC and workflow tests for the invoice endpoints.

Tests that:
- Admin can access and action all invoices.
- ZEV owner can only access invoices for their own ZEVs.
- Participant can only read their own invoices and cannot perform actions.
- Invoice workflow transitions (approve → mark-sent → mark-paid and cancel) are guarded correctly.
- Regenerating a locked invoice raises a 409.
"""
from datetime import datetime, timezone
from datetime import date
from decimal import Decimal

from pathlib import Path

from django.conf import settings
from django.core import mail
from django.core.files.base import ContentFile
from django.test import TestCase
from django.test.utils import override_settings
from rest_framework.test import APIClient

from accounts.models import AppSettings, User, UserRole
from invoices.models import Invoice, InvoiceItem, InvoiceStatus
from invoices.engine import generate_invoice
from invoices.tasks import send_invoice_email_task
from invoices.serializers import InvoiceSerializer
from metering.models import MeterReading, ReadingDirection, ReadingResolution
from tariffs.models import BillingMode, EnergyType, Tariff, TariffCategory, TariffPeriod
from zev.models import MeteringPoint, MeteringPointType, Participant, Zev


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_user(username, role, password="pass1234"):
    return User.objects.create_user(username=username, password=password, role=role)


def make_zev(owner, name="Test ZEV"):
    return Zev.objects.create(name=name, owner=owner, zev_type="vzev", invoice_prefix="T")


def make_participant(zev, user=None, first="Jane", last="Doe"):
    return Participant.objects.create(
        zev=zev,
        user=user,
        first_name=first,
        last_name=last,
        email=f"{first.lower()}@example.com",
        valid_from=date(2026, 1, 1),
    )


_counter = 0


def make_invoice(zev, participant, inv_status=InvoiceStatus.DRAFT):
    global _counter
    _counter += 1
    return Invoice.objects.create(
        invoice_number=f"T-{_counter:05d}",
        zev=zev,
        participant=participant,
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        status=inv_status,
        total_chf=Decimal("42.00"),
    )


def auth(client, user, password="pass1234"):
    resp = client.post("/api/v1/auth/token/", {"username": user.username, "password": password})
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")


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

    def test_admin_can_update_pdf_template(self):
        auth(self.client, self.admin)
        template_path = settings.BASE_DIR / "templates" / "invoices" / "invoice_pdf.html"
        original = template_path.read_text(encoding="utf-8")
        updated = original + "\n<!-- test marker -->\n"
        try:
            resp = self.client.patch(
                "/api/v1/invoices/invoices/pdf-template/",
                {"content": updated},
                format="json",
            )
            self.assertEqual(resp.status_code, 200)
            self.assertIn("detail", resp.data)
            self.assertEqual(template_path.read_text(encoding="utf-8"), updated)
        finally:
            template_path.write_text(original, encoding="utf-8")

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


# ---------------------------------------------------------------------------
# Workflow: status transitions
# ---------------------------------------------------------------------------

class InvoiceWorkflowTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = make_user("wf_owner", UserRole.ZEV_OWNER)
        self.zev = make_zev(self.owner, "WF ZEV")
        self.participant = make_participant(self.zev)
        auth(self.client, self.owner)

    def _action(self, invoice, action_url):
        return self.client.post(f"/api/v1/invoices/invoices/{invoice.pk}/{action_url}/")

    def test_approve_draft(self):
        inv = make_invoice(self.zev, self.participant, InvoiceStatus.DRAFT)
        resp = self._action(inv, "approve")
        self.assertEqual(resp.status_code, 200)
        inv.refresh_from_db()
        self.assertEqual(inv.status, InvoiceStatus.APPROVED)

    def test_approve_already_approved_fails(self):
        inv = make_invoice(self.zev, self.participant, InvoiceStatus.APPROVED)
        resp = self._action(inv, "approve")
        self.assertEqual(resp.status_code, 400)

    def test_mark_sent_from_approved(self):
        inv = make_invoice(self.zev, self.participant, InvoiceStatus.APPROVED)
        resp = self._action(inv, "mark-sent")
        self.assertEqual(resp.status_code, 200)
        inv.refresh_from_db()
        self.assertEqual(inv.status, InvoiceStatus.SENT)
        self.assertIsNotNone(inv.sent_at)

    def test_mark_sent_from_draft_fails(self):
        inv = make_invoice(self.zev, self.participant, InvoiceStatus.DRAFT)
        resp = self._action(inv, "mark-sent")
        self.assertEqual(resp.status_code, 400)

    def test_mark_paid_from_sent(self):
        inv = make_invoice(self.zev, self.participant, InvoiceStatus.SENT)
        resp = self._action(inv, "mark-paid")
        self.assertEqual(resp.status_code, 200)
        inv.refresh_from_db()
        self.assertEqual(inv.status, InvoiceStatus.PAID)

    def test_mark_paid_from_draft_fails(self):
        inv = make_invoice(self.zev, self.participant, InvoiceStatus.DRAFT)
        resp = self._action(inv, "mark-paid")
        self.assertEqual(resp.status_code, 400)

    def test_cancel_draft(self):
        inv = make_invoice(self.zev, self.participant, InvoiceStatus.DRAFT)
        resp = self._action(inv, "cancel")
        self.assertEqual(resp.status_code, 200)
        inv.refresh_from_db()
        self.assertEqual(inv.status, InvoiceStatus.CANCELLED)

    def test_cancel_approved(self):
        inv = make_invoice(self.zev, self.participant, InvoiceStatus.APPROVED)
        resp = self._action(inv, "cancel")
        self.assertEqual(resp.status_code, 200)
        inv.refresh_from_db()
        self.assertEqual(inv.status, InvoiceStatus.CANCELLED)

    def test_cancel_sent(self):
        inv = make_invoice(self.zev, self.participant, InvoiceStatus.SENT)
        resp = self._action(inv, "cancel")
        self.assertEqual(resp.status_code, 200)
        inv.refresh_from_db()
        self.assertEqual(inv.status, InvoiceStatus.CANCELLED)

    def test_cancel_paid_fails(self):
        inv = make_invoice(self.zev, self.participant, InvoiceStatus.PAID)
        resp = self._action(inv, "cancel")
        self.assertEqual(resp.status_code, 400)

    def test_cancel_already_cancelled_fails(self):
        inv = make_invoice(self.zev, self.participant, InvoiceStatus.CANCELLED)
        resp = self._action(inv, "cancel")
        self.assertEqual(resp.status_code, 400)


# ---------------------------------------------------------------------------
# Engine guard: regenerating locked invoices
# ---------------------------------------------------------------------------

class InvoiceEngineGuardTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = make_user("guard_owner", UserRole.ZEV_OWNER)
        self.zev = make_zev(self.owner, "GuardZEV")
        self.participant = make_participant(self.zev)
        auth(self.client, self.owner)

    def _generate(self, participant_id):
        return self.client.post("/api/v1/invoices/invoices/generate/", {
            "participant_id": str(participant_id),
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
        })

    def test_regenerate_approved_invoice_returns_409(self):
        make_invoice(self.zev, self.participant, InvoiceStatus.APPROVED)
        resp = self._generate(self.participant.pk)
        self.assertEqual(resp.status_code, 409)

    def test_regenerate_paid_invoice_returns_409(self):
        make_invoice(self.zev, self.participant, InvoiceStatus.PAID)
        resp = self._generate(self.participant.pk)
        self.assertEqual(resp.status_code, 409)

    def test_regenerate_draft_invoice_succeeds(self):
        make_invoice(self.zev, self.participant, InvoiceStatus.DRAFT)
        resp = self._generate(self.participant.pk)
        # Engine replaces draft; no 409 expected (may be 201 or other non-conflict)
        self.assertNotEqual(resp.status_code, 409)

    def test_regenerate_cancelled_invoice_succeeds(self):
        make_invoice(self.zev, self.participant, InvoiceStatus.CANCELLED)
        resp = self._generate(self.participant.pk)
        self.assertNotEqual(resp.status_code, 409)


class InvoiceBillingIntegrationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = make_user("billing_owner", UserRole.ZEV_OWNER)
        self.zev = make_zev(self.owner, "Billing ZEV")
        self.participant = make_participant(self.zev, first="Bill", last="Ing")

        self.consumption_mp = MeteringPoint.objects.create(
            zev=self.zev,
            participant=self.participant,
            meter_id="CH-BILL-CONS-1",
            meter_type=MeteringPointType.CONSUMPTION,
            valid_from=date(2026, 1, 1),
        )
        self.production_mp = MeteringPoint.objects.create(
            zev=self.zev,
            participant=self.participant,
            meter_id="CH-BILL-PROD-1",
            meter_type=MeteringPointType.PRODUCTION,
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


class InvoicePeriodOverviewTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = make_user("overview_owner", UserRole.ZEV_OWNER)
        self.other_owner = make_user("overview_other_owner", UserRole.ZEV_OWNER)
        self.zev = make_zev(self.owner, "Overview ZEV")

        self.p_with_data = make_participant(self.zev, first="With", last="Data")
        self.p_missing_data = make_participant(self.zev, first="Missing", last="Data")

        self.mp_with_data = MeteringPoint.objects.create(
            zev=self.zev,
            participant=self.p_with_data,
            meter_id="CH-OVERVIEW-1",
            meter_type=MeteringPointType.CONSUMPTION,
            valid_from=date(2026, 1, 1),
        )
        self.mp_missing_data = MeteringPoint.objects.create(
            zev=self.zev,
            participant=self.p_missing_data,
            meter_id="CH-OVERVIEW-2",
            meter_type=MeteringPointType.CONSUMPTION,
            valid_from=date(2026, 1, 1),
        )

        for day in range(1, 32):
            MeterReading.objects.create(
                metering_point=self.mp_with_data,
                timestamp=datetime(2026, 1, day, 0, 0, tzinfo=timezone.utc),
                energy_kwh=Decimal("3.0000"),
                direction=ReadingDirection.IN,
                resolution=ReadingResolution.FIFTEEN_MIN,
            )

        self.invoice = make_invoice(self.zev, self.p_with_data, InvoiceStatus.DRAFT)

    def test_owner_gets_participant_rows_with_invoice_and_metering_readiness(self):
        auth(self.client, self.owner)

        resp = self.client.get(
            "/api/v1/invoices/invoices/period-overview/",
            {
                "zev_id": str(self.zev.id),
                "period_start": "2026-01-01",
                "period_end": "2026-01-31",
            },
        )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["billing_interval"], self.zev.billing_interval)
        self.assertEqual(len(resp.data["rows"]), 2)

        rows_by_participant = {row["participant_name"]: row for row in resp.data["rows"]}

        with_data_row = rows_by_participant[self.p_with_data.full_name]
        self.assertTrue(with_data_row["metering_data_complete"])
        self.assertIsNotNone(with_data_row["invoice"])
        self.assertEqual(with_data_row["invoice"]["id"], str(self.invoice.id))

        missing_data_row = rows_by_participant[self.p_missing_data.full_name]
        self.assertFalse(missing_data_row["metering_data_complete"])
        self.assertEqual(missing_data_row["missing_meter_ids"], ["CH-OVERVIEW-2"])
        self.assertEqual(missing_data_row["missing_meter_details"], [{"meter_id": "CH-OVERVIEW-2", "missing_days": 31}])
        self.assertIsNone(missing_data_row["invoice"])

    def test_owner_cannot_view_other_owners_zev_overview(self):
        auth(self.client, self.other_owner)

        resp = self.client.get(
            "/api/v1/invoices/invoices/period-overview/",
            {
                "zev_id": str(self.zev.id),
                "period_start": "2026-01-01",
                "period_end": "2026-01-31",
            },
        )

        self.assertEqual(resp.status_code, 403)

    def test_partial_daily_coverage_marks_metering_incomplete(self):
        MeterReading.objects.filter(
            metering_point=self.mp_with_data,
            timestamp__date=date(2026, 1, 31),
        ).delete()

        auth(self.client, self.owner)

        resp = self.client.get(
            "/api/v1/invoices/invoices/period-overview/",
            {
                "zev_id": str(self.zev.id),
                "period_start": "2026-01-01",
                "period_end": "2026-01-31",
            },
        )

        self.assertEqual(resp.status_code, 200)
        rows_by_participant = {row["participant_name"]: row for row in resp.data["rows"]}

        with_data_row = rows_by_participant[self.p_with_data.full_name]
        self.assertFalse(with_data_row["metering_data_complete"])
        self.assertEqual(with_data_row["missing_meter_ids"], ["CH-OVERVIEW-1"])
        self.assertEqual(with_data_row["missing_meter_details"], [{"meter_id": "CH-OVERVIEW-1", "missing_days": 1}])


class InvoiceMathEdgeCaseTests(TestCase):
    def setUp(self):
        self.owner = make_user("math_owner", UserRole.ZEV_OWNER)
        self.zev = make_zev(self.owner, "Math ZEV")
        self.participant = make_participant(self.zev, first="Math", last="Case")

        self.consumption_mp = MeteringPoint.objects.create(
            zev=self.zev,
            participant=self.participant,
            meter_id="CH-MATH-CONS-1",
            meter_type=MeteringPointType.CONSUMPTION,
            valid_from=date(2026, 1, 1),
        )

    def test_monthly_fee_counts_intersecting_month_boundaries(self):
        tariff = Tariff.objects.create(
            zev=self.zev,
            name="Ops Monthly",
            category=TariffCategory.GRID_FEES,
            billing_mode=BillingMode.MONTHLY_FEE,
            fixed_price_chf=Decimal("5.00"),
            valid_from=date(2026, 1, 1),
        )

        invoice = generate_invoice(self.participant, date(2026, 1, 15), date(2026, 2, 14))
        item = invoice.items.get(description__startswith=tariff.name)

        self.assertEqual(item.quantity_kwh, Decimal("2.0000"))
        self.assertEqual(item.total_chf, Decimal("10.00"))
        self.assertEqual(invoice.subtotal_chf, Decimal("10.00"))
        self.assertEqual(invoice.total_chf, Decimal("10.00"))

    def test_energy_tariff_applies_only_within_validity_window(self):
        tariff = Tariff.objects.create(
            zev=self.zev,
            name="Grid Window",
            category=TariffCategory.ENERGY,
            billing_mode=BillingMode.ENERGY,
            energy_type=EnergyType.GRID,
            valid_from=date(2026, 1, 15),
            valid_to=date(2026, 1, 31),
        )
        TariffPeriod.objects.create(
            tariff=tariff,
            period_type="flat",
            price_chf_per_kwh=Decimal("0.20000"),
        )

        MeterReading.objects.create(
            metering_point=self.consumption_mp,
            timestamp=datetime(2026, 1, 10, 0, 0, tzinfo=timezone.utc),
            energy_kwh=Decimal("5.0000"),
            direction=ReadingDirection.IN,
            resolution=ReadingResolution.FIFTEEN_MIN,
        )
        MeterReading.objects.create(
            metering_point=self.consumption_mp,
            timestamp=datetime(2026, 1, 20, 0, 0, tzinfo=timezone.utc),
            energy_kwh=Decimal("5.0000"),
            direction=ReadingDirection.IN,
            resolution=ReadingResolution.FIFTEEN_MIN,
        )

        invoice = generate_invoice(self.participant, date(2026, 1, 1), date(2026, 1, 31))
        item = invoice.items.get(description=tariff.name)

        self.assertEqual(item.quantity_kwh, Decimal("5.0000"))
        self.assertEqual(item.total_chf, Decimal("1.00"))
        self.assertEqual(invoice.total_grid_kwh, Decimal("10.0000"))
        self.assertEqual(invoice.subtotal_chf, Decimal("1.00"))

    def test_zero_and_negative_fixed_fees_are_handled_consistently(self):
        zero_fee = Tariff.objects.create(
            zev=self.zev,
            name="Zero Platform Fee",
            category=TariffCategory.LEVIES,
            billing_mode=BillingMode.MONTHLY_FEE,
            fixed_price_chf=Decimal("0.00"),
            valid_from=date(2026, 1, 1),
        )
        yearly_credit = Tariff.objects.create(
            zev=self.zev,
            name="Goodwill Credit",
            category=TariffCategory.LEVIES,
            billing_mode=BillingMode.YEARLY_FEE,
            fixed_price_chf=Decimal("-120.00"),
            valid_from=date(2026, 1, 1),
        )

        invoice = generate_invoice(self.participant, date(2026, 1, 1), date(2026, 1, 31))

        zero_item = invoice.items.get(description__startswith=zero_fee.name)
        credit_item = invoice.items.get(description__startswith=yearly_credit.name)

        self.assertEqual(zero_item.total_chf, Decimal("0.00"))
        self.assertEqual(credit_item.item_type, InvoiceItem.ItemType.CREDIT)
        self.assertEqual(credit_item.total_chf, Decimal("-10.00"))
        self.assertEqual(invoice.subtotal_chf, Decimal("-10.00"))
        self.assertEqual(invoice.total_chf, Decimal("-10.00"))

    def test_subtotal_rounds_to_chf_cent(self):
        tariff = Tariff.objects.create(
            zev=self.zev,
            name="Rounding Grid",
            category=TariffCategory.ENERGY,
            billing_mode=BillingMode.ENERGY,
            energy_type=EnergyType.GRID,
            valid_from=date(2026, 1, 1),
        )
        TariffPeriod.objects.create(
            tariff=tariff,
            period_type="flat",
            price_chf_per_kwh=Decimal("0.33333"),
        )

        MeterReading.objects.create(
            metering_point=self.consumption_mp,
            timestamp=datetime(2026, 1, 5, 0, 0, tzinfo=timezone.utc),
            energy_kwh=Decimal("3.0000"),
            direction=ReadingDirection.IN,
            resolution=ReadingResolution.FIFTEEN_MIN,
        )

        invoice = generate_invoice(self.participant, date(2026, 1, 1), date(2026, 1, 31))
        item = invoice.items.get(description=tariff.name)

        self.assertEqual(item.unit_price_chf, Decimal("0.33333"))
        self.assertEqual(item.total_chf, Decimal("1.00"))
        self.assertEqual(invoice.subtotal_chf, Decimal("1.00"))
        self.assertEqual(invoice.total_chf, Decimal("1.00"))


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    MEDIA_ROOT="/tmp/openzev_test_media",
)
class InvoiceEmailFormattingTests(TestCase):
    def test_email_uses_configured_short_date_format(self):
        owner = make_user("email_owner", UserRole.ZEV_OWNER)
        zev = make_zev(owner, "Email ZEV")
        participant = make_participant(zev, first="Ema", last="Il")
        invoice = make_invoice(zev, participant, InvoiceStatus.APPROVED)
        invoice.pdf_file.save("invoice_test.pdf", ContentFile(b"PDF"), save=True)

        app_settings = AppSettings.load()
        app_settings.date_format_short = AppSettings.SHORT_DATE_MM_SLASH_DD_SLASH_YYYY
        app_settings.save(update_fields=["date_format_short"])

        send_invoice_email_task.run(str(invoice.pk), "recipient@example.com")
        invoice.refresh_from_db()

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("01/01/2026 to 01/31/2026", mail.outbox[0].body)
        self.assertEqual(invoice.status, InvoiceStatus.SENT)
        self.assertIsNotNone(invoice.sent_at)

    def test_email_uses_zev_custom_templates(self):
        owner = make_user("email_tpl_owner", UserRole.ZEV_OWNER)
        zev = make_zev(owner, "Template ZEV")
        zev.email_subject_template = "[{zev_name}] Invoice {invoice_number}"
        zev.email_body_template = "Hello {participant_name}, total {total_chf} CHF"
        zev.save(update_fields=["email_subject_template", "email_body_template"])

        participant = make_participant(zev, first="Tem", last="Plate")
        invoice = make_invoice(zev, participant, InvoiceStatus.APPROVED)
        invoice.pdf_file.save("invoice_test.pdf", ContentFile(b"PDF"), save=True)

        send_invoice_email_task.run(str(invoice.pk), "recipient@example.com")

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].subject, f"[{zev.name}] Invoice {invoice.invoice_number}")
        self.assertIn(f"Hello {participant.full_name}", mail.outbox[0].body)
        self.assertIn("total", mail.outbox[0].body)


class InvoiceDescriptionSerializationTests(TestCase):
    def test_serializer_strips_period_suffix_for_legacy_item_descriptions(self):
        owner = make_user("desc_owner", UserRole.ZEV_OWNER)
        zev = make_zev(owner, "Description ZEV")
        participant = make_participant(zev, first="Des", last="Crip")
        invoice = make_invoice(zev, participant, InvoiceStatus.DRAFT)

        InvoiceItem.objects.create(
            invoice=invoice,
            item_type=InvoiceItem.ItemType.GRID_ENERGY,
            tariff_category=TariffCategory.GRID_FEES,
            description="Grid usage fee 2026-01-01 – 2026-01-31",
            quantity_kwh=Decimal("4.0000"),
            unit="kWh",
            unit_price_chf=Decimal("0.05000"),
            total_chf=Decimal("0.20"),
        )

        serialized = InvoiceSerializer(invoice).data

        self.assertEqual(serialized["items"][0]["description"], "Grid usage fee")
