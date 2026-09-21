"""Backup archive: shape, key preservation, coverage, verification, round trip.

The assertions that matter most are the negative ones. A backup that silently
drops a model, a column or a file is worse than no backup — it is trusted — so
the coverage tests here are what keep the archive honest as the schema grows.
"""

import base64
import datetime
import io
import json
import tempfile
import uuid
import zipfile

from django.apps import apps
from django.core import serializers
from django.core.files.storage import default_storage
from django.db import models, transaction
from django.test import SimpleTestCase, TestCase, override_settings

from accounts.models import EmailVerificationToken, User
from audit.models import AuditEvent
from backups import archive, crypto
from backups.fixtures import PDF_BYTES, build_world
from backups.registry import (
    EXCLUDED_MODELS,
    INSTANCE_SECTIONS,
    MEDIA_FIELDS,
    UNSCOPED_SECTIONS,
    ZEV_SECTIONS,
    backed_up_labels,
)
from invoices.models import ContractIssue, Invoice
from metering.models import ImportLog, MeterReading
from zev.models import Participant, Zev
from zev.test_transfer import rewrite_archive
from zev.transfer import build_archive as build_transfer_archive

KEY = "K" * 40


def build(scope="instance", zev=None, fingerprint=""):
    buffer = io.BytesIO()
    manifest = archive.build_archive(buffer, scope=scope, zev=zev, encryption_fingerprint=fingerprint)
    return buffer.getvalue(), manifest


def read_jsonl(raw: bytes, member: str) -> list[dict]:
    with zipfile.ZipFile(io.BytesIO(raw)) as zf, zf.open(member) as handle:
        return [json.loads(line) for line in io.TextIOWrapper(handle, encoding="utf-8") if line.strip()]


def all_text(raw: bytes) -> str:
    """Every member decoded, so a needle can be searched for anywhere in the archive."""
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        return "\n".join(zf.read(name).decode("utf-8", "replace") for name in zf.namelist())


class ArchiveShapeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.world = build_world()
        cls.raw, cls.manifest = build()

    def test_manifest_identifies_the_archive_as_an_instance_backup(self):
        self.assertEqual(self.manifest["kind"], "backup")
        self.assertEqual(self.manifest["format_version"], archive.FORMAT_VERSION)
        self.assertEqual(self.manifest["scope"], "instance")
        self.assertIsNone(self.manifest["zev_id"])
        self.assertIn("backups", self.manifest["migrations"])
        self.assertIn("zev", self.manifest["migrations"])

    def test_the_manifest_inside_the_zip_is_the_returned_manifest(self):
        with zipfile.ZipFile(io.BytesIO(self.raw)) as zf:
            self.assertEqual(json.loads(zf.read("manifest.json")), self.manifest)

    def test_every_instance_section_and_every_zev_is_present(self):
        with zipfile.ZipFile(io.BytesIO(self.raw)) as zf:
            names = set(zf.namelist())
        for name, _ in INSTANCE_SECTIONS:
            self.assertIn(f"instance/{name}.jsonl", names)
        for name, _ in UNSCOPED_SECTIONS:
            self.assertIn(f"instance/{name}.jsonl", names)
        for zev in (self.world.alpha, self.world.beta):
            for name, _ in ZEV_SECTIONS:
                self.assertIn(f"zevs/{zev.pk}/{name}.jsonl", names)
            self.assertIn(f"zevs/{zev.pk}/account_refs.json", names)

    def test_every_line_is_a_serialized_row(self):
        with zipfile.ZipFile(io.BytesIO(self.raw)) as zf:
            members = [n for n in zf.namelist() if n.endswith(".jsonl")]
        self.assertTrue(members)
        for member in members:
            for row in read_jsonl(self.raw, member):
                self.assertEqual(set(row), {"model", "pk", "fields"}, member)

    def test_primary_keys_are_preserved(self):
        """The property that separates a backup from a transfer archive."""
        alpha = self.world.alpha
        zev_rows = read_jsonl(self.raw, f"zevs/{alpha.pk}/zev.jsonl")
        self.assertEqual([row["pk"] for row in zev_rows], [str(alpha.pk)])

        participants = {row["pk"] for row in read_jsonl(self.raw, f"zevs/{alpha.pk}/participants.jsonl")
                        if row["model"] == "zev.participant"}
        self.assertEqual(participants, {str(p.pk) for p in Participant.objects.filter(zev=alpha)})

        readings = {row["pk"] for row in read_jsonl(self.raw, f"zevs/{alpha.pk}/readings.jsonl")}
        self.assertEqual(readings, {str(r.pk) for r in MeterReading.objects.filter(metering_point__zev=alpha)})

    def test_timestamps_keep_their_microseconds(self):
        """Django's own encoder trims to milliseconds; a restored row must equal the stored one."""
        zev_row = read_jsonl(self.raw, f"zevs/{self.world.alpha.pk}/zev.jsonl")[0]
        stored = Zev.objects.get(pk=self.world.alpha.pk)
        self.assertNotEqual(stored.created_at.microsecond % 1000, 0, "fixture needs sub-millisecond precision")
        self.assertEqual(datetime.datetime.fromisoformat(zev_row["fields"]["created_at"]), stored.created_at)

    def test_integer_keyed_instance_rows_keep_their_keys_too(self):
        users = {row["pk"] for row in read_jsonl(self.raw, "instance/accounts.jsonl") if row["model"] == "accounts.user"}
        self.assertEqual(users, set(User.objects.values_list("pk", flat=True)))

    def test_foreign_keys_are_written_as_the_real_referenced_key(self):
        alpha = self.world.alpha
        rows = read_jsonl(self.raw, f"zevs/{alpha.pk}/zev.jsonl")
        self.assertEqual(rows[0]["fields"]["owner"], self.world.owner.pk)

    def test_a_zev_only_contains_its_own_rows(self):
        alpha_text = "\n".join(
            read_member_text(self.raw, f"zevs/{self.world.alpha.pk}/{name}.jsonl") for name, _ in ZEV_SECTIONS
        )
        self.assertIn("ALPHA-CONS-1", alpha_text)
        self.assertNotIn("BETA-CONS-1", alpha_text)

    def test_invoice_pdfs_travel_as_media_members_with_their_exact_bytes(self):
        alpha = self.world.alpha
        invoice = Invoice.objects.get(zev=alpha)
        with zipfile.ZipFile(io.BytesIO(self.raw)) as zf:
            self.assertEqual(zf.read(f"zevs/{alpha.pk}/media/{invoice.pdf_file.name}"), PDF_BYTES)

    def test_a_pdf_is_filed_under_its_own_zev_not_the_neighbours(self):
        with zipfile.ZipFile(io.BytesIO(self.raw)) as zf:
            names = zf.namelist()
        beta_invoice = Invoice.objects.get(zev=self.world.beta)
        self.assertIn(f"zevs/{self.world.beta.pk}/media/{beta_invoice.pdf_file.name}", names)
        self.assertNotIn(f"zevs/{self.world.alpha.pk}/media/{beta_invoice.pdf_file.name}", names)

    def test_issued_contract_pdfs_travel_base64_encoded_inside_the_row(self):
        alpha = self.world.alpha
        rows = read_jsonl(self.raw, f"zevs/{alpha.pk}/contract_issues.jsonl")
        self.assertEqual(len(rows), 1)
        self.assertEqual(base64.b64decode(rows[0]["fields"]["pdf"]), b"%PDF-contract-bytes")

    def test_rows_that_outlive_their_zev_are_in_the_instance_scope_not_lost(self):
        contracts = read_jsonl(self.raw, "instance/unscoped_contract_issues.jsonl")
        self.assertEqual([r["fields"]["document_number"] for r in contracts], ["C-ORPHAN-1"])
        self.assertTrue(read_jsonl(self.raw, "instance/unscoped_audit_events.jsonl"))
        self.assertEqual(
            [r["fields"]["filename"] for r in read_jsonl(self.raw, "instance/unscoped_import_logs.jsonl")],
            ["unscoped.csv"],
        )
        # ...and not duplicated into a community.
        for zev in (self.world.alpha, self.world.beta):
            numbers = [r["fields"]["document_number"]
                       for r in read_jsonl(self.raw, f"zevs/{zev.pk}/contract_issues.jsonl")]
            self.assertNotIn("C-ORPHAN-1", numbers)

    def test_the_audit_trail_is_carried(self):
        events = read_jsonl(self.raw, f"zevs/{self.world.alpha.pk}/audit_events.jsonl")
        self.assertIn("invoice.sent", [e["fields"]["action_type"] for e in events])

    def test_account_refs_name_every_referenced_user_by_email(self):
        """What lets a per-ZEV restore relink accounts by natural key."""
        with zipfile.ZipFile(io.BytesIO(self.raw)) as zf:
            refs = json.loads(zf.read(f"zevs/{self.world.alpha.pk}/account_refs.json"))["users"]
        by_id = {u["id"]: u for u in refs}
        self.assertEqual(by_id[self.world.owner.pk]["email"], "bk_owner@example.com")
        self.assertEqual(by_id[self.world.member.pk]["username"], "bk_member")

    def test_credentials_travel_because_a_restore_needs_them(self):
        accounts = read_member_text(self.raw, "instance/accounts.jsonl")
        self.assertIn(User.objects.get(pk=self.world.member.pk).password, accounts)
        # Documented in ADR 0024: the client secret is a plaintext column, which is
        # exactly why an unencrypted archive must be warned about.
        self.assertIn("plaintext-client-secret", read_member_text(self.raw, "instance/oauth_providers.jsonl"))

    def test_many_to_many_relations_are_not_serialized(self):
        user_row = next(r for r in read_jsonl(self.raw, "instance/accounts.jsonl") if r["model"] == "accounts.user")
        self.assertNotIn("groups", user_row["fields"])
        self.assertNotIn("user_permissions", user_row["fields"])

    def test_no_row_of_an_excluded_model_is_written(self):
        EmailVerificationToken.objects.create(user=self.world.member, token=uuid.uuid4().hex)
        raw, _ = build()
        excluded = {label.lower() for label in EXCLUDED_MODELS}
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            members = [n for n in zf.namelist() if n.endswith(".jsonl")]
        written = {row["model"] for member in members for row in read_jsonl(raw, member)}
        self.assertEqual(written & excluded, set())
        self.assertNotIn("accounts.emailverificationtoken", written)

    def test_counts_match_the_rows_actually_written(self):
        for section, count in self.manifest["counts"].items():
            self.assertEqual(
                len(read_jsonl(self.raw, f"{section}.jsonl")), count, section,
            )
        self.assertEqual(
            self.manifest["counts"][f"zevs/{self.world.alpha.pk}/readings"],
            MeterReading.objects.filter(metering_point__zev=self.world.alpha).count(),
        )

    def test_per_zev_summary_reports_counts_and_media(self):
        entry = next(z for z in self.manifest["zevs"] if z["id"] == str(self.world.alpha.pk))
        self.assertEqual(entry["name"], "Alpha")
        self.assertEqual(entry["media"], {"files": 1, "bytes": len(PDF_BYTES), "missing": [], "unsafe": []})
        self.assertEqual(entry["counts"]["readings"], 3)

    def test_secret_key_material_never_enters_the_archive(self):
        with override_settings(MFA_ENCRYPTION_KEYS=["M" * 44], SECRET_KEY="S" * 60):
            raw, manifest = build()
        text = all_text(raw)
        self.assertNotIn("M" * 44, text)
        self.assertNotIn("S" * 60, text)
        self.assertEqual(manifest["secret_fingerprints"]["mfa_encryption_keys"], [crypto.key_fingerprint("M" * 44)])
        self.assertEqual(manifest["secret_fingerprints"]["secret_key"], crypto.key_fingerprint("S" * 60))

    def test_the_manifest_records_the_encryption_fingerprint_it_was_told(self):
        _, manifest = build(fingerprint="abcdef0123456789")
        self.assertEqual(manifest["encryption"], {"algorithm": "AES-256-GCM", "key_fingerprint": "abcdef0123456789"})
        self.assertIsNone(self.manifest["encryption"])


