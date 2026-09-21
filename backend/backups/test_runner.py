"""The job lifecycle: what a run records, what it cleans up, and how it fails."""

import io
import os
import tempfile
from pathlib import Path
from unittest import mock

from billiard.exceptions import SoftTimeLimitExceeded
from django.core.files.storage import default_storage
from django.test import TestCase, override_settings

from audit.models import AuditActionCategory, AuditEvent, AuditEventSource, AuditEventStatus
from backups import archive, crypto, tasks
from backups.fixtures import build_world
from backups.models import BackupDestination, BackupJob, BackupJobScope, BackupJobStatus
from backups.test_destinations import FakeS3
from invoices.models import Invoice

KEY = "R" * 40


class RunnerTestCase(TestCase):
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
        self.destination = BackupDestination.objects.create(name="disk", kind="local", path=self.dest_dir.name)

    def job(self, **kwargs):
        return BackupJob.objects.create(destination=self.destination, **kwargs)

    def assertNoLeftovers(self):
        self.assertEqual(os.listdir(self.work_dir.name), [], "the work directory must be empty afterwards")

    def audit(self, action_type):
        return list(AuditEvent.objects.filter(action_type=action_type, target_type="backups.BackupJob"))


class CompletedBackupTests(RunnerTestCase):
    def test_a_completed_job_records_where_the_archive_is_and_what_it_holds(self):
        job = self.job()
        result = tasks.execute_backup_job(job.pk)
        job.refresh_from_db()

        self.assertEqual(job.status, BackupJobStatus.COMPLETED)
        self.assertIsNotNone(job.started_at)
        self.assertIsNotNone(job.completed_at)
        self.assertEqual(job.error_message, "")
        self.assertTrue(Path(job.archive_location).is_file())
        self.assertEqual(job.archive_location, result["location"])
        self.assertEqual(job.archive_bytes, Path(job.archive_location).stat().st_size)
        self.assertEqual(job.manifest_json["kind"], "backup")
        self.assertEqual({z["name"] for z in job.manifest_json["zevs"]}, {"Alpha", "Beta"})

    def test_the_recorded_checksum_is_the_checksum_of_the_stored_bytes(self):
        import hashlib

        job = self.job()
        tasks.execute_backup_job(job.pk)
        job.refresh_from_db()
        self.assertEqual(job.archive_sha256, hashlib.sha256(Path(job.archive_location).read_bytes()).hexdigest())

    def test_the_stored_archive_passes_verification(self):
        job = self.job()
        tasks.execute_backup_job(job.pk)
        job.refresh_from_db()
        with open(job.archive_location, "rb") as handle:
            self.assertGreater(archive.verify_archive(handle)["records"], 0)

    def test_the_archive_name_carries_the_job_id_and_is_safe_as_a_key(self):
        job = self.job()
        tasks.execute_backup_job(job.pk)
        job.refresh_from_db()
        self.assertRegex(job.archive_name, r"^openzev-backup-[a-z0-9-]+-\d{8}-\d{6}-" + str(job.pk)[:8] + r"\.zip$")

    @override_settings(INSTANCE_NAME="Höfli / Prod <1>")
    def test_an_instance_name_is_slugified_into_the_file_name(self):
        job = self.job()
        tasks.execute_backup_job(job.pk)
        job.refresh_from_db()
        self.assertRegex(job.archive_name, r"^openzev-backup-hofli-prod-1-")

    def test_a_zev_job_backs_up_only_that_zev(self):
        job = self.job(scope=BackupJobScope.ZEV, zev=self.world.beta)
        tasks.execute_backup_job(job.pk)
        job.refresh_from_db()
        self.assertEqual([z["name"] for z in job.manifest_json["zevs"]], ["Beta"])
        self.assertIn("openzev-backup-zev-beta-", job.archive_name)

    def test_nothing_is_left_in_the_work_directory(self):
        tasks.execute_backup_job(self.job().pk)
        self.assertNoLeftovers()

    def test_a_pdf_missing_from_storage_is_noted_and_the_backup_still_completes(self):
        invoice = Invoice.objects.get(zev=self.world.alpha)
        default_storage.delete(invoice.pdf_file.name)
        job = self.job()
        tasks.execute_backup_job(job.pk)
        job.refresh_from_db()
        self.assertEqual(job.status, BackupJobStatus.COMPLETED)
        alpha = next(z for z in job.manifest_json["zevs"] if z["name"] == "Alpha")
        self.assertEqual(alpha["media"]["missing"], [invoice.pdf_file.name])


