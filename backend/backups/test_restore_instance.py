"""Whole-instance restore: a round trip is exact, and every refusal changes nothing.

The property that matters is the second one. A restore that half-applies is worse
than no restore: it leaves an instance that is neither the old state nor the
backup. So most tests here corrupt or mis-target an archive and then assert that
the database (and storage) are exactly as they were.
"""

import hashlib
import io
import json
import tempfile
import uuid
import zipfile
from datetime import date
from decimal import Decimal
from io import StringIO
from pathlib import Path
from unittest import mock

from django.apps import apps
from django.conf import settings
from django.core.files.storage import default_storage
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, connection
from django.test import SimpleTestCase, TestCase, override_settings

from accounts.models import User, VatRate
from audit.models import AuditEvent, AuditEventSource
from backups import archive, crypto, restore, storage
from backups.fixtures import PDF_BYTES, build_world
from backups.registry import backed_up_labels
from backups.test_archive import KEY, build
from exports.models import ExportJob
from invoices.models import Invoice
from metering.models import MeterReading
from zev.models import Zev
from zev.transfer import build_archive as build_transfer_archive


def snapshot() -> dict[str, list[dict]]:
    """Every backed-up row, field for field — timestamps and primary keys included."""
    result = {}
    for label in sorted(backed_up_labels()):
        model = apps.get_model(label)
        fields = [f.name for f in model._meta.concrete_fields if f.serialize]
        rows = []
        queryset = model._base_manager.order_by("pk")
        if label == "audit.AuditEvent":
            # A restore records itself in the trail; that is tested on its own.
            queryset = queryset.exclude(action_type=restore.ACTION_RESTORED)
        for obj in queryset:
            rows.append({"pk": obj.pk, **{name: getattr(obj, model._meta.get_field(name).attname) for name in fields}})
        result[label] = rows
    return result


def wipe():
    """A blank instance: no rows in any backed-up table, no invoice PDFs in storage."""
    for invoice in Invoice.objects.exclude(pdf_file=""):
        default_storage.delete(invoice.pdf_file.name)
    ExportJob.objects.all().delete()
    restore._clear()


def restore_from(raw: bytes, **options):
    return restore.restore_instance(io.BytesIO(raw), **options)


def tamper(raw: bytes, edit) -> bytes:
    """Rewrite an archive after ``edit(members, manifest)`` and keep its checksums honest.

    Corruption is tested separately; this builds archives that *verify* but are
    wrong, which is what an attacker or a bug in a future writer would produce.
    """
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        members = {name: zf.read(name) for name in zf.namelist() if name != archive.MANIFEST_NAME}
        manifest = json.loads(zf.read(archive.MANIFEST_NAME))
    edit(members, manifest)
    for name in set(manifest["members"]) - set(members):
        del manifest["members"][name]
    for name, data in members.items():
        entry = manifest["members"].setdefault(name, {})
        entry["sha256"] = hashlib.sha256(data).hexdigest()
        entry["bytes"] = len(data)
        if name.endswith(".jsonl"):
            entry["records"] = data.count(b"\n")
            key = name[: -len(".jsonl")]
            if key in manifest["counts"]:
                manifest["counts"][key] = entry["records"]
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
        zf.writestr(archive.MANIFEST_NAME, json.dumps(manifest))
    return out.getvalue()


def lines(members, name):
    return [json.loads(line) for line in members[name].decode().splitlines() if line]


def put_lines(members, name, records):
    members[name] = ("\n".join(json.dumps(r) for r in records) + "\n").encode()


class RestoreTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.world = build_world()
        cls.raw, cls.manifest = build()
        cls.original = snapshot()
        cls.pdf_names = [i.pdf_file.name for i in Invoice.objects.exclude(pdf_file="")]
        cls.alpha_pdf = cls.world.alpha_invoice.pdf_file.name
        cls.beta_pdf = next(name for name in cls.pdf_names if name != cls.alpha_pdf)

    def setUp(self):
        # Storage is not transactional, so put back what a test may have removed.
        self.addCleanup(self._restore_pdfs)

    def _restore_pdfs(self):
        for name in self.pdf_names:
            if not default_storage.exists(name):
                default_storage.save(name, io.BytesIO(PDF_BYTES if "alpha" in name else PDF_BYTES + b"beta"))


