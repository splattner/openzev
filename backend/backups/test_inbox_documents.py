"""Delivered documents in backups and per-ZEV restore (SPEC-2026-11-participant-document-inbox §6.4).

Kept apart from the shared ``build_world`` fixture: adding rows there would shift
counts that unrelated backup tests pin.
"""

import io
import zipfile

from django.core.files.storage import default_storage
from django.test import TestCase

from backups import restore_zev
from backups.fixtures import build_world
from backups.test_archive import build, read_jsonl
from backups.test_restore_zev import restore_from
from inbox.models import DeliveredDocument, DocumentKind
from inbox.services import deliver
from zev.models import Participant

DELIVERED_BYTES = b"%PDF-1.4 delivered operator document \x00\xfe"


class DeliveredDocumentBackupTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.world = build_world()
        cls.alpha_id = cls.world.alpha.pk
        alice = Participant.objects.get(zev_id=cls.alpha_id, party__first_name="Alice")
        contract = alice.contract_issues.get()
        cls.operator_doc, _ = deliver(
            participant=alice, kind=DocumentKind.OPERATOR, title="ALPHA-RULES", body=DELIVERED_BYTES,
            delivered_by=cls.world.owner,
        )
        cls.contract_doc, _ = deliver(
            participant=alice, kind=DocumentKind.CONTRACT, title="C-ALPHA-1", contract_issue=contract,
            delivered_by=cls.world.owner,
        )
        cls.raw, cls.manifest = build()

    def test_rows_and_files_travel_and_contracts_go_by_reference(self):
        rows = read_jsonl(self.raw, f"zevs/{self.alpha_id}/delivered_documents.jsonl")
        self.assertEqual(sorted(r["fields"]["kind"] for r in rows), ["contract", "operator"])
        contract = next(r for r in rows if r["fields"]["kind"] == "contract")
        self.assertFalse(contract["fields"]["file"])
        with zipfile.ZipFile(io.BytesIO(self.raw)) as zf:
            member = f"zevs/{self.alpha_id}/media/{self.operator_doc.file.name}"
            self.assertEqual(zf.read(member), DELIVERED_BYTES)

    def test_another_zev_does_not_carry_the_documents(self):
        rows = read_jsonl(self.raw, f"zevs/{self.world.beta.pk}/delivered_documents.jsonl")
        self.assertEqual(rows, [])

    def test_restoring_brings_documents_back_with_their_bytes(self):
        DeliveredDocument.objects.filter(zev_id=self.alpha_id).delete()
        default_storage.delete(self.operator_doc.file.name)
        restore_from(self.raw, self.alpha_id)
        document = DeliveredDocument.objects.get(zev_id=self.alpha_id, kind=DocumentKind.OPERATOR)
        with default_storage.open(document.file.name, "rb") as handle:
            self.assertEqual(handle.read(), DELIVERED_BYTES)
        contract = DeliveredDocument.objects.get(zev_id=self.alpha_id, kind=DocumentKind.CONTRACT)
        self.assertEqual(contract.contract_issue.document_number, "C-ALPHA-1")

    def test_a_document_the_restore_would_delete_needs_force(self):
        alice = Participant.objects.get(zev_id=self.alpha_id, party__first_name="Alice")
        deliver(participant=alice, kind=DocumentKind.OPERATOR, title="LATER-LETTER", body=b"%PDF-later")
        with self.assertRaises(restore_zev.RestoreRefused) as caught:
            restore_from(self.raw, self.alpha_id)
        kinds = [c["kind"] for c in caught.exception.plan["conflicts"]]
        self.assertEqual(kinds, ["delivered_document_deleted"])
        self.assertTrue(DeliveredDocument.objects.filter(title="LATER-LETTER").exists())
        restore_from(self.raw, self.alpha_id, force=True)
        self.assertFalse(DeliveredDocument.objects.filter(title="LATER-LETTER").exists())
        self.assertEqual(DeliveredDocument.objects.filter(zev_id=self.alpha_id).count(), 2)
