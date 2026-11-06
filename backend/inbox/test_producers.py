from unittest import mock

from django.core import mail
from django.core.files.base import ContentFile
from django.test import TestCase
from django.test.utils import override_settings
from rest_framework.test import APIClient

from accounts.models import UserRole
from audit.models import AuditEvent
from inbox.models import DeliveredDocument, DocumentKind
from inbox.test_helpers import PDF
from invoices.models import InvoiceStatus
from invoices.tasks import send_invoice_email_task
from invoices.test_helpers import make_invoice, make_participant, make_zev
from invoices.workflow import cancel_invoice, mark_invoice_sent, record_email_delivery
from testing.helpers import authenticate, make_user


def _approved_invoice(zev, participant, body=PDF + b"issued"):
    invoice = make_invoice(zev, participant, InvoiceStatus.APPROVED)
    invoice.pdf_file.save("invoice_x.pdf", ContentFile(body), save=True)
    return invoice


def _bytes(document):
    with document.open_file() as handle:
        return handle.read()


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class EmailDeliveryTests(TestCase):
    def setUp(self):
        self.owner = make_user("inbox_prod_owner", UserRole.USER)
        self.zev = make_zev(self.owner)
        self.participant = make_participant(self.zev)

    def _send(self, invoice):
        send_invoice_email_task.run(str(invoice.pk), "recipient@example.com")

    def test_email_delivery_delivers_attachment_bytes(self):
        invoice = _approved_invoice(self.zev, self.participant)
        self._send(invoice)
        invoice.refresh_from_db()

        document = DeliveredDocument.objects.get(invoice=invoice)
        self.assertEqual(document.kind, DocumentKind.INVOICE)
        self.assertEqual(document.participant_id, self.participant.pk)
        self.assertEqual(document.document_number, invoice.invoice_number)
        self.assertEqual(document.file_name, f"invoice_{invoice.invoice_number}.pdf")
        self.assertEqual(document.delivered_at, invoice.sent_at)
        self.assertEqual((document.period_start, document.period_end), (invoice.period_start, invoice.period_end))

    def test_stored_bytes_equal_email_attachment(self):
        invoice = _approved_invoice(self.zev, self.participant)
        self._send(invoice)

        attachment = mail.outbox[0].attachments[0][1]
        self.assertEqual(_bytes(DeliveredDocument.objects.get(invoice=invoice)), attachment)

    def test_resent_email_does_not_add_a_row(self):
        invoice = _approved_invoice(self.zev, self.participant)
        self._send(invoice)
        first = DeliveredDocument.objects.get(invoice=invoice)
        self._send(invoice)

        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(DeliveredDocument.objects.filter(invoice=invoice).count(), 1)
        self.assertEqual(DeliveredDocument.objects.get(invoice=invoice).pk, first.pk)

    def test_a_later_render_does_not_change_the_delivered_file(self):
        """``generate-pdf`` and the next email re-render ``pdf_file``; the inbox keeps what was sent."""
        invoice = _approved_invoice(self.zev, self.participant, body=PDF + b"first")
        self._send(invoice)
        invoice.refresh_from_db()
        invoice.pdf_file.save("invoice_x.pdf", ContentFile(PDF + b"re-rendered"), save=True)

        self.assertEqual(_bytes(DeliveredDocument.objects.get(invoice=invoice)), PDF + b"first")

    def test_a_failed_delivery_does_not_break_recording_the_email(self):
        invoice = _approved_invoice(self.zev, self.participant)
        with mock.patch("inbox.producers.deliver_invoice_document", side_effect=RuntimeError("storage down")):
            record_email_delivery(invoice, invoice.updated_at, document=PDF)
        invoice.refresh_from_db()

        self.assertEqual(invoice.status, InvoiceStatus.SENT)
        self.assertIsNotNone(invoice.sent_at)
        self.assertFalse(DeliveredDocument.objects.exists())
        failure = AuditEvent.objects.get(action_type="inbox.document.delivered", status="failed")
        self.assertEqual(failure.target_id, str(invoice.pk))
        self.assertIn("storage down", failure.summary)


class MarkSentTests(TestCase):
    def setUp(self):
        self.owner = make_user("inbox_sent_owner", UserRole.USER)
        self.zev = make_zev(self.owner)
        self.participant = make_participant(self.zev)

    def test_mark_sent_delivers_stored_pdf(self):
        invoice = _approved_invoice(self.zev, self.participant)
        mark_invoice_sent(invoice)

        document = DeliveredDocument.objects.get(invoice=invoice)
        self.assertEqual(_bytes(document), PDF + b"issued")
        self.assertEqual(document.delivered_at, invoice.sent_at)

    def test_mark_sent_renders_missing_pdf(self):
        invoice = make_invoice(self.zev, self.participant, InvoiceStatus.APPROVED)
        self.assertFalse(invoice.pdf_file)

        with mock.patch("invoices.pdf.generate_pdf", return_value=PDF + b"rendered now") as renderer:
            mark_invoice_sent(invoice)

        renderer.assert_called_once()
        self.assertEqual(_bytes(DeliveredDocument.objects.get(invoice=invoice)), PDF + b"rendered now")
        # The invoice's own PDF state is untouched.
        invoice.refresh_from_db()
        self.assertFalse(invoice.pdf_file)

    def test_mark_sent_survives_render_failure(self):
        invoice = make_invoice(self.zev, self.participant, InvoiceStatus.APPROVED)
        with mock.patch("invoices.pdf.generate_pdf", side_effect=RuntimeError("renderer crashed")):
            mark_invoice_sent(invoice)
        invoice.refresh_from_db()

        self.assertEqual(invoice.status, InvoiceStatus.SENT)
        self.assertFalse(DeliveredDocument.objects.exists())
        failure = AuditEvent.objects.get(action_type="inbox.document.delivered", status="failed")
        self.assertIn("renderer crashed", failure.summary)

    def test_a_sent_invoice_that_is_cancelled_stays_in_the_inbox_marked_cancelled(self):
        account = make_user("inbox_sent_participant", UserRole.USER)
        participant = make_participant(self.zev, user=account, first="Linked", last="Person")
        invoice = _approved_invoice(self.zev, participant)
        mark_invoice_sent(invoice)
        cancel_invoice(invoice)

        client = APIClient()
        authenticate(client, account)
        response = client.get("/api/v1/inbox/documents/")

        self.assertEqual(response.status_code, 200)
        [row] = response.json()["results"]
        self.assertEqual(row["invoice_status"], InvoiceStatus.CANCELLED)
        self.assertEqual(row["document_number"], invoice.invoice_number)