class RoundTripTests(RestoreTestCase):
    def test_a_fresh_instance_gets_every_row_back_exactly(self):
        wipe()
        self.assertEqual(User.objects.count(), 0)

        report = restore_from(self.raw)

        self.assertEqual(snapshot(), self.original)
        self.assertEqual(report.records, sum(len(rows) for rows in self.original.values()))

    def test_primary_keys_and_timestamps_are_preserved(self):
        wipe()
        restore_from(self.raw)
        alpha = Zev.objects.get(pk=self.world.alpha.pk)
        self.assertEqual(alpha.created_at, self.world.alpha.created_at)
        self.assertEqual(alpha.updated_at, self.world.alpha.updated_at)
        reading = MeterReading.objects.order_by("pk").first()
        original = next(r for r in self.original["metering.MeterReading"] if r["pk"] == reading.pk)
        self.assertEqual(reading.created_at, original["created_at"])

    def test_the_timestamp_flags_are_put_back(self):
        wipe()
        restore_from(self.raw)
        created = MeterReading._meta.get_field("created_at")
        updated = Zev._meta.get_field("updated_at")
        self.assertTrue(created.auto_now_add)
        self.assertTrue(updated.auto_now)
        # And they still work for ordinary writes.
        zev = Zev.objects.get(pk=self.world.alpha.pk)
        before = zev.updated_at
        zev.save()
        zev.refresh_from_db()
        self.assertGreater(zev.updated_at, before)

    def test_invoice_pdfs_come_back_under_the_same_name_and_bytes(self):
        wipe()
        for name in self.pdf_names:
            self.assertFalse(default_storage.exists(name))
        report = restore_from(self.raw)
        self.assertEqual(report.media_files, 2)
        invoice = Invoice.objects.get(pk=self.world.alpha_invoice.pk)
        self.assertEqual(invoice.pdf_file.name, self.alpha_pdf)
        with default_storage.open(invoice.pdf_file.name, "rb") as stored:
            self.assertEqual(stored.read(), PDF_BYTES)

    def test_ordinary_inserts_after_a_restore_do_not_collide(self):
        """The sequences moved: integer-keyed tables must accept the next row."""
        wipe()
        restore_from(self.raw)
        top_user = User.objects.order_by("-pk").first().pk
        top_rate = VatRate.objects.order_by("-pk").first().pk
        user = User.objects.create_user(username="after-restore", email="after@example.com", password="x" * 12)
        rate = VatRate.objects.create(rate=Decimal("0.0100"), valid_from=date(1998, 1, 1), valid_to=date(1998, 12, 31))
        self.assertGreater(user.pk, top_user)
        self.assertGreater(rate.pk, top_rate)

    def test_the_audit_trail_is_restored_and_the_restore_is_added_to_it(self):
        wipe()
        before = {r["pk"] for r in self.original["audit.AuditEvent"]}
        restore_from(self.raw)
        after = {e.pk: e for e in AuditEvent.objects.all()}
        self.assertTrue(before <= set(after))
        added = [e for pk, e in after.items() if pk not in before]
        self.assertEqual([e.action_type for e in added], [restore.ACTION_RESTORED])
        self.assertEqual(added[0].source, AuditEventSource.MANAGEMENT_COMMAND)
        self.assertEqual(added[0].metadata_json["forced"], False)

    def test_rows_that_outlived_a_deleted_community_are_restored(self):
        wipe()
        restore_from(self.raw)
        self.assertTrue(AuditEvent.objects.filter(zev__isnull=True, action_type="settings.updated").exists())
        self.assertEqual(
            len(snapshot()["invoices.ContractIssue"]),
            len(self.original["invoices.ContractIssue"]),
        )

    def test_a_bootstrap_superuser_does_not_make_the_instance_non_empty(self):
        wipe()
        User.objects.create_superuser(username="bootstrap", email="boot@example.com", password="x" * 12)
        restore_from(self.raw)
        self.assertFalse(User.objects.filter(username="bootstrap").exists())
        self.assertEqual(snapshot()["accounts.User"], self.original["accounts.User"])

    def test_an_encrypted_backup_restores_with_its_key(self):
        with override_settings(BACKUP_ENCRYPTION_KEYS=[KEY]):
            sealed = io.BytesIO()
            crypto.encrypt_stream(io.BytesIO(self.raw), sealed)
            wipe()
            restore_from(sealed.getvalue())
        self.assertEqual(snapshot(), self.original)

    def test_an_encrypted_backup_without_its_key_is_refused_before_anything_changes(self):
        with override_settings(BACKUP_ENCRYPTION_KEYS=[KEY]):
            sealed = io.BytesIO()
            crypto.encrypt_stream(io.BytesIO(self.raw), sealed)
        with override_settings(BACKUP_ENCRYPTION_KEYS=[]), self.assertRaises(crypto.BackupCryptoError):
            restore_from(sealed.getvalue(), force=True)
        self.assertEqual(snapshot(), self.original)


