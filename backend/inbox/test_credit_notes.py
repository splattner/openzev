"""Credit notes in the participant inbox (spec §6.2, §6.6): delivered once, when the PDF first exists."""

from io import StringIO
from unittest import mock

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase

from accounts.models import UserRole
from audit.models import AuditEvent, AuditEventStatus
from inbox.backfill import FILE_MISSING, NO_DOCUMENT, backfill_credits
from inbox.models import DeliveredDocument, DocumentKind
from inbox.producers import deliver_credit_note
from inbox.services import deliver
from inbox.tasks import inbox_backfill_task
from inbox.test_helpers import PDF
from invoices.models import CreditKind
from invoices.tasks import generate_credit_pdf_task
from invoices.test_credits import _paid
from invoices.test_helpers import make_participant, make_zev
from invoices.workflow import correct_invoice
from notifications.models import Notification
from testing.helpers import make_user


class CreditNoteBase(TestCase):
    def setUp(self):
        self.owner = make_user("inbox_cn_owner", UserRole.USER)
        self.zev = make_zev(self.owner, "Credit inbox ZEV")
        self.account = make_user("inbox_cn_anna", UserRole.USER)
        self.participant = make_participant(self.zev, user=self.account)

    def credit(self, participant=None, zev=None):
        invoice = _paid(zev or self.zev, participant or self.participant)
        return correct_invoice(invoice, kind=CreditKind.REVERSAL, reason="Wrong readings", user=self.owner)["credit"]

    def documents(self):
        return DeliveredDocument.objects.filter(kind=DocumentKind.CREDIT_NOTE)


class DeliveryOnRenderTests(CreditNoteBase):
    def test_the_first_render_delivers_the_credit_note(self):
        credit = self.credit()
        self.assertFalse(self.documents().exists(), "nothing is delivered before the PDF exists")

        generate_credit_pdf_task(str(credit.pk))

        document = self.documents().get()
        credit.refresh_from_db()
        self.assertEqual(document.participant, self.participant)
        self.assertEqual(document.title, credit.credit_number)
        self.assertEqual(document.document_number, credit.credit_number)
        self.assertEqual(document.delivered_at, credit.created_at)
        self.assertEqual(
            (document.period_start, document.period_end),
            (credit.source_invoice.period_start, credit.source_invoice.period_end),
        )
        with document.open_file() as handle, credit.pdf_file.open("rb") as stored:
            self.assertEqual(handle.read(), stored.read())

    def test_rendering_again_leaves_the_delivered_copy_alone(self):
        credit = self.credit()
        generate_credit_pdf_task(str(credit.pk))
        document = self.documents().get()

        generate_credit_pdf_task(str(credit.pk))

        self.assertEqual(self.documents().count(), 1)
        again = self.documents().get()
        self.assertEqual((again.pk, again.sha256, again.file.name), (document.pk, document.sha256, document.file.name))

    def test_a_failed_render_delivers_nothing_and_a_later_one_does(self):
        credit = self.credit()
        with mock.patch("invoices.credit_pdf.render_pdf", side_effect=RuntimeError("boom")):
            generate_credit_pdf_task(str(credit.pk))
        self.assertFalse(self.documents().exists())

        generate_credit_pdf_task(str(credit.pk))

        self.assertEqual(self.documents().count(), 1)

    def test_the_participant_is_told_once(self):
        credit = self.credit()
        with self.captureOnCommitCallbacks(execute=True):
            generate_credit_pdf_task(str(credit.pk))
        with self.captureOnCommitCallbacks(execute=True):
            generate_credit_pdf_task(str(credit.pk))

        row = Notification.objects.get(type="document.delivered")
        document = self.documents().get()
        self.assertEqual(row.recipient, self.account)
        self.assertEqual(
            row.payload, {"document_id": str(document.pk), "kind": "credit_note", "title": credit.credit_number}
        )

    def test_a_failing_delivery_neither_raises_nor_undoes_the_render(self):
        credit = self.credit()
        with mock.patch("inbox.producers.deliver", side_effect=RuntimeError("disk full")):
            generate_credit_pdf_task(str(credit.pk))
        credit.refresh_from_db()
        self.assertTrue(credit.pdf_file)
        self.assertFalse(self.documents().exists())
        event = AuditEvent.objects.get(action_type="inbox.document.delivered", status=AuditEventStatus.FAILED)
        self.assertEqual(event.target_display, credit.credit_number)

    def test_a_credit_note_without_a_document_is_not_delivered(self):
        credit = self.credit()
        self.assertIsNone(deliver_credit_note(credit))
        self.assertFalse(self.documents().exists())


