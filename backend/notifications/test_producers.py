"""The events the application raises, at the places where they happen."""

from datetime import datetime, timezone as dt_timezone
from decimal import Decimal
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from invoices.models import Invoice, InvoiceStatus
from invoices.test_helpers import make_invoice
from invoices.workflow import mark_invoice_paid, mark_invoice_sent, record_email_delivery, record_payment
from metering.models import ImportLog, ImportSource, MeterReading
from notifications import producers
from notifications.models import Notification
from notifications.test_helpers import Community
from testing.helpers import authenticate, make_user
from zev.access import grant_manager
from zev.models import MeteringPointAssignment


def types(**filters):
    return sorted(Notification.objects.filter(**filters).values_list("type", flat=True))


class InvoiceEventTests(TestCase):
    def setUp(self):
        self.c = Community("i")

    def sent_invoice(self, participant=None, status=InvoiceStatus.SENT):
        invoice = make_invoice(self.c.zev, participant or self.c.participant, status)
        Invoice.objects.filter(pk=invoice.pk).update(total_chf=Decimal("100.00"))
        invoice.refresh_from_db()
        return invoice

    def test_first_email_delivery_notifies_the_participant_but_a_resend_does_not(self):
        invoice = self.sent_invoice(status=InvoiceStatus.APPROVED)
        with self.captureOnCommitCallbacks(execute=True):
            record_email_delivery(invoice, timezone.now())
        row = Notification.objects.get()
        self.assertEqual((row.recipient, row.type, row.target_id), (self.c.login, "invoice.sent", str(invoice.pk)))
        self.assertEqual(set(row.payload), {"invoice_number", "period_start", "period_end"})
        with self.captureOnCommitCallbacks(execute=True):
            record_email_delivery(invoice, timezone.now())
        self.assertEqual(Notification.objects.count(), 1)

    def test_marking_an_invoice_sent_by_hand_notifies_once(self):
        invoice = self.sent_invoice(status=InvoiceStatus.APPROVED)
        with self.captureOnCommitCallbacks(execute=True):
            mark_invoice_sent(invoice)
        with self.captureOnCommitCallbacks(execute=True):
            record_email_delivery(invoice, timezone.now())
        self.assertEqual(types(), ["invoice.sent"])

    def test_a_draft_or_a_cancelled_invoice_notifies_nobody(self):
        cancelled = self.sent_invoice(status=InvoiceStatus.CANCELLED)
        with self.captureOnCommitCallbacks(execute=True):
            record_email_delivery(cancelled, timezone.now())
        self.assertEqual(Notification.objects.count(), 0)

    def test_participant_without_a_login_gets_nothing(self):
        invoice = self.sent_invoice(self.c.no_login, InvoiceStatus.APPROVED)
        with self.captureOnCommitCallbacks(execute=True):
            record_email_delivery(invoice, timezone.now())
        self.assertEqual(Notification.objects.count(), 0)

    def test_mark_paid_and_the_closing_partial_payment_notify_but_an_open_one_does_not(self):
        today = timezone.localdate()
        partial = self.sent_invoice()
        with self.captureOnCommitCallbacks(execute=True):
            record_payment(partial, amount_chf=Decimal("40.00"), paid_on=today)
        self.assertEqual(Notification.objects.count(), 0)
        with self.captureOnCommitCallbacks(execute=True):
            record_payment(partial, amount_chf=Decimal("60.00"), paid_on=today)
        self.assertEqual(types(), ["invoice.paid"])

        marked = self.sent_invoice()
        with self.captureOnCommitCallbacks(execute=True):
            mark_invoice_paid(marked, paid_on=today)
        self.assertEqual(Notification.objects.filter(type="invoice.paid").count(), 2)

    def test_payload_never_carries_amounts_or_names(self):
        invoice = self.sent_invoice()
        with self.captureOnCommitCallbacks(execute=True):
            mark_invoice_paid(invoice)
        text = str(Notification.objects.get().payload)
        for secret in ("100", "Jane", "Doe", "example.com"):
            self.assertNotIn(secret, text)