class EncryptionTests(RunnerTestCase):
    @override_settings(BACKUP_ENCRYPTION_KEYS=[KEY])
    def test_a_configured_key_encrypts_the_archive_and_says_so(self):
        job = self.job()
        result = tasks.execute_backup_job(job.pk)
        job.refresh_from_db()
        self.assertTrue(job.encrypted)
        self.assertEqual(job.encryption_key_fingerprint, crypto.key_fingerprint(KEY))
        self.assertTrue(job.archive_name.endswith(".zip.enc"))
        self.assertTrue(result["encrypted"])
        raw = Path(job.archive_location).read_bytes()
        self.assertTrue(raw.startswith(crypto.MAGIC))
        self.assertNotIn(b"plaintext-client-secret", raw)
        self.assertNoLeftovers()

    @override_settings(BACKUP_ENCRYPTION_KEYS=[KEY])
    def test_an_encrypted_archive_verifies_and_names_its_key_in_the_manifest(self):
        job = self.job()
        tasks.execute_backup_job(job.pk)
        job.refresh_from_db()
        with open(job.archive_location, "rb") as handle:
            result = archive.verify_archive(handle)
        self.assertEqual(result["manifest"]["encryption"]["key_fingerprint"], crypto.key_fingerprint(KEY))
        self.assertEqual(job.manifest_json["encryption"], result["manifest"]["encryption"])

    def test_without_a_key_the_backup_runs_and_is_flagged_unencrypted(self):
        job = self.job()
        tasks.execute_backup_job(job.pk)
        job.refresh_from_db()
        self.assertFalse(job.encrypted)
        self.assertEqual(job.encryption_key_fingerprint, "")
        self.assertTrue(job.archive_name.endswith(".zip"))
        self.assertIn("NOT encrypted", self.audit("backup.completed")[0].summary)

    @override_settings(BACKUP_ENCRYPTION_KEYS=["too-short"])
    def test_a_rejected_key_fails_the_job_with_the_reason(self):
        job = self.job()
        with self.assertRaises(crypto.BackupKeyRejected):
            tasks.execute_backup_job(job.pk)
        job.refresh_from_db()
        self.assertEqual(job.status, BackupJobStatus.FAILED)
        self.assertIn("shorter than", job.error_message)
        self.assertNoLeftovers()


class FailureTests(RunnerTestCase):
    def test_a_missing_destination_fails_the_job(self):
        job = BackupJob.objects.create(destination=None)
        with self.assertRaises(tasks.DestinationError):
            tasks.execute_backup_job(job.pk)
        job.refresh_from_db()
        self.assertEqual(job.status, BackupJobStatus.FAILED)
        self.assertIn("no destination", job.error_message)

    def test_an_unwritable_destination_fails_with_a_readable_message(self):
        blocker = Path(self.dest_dir.name) / "file"
        blocker.write_text("x")
        self.destination.path = str(blocker / "child")
        self.destination.save()
        job = self.job()
        with self.assertRaises(tasks.DestinationError):
            tasks.execute_backup_job(job.pk)
        job.refresh_from_db()
        self.assertEqual(job.status, BackupJobStatus.FAILED)
        self.assertIn("Could not write", job.error_message)
        self.assertNoLeftovers()

    def test_an_unexpected_error_is_generic_on_the_row_and_detailed_only_in_the_log(self):
        job = self.job()
        with mock.patch("backups.tasks.archive.build_archive", side_effect=RuntimeError("db password=hunter2")):
            with self.assertLogs("backups.tasks", level="ERROR") as logs, self.assertRaises(RuntimeError):
                tasks.execute_backup_job(job.pk)
        job.refresh_from_db()
        self.assertEqual(job.status, BackupJobStatus.FAILED)
        self.assertEqual(job.error_message, tasks._GENERIC_FAILURE)
        self.assertNotIn("hunter2", job.error_message)
        self.assertNotIn("hunter2", " ".join(e.summary for e in self.audit("backup.failed")))
        self.assertIn("hunter2", "\n".join(logs.output))
        self.assertNoLeftovers()

    def test_a_soft_time_limit_is_recorded_as_a_clean_failure_then_re_raised(self):
        job = self.job()
        with mock.patch("backups.tasks.archive.build_archive", side_effect=SoftTimeLimitExceeded()):
            with self.assertRaises(SoftTimeLimitExceeded):
                tasks.execute_backup_job(job.pk)
        job.refresh_from_db()
        self.assertEqual(job.status, BackupJobStatus.FAILED)
        self.assertEqual(job.error_message, tasks._INTERRUPTED)
        self.assertNoLeftovers()

    def test_a_failed_job_records_no_artifact(self):
        job = self.job()
        with mock.patch("backups.tasks.archive.build_archive", side_effect=RuntimeError("x")):
            with self.assertRaises(RuntimeError), self.assertLogs("backups.tasks", level="ERROR"):
                tasks.execute_backup_job(job.pk)
        job.refresh_from_db()
        self.assertEqual((job.archive_location, job.archive_sha256, job.archive_bytes), ("", "", None))


