"""Admin purge: the terminal ``disabled -> gone`` transition of the ZEV
lifecycle. See ``zev.purge`` for exactly what is deleted, what survives via
``SET_NULL``, and what is deliberately not done yet (a pre-purge backup).
"""
from datetime import date

from django.core.files.base import ContentFile
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import UserRole
from audit.models import AuditActionCategory, AuditEvent
from audit.services import record_audit_event
from backups.models import BackupJob
from exports.models import ExportJob, ExportType
from invoices.models import ContractIssue, Invoice
from invoices.test_helpers import make_invoice
from metering.models import ImportLog, ImportSource, MeterReading
from tariffs.models import BillingMode, EnergyType, Tariff, TariffCategory, TariffPeriod
from testing.helpers import authenticate as auth, make_user
from zev.models import (
    MeteringPoint,
    MeteringPointAssignment,
    MeteringPointType,
    Participant,
    ParticipantOnboardingToken,
    Zev,
)
from zev.purge import ZevPurgeError, purge_zev

PURGE_URL = "/api/v1/zev/zevs/{id}/purge/"


class _FullyWiredZev(TestCase):
    """A disabled ZEV with one row of everything that hangs off it — every
    CASCADE child, both PROTECT relations, and every SET_NULL survivor."""

    def setUp(self):
        self.owner = make_user("purge_owner", UserRole.ZEV_OWNER)
        self.admin = make_user("purge_admin", UserRole.ADMIN)
        self.zev = Zev.objects.create(name="Purge Me ZEV", owner=self.owner)

        self.participant = Participant.objects.create(
            zev=self.zev, first_name="Paula", last_name="Purged",
            email="paula@example.com", valid_from=date(2026, 1, 1),
        )
        self.onboarding_token = ParticipantOnboardingToken.objects.create(
            participant=self.participant, prefix="purgeprefix", secret="s3cr3t",
        )
        self.meter = MeteringPoint.objects.create(
            zev=self.zev, meter_id="PURGE-METER", meter_type=MeteringPointType.CONSUMPTION,
        )
        self.assignment = MeteringPointAssignment.objects.create(
            metering_point=self.meter, participant=self.participant, valid_from=date(2026, 1, 1),
        )
        self.reading = MeterReading.objects.create(
            metering_point=self.meter, timestamp="2026-01-15T12:00:00Z", energy_kwh="1.5000",
        )
        self.tariff = Tariff.objects.create(
            zev=self.zev, name="Purge Tariff", category=TariffCategory.ENERGY,
            billing_mode=BillingMode.ENERGY, energy_type=EnergyType.LOCAL,
            valid_from=date(2026, 1, 1),
        )
        self.tariff_period = TariffPeriod.objects.create(tariff=self.tariff, price_chf_per_kwh="0.25000")
        self.import_log = ImportLog.objects.create(zev=self.zev, source=ImportSource.CSV)
        self.invoice = make_invoice(self.zev, self.participant)
        self.invoice.pdf_file.save("invoice.pdf", ContentFile(b"%PDF-1.4 fake"), save=True)
        self.export_job = ExportJob.objects.create(zev=self.zev, export_type=ExportType.ANNUAL_STATEMENTS)
        self.export_job.result_file.save("export.zip", ContentFile(b"PK\x03\x04 fake zip"), save=True)

        # SET_NULL survivors.
        self.contract_issue = ContractIssue.objects.create(
            zev=self.zev, participant=self.participant, version=1, document_number="CTR-2026-0001",
            language="de", context_hash="deadbeef" * 8, pdf=b"contract bytes",
        )
        self.backup_job = BackupJob.objects.create(zev=self.zev)
        self.audit_event = record_audit_event(
            action_category=AuditActionCategory.GOVERNANCE, action_type="zev.test_event",
            target_type="zev.Zev", target_id=str(self.zev.id), target_display=self.zev.name,
            summary="A pre-purge event.", zev=self.zev,
        )

        self.zev.disabled_at = timezone.now()
        self.zev.disabled_by = self.owner
        self.zev.save()

        self.owner_client = APIClient()
        auth(self.owner_client, self.owner)
        self.admin_client = APIClient()
        auth(self.admin_client, self.admin)


