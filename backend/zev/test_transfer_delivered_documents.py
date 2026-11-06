"""The ``delivered_documents`` transfer-archive section (format version 11).

The participant document inbox (ADR 0045) travels with its ZEV: rows as they
were (delivery time, supersession, withdrawal) and the exact bytes. No account
reference travels, and a contract arrives holding its own file because
``ContractIssue`` is not part of the archive.
"""
import hashlib
import io
import json
import zipfile
from datetime import date, datetime, timezone

from django.core.files.storage import default_storage
from django.test import TestCase

from accounts.models import UserRole
from inbox.models import DeliveredDocument, DocumentKind
from inbox.services import deliver, withdraw
from inbox.test_helpers import PDF, make_contract_issue
from invoices.models import ContractIssue, Invoice
from testing.helpers import make_user
from zev.transfer import ImportFailed, import_archive
from zev.transfer.export import delivered_document_member_name
from zev.transfer.schema import SECTION_DEPENDENCIES, SECTIONS

from .test_transfer import (
    as_format_version,
    build_populated_zev,
    export_and_clear,
    export_to_bytes,
    rewrite_archive,
)

SECTION_LIST = ["zev", "participants", "invoices", "delivered_documents"]


def _archive_json(raw, name):
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        return json.loads(archive.read(name))


def _stored_files():
    found = set()
    pending = ["inbox/documents"]
    while pending:
        directory = pending.pop()
        if not default_storage.exists(directory):
            continue
        folders, files = default_storage.listdir(directory)
        found.update(f"{directory}/{name}" for name in files)
        pending.extend(f"{directory}/{name}" for name in folders)
    return found


def _delete_issues(zev):
    DeliveredDocument.objects.filter(zev=zev, contract_issue__isnull=False).delete()
    ContractIssue.objects.filter(zev=zev).delete()


class SectionContractTests(TestCase):
    def test_the_section_depends_on_participants_only(self):
        self.assertIn("delivered_documents", SECTIONS)
        self.assertEqual(SECTION_DEPENDENCIES["delivered_documents"], ("participants",))

    def test_member_names_are_per_document_and_stay_in_the_directory(self):
        name = delivered_document_member_name("0b7d1c64-aaaa-bbbb-cccc-000000000001")
        self.assertEqual(name, "delivered_documents/0b7d1c64-aaaa-bbbb-cccc-000000000001.pdf")


class RoundTripTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user("dd_owner", UserRole.USER)
        cls.importer = make_user("dd_importer", UserRole.ADMIN)

    def _zev(self, prefix):
        zev = build_populated_zev(self.owner, name="Inbox ZEV", meter_prefix=prefix)
        return zev, zev.participants.get(party__first_name="Alice")

    def _import(self, raw, **kwargs):
        result = import_archive(io.BytesIO(raw), owner=self.importer, **kwargs)
        return result, DeliveredDocument.objects.filter(zev_id=result["zev_id"])

    def test_an_operator_document_arrives_with_its_bytes_and_history(self):
        zev, alice = self._zev("DDA")
        body = PDF + b"operator"
        document, _ = deliver(
            participant=alice, kind=DocumentKind.OPERATOR, title="House rules", body=body, file_name="rules.pdf",
            delivered_by=self.owner, delivered_at=datetime(2026, 3, 1, 9, 30, tzinfo=timezone.utc),
        )
        raw = export_and_clear(zev, SECTION_LIST)

        result, documents = self._import(raw)

        self.assertEqual(result["counts"]["delivered_documents"], 1)
        imported = documents.get()
        self.assertEqual(imported.title, "House rules")
        self.assertEqual(imported.kind, DocumentKind.OPERATOR)
        self.assertEqual(imported.delivered_at, datetime(2026, 3, 1, 9, 30, tzinfo=timezone.utc))
        self.assertEqual(imported.participant.first_name, "Alice")
        self.assertEqual(imported.file_name, "rules.pdf")
        self.assertEqual(imported.sha256, hashlib.sha256(body).hexdigest())
        self.assertEqual(imported.size_bytes, len(body))
        with imported.open_file() as handle:
            self.assertEqual(handle.read(), body)
        self.assertNotEqual(imported.file.name, document.file.name)

    def test_no_account_travels(self):
        zev, alice = self._zev("DDB")
        document, _ = deliver(
            participant=alice, kind=DocumentKind.OPERATOR, title="Notice", body=PDF, delivered_by=self.owner,
        )
        withdraw(document, self.owner)
        raw = export_and_clear(zev, SECTION_LIST)

        record = _archive_json(raw, "delivered_documents.json")[0]
        self.assertNotIn("delivered_by", record)
        self.assertNotIn("withdrawn_by", record)
        self.assertNotIn("batch_id", record)

        _, documents = self._import(raw)
        imported = documents.get()
        self.assertIsNone(imported.delivered_by)
        self.assertIsNone(imported.withdrawn_by)
        self.assertIsNotNone(imported.withdrawn_at)  # a withdrawn document stays withdrawn

    def test_a_superseded_chain_keeps_its_links(self):
        zev, alice = self._zev("DDC")
        first, _ = deliver(
            participant=alice, kind=DocumentKind.ANNUAL_STATEMENT, title="2025", body=PDF + b"1",
            period=(date(2025, 1, 1), date(2025, 12, 31)),
        )
        second, _ = deliver(
            participant=alice, kind=DocumentKind.ANNUAL_STATEMENT, title="2025", body=PDF + b"2",
            period=(date(2025, 1, 1), date(2025, 12, 31)),
        )
        raw = export_and_clear(zev, SECTION_LIST)

        _, documents = self._import(raw)

        self.assertEqual(documents.count(), 2)
        old = documents.exclude(superseded_at__isnull=True).get()
        current = documents.get(superseded_at__isnull=True)
        self.assertEqual(old.superseded_by_id, current.pk)
        with current.open_file() as handle:
            self.assertEqual(handle.read(), PDF + b"2")
        self.assertEqual((current.period_start, current.period_end), (date(2025, 1, 1), date(2025, 12, 31)))

    def test_a_contract_arrives_holding_its_own_file(self):
        zev, alice = self._zev("DDD")
        issue = make_contract_issue(alice, self.owner)
        deliver(participant=alice, kind=DocumentKind.CONTRACT, title="Contract", contract_issue=issue)
        raw = export_and_clear_with_issues(zev, SECTION_LIST)

        _, documents = self._import(raw)

        imported = documents.get()
        self.assertEqual(imported.kind, DocumentKind.CONTRACT)
        self.assertIsNone(imported.contract_issue)
        self.assertTrue(imported.file.name)
        with imported.open_file() as handle:
            self.assertEqual(handle.read(), b"%PDF-contract")

    def test_an_invoice_document_is_linked_to_its_imported_invoice(self):
        zev, alice = self._zev("DDE")
        invoice = Invoice.objects.get(zev=zev)
        deliver(participant=alice, kind=DocumentKind.INVOICE, title="Invoice", body=PDF + b"inv", invoice=invoice,
                document_number=invoice.invoice_number)
        raw = export_and_clear(zev, SECTION_LIST)

        result, documents = self._import(raw)

        imported = documents.get()
        self.assertEqual(imported.invoice.invoice_number, invoice.invoice_number)
        self.assertEqual(str(imported.invoice.zev_id), result["zev_id"])

    def test_without_the_invoices_section_the_document_keeps_its_bytes_and_no_link(self):
        zev, alice = self._zev("DDF")
        invoice = Invoice.objects.get(zev=zev)
        deliver(participant=alice, kind=DocumentKind.INVOICE, title="Invoice", body=PDF + b"inv", invoice=invoice)
        raw = export_and_clear(zev, ["participants", "delivered_documents"])

        _, documents = self._import(raw)

        imported = documents.get()
        self.assertIsNone(imported.invoice)
        with imported.open_file() as handle:
            self.assertEqual(handle.read(), PDF + b"inv")

    def test_a_document_whose_participant_was_removed_still_travels(self):
        zev, alice = self._zev("DDG")
        deliver(participant=alice, kind=DocumentKind.OPERATOR, title="Orphan", body=PDF)
        DeliveredDocument.objects.filter(zev=zev).update(participant=None)
        raw = export_and_clear(zev, SECTION_LIST)

        _, documents = self._import(raw)

        imported = documents.get()
        self.assertIsNone(imported.participant)
        self.assertEqual(imported.title, "Orphan")

    def test_the_section_can_be_left_out_of_an_import(self):
        zev, alice = self._zev("DDH")
        deliver(participant=alice, kind=DocumentKind.OPERATOR, title="Notice", body=PDF)
        raw = export_and_clear(zev, SECTION_LIST)

        result, documents = self._import(raw, sections=["zev", "participants"])

        self.assertEqual(documents.count(), 0)
        self.assertNotIn("delivered_documents", result["counts"])

    def test_the_default_export_carries_the_section(self):
        zev, alice = self._zev("DDI")
        deliver(participant=alice, kind=DocumentKind.OPERATOR, title="Notice", body=PDF)
        raw = export_to_bytes(zev)
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            manifest = json.loads(archive.read("manifest.json"))
        self.assertIn("delivered_documents", manifest["sections"])
        self.assertEqual(manifest["counts"]["delivered_documents"], 1)
        self.assertEqual(manifest["format_version"], 11)


def export_and_clear_with_issues(zev, sections):
    raw = export_to_bytes(zev, sections)
    _delete_issues(zev)
    from invoices.models import Credit, CreditApplication

    CreditApplication.objects.filter(credit__zev=zev).delete()
    Credit.objects.filter(zev=zev).delete()
    Invoice.objects.filter(zev=zev).delete()
    zev.delete()
    return raw