class DryRunTests(RestoreTestCase):
    def test_dry_run_reads_everything_and_writes_nothing(self):
        wipe()
        report = restore_from(self.raw, dry_run=True)
        self.assertTrue(report.dry_run)
        self.assertEqual(report.records, sum(len(rows) for rows in self.original.values()))
        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(Zev.objects.count(), 0)
        self.assertFalse(any(default_storage.exists(name) for name in self.pdf_names))
        self.assertFalse(AuditEvent.objects.exists())

    def test_dry_run_refuses_exactly_when_the_real_run_would(self):
        with self.assertRaises(restore.RestoreError):
            restore_from(self.raw, dry_run=True)

    def test_dry_run_with_force_reports_what_would_be_replaced(self):
        report = restore_from(self.raw, dry_run=True, force=True)
        self.assertEqual(report.replaced["zev.Zev"], 2)
        self.assertEqual(snapshot(), self.original)

    def test_dry_run_still_rejects_records_the_schema_cannot_hold(self):
        wipe()

        def edit(members, manifest):
            records = lines(members, "instance/app_settings.jsonl")
            records[0]["fields"]["a_column_that_does_not_exist"] = 1
            put_lines(members, "instance/app_settings.jsonl", records)

        with self.assertRaises(restore.RestoreError):
            restore_from(tamper(self.raw, edit), dry_run=True)


