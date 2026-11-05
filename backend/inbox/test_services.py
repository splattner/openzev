from datetime import date
from unittest import mock

from django.core.files.storage import default_storage
from django.test import TestCase

from accounts.models import UserRole
from audit.models import AuditEvent
from inbox import services
from inbox.models import DeliveredDocument, DocumentKind
from inbox.test_helpers import PDF, deliver_operator_document, make_contract_issue
from invoices.test_helpers import make_invoice, make_participant, make_zev
from testing.helpers import make_user

YEAR = (date(2026, 1, 1), date(2026, 12, 31))


class DeliverTests(TestCase):
    def setUp(self):
        self.owner = make_user("inbox_svc_owner", UserRole.USER)
        self.zev = make_zev(self.owner)
        self.participant = make_participant(self.zev)

    def test_deliver_stores_bytes_and_sha256(self):
        import hashlib

        document = deliver_operator_document(self.participant)
        self.assertEqual(document.sha256, hashlib.sha256(PDF).hexdigest())
        self.assertEqual(document.size_bytes, len(PDF))
        with default_storage.open(document.file.name, "rb") as handle:
            self.assertEqual(handle.read(), PDF)
        self.assertTrue(document.file.name.startswith(f"inbox/documents/{self.zev.pk}/"))

    def test_deliver_is_idempotent_for_invoice(self):
        invoice = make_invoice(self.zev, self.participant)
        kwargs = dict(participant=self.participant, kind=DocumentKind.INVOICE, title=invoice.invoice_number,
                      body=PDF, invoice=invoice)
        first, created = services.deliver(**kwargs)
        second, created_again = services.deliver(**{**kwargs, "body": b"%PDF-other"})
        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(DeliveredDocument.objects.count(), 1)
        # The first delivery's bytes stand; the second wrote nothing.
        with default_storage.open(second.file.name, "rb") as handle:
            self.assertEqual(handle.read(), PDF)

    def test_deliver_contract_references_the_issue_without_a_copy(self):
        issue = make_contract_issue(self.participant, self.owner)
        document, created = services.deliver(
            participant=self.participant, kind=DocumentKind.CONTRACT, title=issue.document_number,
            contract_issue=issue, document_number=issue.document_number,
        )
        self.assertTrue(created)
        self.assertFalse(document.file)
        self.assertEqual(document.size_bytes, len(b"%PDF-contract"))
        again, created_again = services.deliver(
            participant=self.participant, kind=DocumentKind.CONTRACT, title=issue.document_number,
            contract_issue=issue,
        )
        self.assertFalse(created_again)
        self.assertEqual(again.pk, document.pk)

    def test_a_contract_with_a_body_or_an_other_kind_without_one_is_refused(self):
        issue = make_contract_issue(self.participant, self.owner)
        with self.assertRaises(ValueError):
            services.deliver(participant=self.participant, kind=DocumentKind.CONTRACT, title="c",
                             contract_issue=issue, body=PDF)
        with self.assertRaises(ValueError):
            services.deliver(participant=self.participant, kind=DocumentKind.OPERATOR, title="x")
        with self.assertRaises(ValueError):
            stored = services.store_file(self.zev, PDF)
            try:
                services.deliver(participant=self.participant, kind=DocumentKind.OPERATOR, title="x",
                                 body=PDF, stored=stored)
            finally:
                services.discard_file(stored.name)

    def test_deliver_removes_the_file_when_the_row_cannot_be_written(self):
        before = set(default_storage.listdir(f"inbox/documents/{self.zev.pk}")[1]) if default_storage.exists(
            f"inbox/documents/{self.zev.pk}") else set()
        with mock.patch.object(DeliveredDocument.objects, "create", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                deliver_operator_document(self.participant)
        after = set(default_storage.listdir(f"inbox/documents/{self.zev.pk}")[1]) if default_storage.exists(
            f"inbox/documents/{self.zev.pk}") else set()
        self.assertEqual(before, after)
        self.assertEqual(DeliveredDocument.objects.count(), 0)

    def test_redelivering_a_report_supersedes_the_earlier_one(self):
        kwargs = dict(participant=self.participant, kind=DocumentKind.ANNUAL_STATEMENT, title="Statement 2026",
                      period=YEAR)
        first, _ = services.deliver(body=PDF, **kwargs)
        second, created = services.deliver(body=b"%PDF-corrected", **kwargs)
        self.assertTrue(created)
        first.refresh_from_db()
        self.assertIsNotNone(first.superseded_at)
        self.assertEqual(first.superseded_by_id, second.pk)
        self.assertIsNone(second.superseded_at)
        self.assertFalse(first.is_current)
        self.assertTrue(second.is_current)

    def test_a_shared_stored_file_backs_several_rows_and_survives_deleting_one(self):
        other = make_participant(self.zev, first="Max", last="Muster")
        stored = services.store_file(self.zev, PDF, "rules.pdf")
        a, _ = services.deliver(participant=self.participant, kind=DocumentKind.OPERATOR, title="Rules", stored=stored)
        b, _ = services.deliver(participant=other, kind=DocumentKind.OPERATOR, title="Rules", stored=stored)
        self.assertEqual(a.file.name, b.file.name)
        self.assertEqual(a.file_name, "rules.pdf")
        a.delete()
        self.assertFalse(services.remove_file_if_unreferenced(b.file.name))
        self.assertTrue(default_storage.exists(b.file.name))
        b.delete()
        self.assertTrue(services.remove_file_if_unreferenced(stored.name))
        self.assertFalse(default_storage.exists(stored.name))

    def test_audit_event_written_per_delivery(self):
        document = deliver_operator_document(self.participant)
        event = AuditEvent.objects.get(action_type="inbox.document.delivered")
        self.assertEqual(event.target_id, str(document.pk))
        self.assertEqual(event.zev_id, self.zev.pk)
        self.assertEqual(event.metadata_json["kind"], "operator")


class SupersedeAndWithdrawTests(TestCase):
    def setUp(self):
        self.owner = make_user("inbox_sw_owner", UserRole.USER)
        self.zev = make_zev(self.owner)
        self.participant = make_participant(self.zev)

    def test_supersede_links_both_rows_and_is_idempotent(self):
        old = deliver_operator_document(self.participant, "Old")
        new = deliver_operator_document(self.participant, "New")
        services.supersede(old, new)
        old.refresh_from_db()
        self.assertEqual(old.superseded_by_id, new.pk)
        stamp = old.superseded_at
        services.supersede(old, deliver_operator_document(self.participant, "Newer"))
        old.refresh_from_db()
        self.assertEqual((old.superseded_by_id, old.superseded_at), (new.pk, stamp))
        self.assertEqual(AuditEvent.objects.filter(action_type="inbox.document.superseded").count(), 1)

    def test_a_document_cannot_supersede_itself(self):
        document = deliver_operator_document(self.participant)
        with self.assertRaises(ValueError):
            services.supersede(document, document)

    def test_withdraw_only_operator_documents(self):
        invoice = make_invoice(self.zev, self.participant)
        document, _ = services.deliver(participant=self.participant, kind=DocumentKind.INVOICE,
                                       title="I", body=PDF, invoice=invoice)
        with self.assertRaises(ValueError):
            services.withdraw(document, self.owner)

    def test_withdraw_hides_but_keeps_row_and_file_and_is_idempotent(self):
        document = deliver_operator_document(self.participant)
        services.withdraw(document, self.owner)
        stamp = document.withdrawn_at
        services.withdraw(document, self.owner)
        document.refresh_from_db()
        self.assertEqual(document.withdrawn_at, stamp)
        self.assertEqual(document.withdrawn_by_id, self.owner.pk)
        self.assertTrue(default_storage.exists(document.file.name))
        self.assertEqual(AuditEvent.objects.filter(action_type="inbox.document.withdrawn").count(), 1)
