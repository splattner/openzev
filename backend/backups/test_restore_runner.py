"""The restore job lifecycle: what a run records, and that a failed one changes nothing."""

import io
import os
import tempfile
import zipfile
from pathlib import Path
from unittest import mock

from billiard.exceptions import SoftTimeLimitExceeded
from django.core.files.storage import default_storage
from django.test import TestCase, override_settings

from audit.models import AuditEvent, AuditEventSource
from backups import archive, crypto, restore, restore_zev, storage, tasks
from backups.fixtures import PDF_BYTES, build_world
from backups.models import BackupDestination, BackupJob, BackupJobScope, BackupJobStatus, BackupJobTrigger, RestoreJob
from backups.test_destinations import FakeS3
from backups.test_restore_zev import zev_rows
from exports.models import ExportJob
from invoices.models import Invoice
from metering.models import MeterReading
from zev.models import Participant, Zev

KEY = "S" * 40


class RestoreRunnerTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.world = build_world()
        cls.alpha_id = cls.world.alpha.pk
        cls.alpha_pdf = cls.world.alpha_invoice.pdf_file.name

    def setUp(self):
        self.dest_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dest_dir.cleanup)
        self.work_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.work_dir.cleanup)
        override = override_settings(BACKUP_WORK_DIR=self.work_dir.name)
        override.enable()
        self.addCleanup(override.disable)
        self.addCleanup(self._put_pdf_back)
        self.destination = BackupDestination.objects.create(name="disk", kind="local", path=self.dest_dir.name)
        self.backup = self.take_backup()
        self.original = zev_rows(self.alpha_id)

    def _put_pdf_back(self):
        default_storage.delete(self.alpha_pdf)
        default_storage.save(self.alpha_pdf, io.BytesIO(PDF_BYTES))

    def take_backup(self, **kwargs) -> BackupJob:
        job = BackupJob.objects.create(destination=self.destination, requester=self.world.admin, **kwargs)
        tasks.execute_backup_job(job.pk)
        job.refresh_from_db()
        return job

    def restore_job(self, **kwargs) -> RestoreJob:
        defaults = {
            "target_zev_id": self.alpha_id, "target_zev_name": "Alpha", "source_backup": self.backup,
            "requester": self.world.admin, "dry_run": False,
        }
        return RestoreJob.objects.create(**{**defaults, **kwargs})

    def damage(self):
        Zev.objects.filter(pk=self.alpha_id).update(name="Damaged")
        Participant.objects.filter(zev_id=self.alpha_id, first_name="Alice").delete()
        MeterReading.objects.filter(metering_point__zev_id=self.alpha_id).delete()

    def events(self, action_type):
        return list(AuditEvent.objects.filter(action_type=action_type, target_type="backups.RestoreJob"))

    def assertNoLeftovers(self):
        self.assertEqual(os.listdir(self.work_dir.name), [], "the work directory must be empty afterwards")


