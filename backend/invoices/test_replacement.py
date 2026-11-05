"""A replacement is one operation: failure keeps the issued invoice valid."""
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import patch

from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from accounts.models import AppSettings
from audit.models import AuditEvent
from invoices.engine import DynamicPriceGapError, generate_invoice
from invoices.models import Invoice, InvoiceStatus, Payment
from invoices.test_reading_impact import ImpactBase, JUNE, _change
from invoices.workflow import approve_invoice
from metering.models import MeterReading
from tariffs.models import Tariff, TariffPeriod
from testing.helpers import authenticate, create_managed_zev, make_user
from zev.models import ZevAccessGrant, ZevAccessRole


class ReplacementTests(ImpactBase):
    def setUp(self):
        super().setUp()
        AppSettings.load()
        self._assign(self.cons, self.alice, date(2025, 1, 1))
        tariff = Tariff.objects.create(zev=self.zev, name="Grid", energy_type="grid", category="energy", valid_from=date(2025, 1, 1))
        TariffPeriod.objects.create(tariff=tariff, period_type="flat", price_chf_per_kwh=Decimal("0.30"))
        self.reading = MeterReading.objects.create(
            metering_point=self.cons, timestamp=datetime(2025, 6, 10, tzinfo=timezone.utc), energy_kwh=Decimal("1.0000"), direction="in",
        )
        self.original = generate_invoice(self.alice, *JUNE)
        approve_invoice(self.original)
        self.reading.energy_kwh = Decimal("2.0000")
        self.reading.save(update_fields=["energy_kwh"])
        self.log, _ = self._flag([_change(self.cons, self.reading.timestamp.isoformat())])
        self.client = APIClient()
        authenticate(self.client, self.owner)
        self.url = f"/api/v1/invoices/invoices/{self.original.pk}/replace/"
        self.pdf = patch("invoices.views.generate_invoice_pdf_task.delay").start()
        self.addCleanup(patch.stopall)

    def test_preview_matches_replacement_without_any_database_writes(self):
        url = self.url.replace("replace/", "calculation-preview/")
        with CaptureQueriesContext(connection) as queries:
            response = self.client.post(url, {"participant_id": str(self.bob.pk), "period_start": "2000-01-01"})
            repeated = self.client.post(url)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data, repeated.data)
        self.assertEqual(set(response.data), {"total_chf", "total_local_kwh", "total_grid_kwh", "total_feed_in_kwh"})
        self.assertFalse([q["sql"] for q in queries if q["sql"].lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE"}])
        self.assertFalse([q["sql"] for q in queries if "FOR UPDATE" in q["sql"].upper()])
        self.assertFalse([q["sql"] for q in queries if "pg_advisory_xact_lock" in q["sql"]])
        self.original.refresh_from_db()
        self.assertEqual(self.original.status, InvoiceStatus.APPROVED)
        self.assertTrue(self.original.reading_impacts.filter(resolved_at__isnull=True).exists())
        self.pdf.assert_not_called()
        replacement = self.client.post(self.url)
        self.assertEqual(replacement.status_code, 201, replacement.data)
        self.assertEqual(response.data, {field: replacement.data[field] for field in response.data})

    def test_preview_draft_matches_generation_and_keeps_existing_items(self):
        Invoice.objects.filter(pk=self.original.pk).update(status=InvoiceStatus.DRAFT, approved_at=None)
        with CaptureQueriesContext(connection) as queries:
            response = self.client.post(self.url.replace("replace/", "calculation-preview/"))
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse([q["sql"] for q in queries if q["sql"].lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE"}])
        actual = generate_invoice(self.alice, *JUNE)
        self.assertEqual(Decimal(response.data["total_chf"]), actual.total_chf)
        self.assertEqual(Decimal(response.data["total_grid_kwh"]), actual.total_grid_kwh)

    def test_preview_can_show_unchanged_amount_with_changed_energy(self):
        self.reading.energy_kwh = Decimal("1.0001")
        self.reading.save(update_fields=["energy_kwh"])
        response = self.client.post(self.url.replace("replace/", "calculation-preview/"))
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(Decimal(response.data["total_chf"]), self.original.total_chf)
        self.assertNotEqual(Decimal(response.data["total_grid_kwh"]), self.original.total_grid_kwh)
        replacement = self.client.post(self.url)
        self.assertEqual(replacement.status_code, 201, replacement.data)
        self.assertEqual(response.data, {field: replacement.data[field] for field in response.data})

    def test_preview_price_gap_leaves_original_and_returns_structured_error(self):
        tariff = Tariff.objects.get(zev=self.zev, name="Grid")
        error = DynamicPriceGapError(tariff=tariff, missing_at=self.reading.timestamp)
        with patch("invoices.views.generate_invoice", side_effect=error), CaptureQueriesContext(connection) as queries:
            response = self.client.post(self.url.replace("replace/", "calculation-preview/"))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "dynamic_price_gap")
        self.assertFalse([q["sql"] for q in queries if q["sql"].lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE"}])
        self.pdf.assert_not_called()

    def test_replace_price_gap_leaves_original_and_returns_structured_error(self):
        tariff = Tariff.objects.get(zev=self.zev, name="Grid")
        error = DynamicPriceGapError(tariff=tariff, missing_at=self.reading.timestamp)
        with patch("invoices.replacement.generate_invoice", side_effect=error):
            response = self.client.post(self.url)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "dynamic_price_gap")
        self.original.refresh_from_db()
        self.assertEqual(self.original.status, InvoiceStatus.APPROVED)
        self.assertTrue(self.original.reading_impacts.filter(resolved_at__isnull=True).exists())
        self.pdf.assert_not_called()
        event = AuditEvent.objects.get(action_type="invoice.replace", status="failed")
        self.assertIn("has no dynamic price", event.metadata_json["error"])

    def test_preview_is_scoped_to_managers_and_rejects_disabled_community(self):
        url = self.url.replace("replace/", "calculation-preview/")
        viewer = make_user("preview_viewer")
        ZevAccessGrant.objects.create(zev=self.zev, user=viewer, role=ZevAccessRole.VIEWER)
        for user in (viewer, make_user("preview_foreign")):
            authenticate(self.client, user)
            self.assertEqual(self.client.post(url).status_code, 403)
        participant = make_user("preview_participant")
        self.alice.user = participant
        self.alice.save(update_fields=["user"])
        authenticate(self.client, participant)
        self.assertEqual(self.client.post(url).status_code, 403)
        foreign_manager = make_user("preview_foreign_manager")
        create_managed_zev(name="Other", owner=foreign_manager)
        authenticate(self.client, foreign_manager)
        self.assertEqual(self.client.post(url).status_code, 404)
        from django.utils import timezone as django_timezone
        self.zev.disabled_at = django_timezone.now()
        self.zev.save(update_fields=["disabled_at"])
        authenticate(self.client, self.owner)
        with CaptureQueriesContext(connection) as queries:
            self.assertEqual(self.client.post(url).status_code, 400)
        self.assertFalse([q["sql"] for q in queries if q["sql"].lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE"}])

    def test_replaces_in_one_request_and_retains_original_values(self):
        before = self.original.total_chf
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 201, response.data)
        replacement = Invoice.objects.get(pk=response.data["id"])
        self.original.refresh_from_db()
        self.assertEqual(self.original.status, InvoiceStatus.CANCELLED)
        self.assertEqual(self.original.total_chf, before)
        self.assertEqual(replacement.status, InvoiceStatus.DRAFT)
        self.assertEqual(replacement.total_chf - before, Decimal("0.30"))
        self.assertEqual((replacement.participant_id, replacement.period_start, replacement.period_end), (self.alice.pk, *JUNE))
        self.assertFalse(self.original.reading_impacts.filter(resolved_at__isnull=True).exists())
        self.pdf.assert_called_once_with(str(replacement.pk))
        event = AuditEvent.objects.get(action_type="invoice.replace")
        self.assertEqual(event.metadata_json["replacement_id"], str(replacement.pk))
        retry = self.client.post(self.url)
        self.assertEqual(retry.status_code, 400)
        self.assertEqual(Invoice.objects.filter(participant=self.alice).count(), 2)

    def test_retains_legacy_issued_invoice_without_approval_timestamp(self):
        self.original.approved_at = None
        self.original.save(update_fields=["approved_at"])
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 201, response.data)
        self.original.refresh_from_db()
        self.assertEqual(self.original.status, InvoiceStatus.CANCELLED)
        self.assertIsNotNone(self.original.approved_at)

    def test_audit_uses_locked_state_instead_of_stale_detail_state(self):
        Invoice.objects.filter(pk=self.original.pk).update(status=InvoiceStatus.SENT)
        with patch("invoices.views.InvoiceViewSet.get_object", return_value=self.original):
            response = self.client.post(self.url)
        self.assertEqual(response.status_code, 201, response.data)
        event = AuditEvent.objects.get(action_type="invoice.replace")
        self.assertEqual(event.changes_json["status"]["before"], InvoiceStatus.SENT)

    def test_generation_failure_rolls_back_cancellation_impacts_and_counter(self):
        self.zev.refresh_from_db()
        counter = self.zev.invoice_counter
        def fail_after_generation(*args, **kwargs):
            generate_invoice(*args, **kwargs)
            raise ValueError("Pricing failed")
        with patch("invoices.replacement.generate_invoice", side_effect=fail_after_generation):
            response = self.client.post(self.url)
        self.assertEqual(response.status_code, 400)
        self.original.refresh_from_db()
        self.zev.refresh_from_db()
        self.assertEqual(self.original.status, InvoiceStatus.APPROVED)
        self.assertTrue(self.original.reading_impacts.filter(resolved_at__isnull=True).exists())
        self.assertEqual(self.zev.invoice_counter, counter)
        self.assertEqual(Invoice.objects.filter(participant=self.alice).count(), 1)
        self.pdf.assert_not_called()

    def test_rejects_recorded_payments_and_paid_invoices(self):
        self.original.status = InvoiceStatus.SENT
        self.original.save(update_fields=["status"])
        Payment.objects.create(invoice=self.original, amount_chf=Decimal("0.10"), paid_on=date(2025, 7, 1))
        self.assertEqual(self.client.post(self.url).status_code, 400)
        self.original.status = InvoiceStatus.PAID
        self.original.save(update_fields=["status"])
        self.assertEqual(self.client.post(self.url).status_code, 400)
        self.assertEqual(Invoice.objects.filter(participant=self.alice).count(), 1)

    def test_viewer_foreign_user_and_disabled_manager_cannot_replace(self):
        viewer = make_user("replacement_viewer")
        ZevAccessGrant.objects.create(zev=self.zev, user=viewer, role=ZevAccessRole.VIEWER)
        authenticate(self.client, viewer)
        self.assertEqual(self.client.post(self.url).status_code, 403)
        authenticate(self.client, make_user("replacement_foreign"))
        self.assertEqual(self.client.post(self.url).status_code, 403)
        from django.utils import timezone as django_timezone
        self.zev.disabled_at = django_timezone.now()
        self.zev.save(update_fields=["disabled_at"])
        authenticate(self.client, self.owner)
        self.assertEqual(self.client.post(self.url).status_code, 400)
        self.original.refresh_from_db()
        self.assertEqual(self.original.status, InvoiceStatus.APPROVED)