def read_member_text(raw: bytes, member: str) -> str:
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        return zf.read(member).decode("utf-8")


class ZevScopeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.world = build_world()
        cls.raw, cls.manifest = build("zev", cls.world.alpha)

    def test_only_the_requested_zev_is_written(self):
        with zipfile.ZipFile(io.BytesIO(self.raw)) as zf:
            names = zf.namelist()
        self.assertFalse([n for n in names if n.startswith("instance/")])
        self.assertTrue(all(n == "manifest.json" or n.startswith(f"zevs/{self.world.alpha.pk}/") for n in names))
        self.assertNotIn("BETA-CONS-1", all_text(self.raw))

    def test_the_manifest_names_the_zev(self):
        self.assertEqual(self.manifest["scope"], "zev")
        self.assertEqual(self.manifest["zev_id"], str(self.world.alpha.pk))
        self.assertEqual([z["name"] for z in self.manifest["zevs"]], ["Alpha"])

    def test_account_refs_are_present_so_a_safety_backup_can_undo_a_restore(self):
        with zipfile.ZipFile(io.BytesIO(self.raw)) as zf:
            refs = json.loads(zf.read(f"zevs/{self.world.alpha.pk}/account_refs.json"))["users"]
        self.assertIn(self.world.owner.pk, [u["id"] for u in refs])

    def test_a_zev_scope_needs_a_zev_and_an_instance_scope_refuses_one(self):
        with self.assertRaises(ValueError):
            archive.build_archive(io.BytesIO(), scope="zev")
        with self.assertRaises(ValueError):
            archive.build_archive(io.BytesIO(), scope="instance", zev=self.world.alpha)
        with self.assertRaises(ValueError):
            archive.build_archive(io.BytesIO(), scope="galaxy")