class CompletedRestoreTests(RestoreRunnerTestCase):
    def test_a_restore_brings_the_community_back_and_records_the_plan(self):
        self.damage()
        job = self.restore_job()
        plan = tasks.execute_restore_job(job.pk)
        job.refresh_from_db()

        self.assertEqual(job.status, BackupJobStatus.COMPLETED)
        self.assertEqual(job.error_message, "")
        self.assertEqual(zev_rows(self.alpha_id), self.original)
        self.assertEqual(job.plan_json, plan)
        self.assertGreater(job.plan_json["restored"]["metering.MeterReading"], 0)
        self.assertEqual(job.target_zev_name, "Alpha")
        self.assertNoLeftovers()

    def test_a_safety_backup_of_the_damaged_state_is_taken_first_and_linked(self):
        self.damage()
        job = self.restore_job()
        tasks.execute_restore_job(job.pk)
        job.refresh_from_db()

        safety = job.safety_backup
        self.assertIsNotNone(safety)
        self.assertEqual((safety.scope, safety.trigger, safety.status), ("zev", "pre_restore", "completed"))
        self.assertEqual(safety.zev_id, self.alpha_id)
        self.assertEqual(job.plan_json["safety_backup_id"], str(safety.pk))
        # It holds the state *before* the restore, not after.
        self.assertEqual(safety.manifest_json["zevs"][0]["name"], "Damaged")
        self.assertEqual(safety.manifest_json["zevs"][0]["counts"]["readings"], 0)
        self.assertEqual(safety.destination_id, self.destination.pk)

    def test_the_safety_backup_can_undo_the_restore(self):
        self.damage()
        damaged = zev_rows(self.alpha_id)
        first = self.restore_job()
        tasks.execute_restore_job(first.pk)
        first.refresh_from_db()
        self.assertNotEqual(zev_rows(self.alpha_id), damaged)

        undo = self.restore_job(source_backup=first.safety_backup, force=True)
        tasks.execute_restore_job(undo.pk)
        self.assertEqual(zev_rows(self.alpha_id), damaged)

    def test_a_dry_run_previews_without_writing_or_backing_up(self):
        self.damage()
        damaged = zev_rows(self.alpha_id)
        before = BackupJob.objects.count()
        job = self.restore_job(dry_run=True)
        plan = tasks.execute_restore_job(job.pk)
        job.refresh_from_db()
        self.assertEqual(job.status, BackupJobStatus.COMPLETED)
        self.assertEqual(zev_rows(self.alpha_id), damaged)
        self.assertEqual(BackupJob.objects.count(), before)
        self.assertIsNone(job.safety_backup)
        self.assertIsNone(plan["restored"])
        self.assertEqual(len(self.events("restore.previewed")), 1)
        self.assertEqual(self.events("restore.started"), [])

    def test_a_restore_is_audited_started_and_completed_with_what_it_did(self):
        self.damage()
        job = self.restore_job()
        tasks.execute_restore_job(job.pk, source=AuditEventSource.CELERY)
        started = self.events("restore.started")
        done = AuditEvent.objects.get(action_type="zev.restored")
        self.assertEqual(len(started), 1)
        self.assertEqual(started[0].status, "started")
        self.assertEqual(done.zev_id, self.alpha_id)
        self.assertEqual(done.actor_user_id, self.world.admin.pk)
        self.assertEqual(done.metadata_json["source_backup"], str(self.backup.pk))
        self.assertFalse(done.metadata_json["force"])
        job.refresh_from_db()
        self.assertEqual(done.metadata_json["safety_backup"], str(job.safety_backup_id))
        self.assertGreater(done.metadata_json["sections"]["metering.MeterReading"], 0)

    def test_the_restore_leaves_every_earlier_audit_event_as_it_was(self):
        events = {e.pk: (e.zev_id, e.summary, e.created_at) for e in AuditEvent.objects.all()}
        self.damage()
        job = self.restore_job()
        tasks.execute_restore_job(job.pk)
        after = {e.pk: (e.zev_id, e.summary, e.created_at) for e in AuditEvent.objects.filter(pk__in=events)}
        self.assertEqual(after, events)

    def test_a_broken_audit_write_does_not_undo_a_finished_restore(self):
        self.damage()
        job = self.restore_job()
        with mock.patch.object(tasks, "record_audit_event", side_effect=RuntimeError("audit down")):
            tasks.execute_restore_job(job.pk)
        job.refresh_from_db()
        self.assertEqual(job.status, BackupJobStatus.COMPLETED)
        self.assertEqual(zev_rows(self.alpha_id), self.original)