class ClaimTests(RunnerTestCase):
    def test_a_job_runs_once_even_if_delivered_twice(self):
        job = self.job()
        first = tasks.execute_backup_job(job.pk)
        second = tasks.execute_backup_job(job.pk)
        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertEqual(len(os.listdir(self.dest_dir.name)), 1)

    def test_a_job_that_is_already_running_is_not_claimed(self):
        job = self.job(status=BackupJobStatus.RUNNING)
        self.assertIsNone(tasks.execute_backup_job(job.pk))

    def test_a_late_completion_does_not_resurrect_a_job_someone_already_failed(self):
        job = self.job()
        real_store = tasks.store_archive

        def fail_midway_then_store(*args, **kwargs):
            BackupJob.objects.filter(pk=job.pk).update(status=BackupJobStatus.FAILED, error_message="swept")
            return real_store(*args, **kwargs)

        with mock.patch("backups.tasks.store_archive", side_effect=fail_midway_then_store):
            with self.assertLogs("backups.tasks", level="WARNING"):
                result = tasks.execute_backup_job(job.pk)
        self.assertIsNone(result)
        job.refresh_from_db()
        self.assertEqual((job.status, job.error_message), (BackupJobStatus.FAILED, "swept"))
        self.assertEqual(job.archive_location, "")


class AuditTests(RunnerTestCase):
    def test_started_and_completed_events_are_recorded_in_the_system_category(self):
        job = self.job()
        tasks.execute_backup_job(job.pk)
        started, completed = self.audit("backup.started")[0], self.audit("backup.completed")[0]
        self.assertEqual(started.status, AuditEventStatus.STARTED)
        self.assertEqual(completed.status, AuditEventStatus.SUCCESS)
        self.assertEqual(completed.action_category, AuditActionCategory.SYSTEM)
        self.assertEqual(completed.target_id, str(job.pk))
        self.assertEqual(completed.source, AuditEventSource.CELERY)

    def test_the_completed_event_carries_counts_but_no_contents(self):
        tasks.execute_backup_job(self.job().pk)
        metadata = self.audit("backup.completed")[0].metadata_json
        self.assertEqual(metadata["zevs"], 2)
        self.assertGreater(metadata["records"], 0)
        self.assertEqual(metadata["media_files"], 2)
        self.assertEqual(metadata["encrypted"], False)
        self.assertEqual(metadata["destination"], "disk")

    def test_the_command_line_source_is_recorded(self):
        tasks.execute_backup_job(self.job().pk, source=AuditEventSource.MANAGEMENT_COMMAND)
        self.assertEqual(self.audit("backup.completed")[0].source, AuditEventSource.MANAGEMENT_COMMAND)

    def test_a_failure_is_audited_as_failed(self):
        job = self.job()
        with mock.patch("backups.tasks.archive.build_archive", side_effect=RuntimeError("x")):
            with self.assertRaises(RuntimeError), self.assertLogs("backups.tasks", level="ERROR"):
                tasks.execute_backup_job(job.pk)
        self.assertEqual(self.audit("backup.failed")[0].status, AuditEventStatus.FAILED)

    def test_a_broken_audit_write_does_not_fail_a_completed_backup(self):
        job = self.job()
        with mock.patch("backups.tasks.record_audit_event", side_effect=RuntimeError("audit down")):
            with self.assertLogs("backups.tasks", level="ERROR"):
                result = tasks.execute_backup_job(job.pk)
        self.assertIsNotNone(result)
        job.refresh_from_db()
        self.assertEqual(job.status, BackupJobStatus.COMPLETED)

    def test_a_zev_backup_is_attributed_to_its_zev(self):
        job = self.job(scope=BackupJobScope.ZEV, zev=self.world.alpha)
        tasks.execute_backup_job(job.pk)
        self.assertEqual(self.audit("backup.completed")[0].zev_id, self.world.alpha.pk)