class MediaTests(TestCase):
    def setUp(self):
        self.world = build_world()

    def test_a_missing_pdf_is_recorded_and_does_not_fail_the_backup(self):
        invoice = Invoice.objects.get(zev=self.world.alpha)
        default_storage.delete(invoice.pdf_file.name)
        raw, manifest = build()
        entry = next(z for z in manifest["zevs"] if z["id"] == str(self.world.alpha.pk))
        self.assertEqual(entry["media"]["files"], 0)
        self.assertEqual(entry["media"]["missing"], [invoice.pdf_file.name])
        archive.verify_archive(io.BytesIO(raw))  # still a valid archive

    def test_a_path_escaping_name_is_refused_not_written(self):
        Invoice.objects.filter(zev=self.world.alpha).update(pdf_file="../../etc/passwd")
        raw, manifest = build()
        entry = next(z for z in manifest["zevs"] if z["id"] == str(self.world.alpha.pk))
        self.assertEqual(entry["media"]["unsafe"], ["../../etc/passwd"])
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            self.assertFalse([n for n in zf.namelist() if ".." in n])

    def test_an_absolute_name_is_refused_too(self):
        Invoice.objects.filter(zev=self.world.alpha).update(pdf_file="/etc/passwd")
        _, manifest = build()
        entry = next(z for z in manifest["zevs"] if z["id"] == str(self.world.alpha.pk))
        self.assertEqual(entry["media"]["unsafe"], ["/etc/passwd"])

    def test_a_file_named_by_two_invoices_is_stored_once(self):
        alpha = self.world.alpha
        original = Invoice.objects.get(zev=alpha)
        clone = Invoice.objects.get(pk=original.pk)
        clone.pk = uuid.uuid4()
        clone.invoice_number = "TRF-00099"
        clone.save()
        with self.assertNoLogs(level="WARNING"):
            raw, _ = build("zev", alpha)
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            names = [n for n in zf.namelist() if "/media/" in n]
        self.assertEqual(names, [f"zevs/{alpha.pk}/media/{original.pdf_file.name}"])