class RefusedRestoreTests(RestoreRunnerTestCase):
    def test_a_refused_restore_fails_with_the_plan_and_changes_nothing(self):
        self.damage()
        damaged = zev_rows(self.alpha_id)
        ExportJob.objects.create(zev_id=self.alpha_id, requester=self.world.owner, status="running")
        job = self.restore_job()
        before = BackupJob.objects.count()

        with self.assertRaises(restore_zev.RestoreRefused):
            tasks.execute_restore_job(job.pk)

        job.refresh_from_db()
        self.assertEqual(job.status, BackupJobStatus.FAILED)
        self.assertIn("refused", job.error_message)
        self.assertEqual(job.plan_json["conflicts"][0]["kind"], "export_in_progress")
        self.assertEqual(zev_rows(self.alpha_id), damaged)
        self.assertEqual(BackupJob.objects.count(), before, "no safety backup for a refused restore")
        self.assertEqual(self.events("restore.failed")[0].metadata_json["conflicts"], ["export_in_progress"])

    def test_force_is_recorded_and_lets_an_overridable_conflict_through(self):
        Invoice.objects.filter(pk=self.world.alpha_invoice.pk).update(status="paid")
        raw_before = Invoice.objects.get(pk=self.world.alpha_invoice.pk).status
        self.assertEqual(raw_before, "paid")
        # The backup was taken while it was 'sent'; rolling that back needs force.
        refused = self.restore_job()
        with self.assertRaises(restore_zev.RestoreRefused):
            tasks.execute_restore_job(refused.pk)

        forced = self.restore_job(force=True)
        tasks.execute_restore_job(forced.pk)
        forced.refresh_from_db()
        self.assertEqual(forced.status, BackupJobStatus.COMPLETED)
        self.assertEqual(Invoice.objects.get(pk=self.world.alpha_invoice.pk).status, "sent")
        done = AuditEvent.objects.get(action_type="zev.restored")
        self.assertTrue(done.metadata_json["force"])
        self.assertEqual(done.metadata_json["overridden"], ["sent_invoice_reverted"])


