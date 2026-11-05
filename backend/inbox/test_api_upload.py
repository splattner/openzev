"""Operator documents: upload, audience, withdrawal (SPEC-2026-11-participant-document-inbox §5.2)."""

from datetime import date, timedelta

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import UserRole
from audit.models import AuditEvent
from inbox.models import DeliveredDocument, DocumentKind
from inbox.test_helpers import PDF, deliver_operator_document
from invoices.test_helpers import make_participant, make_zev
from testing.helpers import authenticate, make_user
from zev.models import Participant

DOCS = "/api/v1/inbox/documents/"


def upload(content=PDF, name="rules.pdf", content_type="application/pdf"):
    return SimpleUploadedFile(name, content, content_type=content_type)


class UploadTests(TestCase):
    def setUp(self):
        self.owner = make_user("inbox_up_owner", UserRole.USER)
        self.zev = make_zev(self.owner)
        self.account = make_user("inbox_up_account", UserRole.USER)
        self.anna = make_participant(self.zev, user=self.account, first="Anna", last="A")
        self.ben = make_participant(self.zev, first="Ben", last="B")
        self.client = APIClient()
        authenticate(self.client, self.owner)

    def post(self, *, user=None, **fields):
        client = self.client
        if user is not None:
            client = APIClient()
            authenticate(client, user)
        body = {"zev": str(self.zev.pk), "title": "House rules", "file": upload(), **fields}
        return client.post(DOCS, body, format="multipart")

    def test_upload_all_creates_a_row_per_current_participant(self):
        Participant.objects.create(
            zev=self.zev, first_name="Old", last_name="Gone", email="old@example.com",
            valid_from=date(2020, 1, 1), valid_to=timezone.localdate() - timedelta(days=30),
        )

        response = self.post()

        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual(body["delivered"], 2)
        rows = DeliveredDocument.objects.filter(kind=DocumentKind.OPERATOR)
        self.assertEqual({row.participant_id for row in rows}, {self.anna.pk, self.ben.pk})
        # One stored file backs every row, and the batch ties them together.
        self.assertEqual(len({row.file.name for row in rows}), 1)
        self.assertEqual({str(row.batch_id) for row in rows}, {body["batch_id"]})
        self.assertEqual({row.delivered_by_id for row in rows}, {self.owner.pk})
        self.assertEqual(rows[0].title, "House rules")

    def test_upload_selected_delivers_only_to_the_chosen(self):
        response = self.post(audience="selected", participant_ids=[str(self.ben.pk)])

        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            list(DeliveredDocument.objects.values_list("participant_id", flat=True)), [self.ben.pk]
        )

    def test_upload_selected_rejects_participant_of_other_zev(self):
        other_zev = make_zev(self.owner, "Other")
        stranger = make_participant(other_zev, first="Eve", last="E")

        response = self.post(audience="selected", participant_ids=[str(stranger.pk)])

        self.assertEqual(response.status_code, 400)
        self.assertIn("participant_ids", response.json())
        self.assertFalse(DeliveredDocument.objects.exists())

    def test_selected_without_participants_is_a_field_error(self):
        response = self.post(audience="selected")

        self.assertEqual(response.status_code, 400)
        self.assertIn("participant_ids", response.json())

    def test_upload_rejects_non_pdf_magic_bytes(self):
        response = self.post(file=upload(b"MZ\x90\x00 not a pdf", "evil.pdf"))

        self.assertEqual(response.status_code, 400)
        self.assertIn("file", response.json())
        self.assertFalse(DeliveredDocument.objects.exists())

    @override_settings(INBOX_MAX_UPLOAD_BYTES=64)
    def test_upload_rejects_oversize(self):
        response = self.post(file=upload(PDF + b"x" * 100))

        self.assertEqual(response.status_code, 400)
        self.assertIn("file", response.json())

    def test_upload_rejects_empty(self):
        response = self.post(file=upload(b""))

        self.assertEqual(response.status_code, 400)
        self.assertIn("file", response.json())

    def test_upload_ignores_client_content_type(self):
        response = self.post(file=upload(PDF, "../../evil.html", content_type="text/html"))

        self.assertEqual(response.status_code, 201)
        row = DeliveredDocument.objects.first()
        self.assertEqual(row.content_type, "application/pdf")
        self.assertNotIn("..", row.file_name)
        self.assertNotIn("/", row.file_name)
        self.assertTrue(row.file.name.startswith(f"inbox/documents/{self.zev.pk}/"))

    def test_upload_refused_for_disabled_zev(self):
        self.zev.disabled_at = timezone.now()
        self.zev.save(update_fields=["disabled_at"])

        self.assertEqual(self.post().status_code, 400)
        self.assertEqual(self.post(user=make_user("inbox_up_admin", UserRole.ADMIN)).status_code, 201)

    def test_later_participant_gets_no_backlog(self):
        self.post()
        late = make_participant(self.zev, first="Late", last="Comer")

        self.assertFalse(DeliveredDocument.objects.filter(participant=late).exists())

    def test_response_counts_recipients_without_account(self):
        body = self.post().json()

        self.assertEqual((body["delivered"], body["without_account"]), (2, 1))
        self.assertEqual(len(body["documents"]), 2)

    def test_the_participant_downloads_exactly_what_was_uploaded(self):
        self.post()
        document = DeliveredDocument.objects.get(participant=self.anna)
        client = APIClient()
        authenticate(client, self.account)

        response = client.get(f"{DOCS}{document.pk}/file/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), PDF)
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertIn("attachment", response["Content-Disposition"])

    def test_only_a_manager_of_the_zev_may_upload(self):
        stranger = make_user("inbox_up_stranger", UserRole.USER)
        make_zev(stranger, "Elsewhere")

        self.assertEqual(self.post(user=stranger).status_code, 404)
        self.assertEqual(self.post(user=self.account).status_code, 404)
        self.assertFalse(DeliveredDocument.objects.exists())

    def test_anonymous_is_refused(self):
        response = APIClient().post(DOCS, {"zev": str(self.zev.pk), "title": "x", "file": upload()}, format="multipart")

        self.assertEqual(response.status_code, 401)

    def test_a_failed_batch_leaves_no_file_and_no_rows(self):
        before = set(default_storage.listdir(f"inbox/documents/{self.zev.pk}")[1]) if default_storage.exists(f"inbox/documents/{self.zev.pk}") else set()
        from unittest import mock

        with mock.patch("inbox.views.deliver", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self.post()

        self.assertFalse(DeliveredDocument.objects.exists())
        after = set(default_storage.listdir(f"inbox/documents/{self.zev.pk}")[1]) if default_storage.exists(f"inbox/documents/{self.zev.pk}") else set()
        self.assertEqual(after, before)

    def test_audit_event_per_recipient(self):
        self.post()

        self.assertEqual(AuditEvent.objects.filter(action_type="inbox.document.delivered").count(), 2)


class WithdrawTests(TestCase):
    def setUp(self):
        self.owner = make_user("inbox_wd_owner", UserRole.USER)
        self.zev = make_zev(self.owner)
        self.account = make_user("inbox_wd_account", UserRole.USER)
        self.participant = make_participant(self.zev, user=self.account)
        self.document = deliver_operator_document(self.participant)
        self.client = APIClient()
        authenticate(self.client, self.owner)

    def url(self, document=None):
        return f"{DOCS}{(document or self.document).pk}/withdraw/"

    def test_manager_withdraws_an_operator_document_and_keeps_the_file(self):
        response = self.client.post(self.url())

        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.json()["withdrawn_at"])
        self.document.refresh_from_db()
        self.assertEqual(self.document.withdrawn_by, self.owner)
        self.assertTrue(default_storage.exists(self.document.file.name))

    def test_a_withdrawn_document_disappears_for_the_participant_only(self):
        self.client.post(self.url())
        participant = APIClient()
        authenticate(participant, self.account)

        self.assertEqual(participant.get(f"{DOCS}{self.document.pk}/").status_code, 404)
        self.assertEqual(participant.get(f"{DOCS}{self.document.pk}/file/").status_code, 404)
        listed = self.client.get(DOCS, {"include_withdrawn": "true"}).json()["results"]
        self.assertEqual([row["id"] for row in listed], [str(self.document.pk)])

    def test_withdrawing_twice_is_harmless(self):
        first = self.client.post(self.url()).json()["withdrawn_at"]
        second = self.client.post(self.url())

        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["withdrawn_at"], first)

    def test_a_document_that_is_not_an_operator_document_cannot_be_withdrawn(self):
        report = DeliveredDocument.objects.create(
            zev=self.zev, participant=self.participant, kind=DocumentKind.TARIFF_OVERVIEW, title="T",
            file=default_storage.save("inbox/documents/x.pdf", ContentFile(PDF)), sha256="a" * 64,
        )

        response = self.client.post(self.url(report))

        self.assertEqual(response.status_code, 400)
        report.refresh_from_db()
        self.assertIsNone(report.withdrawn_at)

    def test_participant_viewer_and_stranger_cannot_withdraw(self):
        from zev.models import ZevAccessGrant, ZevAccessRole

        viewer = make_user("inbox_wd_viewer", UserRole.USER)
        ZevAccessGrant.objects.create(zev=self.zev, user=viewer, role=ZevAccessRole.VIEWER)
        stranger = make_user("inbox_wd_stranger", UserRole.USER)
        make_zev(stranger, "Elsewhere")
        for user in (self.account, viewer, stranger):
            client = APIClient()
            authenticate(client, user)
            self.assertEqual(client.post(self.url()).status_code, 404, user.username)

        self.document.refresh_from_db()
        self.assertIsNone(self.document.withdrawn_at)

    def test_withdrawal_is_audited(self):
        self.client.post(self.url())

        self.assertTrue(AuditEvent.objects.filter(action_type="inbox.document.withdrawn").exists())