class CoverageTests(SimpleTestCase):
    """Fail when a model is added and nobody decides whether it is backed up."""

    def test_every_installed_model_is_backed_up_or_excluded_with_a_reason(self):
        installed = {model._meta.label for model in apps.get_models()}
        decided = backed_up_labels() | set(EXCLUDED_MODELS)
        self.assertEqual(
            sorted(installed - decided), [],
            "These models are neither in a backup section nor in EXCLUDED_MODELS. "
            "Decide which, in backups/registry.py.",
        )

    def test_no_stale_entries(self):
        installed = {model._meta.label for model in apps.get_models()}
        self.assertEqual(sorted((backed_up_labels() | set(EXCLUDED_MODELS)) - installed), [])

    def test_a_model_is_not_both_backed_up_and_excluded(self):
        self.assertEqual(sorted(backed_up_labels() & set(EXCLUDED_MODELS)), [])

    def test_every_exclusion_says_why(self):
        self.assertTrue(all(reason.strip() for reason in EXCLUDED_MODELS.values()))

    def test_every_file_field_on_a_backed_up_model_is_copied_into_the_archive(self):
        """The omission that made the old ``pg_dump`` guidance lose every invoice PDF."""
        found = {
            (model._meta.label, field.name)
            for label in backed_up_labels()
            for model in [apps.get_model(label)]
            for field in model._meta.get_fields()
            if isinstance(field, models.FileField)
        }
        self.assertEqual(found, {(label, field) for label, field, _ in MEDIA_FIELDS})

    def test_every_zev_lookup_resolves_on_its_model(self):
        for _, parts in ZEV_SECTIONS:
            for part in parts:
                model = apps.get_model(part.label)
                # Building the queryset resolves the lookup; a typo raises FieldError.
                str(model.objects.filter(**{part.lookup: uuid.uuid4()}).order_by(*part.order).query)

    def test_null_zev_sections_target_models_that_really_have_a_nullable_zev(self):
        for _, label in UNSCOPED_SECTIONS:
            field = apps.get_model(label)._meta.get_field("zev")
            self.assertTrue(field.null, label)

    def test_the_unscoped_models_are_also_written_per_zev(self):
        """A row with a ZEV goes in that ZEV's section; only the nulls are unscoped."""
        per_zev = {part.label for _, parts in ZEV_SECTIONS for part in parts}
        for _, label in UNSCOPED_SECTIONS:
            self.assertIn(label, per_zev)


class DurabilityTests(TestCase):
    def test_a_backup_refuses_to_run_inside_an_outer_transaction(self):
        """The isolation level can only be set by the outermost transaction; inside
        another the guard fails loudly rather than degrading to a savepoint."""
        zev = build_world().alpha
        with transaction.atomic(), self.assertRaises(RuntimeError):
            archive.build_archive(io.BytesIO(), scope="zev", zev=zev)


class VerifyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.world = build_world()
        cls.raw, cls.manifest = build()

    def test_a_fresh_archive_verifies(self):
        result = archive.verify_archive(io.BytesIO(self.raw))
        self.assertEqual(result["members"], len(self.manifest["members"]))
        self.assertGreater(result["records"], 0)

    def test_a_tampered_member_is_caught_by_its_checksum(self):
        member = f"zevs/{self.world.alpha.pk}/participants.jsonl"
        original = read_member_text(self.raw, member)
        tampered = rewrite_archive(self.raw, replace={member: original.replace("Alice", "Mallory").encode()})
        with self.assertRaises(archive.ArchiveError) as raised:
            archive.verify_archive(io.BytesIO(tampered))
        self.assertTrue(any("checksum mismatch" in f and member in f for f in raised.exception.failures))

    def test_a_member_missing_from_the_archive_is_caught(self):
        member = f"zevs/{self.world.alpha.pk}/readings.jsonl"
        stripped = rewrite_archive(self.raw, drop=(member,))
        with self.assertRaises(archive.ArchiveError) as raised:
            archive.verify_archive(io.BytesIO(stripped))
        self.assertTrue(any("missing from the archive" in f for f in raised.exception.failures))

    def test_a_member_the_manifest_does_not_vouch_for_is_caught(self):
        injected = rewrite_archive(self.raw, replace={"instance/injected.jsonl": b"{}\n"})
        with self.assertRaises(archive.ArchiveError) as raised:
            archive.verify_archive(io.BytesIO(injected))
        self.assertTrue(any("not in the manifest" in f for f in raised.exception.failures))

    def test_a_manifest_count_that_disagrees_with_its_member_is_caught(self):
        manifest = json.loads(json.dumps(self.manifest))
        section = f"zevs/{self.world.alpha.pk}/readings"
        manifest["counts"][section] += 1
        altered = rewrite_archive(self.raw, replace={"manifest.json": manifest})
        with self.assertRaises(archive.ArchiveError) as raised:
            archive.verify_archive(io.BytesIO(altered))
        self.assertTrue(any(section in f and "manifest counts" in f for f in raised.exception.failures))

    def test_a_transfer_archive_is_refused_by_kind_with_a_pointer_to_where_it_belongs(self):
        buffer = io.BytesIO()
        build_transfer_archive(self.world.alpha, None, buffer)
        with self.assertRaises(archive.ArchiveError) as raised:
            archive.verify_archive(io.BytesIO(buffer.getvalue()))
        self.assertIn("not a backup", str(raised.exception))

    def test_an_unknown_format_version_is_refused(self):
        manifest = {**self.manifest, "format_version": 99}
        altered = rewrite_archive(self.raw, replace={"manifest.json": manifest})
        with self.assertRaises(archive.ArchiveError) as raised:
            archive.verify_archive(io.BytesIO(altered))
        self.assertIn("Unsupported backup format version", str(raised.exception))

    def test_a_missing_manifest_is_refused(self):
        with self.assertRaises(archive.ArchiveError):
            archive.verify_archive(io.BytesIO(rewrite_archive(self.raw, drop=("manifest.json",))))

    def test_a_malformed_manifest_is_refused_not_a_crash(self):
        for broken in ({"kind": "backup", "format_version": 1, "scope": "instance"}, [], "text"):
            altered = rewrite_archive(self.raw, replace={"manifest.json": broken})
            with self.assertRaises(archive.ArchiveError):
                archive.verify_archive(io.BytesIO(altered))

    def test_something_that_is_not_a_zip_is_refused(self):
        with self.assertRaises(archive.ArchiveError):
            archive.verify_archive(io.BytesIO(b"definitely not a zip"))

    def test_reported_failures_are_capped_but_the_total_is_not(self):
        manifest = json.loads(json.dumps(self.manifest))
        for index in range(80):
            manifest["members"][f"phantom/{index}.jsonl"] = {"sha256": "0" * 64, "bytes": 1, "records": 0}
        altered = rewrite_archive(self.raw, replace={"manifest.json": manifest})
        with self.assertRaises(archive.ArchiveError) as raised:
            archive.verify_archive(io.BytesIO(altered))
        self.assertEqual(len(raised.exception.failures), 50)
        self.assertGreaterEqual(raised.exception.total_failures, 80)