class FailedRestoreTests(RestoreRunnerTestCase):
    def test_a_failing_safety_backup_stops_the_restore_before_any_write(self):
        self.damage()
        damaged = zev_rows(self.alpha_id)
        job = self.restore_job()
        def failing(job_id, **kwargs):
            BackupJob.objects.filter(pk=job_id).update(status="running")
            tasks._mark_failed(BackupJob.objects.get(pk=job_id), "Could not write to /nowhere: permission denied.")
            raise storage.DestinationError("permission denied")

        with mock.patch.object(tasks, "execute_backup_job", failing), self.assertRaises(restore.RestoreError):
            tasks.execute_restore_job(job.pk)
        job.refresh_from_db()
        self.assertEqual(job.status, BackupJobStatus.FAILED)
        self.assertIn("safety backup failed", job.error_message)
        self.assertIn("permission denied", job.error_message)
        self.assertEqual(zev_rows(self.alpha_id), damaged)

    def test_no_place_to_write_the_safety_backup_is_a_clear_refusal(self):
        self.damage()
        damaged = zev_rows(self.alpha_id)
        # A file given on the command line has no destination of its own to fall back on.
        job = self.restore_job(source_backup=None, source_description=self.backup.archive_location)
        with self.assertRaisesMessage(restore.RestoreError, "nowhere to write the safety backup"):
            tasks.execute_restore_job(job.pk, archive_file=self.backup.archive_location)
        job.refresh_from_db()
        self.assertEqual(job.status, BackupJobStatus.FAILED)
        self.assertEqual(zev_rows(self.alpha_id), damaged)

    def test_an_explicit_safety_destination_is_used(self):
        other_dir = tempfile.TemporaryDirectory()
        self.addCleanup(other_dir.cleanup)
        other = BackupDestination.objects.create(name="other", kind="local", path=other_dir.name)
        self.damage()
        job = self.restore_job(safety_destination=other)
        tasks.execute_restore_job(job.pk)
        job.refresh_from_db()
        self.assertEqual(job.safety_backup.destination_id, other.pk)
        self.assertTrue(list(Path(other_dir.name).glob("*.zip")))

    def test_an_unexpected_error_is_generic_on_the_row_and_detailed_only_in_the_log(self):
        job = self.restore_job()
        with (
            mock.patch.object(tasks, "restore_zev", side_effect=RuntimeError("secret internal detail")),
            self.assertLogs("backups.tasks", level="ERROR"),
            self.assertRaises(RuntimeError),
        ):
            tasks.execute_restore_job(job.pk)
        job.refresh_from_db()
        self.assertEqual(job.status, BackupJobStatus.FAILED)
        self.assertNotIn("secret internal detail", job.error_message)
        self.assertIn("Nothing was changed", job.error_message)
        self.assertNoLeftovers()

    def test_a_soft_time_limit_fails_the_job(self):
        job = self.restore_job()
        with (
            mock.patch.object(tasks, "restore_zev", side_effect=SoftTimeLimitExceeded()),
            self.assertLogs("backups.tasks", level="ERROR"),
            self.assertRaises(SoftTimeLimitExceeded),
        ):
            tasks.execute_restore_job(job.pk)
        job.refresh_from_db()
        self.assertIn("time limit", job.error_message)

    def test_a_backup_file_that_is_gone_fails_with_a_readable_reason(self):
        Path(self.backup.archive_location).unlink()
        job = self.restore_job()
        with self.assertRaisesMessage(storage.DestinationError, "no longer available"):
            tasks.execute_restore_job(job.pk)
        job.refresh_from_db()
        self.assertEqual(job.error_message, "The backup file is no longer available.")

    def test_a_backup_whose_row_was_deleted_fails_with_a_readable_reason(self):
        job = self.restore_job()
        RestoreJob.objects.filter(pk=job.pk).update(source_backup=None)
        with self.assertRaisesMessage(restore.RestoreError, "no longer exists"):
            tasks.execute_restore_job(job.pk)

    def test_a_damaged_archive_stores_the_verification_failures_in_the_plan(self):
        path = Path(self.backup.archive_location)
        with zipfile.ZipFile(path) as zf:
            members = {name: zf.read(name) for name in zf.namelist()}
        members["stowaway.txt"] = b"x"
        with zipfile.ZipFile(path, "w") as zf:
            for name, data in members.items():
                zf.writestr(name, data)
        job = self.restore_job()
        with self.assertRaises(archive.ArchiveError):
            tasks.execute_restore_job(job.pk)
        job.refresh_from_db()
        self.assertIn("stowaway.txt", job.plan_json["verification_failures"][0])

    def test_a_job_runs_once_if_delivered_twice(self):
        self.damage()
        job = self.restore_job()
        self.assertIsNotNone(tasks.execute_restore_job(job.pk))
        self.assertIsNone(tasks.execute_restore_job(job.pk))

    def test_a_late_completion_does_not_resurrect_a_job_someone_failed(self):
        job = self.restore_job()

        def fail_meanwhile(*args, **kwargs):
            RestoreJob.objects.filter(pk=job.pk).update(status=BackupJobStatus.FAILED, error_message="cancelled")
            return mock.Mock(plan={
                "zev": {"name": "Alpha"}, "blocked": False, "conflicts": [], "restored": {}, "safety_backup_id": None,
                "accounts": {"relink": 0, "missing": []}, "backup": {"created_at": "x"},
            })

        with mock.patch.object(tasks, "restore_zev", side_effect=fail_meanwhile):
            self.assertIsNone(tasks.execute_restore_job(job.pk))
        job.refresh_from_db()
        self.assertEqual((job.status, job.error_message), ("failed", "cancelled"))