class RefusalTests(RestoreTestCase):
    def test_a_populated_instance_is_refused_without_force_and_left_alone(self):
        with self.assertRaisesMessage(restore.RestoreError, "--force"):
            restore_from(self.raw)
        self.assertEqual(snapshot(), self.original)

    def test_force_replaces_the_instance_with_the_backup(self):
        Zev.objects.filter(pk=self.world.alpha.pk).update(name="Renamed after the backup")
        Zev.objects.create(name="Not in the backup", owner=self.world.owner)
        User.objects.create_user(username="intruder", email="intruder@example.com", password="x" * 12)
        AuditEvent.objects.filter(action_type="invoice.sent").delete()

        report = restore_from(self.raw, force=True)

        self.assertEqual(snapshot()["zev.Zev"], self.original["zev.Zev"])
        self.assertEqual(snapshot()["accounts.User"], self.original["accounts.User"])
        self.assertTrue(AuditEvent.objects.filter(action_type="invoice.sent").exists())
        self.assertGreater(sum(report.replaced.values()), 0)
        restored = AuditEvent.objects.get(action_type=restore.ACTION_RESTORED)
        self.assertTrue(restored.metadata_json["forced"])

    def test_force_survives_rows_outside_the_backup_that_point_at_it(self):
        """An export job protects its community, a token cascades from its user."""
        from accounts.models import EmailVerificationToken

        ExportJob.objects.create(zev=self.world.alpha, requester=self.world.owner)
        EmailVerificationToken.objects.create(user=self.world.owner, token="t" * 64)
        restore_from(self.raw, force=True)
        self.assertEqual(snapshot()["zev.Zev"], self.original["zev.Zev"])

    def test_a_transfer_archive_is_refused_by_name(self):
        buffer = io.BytesIO()
        build_transfer_archive(self.world.alpha, None, buffer)
        wipe()
        with self.assertRaisesMessage(archive.ArchiveError, "not a backup"):
            restore_from(buffer.getvalue())
        self.assertEqual(Zev.objects.count(), 0)

    def test_a_single_community_backup_is_refused(self):
        raw, _ = build(scope="zev", zev=self.world.alpha)
        wipe()
        with self.assertRaisesMessage(restore.RestoreError, "single community"):
            restore_from(raw)
        self.assertEqual(Zev.objects.count(), 0)

    def test_a_backup_from_a_newer_version_is_refused(self):
        def edit(members, manifest):
            manifest["migrations"]["zev"].append("9999_from_the_future")

        wipe()
        with self.assertRaisesMessage(restore.RestoreError, "newer version"):
            restore_from(tamper(self.raw, edit))
        self.assertEqual(Zev.objects.count(), 0)

    def test_a_database_that_has_not_applied_the_backups_migrations_is_told_to_migrate(self):
        recorder = restore.MigrationRecorder(connection).applied_migrations()
        missing = next(key for key in recorder if key[0] == "zev")
        without = {key: value for key, value in recorder.items() if key != missing}
        wipe()
        with (
            mock.patch.object(restore.MigrationRecorder, "applied_migrations", return_value=without),
            self.assertRaisesMessage(restore.RestoreError, "migrate"),
        ):
            restore_from(self.raw)

    def test_a_database_newer_than_the_backup_is_told_how_to_go_back(self):
        def edit(members, manifest):
            manifest["migrations"]["zev"] = manifest["migrations"]["zev"][:-1]

        wipe()
        with self.assertRaises(restore.RestoreError) as caught:
            restore_from(tamper(self.raw, edit))
        message = str(caught.exception)
        self.assertIn("newer than the backup", message)
        self.assertIn("migrate zev", message)

    def test_unrelated_apps_migrating_does_not_block_a_restore(self):
        def edit(members, manifest):
            manifest["migrations"]["django_celery_beat"] = []

        wipe()
        restore_from(tamper(self.raw, edit))
        self.assertEqual(snapshot(), self.original)


class IntegrityTests(RestoreTestCase):
    def test_a_corrupted_member_is_refused_before_anything_changes(self):
        with zipfile.ZipFile(io.BytesIO(self.raw)) as zf:
            members = {n: zf.read(n) for n in zf.namelist()}
        target = next(n for n in members if n.endswith("accounts.jsonl"))
        members[target] = members[target].replace(b"bk_admin", b"bk_evil!")
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as zf:
            for name, data in members.items():
                zf.writestr(name, data)
        with self.assertRaises(archive.ArchiveError):
            restore_from(out.getvalue(), force=True)
        self.assertEqual(snapshot(), self.original)

    def test_a_backup_missing_a_whole_section_is_refused(self):
        def edit(members, manifest):
            del members["instance/accounts.jsonl"]
            manifest["counts"].pop("instance/accounts", None)

        wipe()
        with self.assertRaises(archive.ArchiveError) as caught:
            restore_from(tamper(self.raw, edit))
        self.assertIn("instance/accounts.jsonl", "\n".join(caught.exception.failures))
        self.assertEqual(User.objects.count(), 0)

    def test_a_section_cannot_create_rows_of_a_model_it_does_not_own(self):
        def edit(members, manifest):
            records = lines(members, "instance/accounts.jsonl")
            records.append({"model": "sessions.session", "pk": "abc", "fields": {"session_data": "x", "expire_date": "2030-01-01T00:00:00Z"}})
            put_lines(members, "instance/accounts.jsonl", records)

        wipe()
        with self.assertRaisesMessage(restore.RestoreError, "does not belong"):
            restore_from(tamper(self.raw, edit))
        self.assertEqual(User.objects.count(), 0)

    def test_a_record_the_schema_cannot_read_is_reported_without_quoting_its_content(self):
        def edit(members, manifest):
            name = f"zevs/{self.world.alpha.pk}/participants.jsonl"
            records = lines(members, name)
            records[0]["fields"]["not_a_column"] = "Secret Personal Name"
            put_lines(members, name, records)

        wipe()
        with self.assertRaises(restore.RestoreError) as caught:
            restore_from(tamper(self.raw, edit))
        self.assertIn("participants.jsonl", str(caught.exception))
        self.assertNotIn("Secret Personal Name", str(caught.exception))
        self.assertEqual(Zev.objects.count(), 0)

    def test_rows_pointing_at_rows_the_backup_lacks_roll_everything_back(self):
        def edit(members, manifest):
            name = f"zevs/{self.world.alpha.pk}/invoices.jsonl"
            records = lines(members, name)
            invoice = next(r for r in records if r["model"] == "invoices.invoice")
            invoice["fields"]["participant"] = str(uuid.uuid4())
            put_lines(members, name, records)

        wipe()
        with self.assertRaises(restore.RestoreError):
            restore_from(tamper(self.raw, edit))
        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(Zev.objects.count(), 0)
        self.assertFalse(any(default_storage.exists(n) for n in self.pdf_names))