class OlderArchiveTests(TestCase):
    def test_a_version_10_archive_imports_with_an_empty_inbox(self):
        owner = make_user("dd_old_owner", UserRole.USER)
        importer = make_user("dd_old_importer", UserRole.ADMIN)
        zev = build_populated_zev(owner, name="Old", meter_prefix="DDO")
        raw = as_format_version(export_and_clear(zev, SECTION_LIST), 10)

        result = import_archive(io.BytesIO(raw), owner=importer)

        self.assertNotIn("delivered_documents", result["counts"])
        self.assertFalse(DeliveredDocument.objects.filter(zev_id=result["zev_id"]).exists())


class RejectedArchiveTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user("dd_bad_owner", UserRole.USER)
        cls.importer = make_user("dd_bad_importer", UserRole.ADMIN)

    def _raw(self, prefix, body=PDF + b"x"):
        zev = build_populated_zev(self.owner, name="Bad", meter_prefix=prefix)
        alice = zev.participants.get(party__first_name="Alice")
        document, _ = deliver(participant=alice, kind=DocumentKind.OPERATOR, title="Notice", body=body)
        raw = export_and_clear(zev, SECTION_LIST)
        return raw, str(document.pk)

    def _errors(self, raw):
        with self.assertRaises(ImportFailed) as ctx:
            import_archive(io.BytesIO(raw), owner=self.importer)
        return ctx.exception.errors

    def test_bytes_that_do_not_match_the_checksum_are_rejected(self):
        raw, document_id = self._raw("DDR1")
        tampered = rewrite_archive(raw, replace={delivered_document_member_name(document_id): PDF + b"changed"})

        errors = self._errors(tampered)

        self.assertEqual(errors[0]["section"], "delivered_documents")
        self.assertIn("sha256", errors[0]["errors"])

    def test_a_missing_member_is_rejected(self):
        raw, document_id = self._raw("DDR2")
        stripped = rewrite_archive(raw, drop=(delivered_document_member_name(document_id),))

        errors = self._errors(stripped)

        self.assertEqual(errors[0]["section"], "delivered_documents")

    def test_something_that_is_not_a_pdf_is_rejected(self):
        raw, document_id = self._raw("DDR3")
        records = _archive_json(raw, "delivered_documents.json")
        records[0].pop("sha256")
        swapped = rewrite_archive(
            raw,
            replace={
                delivered_document_member_name(document_id): b"<html>not a pdf</html>",
                "delivered_documents.json": records,
            },
        )

        errors = self._errors(swapped)

        self.assertIn("not a PDF", errors[0]["errors"]["__all__"][0])

    def test_an_unknown_kind_is_rejected(self):
        raw, _ = self._raw("DDR4")
        records = _archive_json(raw, "delivered_documents.json")
        records[0]["kind"] = "love_letter"

        errors = self._errors(rewrite_archive(raw, replace={"delivered_documents.json": records}))

        self.assertIn("kind", errors[0]["errors"])

    def test_a_participant_that_was_not_imported_is_rejected(self):
        raw, _ = self._raw("DDR5")
        records = _archive_json(raw, "delivered_documents.json")
        records[0]["participant_id"] = "00000000-0000-0000-0000-000000000000"

        errors = self._errors(rewrite_archive(raw, replace={"delivered_documents.json": records}))

        self.assertIn("participant_id", errors[0]["errors"])

    def test_a_count_that_disagrees_with_the_manifest_is_rejected(self):
        raw, _ = self._raw("DDR6")
        manifest = _archive_json(raw, "manifest.json")
        manifest["counts"]["delivered_documents"] = 5

        errors = self._errors(rewrite_archive(raw, replace={"manifest.json": manifest}))

        self.assertEqual(errors[0]["section"], "delivered_documents")

    def test_a_rejected_import_leaves_no_files_behind(self):
        """The rows roll back with the transaction; the files written for the
        valid documents must not stay behind."""
        raw, _ = self._raw("DDR7")
        records = _archive_json(raw, "delivered_documents.json")
        records.append({**records[0], "id": "11111111-1111-1111-1111-111111111111", "participant_id": "0" * 8 + "-0000-0000-0000-" + "0" * 12})
        before = _stored_files()

        self._errors(rewrite_archive(raw, replace={"delivered_documents.json": records}))

        self.assertEqual(_stored_files(), before)

    def test_a_row_that_fails_validation_discards_its_own_file(self):
        raw, _ = self._raw("DDR8")
        records = _archive_json(raw, "delivered_documents.json")
        records[0]["title"] = "x" * 500  # too long: fails after the file was written
        before = _stored_files()

        errors = self._errors(rewrite_archive(raw, replace={"delivered_documents.json": records}))

        self.assertIn("title", errors[0]["errors"])
        self.assertEqual(_stored_files(), before)
