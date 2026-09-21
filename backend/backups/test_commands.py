"""``openzev_backup`` and ``openzev_backup_verify``."""

import io
import tempfile
import zipfile
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings

from audit.models import AuditEvent, AuditEventSource
from backups import crypto
from backups.fixtures import build_world
from backups.models import BackupDestination, BackupJob, BackupJobStatus
from zev.models import Zev

KEY = "C" * 40


def run(*args, **kwargs):
    out, err = io.StringIO(), io.StringIO()
    call_command(*args, stdout=out, stderr=err, **kwargs)
    return out.getvalue(), err.getvalue()


class CommandTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.world = build_world()

    def setUp(self):
        self.dest_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dest_dir.cleanup)
        self.work_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.work_dir.cleanup)
        override = override_settings(BACKUP_WORK_DIR=self.work_dir.name)
        override.enable()
        self.addCleanup(override.disable)

    def archives(self):
        return sorted(Path(self.dest_dir.name).glob("openzev-backup-*"))


class BackupCommandTests(CommandTestCase):
    def test_backs_up_to_a_local_path_without_a_saved_destination(self):
        out, _ = run("openzev_backup", "--path", self.dest_dir.name)
        (archive,) = self.archives()
        self.assertIn("Backup complete.", out)
        self.assertIn(str(archive), out)
        job = BackupJob.objects.get()
        self.assertEqual((job.status, job.destination), (BackupJobStatus.COMPLETED, None))
        self.assertEqual(job.archive_location, str(archive))

    def test_backs_up_to_a_named_destination(self):
        BackupDestination.objects.create(name="nightly", kind="local", path=self.dest_dir.name)
        run("openzev_backup", "--destination", "nightly")
        self.assertEqual(len(self.archives()), 1)
        self.assertEqual(BackupJob.objects.get().destination.name, "nightly")

    def test_an_unencrypted_backup_warns_loudly_on_stderr_before_it_starts(self):
        _, err = run("openzev_backup", "--path", self.dest_dir.name)
        self.assertIn("will NOT be encrypted", err)
        self.assertIn("password hashes", err)

    @override_settings(BACKUP_ENCRYPTION_KEYS=[KEY])
    def test_an_encrypted_backup_does_not_warn_and_reports_the_key(self):
        out, err = run("openzev_backup", "--path", self.dest_dir.name)
        self.assertNotIn("NOT be encrypted", err)
        self.assertIn(f"yes (key {crypto.key_fingerprint(KEY)})", out)
        (archive,) = self.archives()
        self.assertTrue(archive.name.endswith(".zip.enc"))

    def test_the_report_gives_the_checksum_so_a_copy_can_be_checked_by_hand(self):
        out, _ = run("openzev_backup", "--path", self.dest_dir.name)
        self.assertIn(BackupJob.objects.get().archive_sha256, out)

    def test_a_zev_can_be_selected_by_id(self):
        run("openzev_backup", "--path", self.dest_dir.name, "--zev", str(self.world.beta.pk))
        self.assertEqual([z["name"] for z in BackupJob.objects.get().manifest_json["zevs"]], ["Beta"])

    def test_a_zev_can_be_selected_by_name(self):
        run("openzev_backup", "--path", self.dest_dir.name, "--zev", "Alpha")
        job = BackupJob.objects.get()
        self.assertEqual((job.scope, job.zev_id), ("zev", self.world.alpha.pk))

    def test_an_ambiguous_zev_name_is_refused_with_the_ids_to_choose_from(self):
        twin = Zev.objects.create(name="Alpha", owner=self.world.owner)
        with self.assertRaises(CommandError) as raised:
            run("openzev_backup", "--path", self.dest_dir.name, "--zev", "Alpha")
        self.assertIn(str(twin.pk), str(raised.exception))
        self.assertFalse(BackupJob.objects.exists())

    def test_unknown_zev_destination_and_bad_paths_are_refused_before_anything_runs(self):
        bad = {
            "unknown zev name": (["--path", self.dest_dir.name, "--zev", "Nope"], "No ZEV named"),
            "unknown zev id": (["--path", self.dest_dir.name, "--zev", "00000000-0000-0000-0000-000000000000"], "No ZEV with id"),
            "unknown destination": (["--destination", "missing"], "No backup destination"),
            "relative path": (["--path", "relative/dir"], "absolute"),
            "media root": (["--path", settings.MEDIA_ROOT], "MEDIA_ROOT"),
        }
        for label, (args, expected) in bad.items():
            with self.subTest(label), self.assertRaises(CommandError) as raised:
                run("openzev_backup", *args)
            self.assertIn(expected, str(raised.exception))
        self.assertFalse(BackupJob.objects.exists())

    def test_a_disabled_destination_is_refused(self):
        BackupDestination.objects.create(name="off", kind="local", path=self.dest_dir.name, enabled=False)
        with self.assertRaises(CommandError) as raised:
            run("openzev_backup", "--destination", "off")
        self.assertIn("disabled", str(raised.exception))

    def test_one_of_destination_or_path_is_required(self):
        with self.assertRaises(CommandError):
            run("openzev_backup")
        with self.assertRaises(CommandError):
            run("openzev_backup", "--path", self.dest_dir.name, "--destination", "x")

    def test_a_failure_exits_non_zero_with_the_safe_message_and_marks_the_job_failed(self):
        with mock.patch("backups.tasks.archive.build_archive", side_effect=RuntimeError("password=hunter2")):
            with self.assertLogs("backups.tasks", level="ERROR"), self.assertRaises(CommandError) as raised:
                run("openzev_backup", "--path", self.dest_dir.name)
        self.assertNotIn("hunter2", str(raised.exception))
        self.assertEqual(BackupJob.objects.get().status, BackupJobStatus.FAILED)
        self.assertEqual(self.archives(), [])

    @override_settings(BACKUP_ENCRYPTION_KEYS=["too-short"])
    def test_a_rejected_key_stops_the_command_before_a_job_is_created(self):
        with self.assertRaises(CommandError) as raised:
            run("openzev_backup", "--path", self.dest_dir.name)
        self.assertIn("shorter than", str(raised.exception))
        self.assertFalse(BackupJob.objects.exists())

    def test_the_run_is_audited_as_a_management_command(self):
        run("openzev_backup", "--path", self.dest_dir.name)
        event = AuditEvent.objects.get(action_type="backup.completed")
        self.assertEqual(event.source, AuditEventSource.MANAGEMENT_COMMAND)

    def test_a_pdf_missing_from_storage_is_called_out_on_stderr(self):
        from django.core.files.storage import default_storage
        from invoices.models import Invoice

        default_storage.delete(Invoice.objects.get(zev=self.world.alpha).pdf_file.name)
        _, err = run("openzev_backup", "--path", self.dest_dir.name)
        self.assertIn("1 invoice PDF(s)", err)

    def test_it_needs_no_broker(self):
        """The command must work where only the database is up."""
        with mock.patch("backups.tasks.run_backup_job.delay", side_effect=AssertionError("broker used")):
            run("openzev_backup", "--path", self.dest_dir.name)