class PurgeServiceTests(_FullyWiredZev):
    """purge_zev() called directly — the deletion/survival contract."""

    def test_refuses_an_active_zev(self):
        self.zev.disabled_at = None
        self.zev.save()
        with self.assertRaises(ZevPurgeError):
            purge_zev(self.zev)
        self.assertTrue(Zev.objects.filter(pk=self.zev.pk).exists())

    def test_deletes_the_zev_and_every_cascade_child(self):
        invoice_pdf_name = self.invoice.pdf_file.name
        export_file_name = self.export_job.result_file.name
        from django.core.files.storage import default_storage
        self.assertTrue(default_storage.exists(invoice_pdf_name))
        self.assertTrue(default_storage.exists(export_file_name))

        result = purge_zev(self.zev)

        self.assertFalse(Zev.objects.filter(pk=self.zev.pk).exists())
        self.assertFalse(Participant.objects.filter(pk=self.participant.pk).exists())
        self.assertFalse(ParticipantOnboardingToken.objects.filter(pk=self.onboarding_token.pk).exists())
        self.assertFalse(MeteringPoint.objects.filter(pk=self.meter.pk).exists())
        self.assertFalse(MeteringPointAssignment.objects.filter(pk=self.assignment.pk).exists())
        self.assertFalse(MeterReading.objects.filter(pk=self.reading.pk).exists())
        self.assertFalse(Tariff.objects.filter(pk=self.tariff.pk).exists())
        self.assertFalse(TariffPeriod.objects.filter(pk=self.tariff_period.pk).exists())
        self.assertFalse(ImportLog.objects.filter(pk=self.import_log.pk).exists())
        self.assertFalse(Invoice.objects.filter(pk=self.invoice.pk).exists())
        self.assertFalse(ExportJob.objects.filter(pk=self.export_job.pk).exists())

        # Media files removed from storage, not just the rows.
        self.assertFalse(default_storage.exists(invoice_pdf_name))
        self.assertFalse(default_storage.exists(export_file_name))
        self.assertEqual(result.media_files_deleted, 2)

        self.assertEqual(result.deleted_counts["invoices"], 1)
        self.assertEqual(result.deleted_counts["export_jobs"], 1)
        self.assertEqual(result.deleted_counts["participants"], 1)
        self.assertEqual(result.deleted_counts["metering_points"], 1)
        self.assertEqual(result.deleted_counts["tariffs"], 1)
        self.assertEqual(result.zev_name, "Purge Me ZEV")

    def test_set_null_rows_survive_with_their_zev_link_cleared(self):
        purge_zev(self.zev)

        self.contract_issue.refresh_from_db()
        self.assertIsNone(self.contract_issue.zev_id)
        self.assertIsNone(self.contract_issue.participant_id)
        self.assertEqual(self.contract_issue.document_number, "CTR-2026-0001")

        self.backup_job.refresh_from_db()
        self.assertIsNone(self.backup_job.zev_id)

        self.audit_event.refresh_from_db()
        self.assertIsNone(self.audit_event.zev_id)
        self.assertEqual(self.audit_event.target_display, "Purge Me ZEV")


class PurgeEndpointTests(_FullyWiredZev):
    def test_owner_cannot_purge(self):
        response = self.owner_client.post(
            PURGE_URL.format(id=self.zev.id), {"confirm_name": self.zev.name}, format="json",
        )
        self.assertEqual(response.status_code, 403, response.content)
        self.assertTrue(Zev.objects.filter(pk=self.zev.pk).exists())

    def test_admin_purge_requires_the_exact_name(self):
        response = self.admin_client.post(
            PURGE_URL.format(id=self.zev.id), {"confirm_name": "wrong name"}, format="json",
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertTrue(Zev.objects.filter(pk=self.zev.pk).exists())

    def test_admin_cannot_purge_an_active_zev(self):
        self.zev.disabled_at = None
        self.zev.save()
        response = self.admin_client.post(
            PURGE_URL.format(id=self.zev.id), {"confirm_name": self.zev.name}, format="json",
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertTrue(Zev.objects.filter(pk=self.zev.pk).exists())

    def test_admin_can_purge_with_the_exact_name(self):
        response = self.admin_client.post(
            PURGE_URL.format(id=self.zev.id), {"confirm_name": self.zev.name}, format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertFalse(Zev.objects.filter(pk=self.zev.pk).exists())
        self.assertEqual(response.json()["deleted_counts"]["invoices"], 1)

    def test_purge_is_audited(self):
        self.admin_client.post(PURGE_URL.format(id=self.zev.id), {"confirm_name": self.zev.name}, format="json")
        event = AuditEvent.objects.filter(action_type="zev.purge").latest("created_at")
        self.assertEqual(event.target_display, "Purge Me ZEV")
        self.assertIsNone(event.zev_id)
        self.assertEqual(event.metadata_json["deleted_counts"]["invoices"], 1)
