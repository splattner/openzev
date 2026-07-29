from accounts.models import AppSettings, UserRole
from datetime import date
from django.core import mail
from django.core.files.base import ContentFile
from django.test import TestCase
from django.test.utils import override_settings

from invoices.models import InvoiceStatus
from invoices.tasks import send_invoice_email_task
from invoices.test_helpers import make_invoice, make_participant, make_user, make_zev


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
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

    def test_email_includes_due_date_variable(self):
        owner = make_user("email_due_owner", UserRole.ZEV_OWNER)
        zev = make_zev(owner, "Due Date ZEV")
        zev.email_body_template = "Due: {due_date}"
        zev.save(update_fields=["email_body_template"])

        participant = make_participant(zev, first="Due", last="Date")
        invoice = make_invoice(zev, participant, InvoiceStatus.APPROVED)
        invoice.due_date = date(2026, 2, 15)
        invoice.save(update_fields=["due_date"])
        invoice.pdf_file.save("invoice_test.pdf", ContentFile(b"PDF"), save=True)

        send_invoice_email_task.run(str(invoice.pk), "recipient@example.com")

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Due: 15.02.2026", mail.outbox[0].body)

    def test_email_due_date_empty_when_not_set(self):
        owner = make_user("email_due_none_owner", UserRole.ZEV_OWNER)
        zev = make_zev(owner, "No Due ZEV")
        zev.email_body_template = "Due: [{due_date}]"
        zev.save(update_fields=["email_body_template"])

        participant = make_participant(zev, first="No", last="Due")
        invoice = make_invoice(zev, participant, InvoiceStatus.APPROVED)
        invoice.due_date = None
        invoice.save(update_fields=["due_date"])
        invoice.pdf_file.save("invoice_test.pdf", ContentFile(b"PDF"), save=True)

        send_invoice_email_task.run(str(invoice.pk), "recipient@example.com")

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Due: []", mail.outbox[0].body)