class VerifyCommandTests(CommandTestCase):
    def backup(self):
        run("openzev_backup", "--path", self.dest_dir.name)
        return self.archives()[0]

    def test_a_good_backup_verifies_and_is_summarised(self):
        path = self.backup()
        out, _ = run("openzev_backup_verify", str(path))
        self.assertIn("Backup verified.", out)
        self.assertIn("Alpha, Beta", out)
        self.assertIn("encrypted  NO", out)

    @override_settings(BACKUP_ENCRYPTION_KEYS=[KEY])
    def test_an_encrypted_backup_verifies_with_its_key_and_shows_the_fingerprint(self):
        path = self.backup()
        out, _ = run("openzev_backup_verify", str(path))
        self.assertIn(f"yes (key {crypto.key_fingerprint(KEY)})", out)

    @override_settings(BACKUP_ENCRYPTION_KEYS=[KEY])
    def test_an_encrypted_backup_cannot_be_verified_without_its_key(self):
        path = self.backup()
        with override_settings(BACKUP_ENCRYPTION_KEYS=[]):
            with self.assertRaises(CommandError) as raised:
                run("openzev_backup_verify", str(path))
        self.assertIn(crypto.key_fingerprint(KEY), str(raised.exception))

    def test_a_corrupted_backup_fails_and_lists_what_is_wrong(self):
        path = self.backup()
        with zipfile.ZipFile(path) as source:
            members = {name: source.read(name) for name in source.namelist()}
        target = next(n for n in members if n.endswith("/participants.jsonl"))
        members[target] = members[target].replace(b"Alice", b"Mallo")
        with zipfile.ZipFile(path, "w") as rewritten:
            for name, payload in members.items():
                rewritten.writestr(name, payload)
        out, err = io.StringIO(), io.StringIO()
        with self.assertRaises(CommandError) as raised:
            call_command("openzev_backup_verify", str(path), stdout=out, stderr=err)
        self.assertIn("failed verification", str(raised.exception))
        self.assertIn("checksum mismatch", err.getvalue())

    def test_a_missing_file_is_a_clear_error(self):
        with self.assertRaises(CommandError) as raised:
            run("openzev_backup_verify", "/nonexistent/backup.zip")
        self.assertIn("Cannot read", str(raised.exception))

    def test_a_file_that_is_not_a_backup_is_refused(self):
        junk = Path(self.dest_dir.name) / "junk.zip"
        junk.write_bytes(b"not a zip")
        with self.assertRaises(CommandError):
            run("openzev_backup_verify", str(junk))