class RollbackTests(RestoreTestCase):
    def test_a_failure_after_the_media_step_undoes_the_rows_and_the_files(self):
        wipe()
        with (
            mock.patch.object(restore, "_reconcile_sequences", side_effect=IntegrityError("boom")),
            self.assertRaises(restore.RestoreError),
        ):
            restore_from(self.raw)
        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(Zev.objects.count(), 0)
        self.assertFalse(any(default_storage.exists(n) for n in self.pdf_names))

    def test_a_failed_forced_restore_leaves_the_existing_data_in_place(self):
        Zev.objects.filter(pk=self.world.beta.pk).update(name="Edited after the backup")
        edited = snapshot()
        with (
            mock.patch.object(restore, "_reconcile_sequences", side_effect=IntegrityError("boom")),
            self.assertRaises(restore.RestoreError),
        ):
            restore_from(self.raw, force=True)
        self.assertEqual(snapshot(), edited)

    def test_the_timestamp_flags_come_back_even_when_the_load_fails(self):
        wipe()
        with (
            mock.patch.object(restore, "_reconcile_sequences", side_effect=IntegrityError("boom")),
            self.assertRaises(restore.RestoreError),
        ):
            restore_from(self.raw)
        self.assertTrue(MeterReading._meta.get_field("created_at").auto_now_add)

    def test_an_audit_failure_does_not_undo_a_finished_restore(self):
        wipe()
        with mock.patch.object(restore, "record_audit_event", side_effect=RuntimeError("audit down")):
            restore_from(self.raw)
        self.assertEqual(snapshot(), self.original)


class MediaTests(RestoreTestCase):
    def test_a_file_already_at_that_name_is_replaced_not_renamed(self):
        name = self.alpha_pdf
        default_storage.delete(name)
        default_storage.save(name, io.BytesIO(b"stale bytes"))
        restore_from(self.raw, force=True)
        self.assertEqual(Invoice.objects.get(pk=self.world.alpha_invoice.pk).pdf_file.name, name)
        with default_storage.open(name, "rb") as stored:
            self.assertEqual(stored.read(), PDF_BYTES)

    def test_a_pdf_that_was_missing_when_the_backup_was_taken_is_reported(self):
        default_storage.delete(self.beta_pdf)
        raw, manifest = build()
        wipe()
        report = restore_from(raw)
        self.assertEqual(report.media_missing, 1)
        self.assertEqual(report.media_files, 1)

    def test_media_the_database_does_not_reference_is_not_written(self):
        alpha = str(self.world.alpha.pk)

        def edit(members, manifest):
            members[f"zevs/{alpha}/media/planted.txt"] = b"not an invoice"
            members[f"zevs/{alpha}/media/../../escape.txt"] = b"path traversal"

        wipe()
        report = restore_from(tamper(self.raw, edit))
        self.assertEqual(report.media_skipped, 2)
        self.assertFalse(default_storage.exists("planted.txt"))
        self.assertFalse((Path(settings.MEDIA_ROOT).parent / "escape.txt").exists())


