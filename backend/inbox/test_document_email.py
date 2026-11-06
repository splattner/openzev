"""The optional email for a delivered document (SPEC-2026-11-participant-document-inbox §6.5)."""

from unittest import mock

from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import UserRole
from audit.models import AuditEvent, AuditEventStatus
from inbox.models import DeliveredDocument, DocumentKind
from inbox.services import deliver, withdraw
from inbox.tasks import send_document_email_task
from inbox.test_helpers import make_contract_issue
from invoices.models import EmailTemplate
from invoices.test_helpers import make_participant, make_zev
from testing.helpers import authenticate, make_user

UPLOAD = "/api/v1/inbox/documents/"
TARIFFS = "/api/v1/inbox/issue/tariff-overview/"
CONTRACT = "/api/v1/inbox/documents/deliver-contract/"


class DocumentEmailBase(TestCase):
    def setUp(self):
        self.owner = make_user("inbox_em_owner", UserRole.USER)
        self.zev = make_zev(self.owner)
        self.account = make_user("inbox_em_account", UserRole.USER)
        self.anna = make_participant(self.zev, user=self.account, first="Anna", last="A")
        self.ben = make_participant(self.zev, first="Ben", last="B")
        self.client = APIClient()
        authenticate(self.client, self.owner)

    def upload(self, **extra):
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(
                UPLOAD,
                {"zev": str(self.zev.pk), "title": "House rules", "file": SimpleUploadedFile("r.pdf", b"%PDF-1.7\n"), **extra},
                format="multipart",
            )

    def emailed_audit(self):
        return AuditEvent.objects.filter(action_type="inbox.document.emailed")


class NotifyFlagTests(DocumentEmailBase):
    def test_nothing_is_emailed_unless_asked(self):
        response = self.upload()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(mail.outbox, [])
        body = response.json()
        self.assertEqual((body["emailed"], body["without_email"]), (0, 0))

    def test_notify_emails_every_recipient_with_an_address(self):
        response = self.upload(notify="true")

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual((body["delivered"], body["emailed"], body["without_email"]), (2, 2, 0))
        self.assertEqual(sorted(m.to[0] for m in mail.outbox), ["anna@example.com", "ben@example.com"])

    def test_a_participant_without_an_address_is_counted_not_emailed(self):
        self.ben.party.email = ""
        self.ben.party.save()

        body = self.upload(notify="true").json()

        self.assertEqual((body["emailed"], body["without_email"]), (1, 1))
        self.assertEqual([m.to[0] for m in mail.outbox], ["anna@example.com"])

    def test_the_email_links_to_the_inbox_and_carries_no_attachment(self):
        self.upload(notify="true", audience="selected", participant_ids=[str(self.anna.pk)])

        message = mail.outbox[0]
        self.assertIn("House rules", message.subject)
        self.assertIn("/me/documents", message.body)
        self.assertEqual(message.attachments, [])

    def test_the_default_text_follows_the_zevs_language(self):
        self.zev.invoice_language = "de"
        self.zev.save()

        self.upload(notify="true", audience="selected", participant_ids=[str(self.anna.pk)])

        self.assertIn("Neues Dokument", mail.outbox[0].subject)
        self.assertIn("Guten Tag Anna", mail.outbox[0].body)

    def test_a_saved_template_replaces_the_default_for_every_language(self):
        EmailTemplate.objects.create(
            template_key="document_delivered", subject="{title} for {participant_name}", body="Read it: {inbox_url}"
        )

        self.upload(notify="true", audience="selected", participant_ids=[str(self.anna.pk)])

        self.assertEqual(mail.outbox[0].subject, "House rules for Anna A")
        self.assertTrue(mail.outbox[0].body.startswith("Read it: http"))

    def test_a_broken_saved_template_falls_back_to_the_default(self):
        EmailTemplate.objects.create(template_key="document_delivered", subject="{nope}", body="{nope}")

        self.upload(notify="true", audience="selected", participant_ids=[str(self.anna.pk)])

        self.assertIn("House rules", mail.outbox[0].subject)

    def test_the_tariff_overview_emails_too(self):
        with self.captureOnCommitCallbacks(execute=True):
            body = self.client.post(TARIFFS, {"zev": str(self.zev.pk), "notify": True}, format="json").json()
        self.assertEqual(body["emailed"], 2)
        self.assertEqual(len(mail.outbox), 2)

    def test_a_contract_delivered_twice_is_emailed_once(self):
        issue = make_contract_issue(self.anna, self.owner)
        for _ in range(2):
            with self.captureOnCommitCallbacks(execute=True):
                self.client.post(CONTRACT, {"contract_issue": str(issue.pk), "notify": True}, format="json")
        self.assertEqual(len(mail.outbox), 1)

    def test_a_refused_delivery_emails_nobody(self):
        response = self.upload(notify="true", audience="selected", participant_ids=["00000000-0000-0000-0000-000000000000"])
        self.assertEqual(response.status_code, 400)
        self.assertEqual(mail.outbox, [])


class SendTaskTests(DocumentEmailBase):
    def document(self, **extra):
        document, _ = deliver(
            participant=self.anna, kind=DocumentKind.OPERATOR, title="Notice", body=b"%PDF-1.7\n",
            file_name="n.pdf", delivered_by=self.owner, **extra,
        )
        return document

    def test_a_send_is_audited_without_the_address(self):
        document = self.document()

        self.assertTrue(send_document_email_task.run(str(document.pk)))

        event = self.emailed_audit().get()
        self.assertEqual((event.status, event.target_id), (AuditEventStatus.SUCCESS, str(document.pk)))
        self.assertNotIn("anna@example.com", str(event.metadata_json) + event.summary)

    def test_a_withdrawn_document_is_not_emailed(self):
        document = self.document()
        withdraw(document, self.owner)

        self.assertFalse(send_document_email_task.run(str(document.pk)))
        self.assertEqual(mail.outbox, [])

    def test_an_unknown_document_is_ignored(self):
        self.assertFalse(send_document_email_task.run("00000000-0000-0000-0000-000000000000"))

    def test_an_invoice_is_never_emailed_from_here(self):
        from inbox.emails import queue_document_emails

        document = self.document()
        DeliveredDocument.objects.filter(pk=document.pk).update(kind=DocumentKind.INVOICE)
        document.refresh_from_db()
        self.assertEqual(queue_document_emails([document]), (0, 0))

    def test_a_failing_send_retries_and_audits_once_when_it_gives_up(self):
        document = self.document()
        with mock.patch("inbox.emails.EmailMessage.send", side_effect=OSError("550 anna@example.com rejected")):
            with mock.patch.object(send_document_email_task, "retry", side_effect=RuntimeError("retried")) as retry:
                with self.assertRaises(RuntimeError):
                    send_document_email_task.run(str(document.pk))
                retry.assert_called_once()
                self.assertEqual(self.emailed_audit().count(), 0)

                with mock.patch.object(type(send_document_email_task.request), "retries", 3, create=True):
                    self.assertFalse(send_document_email_task.run(str(document.pk)))

        event = self.emailed_audit().get()
        self.assertEqual(event.status, AuditEventStatus.FAILED)
        self.assertEqual(event.metadata_json["error"], "OSError")
        self.assertNotIn("anna@example.com", str(event.metadata_json) + event.summary)