class SourceTests(RestoreRunnerTestCase):
    def test_an_encrypted_backup_restores_with_its_key_and_is_refused_without_it(self):
        with override_settings(BACKUP_ENCRYPTION_KEYS=[KEY]):
            sealed = self.take_backup()
        self.assertTrue(sealed.encrypted)
        self.damage()

        job = self.restore_job(source_backup=sealed)
        with override_settings(BACKUP_ENCRYPTION_KEYS=[]), self.assertRaises(crypto.BackupCryptoError):
            tasks.execute_restore_job(job.pk)
        job.refresh_from_db()
        self.assertIn(sealed.encryption_key_fingerprint, job.error_message)

        job = self.restore_job(source_backup=sealed)
        with override_settings(BACKUP_ENCRYPTION_KEYS=[KEY]):
            tasks.execute_restore_job(job.pk)
        self.assertEqual(zev_rows(self.alpha_id), self.original)

    def test_a_backup_in_s3_is_downloaded_and_restored(self):
        fake = FakeS3()
        bucket = BackupDestination.objects.create(name="bucket", kind="s3", bucket="bkt", prefix="openzev")
        with mock.patch("backups.storage.s3_client", return_value=fake):
            job = BackupJob.objects.create(destination=bucket)
            tasks.execute_backup_job(job.pk)
            job.refresh_from_db()
            self.assertTrue(job.archive_location.startswith("s3://bkt/openzev/"))
            self.damage()
            restore_job = self.restore_job(source_backup=job, safety_destination=self.destination)
            tasks.execute_restore_job(restore_job.pk)
        self.assertEqual(zev_rows(self.alpha_id), self.original)
        self.assertNoLeftovers()

    def test_a_local_file_can_stand_in_for_the_backup_job(self):
        self.damage()
        job = self.restore_job(source_backup=None, source_description=self.backup.archive_location)
        tasks.execute_restore_job(job.pk, archive_file=self.backup.archive_location, safety_destination=self.destination)
        self.assertEqual(zev_rows(self.alpha_id), self.original)
        # A destination given directly is not a saved one: no foreign key on the safety backup.
        job.refresh_from_db()
        self.assertIsNone(job.safety_backup.destination_id)

    def test_the_job_trigger_of_the_safety_backup_is_distinguishable_from_a_manual_one(self):
        self.damage()
        job = self.restore_job()
        tasks.execute_restore_job(job.pk)
        self.assertEqual(BackupJob.objects.filter(trigger=BackupJobTrigger.PRE_RESTORE).count(), 1)
        self.assertEqual(BackupJob.objects.filter(scope=BackupJobScope.ZEV).count(), 1)


class FetchFromDestinationTests(RestoreRunnerTestCase):
    def test_a_local_location_outside_its_destination_is_never_followed(self):
        outside = Path(self.work_dir.name) / "elsewhere.zip"
        outside.write_bytes(b"x")
        with self.assertRaises(storage.DestinationError):
            storage.fetch_from_destination(self.destination, str(outside), Path(self.work_dir.name) / "out")

    def test_a_traversal_out_of_the_destination_is_never_followed(self):
        sneaky = f"{self.dest_dir.name}/../{Path(self.work_dir.name).name}/x"
        Path(self.work_dir.name, "x").write_bytes(b"x")
        with self.assertRaises(storage.DestinationError):
            storage.fetch_from_destination(self.destination, sneaky, Path(self.work_dir.name) / "out")

    def test_an_s3_location_in_another_bucket_or_prefix_is_never_followed(self):
        bucket = BackupDestination.objects.create(name="b", kind="s3", bucket="mine", prefix="openzev")
        for location in ("s3://other/openzev/a.zip", "s3://mine/elsewhere/a.zip", "https://x/a.zip"):
            with self.subTest(location), mock.patch("backups.storage.s3_client") as client:
                with self.assertRaises(storage.DestinationError):
                    storage.fetch_from_destination(bucket, location, Path(self.work_dir.name) / "out")
                client.assert_not_called()

    def test_a_destination_that_no_longer_exists_says_so(self):
        with self.assertRaisesMessage(storage.DestinationError, "no longer exists"):
            storage.fetch_from_destination(None, "/x", Path(self.work_dir.name) / "out")

    def test_a_provider_error_is_a_safe_message(self):
        bucket = BackupDestination.objects.create(name="b", kind="s3", bucket="mine")
        with mock.patch("backups.storage.s3_client", return_value=FakeS3()), self.assertRaises(storage.DestinationError) as caught:
            storage.fetch_from_destination(bucket, "s3://mine/missing.zip", Path(self.work_dir.name) / "out")
        self.assertNotIn("internal detail", str(caught.exception))