class ServiceTests(CreditNoteBase):
    def test_a_credit_note_needs_its_number(self):
        with self.assertRaises(ValueError):
            deliver(participant=self.participant, kind=DocumentKind.CREDIT_NOTE, title="CN", body=PDF)

    def test_delivering_the_same_number_again_returns_the_row(self):
        first, created = deliver(
            participant=self.participant, kind=DocumentKind.CREDIT_NOTE, title="CN-1", body=PDF, document_number="CN-1"
        )
        second, created_again = deliver(
            participant=self.participant, kind=DocumentKind.CREDIT_NOTE, title="CN-1", body=PDF + b"x",
            document_number="CN-1",
        )
        self.assertEqual((created, created_again, second.pk), (True, False, first.pk))

    def test_the_same_number_in_another_zev_is_its_own_document(self):
        other_zev = make_zev(make_user("inbox_cn_other", UserRole.USER), "Other")
        for participant in (self.participant, make_participant(other_zev)):
            deliver(
                participant=participant, kind=DocumentKind.CREDIT_NOTE, title="CN-1", body=PDF, document_number="CN-1"
            )
        self.assertEqual(self.documents().count(), 2)

    def test_the_database_refuses_a_second_row_for_one_number(self):
        deliver(
            participant=self.participant, kind=DocumentKind.CREDIT_NOTE, title="CN-1", body=PDF, document_number="CN-1"
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            DeliveredDocument.objects.create(
                participant=self.participant, kind=DocumentKind.CREDIT_NOTE, title="CN-1", document_number="CN-1",
                file="inbox/documents/x/y.pdf",
            )


class BackfillTests(CreditNoteBase):
    def rendered(self, **kwargs):
        credit = self.credit(**kwargs)
        credit.pdf_file.save("credit_old.pdf", ContentFile(PDF + b"old"), save=True)
        return credit

    def test_delivers_the_stored_pdf_dated_by_issue(self):
        credit = self.rendered()

        report = backfill_credits()

        self.assertEqual((report.delivered, report.clean), (1, True))
        document = self.documents().get()
        self.assertEqual(document.delivered_at, credit.created_at)
        with document.open_file() as handle:
            self.assertEqual(handle.read(), PDF + b"old")

    def test_skips_and_reports_a_credit_note_without_a_document(self):
        no_pdf = self.credit()
        gone = self.rendered()
        default_storage.delete(gone.pdf_file.name)

        report = backfill_credits()

        self.assertCountEqual(
            report.missing, [(no_pdf.credit_number, NO_DOCUMENT), (gone.credit_number, FILE_MISSING)]
        )
        self.assertFalse(report.clean)
        self.assertFalse(self.documents().exists())

    def test_is_idempotent_and_dry_run_writes_nothing(self):
        self.rendered()
        self.assertEqual(backfill_credits(dry_run=True).delivered, 1)
        self.assertFalse(self.documents().exists())

        backfill_credits()
        again = backfill_credits()

        self.assertEqual((again.delivered, again.already_delivered), (0, 1))
        self.assertEqual(self.documents().count(), 1)

    def test_a_note_delivered_by_the_render_is_not_delivered_twice(self):
        credit = self.credit()
        generate_credit_pdf_task(str(credit.pk))

        report = backfill_credits()

        self.assertEqual((report.delivered, report.already_delivered), (0, 1))

    def test_zev_filter_limits_the_run(self):
        other_zev = make_zev(make_user("inbox_cn_other2", UserRole.USER), "Other")
        mine = self.rendered()
        other = self.credit(participant=make_participant(other_zev), zev=other_zev)
        other.pdf_file.save("credit_other.pdf", ContentFile(PDF), save=True)

        backfill_credits(zev=self.zev)

        self.assertEqual(list(self.documents().values_list("document_number", flat=True)), [mine.credit_number])

    def test_the_command_and_the_task_cover_credit_notes(self):
        self.rendered()
        out = StringIO()
        call_command("openzev_inbox_backfill", "--dry-run", stdout=out)
        self.assertIn("Would deliver 1 credit note(s)", out.getvalue())

        result = inbox_backfill_task()

        self.assertEqual(result["credit_notes"]["delivered"], 1)
        self.assertEqual(result["delivered"], 1)