class S3RunnerTests(RunnerTestCase):
    def test_the_archive_is_uploaded_to_the_bucket_and_the_location_recorded(self):
        fake = FakeS3()
        bucket = BackupDestination.objects.create(name="cloud", kind="s3", bucket="openzev-prod", prefix="nightly")
        job = BackupJob.objects.create(destination=bucket)
        with mock.patch("backups.storage.s3_client", return_value=fake):
            tasks.execute_backup_job(job.pk)
        job.refresh_from_db()

        self.assertEqual(job.status, BackupJobStatus.COMPLETED)
        self.assertEqual(job.archive_location, f"s3://openzev-prod/nightly/{job.archive_name}")
        upload = fake.uploads[0]
        self.assertEqual(upload["key"], f"nightly/{job.archive_name}")
        # What reached the bucket is exactly what was checksummed and recorded.
        import hashlib

        self.assertEqual(hashlib.sha256(upload["bytes"]).hexdigest(), job.archive_sha256)
        self.assertEqual(len(upload["bytes"]), job.archive_bytes)
        self.assertNoLeftovers()

    def test_a_provider_error_fails_the_job_with_a_safe_message(self):
        from botocore.exceptions import ClientError

        bucket = BackupDestination.objects.create(name="cloud", kind="s3", bucket="openzev-prod")
        job = BackupJob.objects.create(destination=bucket)
        fake = FakeS3()
        fake.upload_file = mock.Mock(side_effect=ClientError({"Error": {"Code": "AccessDenied", "Message": "LEAK"}}, "PutObject"))
        with mock.patch("backups.storage.s3_client", return_value=fake):
            with self.assertRaises(tasks.DestinationError), self.assertLogs("backups.tasks", level="ERROR"):
                tasks.execute_backup_job(job.pk)
        job.refresh_from_db()
        self.assertEqual(job.status, BackupJobStatus.FAILED)
        self.assertIn("Access denied", job.error_message)
        self.assertNotIn("LEAK", job.error_message)


class CeleryTaskTests(RunnerTestCase):
    def test_the_celery_task_runs_the_job(self):
        job = self.job()
        tasks.run_backup_job.apply(args=[str(job.pk)]).get()
        job.refresh_from_db()
        self.assertEqual(job.status, BackupJobStatus.COMPLETED)

    def test_the_task_has_time_limits_with_the_hard_limit_above_the_soft_one(self):
        self.assertGreater(tasks._HARD_LIMIT_S, tasks._SOFT_LIMIT_S)
        self.assertEqual(tasks.run_backup_job.soft_time_limit, tasks._SOFT_LIMIT_S)
        self.assertEqual(tasks.run_backup_job.time_limit, tasks._HARD_LIMIT_S)


class WholeArchiveIsNeverInMemoryTests(RunnerTestCase):
    def test_the_runner_hands_the_builder_a_file_not_a_buffer(self):
        """``ExportResult.payload: bytes`` is exactly what a backup must not copy."""
        seen = {}
        real = archive.build_archive

        def spy(fileobj, **kwargs):
            seen["type"] = type(fileobj)
            return real(fileobj, **kwargs)

        with mock.patch("backups.tasks.archive.build_archive", side_effect=spy):
            tasks.execute_backup_job(self.job().pk)
        self.assertNotEqual(seen["type"], io.BytesIO)
        self.assertTrue(issubclass(seen["type"], io.BufferedIOBase))