class KeyWarningTests(SimpleTestCase):
    def manifest(self, fingerprints, totp=1):
        return {
            "members": {"instance/accounts.jsonl": {"models": {"accounts.TotpDevice": totp}}},
            "secret_fingerprints": {"mfa_encryption_keys": fingerprints, "secret_key": "x"},
        }

    @override_settings(MFA_ENCRYPTION_KEYS=["M" * 44])
    def test_a_backup_from_an_instance_with_other_mfa_keys_warns_and_names_the_fingerprint(self):
        warnings = restore.key_warnings(self.manifest(["9f8e7d6c5b4a3928"]))
        self.assertEqual(len(warnings), 1)
        self.assertIn("9f8e7d6c5b4a3928", warnings[0])
        self.assertIn("1 authenticator", warnings[0])

    @override_settings(MFA_ENCRYPTION_KEYS=["M" * 44])
    def test_a_matching_key_is_silent(self):
        self.assertEqual(restore.key_warnings(self.manifest([crypto.key_fingerprint("M" * 44)])), [])

    @override_settings(MFA_ENCRYPTION_KEYS=["M" * 44])
    def test_no_authenticators_means_nothing_to_warn_about(self):
        self.assertEqual(restore.key_warnings(self.manifest(["9f8e7d6c5b4a3928"], totp=0)), [])


class SourceUrlTests(SimpleTestCase):
    def test_bucket_and_key_are_split(self):
        self.assertEqual(storage.parse_s3_url("s3://bkt/some/prefix/a.zip.enc"), ("bkt", "some/prefix/a.zip.enc"))

    def test_anything_else_is_refused(self):
        for bad in ("s3://bucket", "s3:///key", "https://example.com/a", "bucket/key"):
            with self.subTest(bad), self.assertRaises(storage.DestinationError):
                storage.parse_s3_url(bad)

    @override_settings(BACKUP_S3_ACCESS_KEY_ID="", BACKUP_S3_SECRET_ACCESS_KEY="")
    def test_download_uses_the_endpoint_and_default_credentials_when_no_keys_are_set(self):
        client = mock.Mock()
        with mock.patch.object(storage, "s3_client", return_value=client) as make:
            storage.fetch_archive("s3://bkt/a/b.zip", "/tmp/x", endpoint_url="https://minio.test", region="eu-1")
        source = make.call_args.args[0]
        self.assertEqual((source.endpoint_url, source.region, source.credential_mode), ("https://minio.test", "eu-1", "default"))
        self.assertEqual(client.download_file.call_args.args[:2], ("bkt", "a/b.zip"))

    @override_settings(BACKUP_S3_ACCESS_KEY_ID="AK", BACKUP_S3_SECRET_ACCESS_KEY="SK")
    def test_download_uses_environment_credentials_when_both_are_set(self):
        with mock.patch.object(storage, "s3_client", return_value=mock.Mock()) as make:
            storage.fetch_archive("s3://bkt/k", "/tmp/x")
        self.assertEqual(make.call_args.args[0].credential_mode, "environment")

    def test_a_provider_error_becomes_a_safe_message(self):
        from botocore.exceptions import ClientError

        error = ClientError({"Error": {"Code": "NoSuchKey", "Message": "secret-bucket-detail"}}, "GetObject")
        client = mock.Mock()
        client.download_file.side_effect = error
        with (
            mock.patch.object(storage, "s3_client", return_value=client),
            self.assertRaises(storage.DestinationError) as caught,
        ):
            storage.fetch_archive("s3://bkt/k", "/tmp/x")
        self.assertNotIn("secret-bucket-detail", str(caught.exception))