class MeteringDataEventTests(TestCase):
    def setUp(self):
        self.c = Community("m")
        self.log = ImportLog.objects.create(zev=self.c.zev, imported_by=self.c.manager, source=ImportSource.CSV)

    def readings(self, metering_point, *stamps):
        for stamp in stamps:
            MeterReading.objects.create(
                metering_point=metering_point, timestamp=stamp, energy_kwh=Decimal("1.0"),
                import_batch=self.log.batch_id,
            )

    def test_one_notification_per_point_for_the_participant_holding_it(self):
        self.readings(self.c.metering_point, datetime(2026, 3, 1, 10, tzinfo=dt_timezone.utc),
                      datetime(2026, 3, 3, 10, tzinfo=dt_timezone.utc))
        with self.captureOnCommitCallbacks(execute=True):
            producers.notify_metering_data(self.log)
        row = Notification.objects.get()
        self.assertEqual((row.recipient, row.type, row.target_id), (self.c.login, "metering.data", str(self.c.metering_point.pk)))
        self.assertEqual(row.payload, {
            "meter_id": self.c.metering_point.meter_id, "first_day": "2026-03-01", "last_day": "2026-03-03",
        })

    def test_a_second_import_the_same_day_updates_the_unread_line(self):
        self.readings(self.c.metering_point, datetime(2026, 3, 1, 10, tzinfo=dt_timezone.utc))
        with self.captureOnCommitCallbacks(execute=True):
            producers.notify_metering_data(self.log)
        second = ImportLog.objects.create(zev=self.c.zev, imported_by=self.c.manager, source=ImportSource.CSV)
        MeterReading.objects.create(
            metering_point=self.c.metering_point, timestamp=datetime(2026, 3, 5, 10, tzinfo=dt_timezone.utc),
            energy_kwh=Decimal("1.0"), import_batch=second.batch_id,
        )
        with self.captureOnCommitCallbacks(execute=True):
            producers.notify_metering_data(second)
        row = Notification.objects.get()
        self.assertEqual((row.payload["first_day"], row.payload["last_day"]), ("2026-03-01", "2026-03-05"))

    def test_only_participants_whose_assignment_overlaps_the_data_are_told(self):
        MeteringPointAssignment.objects.filter(pk=self.c.assignment.pk).update(
            valid_to=datetime(2026, 2, 28).date()
        )
        self.readings(self.c.metering_point, datetime(2026, 3, 1, 10, tzinfo=dt_timezone.utc))
        with self.captureOnCommitCallbacks(execute=True):
            producers.notify_metering_data(self.log)
        self.assertEqual(Notification.objects.count(), 0)

    def test_an_import_without_readings_notifies_nobody(self):
        with self.captureOnCommitCallbacks(execute=True):
            producers.notify_metering_data(self.log)
        self.assertEqual(Notification.objects.count(), 0)


class ImportOutcomeTests(TestCase):
    def setUp(self):
        self.c = Community("o")
        self.other_manager = make_user("mgr_o2")
        grant_manager(self.c.zev, self.other_manager)

    def outcome(self, **fields):
        log = ImportLog.objects.create(zev=self.c.zev, imported_by=self.c.manager, source=ImportSource.CSV, **fields)
        with self.captureOnCommitCallbacks(execute=True):
            producers.notify_import_outcome(log)
        return log

    def test_finished_import_tells_the_other_managers_not_the_uploader(self):
        self.outcome(rows_imported=10, rows_skipped=2, errors=[{"row": 3, "error": "x"}])
        row = Notification.objects.get()
        self.assertEqual((row.recipient, row.type), (self.other_manager, "import.finished"))
        self.assertEqual(row.payload["rows_imported"], 10)
        self.assertEqual(row.payload["issues"], 1)

    def test_import_that_imported_nothing_with_errors_failed(self):
        self.outcome(rows_imported=0, rows_skipped=5, errors=[{"row": None, "error": "bad"}])
        self.assertEqual(types(), ["import.failed"])

    def test_rejected_sdat_delivery_failed(self):
        self.outcome(rows_imported=0, result_status="rejected")
        self.assertEqual(types(), ["import.failed"])

    def test_unchanged_delivery_is_not_a_failure(self):
        self.outcome(rows_imported=0, result_status="unchanged")
        self.assertEqual(types(), ["import.finished"])

    def test_producer_failure_never_reaches_the_caller(self):
        with mock.patch("notifications.producers.manager_accounts", side_effect=RuntimeError("boom")):
            producers.notify_import_outcome(
                ImportLog.objects.create(zev=self.c.zev, source=ImportSource.CSV)
            )


class ImportUploadWiringTests(TestCase):
    """The upload endpoint raises the events; other imports (transfer, seed) do not."""

    def setUp(self):
        self.c = Community("u")
        self.second_manager = make_user("mgr_u2")
        grant_manager(self.c.zev, self.second_manager)
        self.client = APIClient()
        authenticate(self.client, self.c.manager)

    def test_csv_upload_notifies_participant_and_other_manager(self):
        csv = f"meter_id,timestamp,energy_kwh\n{self.c.metering_point.meter_id},2026-03-01T10:00:00Z,1.5\n"
        upload = SimpleUploadedFile("data.csv", csv.encode(), content_type="text/csv")
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                "/api/v1/metering/import/csv/", {"file": upload, "zev_id": str(self.c.zev.pk)}, format="multipart"
            )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(
            sorted((n.recipient.username, n.type) for n in Notification.objects.select_related("recipient")),
            [("mgr_u2", "import.finished"), ("part_u", "metering.data")],
        )


class GenerationEventTests(TestCase):
    def setUp(self):
        self.c = Community("g")

    def run_task(self, **engine):
        from invoices.tasks import generate_zev_invoices_task

        with mock.patch("invoices.tasks._render_pdfs", return_value=0), \
                mock.patch("invoices.engine.generate_invoices_for_zev", **engine), \
                self.captureOnCommitCallbacks(execute=True):
            try:
                generate_zev_invoices_task.run(str(self.c.zev.pk), "2026-01-01", "2026-01-31")
            except RuntimeError:
                pass

    def test_finished_batch_tells_the_managers(self):
        self.run_task(return_value=([], [{"participant": "x", "error": "y"}]))
        row = Notification.objects.get()
        self.assertEqual((row.recipient, row.type), (self.c.manager, "invoices.generated"))
        self.assertEqual((row.payload["created"], row.payload["failed"]), (0, 1))

    def test_aborted_batch_tells_the_managers(self):
        self.run_task(side_effect=RuntimeError("db down"))
        self.assertEqual(types(), ["invoices.generation_failed"])

