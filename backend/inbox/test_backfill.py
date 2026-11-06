from datetime import datetime, timezone
from io import StringIO

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management import call_command
from django.test import TestCase

from accounts.models import UserRole
from inbox.backfill import FILE_MISSING, NO_DOCUMENT, backfill_invoices
from inbox.models import DeliveredDocument
from inbox.test_helpers import PDF
from invoices.models import Invoice, InvoiceStatus
from invoices.test_helpers import make_invoice, make_participant, make_zev
from testing.helpers import make_user

SENT_AT = datetime(2026, 2, 3, 10, 0, tzinfo=timezone.utc)


def _sent_invoice(zev, participant, *, with_pdf=True, body=PDF + b"old", sent_at=SENT_AT):
    invoice = make_invoice(zev, participant, InvoiceStatus.SENT)
    Invoice.objects.filter(pk=invoice.pk).update(sent_at=sent_at)
    invoice.refresh_from_db()
    if with_pdf:
        invoice.pdf_file.save("invoice_old.pdf", ContentFile(body), save=True)
    return invoice


class BackfillTests(TestCase):
    def setUp(self):
        self.owner = make_user("inbox_bf_owner", UserRole.USER)
        self.zev = make_zev(self.owner)
        self.participant = make_participant(self.zev)

    def test_creates_rows_for_sent_invoices_dated_by_sent_at(self):
        invoice = _sent_invoice(self.zev, self.participant)

        report = backfill_invoices()

        self.assertEqual(report.delivered, 1)
        document = DeliveredDocument.objects.get(invoice=invoice)
        self.assertEqual(document.delivered_at, SENT_AT)
        with document.open_file() as handle:
            self.assertEqual(handle.read(), PDF + b"old")

    def test_drafts_and_approved_invoices_are_left_alone(self):
        make_invoice(self.zev, self.participant, InvoiceStatus.DRAFT)
        approved = make_invoice(self.zev, self.participant, InvoiceStatus.APPROVED)
        approved.pdf_file.save("invoice_a.pdf", ContentFile(PDF), save=True)

        report = backfill_invoices()

        self.assertEqual((report.delivered, report.already_delivered, report.missing), (0, 0, []))
        self.assertFalse(DeliveredDocument.objects.exists())

    def test_skips_missing_documents_and_reports_them(self):
        no_document = _sent_invoice(self.zev, self.participant, with_pdf=False)
        gone = _sent_invoice(self.zev, self.participant)
        default_storage.delete(gone.pdf_file.name)

        report = backfill_invoices()

        self.assertEqual(report.delivered, 0)
        self.assertCountEqual(
            report.missing, [(no_document.invoice_number, NO_DOCUMENT), (gone.invoice_number, FILE_MISSING)]
        )
        self.assertFalse(report.clean)
        self.assertFalse(DeliveredDocument.objects.exists())

    def test_dry_run_writes_nothing(self):
        _sent_invoice(self.zev, self.participant)

        report = backfill_invoices(dry_run=True)

        self.assertEqual(report.delivered, 1)
        self.assertTrue(report.dry_run)
        self.assertFalse(DeliveredDocument.objects.exists())

    def test_is_idempotent(self):
        _sent_invoice(self.zev, self.participant)
        backfill_invoices()

        again = backfill_invoices()

        self.assertEqual((again.delivered, again.already_delivered), (0, 1))
        self.assertEqual(DeliveredDocument.objects.count(), 1)

    def test_an_invoice_without_sent_at_falls_back_to_approval_then_update_time(self):
        invoice = _sent_invoice(self.zev, self.participant, sent_at=None)
        approved_at = datetime(2026, 1, 20, 8, 0, tzinfo=timezone.utc)
        Invoice.objects.filter(pk=invoice.pk).update(approved_at=approved_at)

        backfill_invoices()

        self.assertEqual(DeliveredDocument.objects.get(invoice=invoice).delivered_at, approved_at)

    def test_zev_filter_limits_the_run(self):
        other_zev = make_zev(make_user("inbox_bf_other", UserRole.USER), "Other")
        mine = _sent_invoice(self.zev, self.participant)
        _sent_invoice(other_zev, make_participant(other_zev))

        backfill_invoices(zev=self.zev)

        self.assertEqual(list(DeliveredDocument.objects.values_list("invoice_id", flat=True)), [mine.pk])

    def test_management_command_reports_what_it_skipped(self):
        invoice = _sent_invoice(self.zev, self.participant, with_pdf=False)
        out = StringIO()

        call_command("openzev_inbox_backfill", "--dry-run", stdout=out)

        text = out.getvalue()
        self.assertIn("Would deliver 0 invoice(s)", text)
        self.assertIn(f"skipped {invoice.invoice_number}: no_document", text)