class CommandTests(RestoreTestCase):
    def setUp(self):
        super().setUp()
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def backup_file(self, raw=None) -> Path:
        path = self.tmp / "backup.zip"
        path.write_bytes(self.raw if raw is None else raw)
        return path

    def run_command(self, source, *extra):
        out, err = StringIO(), StringIO()
        call_command("openzev_restore", "--mode", "instance", "--from", str(source), *extra, stdout=out, stderr=err)
        return out.getvalue(), err.getvalue()

    def test_restores_from_a_file_and_prints_a_summary(self):
        wipe()
        out, _ = self.run_command(self.backup_file())
        self.assertIn("Restore complete.", out)
        self.assertIn("zev.Zev", out)
        self.assertIn(f"version       {self.manifest['openzev_version']}", out)
        self.assertEqual(snapshot()["zev.Zev"], self.original["zev.Zev"])

    def test_dry_run_says_it_changed_nothing(self):
        wipe()
        out, _ = self.run_command(self.backup_file(), "--dry-run")
        self.assertIn("nothing was changed", out)
        self.assertEqual(Zev.objects.count(), 0)

    def test_a_forced_restore_names_what_it_replaced(self):
        out, _ = self.run_command(self.backup_file(), "--force")
        self.assertIn("existing rows (", out)
        self.assertIn("zev.Zev 2", out)

    def test_refusal_is_a_command_error_with_the_reason(self):
        with self.assertRaisesMessage(CommandError, "--force"):
            self.run_command(self.backup_file())

    def test_a_missing_file_is_a_command_error(self):
        with self.assertRaisesMessage(CommandError, "Cannot read"):
            self.run_command("/nonexistent/backup.zip")

    def test_verification_failures_are_listed_on_stderr(self):
        with zipfile.ZipFile(io.BytesIO(self.raw)) as zf:
            members = {name: zf.read(name) for name in zf.namelist()}
        members["stowaway.txt"] = b"not vouched for by the manifest"
        rebuilt = io.BytesIO()
        with zipfile.ZipFile(rebuilt, "w") as zf:
            for name, data in members.items():
                zf.writestr(name, data)
        err = StringIO()
        with self.assertRaises(CommandError):
            call_command(
                "openzev_restore", "--mode", "instance", "--from", str(self.backup_file(rebuilt.getvalue())),
                "--force", stdout=StringIO(), stderr=err,
            )
        self.assertIn("stowaway.txt", err.getvalue())

    def test_an_s3_source_is_downloaded_then_restored(self):
        wipe()

        def fake_fetch(url, target, *, endpoint_url="", region=""):
            self.assertEqual((url, endpoint_url, region), ("s3://bkt/openzev/b.zip", "https://minio.test", "eu-1"))
            target.write_bytes(self.raw)

        with mock.patch("backups.management.commands.openzev_restore.fetch_archive", side_effect=fake_fetch):
            out, _ = self.run_command(
                "s3://bkt/openzev/b.zip", "--endpoint-url", "https://minio.test", "--region", "eu-1"
            )
        self.assertIn("Restore complete.", out)
        self.assertEqual(snapshot()["zev.Zev"], self.original["zev.Zev"])

    def test_an_s3_failure_is_a_command_error_with_the_safe_message(self):
        with (
            mock.patch(
                "backups.management.commands.openzev_restore.fetch_archive",
                side_effect=storage.DestinationError("Could not reach the storage endpoint."),
            ),
            self.assertRaisesMessage(CommandError, "Could not reach"),
        ):
            self.run_command("s3://bkt/k")

    def test_a_warning_from_preflight_is_printed_on_stderr(self):
        wipe()
        with mock.patch.object(restore, "key_warnings", return_value=["The MFA key does not match."]):
            _, err = self.run_command(self.backup_file())
        self.assertIn("WARNING: The MFA key does not match.", err)


class SequenceTests(RestoreTestCase):
    """The reset itself is a PostgreSQL statement (``setval``); SQLite needs none.

    What can be checked everywhere is *which* tables are handed to the database:
    every integer-keyed backed-up model, and none of the UUID-keyed ones. The
    statement's effect was verified against a real PostgreSQL restore (see the
    spec's verification notes).
    """

    def test_every_integer_keyed_model_is_reset_and_no_other(self):
        wipe()
        with mock.patch.object(restore.connection.ops, "sequence_reset_sql", return_value=[]) as reset:
            restore_from(self.raw)
        models = reset.call_args.args[1]
        expected = {
            apps.get_model(label)
            for label in backed_up_labels()
            if apps.get_model(label)._meta.pk.get_internal_type() in {"AutoField", "BigAutoField", "SmallAutoField"}
        }
        self.assertEqual(set(models), expected)
        self.assertIn(User, models)
        self.assertIn(VatRate, models)
        self.assertNotIn(Zev, models)