@override_settings(BACKUP_ENCRYPTION_KEYS=[KEY])
class EncryptedArchiveTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.world = build_world()

    def _encrypted(self):
        raw, _ = build(fingerprint=crypto.active_fingerprint())
        sealed = io.BytesIO()
        crypto.encrypt_stream(io.BytesIO(raw), sealed, chunk_size=4096)
        return sealed.getvalue(), raw

    def test_an_encrypted_archive_verifies_and_hides_its_contents(self):
        sealed, _ = self._encrypted()
        self.assertNotIn(b"plaintext-client-secret", sealed)
        self.assertNotIn(b"ALPHA-CONS-1", sealed)
        result = archive.verify_archive(io.BytesIO(sealed))
        self.assertEqual(result["manifest"]["encryption"]["key_fingerprint"], crypto.active_fingerprint())

    def test_an_encrypted_archive_cannot_be_verified_without_its_key(self):
        sealed, _ = self._encrypted()
        with override_settings(BACKUP_ENCRYPTION_KEYS=["Z" * 40]):
            with self.assertRaises(crypto.BackupKeyMissing):
                archive.verify_archive(io.BytesIO(sealed))

    def test_the_decrypted_temp_file_does_not_outlive_verification(self):
        with tempfile.TemporaryDirectory() as work:
            sealed, _ = self._encrypted()
            with override_settings(BACKUP_WORK_DIR=work):
                archive.verify_archive(io.BytesIO(sealed))
                import os
                self.assertEqual(os.listdir(work), [])


class RoundTripTests(TestCase):
    """The format must be restorable, not merely well-formed."""

    def test_deserializing_the_sections_reproduces_the_rows_with_their_keys(self):
        world = build_world()
        alpha = world.alpha
        alpha_id = alpha.pk  # Django clears ``pk`` on a deleted instance
        raw, _ = build("zev", alpha)

        before = {
            "readings": sorted(
                (str(r.pk), str(r.energy_kwh), r.timestamp.isoformat(), r.direction)
                for r in MeterReading.objects.filter(metering_point__zev=alpha)
            ),
            "participants": sorted(str(p.pk) for p in Participant.objects.filter(zev=alpha)),
            "contract_pdf": bytes(ContractIssue.objects.get(zev=alpha).pdf),
            "invoice": {(str(i.pk), i.invoice_number, str(i.total_chf), i.pdf_file.name) for i in Invoice.objects.filter(zev=alpha)},
            "audit": AuditEvent.objects.filter(zev=alpha).count(),
            "import_logs": ImportLog.objects.filter(zev=alpha).count(),
        }

        # Wipe the community. Invoices are PROTECT, so they go first; contract
        # issues and audit rows are SET_NULL, so they survive as orphans and the
        # reload must update them in place rather than duplicate them.
        Invoice.objects.filter(zev=alpha).delete()
        alpha.delete()
        self.assertFalse(MeterReading.objects.filter(metering_point__zev_id=alpha_id).exists())

        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            for name, _ in ZEV_SECTIONS:
                with zf.open(f"zevs/{alpha_id}/{name}.jsonl") as handle:
                    for deserialized in serializers.deserialize("jsonl", io.TextIOWrapper(handle, encoding="utf-8")):
                        deserialized.save()

        self.assertEqual(
            before["readings"],
            sorted(
                (str(r.pk), str(r.energy_kwh), r.timestamp.isoformat(), r.direction)
                for r in MeterReading.objects.filter(metering_point__zev_id=alpha_id)
            ),
        )
        self.assertEqual(
            before["participants"], sorted(str(p.pk) for p in Participant.objects.filter(zev_id=alpha_id))
        )
        self.assertEqual(before["contract_pdf"], bytes(ContractIssue.objects.get(zev_id=alpha_id).pdf))
        self.assertEqual(
            before["invoice"],
            {(str(i.pk), i.invoice_number, str(i.total_chf), i.pdf_file.name) for i in Invoice.objects.filter(zev_id=alpha_id)},
        )
        self.assertEqual(before["audit"], AuditEvent.objects.filter(zev_id=alpha_id).count())
        self.assertEqual(before["import_logs"], ImportLog.objects.filter(zev_id=alpha_id).count())
        self.assertEqual(User.objects.get(pk=world.owner.pk).pk, world.owner.pk)
