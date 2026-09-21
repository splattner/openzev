"""Retention, expiry and stalled-job recovery: what is deleted, and above all what is never deleted."""

import io
import os
import tempfile
from datetime import timedelta
from pathlib import Path
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone

from audit.models import AuditEvent
from backups import retention, storage, tasks
from backups.fixtures import build_world
from backups.models import BackupDestination, BackupJob, BackupJobStatus, RestoreJob
from backups.test_destinations import FakeS3


class SweepTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.world = build_world()

    def setUp(self):
        self.dest_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dest_dir.cleanup)
        self.destination = BackupDestination.objects.create(name="disk", kind="local", path=self.dest_dir.name)
        self.clock = 0

    def backup(self, destination=None, **kwargs) -> BackupJob:
        """A real, finished backup, spaced one hour apart from the last, oldest first."""
        job = BackupJob.objects.create(destination=destination or self.destination, **kwargs)
        # Fixtures are built without the sweep that follows every real backup, so
        # each test decides when the sweep runs.
        with mock.patch.object(tasks, "_sweep_best_effort"):
            tasks.execute_backup_job(job.pk)
        job.refresh_from_db()
        self.clock += 1
        BackupJob.objects.filter(pk=job.pk).update(completed_at=timezone.now() - timedelta(hours=100 - self.clock))
        job.refresh_from_db()
        return job

    def exists(self, job) -> bool:
        return Path(job.archive_location).exists()

    def deleted(self, job) -> bool:
        job.refresh_from_db()
        return job.artifact_deleted_at is not None


class RetentionTests(SweepTestCase):
    def test_nothing_is_deleted_unless_retention_is_switched_on(self):
        jobs = [self.backup() for _ in range(4)]
        report = retention.sweep()
        self.assertEqual(report["retention"], [])
        self.assertTrue(all(self.exists(j) for j in jobs))

    def test_the_newest_n_are_kept_and_older_ones_deleted(self):
        BackupDestination.objects.filter(pk=self.destination.pk).update(retention_count=2)
        jobs = [self.backup() for _ in range(4)]
        report = retention.sweep()
        self.assertEqual(sorted(report["retention"]), sorted(j.archive_name for j in jobs[:2]))
        self.assertEqual([self.exists(j) for j in jobs], [False, False, True, True])
        self.assertEqual([self.deleted(j) for j in jobs], [True, True, False, False])

    def test_the_row_outlives_its_file_and_says_why_it_went(self):
        BackupDestination.objects.filter(pk=self.destination.pk).update(retention_count=1)
        old, _new = self.backup(), self.backup()
        retention.sweep()
        old.refresh_from_db()
        self.assertEqual((old.status, old.artifact_deleted_reason), (BackupJobStatus.COMPLETED, "retention"))
        self.assertFalse(old.artifact_available)
        self.assertEqual(old.manifest_json["kind"], "backup")

    def test_the_newest_backup_is_never_deleted_even_at_one(self):
        BackupDestination.objects.filter(pk=self.destination.pk).update(retention_count=1)
        only = self.backup()
        retention.sweep()
        self.assertTrue(self.exists(only))

    def test_each_kind_is_counted_separately_so_a_community_backup_cannot_evict_the_instance_backup(self):
        BackupDestination.objects.filter(pk=self.destination.pk).update(retention_count=1)
        instance = self.backup()
        alpha = self.backup(scope="zev", zev=self.world.alpha)
        beta = self.backup(scope="zev", zev=self.world.beta)
        retention.sweep()
        self.assertTrue(all(self.exists(j) for j in (instance, alpha, beta)))

    def test_a_safety_backup_is_never_counted_or_deleted_by_retention(self):
        BackupDestination.objects.filter(pk=self.destination.pk).update(retention_count=1)
        safety = self.backup(scope="zev", zev=self.world.alpha, trigger="pre_restore")
        newer = [self.backup(scope="zev", zev=self.world.alpha) for _ in range(2)]
        retention.sweep()
        self.assertTrue(self.exists(safety))
        self.assertEqual([self.exists(j) for j in newer], [False, True])

    def test_a_failed_or_running_job_is_not_a_backup_to_keep_or_delete(self):
        BackupDestination.objects.filter(pk=self.destination.pk).update(retention_count=1)
        good = self.backup()
        BackupJob.objects.create(destination=self.destination, status=BackupJobStatus.FAILED)
        BackupJob.objects.create(destination=self.destination, status=BackupJobStatus.RUNNING)
        retention.sweep()
        self.assertTrue(self.exists(good))

    def test_destinations_are_independent(self):
        other_dir = tempfile.TemporaryDirectory()
        self.addCleanup(other_dir.cleanup)
        other = BackupDestination.objects.create(name="other", kind="local", path=other_dir.name, retention_count=1)
        BackupDestination.objects.filter(pk=self.destination.pk).update(retention_count=0)
        keep_all = [self.backup() for _ in range(3)]
        pruned = [self.backup(destination=other) for _ in range(3)]
        retention.sweep()
        self.assertTrue(all(self.exists(j) for j in keep_all))
        self.assertEqual([self.exists(j) for j in pruned], [False, False, True])

    def test_a_backup_a_restore_is_reading_is_not_deleted(self):
        BackupDestination.objects.filter(pk=self.destination.pk).update(retention_count=1)
        old, _new = self.backup(), self.backup()
        RestoreJob.objects.create(
            target_zev_id=self.world.alpha.pk, source_backup=old, status=BackupJobStatus.RUNNING, dry_run=False,
        )
        retention.sweep()
        self.assertTrue(self.exists(old))
        # ...and once the restore is over it goes on the next sweep.
        RestoreJob.objects.update(status=BackupJobStatus.COMPLETED)
        retention.sweep()
        self.assertFalse(self.exists(old))

    def test_a_backup_being_verified_is_not_deleted(self):
        BackupDestination.objects.filter(pk=self.destination.pk).update(retention_count=1)
        old, _new = self.backup(), self.backup()
        BackupJob.objects.filter(pk=old.pk).update(verify_started_at=timezone.now())
        retention.sweep()
        self.assertTrue(self.exists(old))

    def test_a_dry_run_reports_and_deletes_nothing(self):
        BackupDestination.objects.filter(pk=self.destination.pk).update(retention_count=1)
        old, _new = self.backup(), self.backup()
        report = retention.sweep(dry_run=True)
        self.assertEqual(report["retention"], [old.archive_name])
        self.assertTrue(self.exists(old))
        self.assertFalse(self.deleted(old))

    def test_a_deletion_is_audited_with_its_reason_and_location(self):
        BackupDestination.objects.filter(pk=self.destination.pk).update(retention_count=1)
        old, _new = self.backup(), self.backup()
        retention.sweep()
        event = AuditEvent.objects.get(action_type="backup.artifact_deleted")
        self.assertEqual(event.target_id, str(old.pk))
        self.assertEqual(event.metadata_json["reason"], "retention")
        self.assertEqual(event.metadata_json["location"], old.archive_location)
        self.assertEqual(event.source, "celery")

    def test_a_second_sweep_has_nothing_left_to_do(self):
        BackupDestination.objects.filter(pk=self.destination.pk).update(retention_count=1)
        self.backup(), self.backup()
        retention.sweep()
        self.assertEqual(retention.sweep()["retention"], [])


class ExpiryTests(SweepTestCase):
    def test_a_safety_backup_is_given_an_expiry(self):
        job = self.backup(scope="zev", zev=self.world.alpha, trigger="pre_restore")
        self.assertAlmostEqual(
            (job.file_expires_at - job.completed_at).total_seconds(), 30 * 86400, delta=3600 * 101,
        )

    def test_no_other_backup_expires(self):
        manual, scheduled = self.backup(), self.backup(trigger="scheduled")
        self.assertIsNone(manual.file_expires_at)
        self.assertIsNone(scheduled.file_expires_at)

    @override_settings(BACKUP_SAFETY_RETENTION_DAYS=0)
    def test_zero_days_keeps_safety_backups_forever(self):
        self.assertIsNone(self.backup(scope="zev", zev=self.world.alpha, trigger="pre_restore").file_expires_at)

    def test_a_backup_written_to_an_ad_hoc_path_is_left_for_its_operator(self):
        """``--path`` names no saved destination, so nothing bounds where a delete may reach."""
        adhoc = BackupDestination(name="(command line)", kind="local", path=self.dest_dir.name)
        job = BackupJob.objects.create(scope="zev", zev=self.world.alpha, trigger="pre_restore")
        with mock.patch.object(tasks, "_sweep_best_effort"):
            tasks.execute_backup_job(job.pk, destination=adhoc)
        job.refresh_from_db()
        self.assertIsNone(job.destination_id)
        self.assertIsNone(job.file_expires_at)
        BackupJob.objects.filter(pk=job.pk).update(file_expires_at=timezone.now() - timedelta(days=1))
        report = retention.sweep()
        self.assertEqual((report["expired"], report["errors"]), ([], 0))
        self.assertTrue(self.exists(job))

    def test_an_expired_backup_whose_destination_was_deleted_is_skipped_without_an_error(self):
        job = self.backup(scope="zev", zev=self.world.alpha, trigger="pre_restore")
        BackupJob.objects.filter(pk=job.pk).update(file_expires_at=timezone.now() - timedelta(days=1), destination=None)
        report = retention.sweep()
        self.assertEqual((report["expired"], report["errors"]), ([], 0))

    def test_an_expired_backup_is_deleted_and_an_unexpired_one_is_not(self):
        expired = self.backup(scope="zev", zev=self.world.alpha, trigger="pre_restore")
        fresh = self.backup(scope="zev", zev=self.world.beta, trigger="pre_restore")
        BackupJob.objects.filter(pk=expired.pk).update(file_expires_at=timezone.now() - timedelta(minutes=1))
        report = retention.sweep()
        self.assertEqual(report["expired"], [expired.archive_name])
        self.assertFalse(self.exists(expired))
        self.assertTrue(self.exists(fresh))
        expired.refresh_from_db()
        self.assertEqual(expired.artifact_deleted_reason, "expired")

    def test_an_expired_backup_a_restore_is_reading_is_kept_until_it_is_done(self):
        job = self.backup(scope="zev", zev=self.world.alpha, trigger="pre_restore")
        BackupJob.objects.filter(pk=job.pk).update(file_expires_at=timezone.now() - timedelta(minutes=1))
        RestoreJob.objects.create(
            target_zev_id=self.world.alpha.pk, source_backup=job, status=BackupJobStatus.QUEUED, dry_run=False,
        )
        retention.sweep()
        self.assertTrue(self.exists(job))


class DeletionRobustnessTests(SweepTestCase):
    def test_a_file_that_is_already_gone_is_recorded_as_deleted(self):
        job = self.backup()
        Path(job.archive_location).unlink()
        self.assertFalse(retention.delete_artifact(job, reason="manual"))
        self.assertTrue(self.deleted(job))
        self.assertTrue(AuditEvent.objects.get(action_type="backup.artifact_deleted").metadata_json["already_gone"])

    def test_a_destination_that_is_gone_raises_and_leaves_the_row_alone(self):
        job = self.backup()
        BackupDestination.objects.filter(pk=self.destination.pk).delete()
        job.refresh_from_db()
        with self.assertRaises(storage.DestinationError):
            retention.delete_artifact(job, reason="manual")
        self.assertFalse(self.deleted(job))

    def test_one_unreachable_destination_does_not_stop_the_others(self):
        other_dir = tempfile.TemporaryDirectory()
        self.addCleanup(other_dir.cleanup)
        other = BackupDestination.objects.create(name="other", kind="local", path=other_dir.name, retention_count=1)
        BackupDestination.objects.filter(pk=self.destination.pk).update(retention_count=1)
        broken = [self.backup(), self.backup()]
        healthy = [self.backup(destination=other), self.backup(destination=other)]

        real = storage.delete_from_destination

        def flaky(destination, location):
            if destination.pk == self.destination.pk:
                raise storage.DestinationError("could not reach it")
            return real(destination, location)

        with mock.patch.object(retention, "delete_from_destination", flaky), self.assertLogs("backups.retention", "WARNING"):
            report = retention.sweep()
        self.assertEqual(report["errors"], 1)
        self.assertTrue(self.exists(broken[0]), "not deleted, so the next sweep tries again")
        self.assertFalse(self.exists(healthy[0]))

    def test_an_unexpected_error_on_one_row_is_contained_and_counted(self):
        BackupDestination.objects.filter(pk=self.destination.pk).update(retention_count=1)
        self.backup(), self.backup()
        with mock.patch.object(retention, "delete_from_destination", side_effect=RuntimeError("boom")), \
                self.assertLogs("backups.retention", "ERROR"):
            report = retention.sweep()
        self.assertEqual(report["errors"], 1)

    def test_a_broken_audit_write_does_not_undo_a_deletion(self):
        job = self.backup()
        with mock.patch.object(retention, "record_audit_event", side_effect=RuntimeError("audit down")), \
                self.assertLogs("backups.retention", "ERROR"):
            retention.delete_artifact(job, reason="manual")
        self.assertFalse(self.exists(job))
        self.assertTrue(self.deleted(job))


class StorageDeleteTests(SweepTestCase):
    def test_a_location_outside_its_destination_is_never_followed(self):
        outside = Path(tempfile.mkdtemp()) / "elsewhere.zip"
        outside.write_bytes(b"x")
        self.addCleanup(outside.unlink)
        with self.assertRaises(storage.DestinationError):
            storage.delete_from_destination(self.destination, str(outside))
        self.assertTrue(outside.exists())

    def test_a_traversal_out_of_the_destination_is_never_followed(self):
        sibling = Path(tempfile.mkdtemp())
        (sibling / "x").write_bytes(b"x")
        self.addCleanup(lambda: (sibling / "x").unlink(missing_ok=True))
        with self.assertRaises(storage.DestinationError):
            storage.delete_from_destination(self.destination, f"{self.dest_dir.name}/../{sibling.name}/x")
        self.assertTrue((sibling / "x").exists())

    def test_an_s3_location_in_another_bucket_or_prefix_is_never_deleted(self):
        bucket = BackupDestination.objects.create(name="b", kind="s3", bucket="mine", prefix="openzev")
        for location in ("s3://other/openzev/a.zip", "s3://mine/elsewhere/a.zip", "https://x/a.zip"):
            with self.subTest(location), mock.patch("backups.storage.s3_client") as client:
                with self.assertRaises(storage.DestinationError):
                    storage.delete_from_destination(bucket, location)
                client.assert_not_called()

    def test_an_s3_object_is_deleted_inside_its_bucket_and_prefix(self):
        bucket = BackupDestination.objects.create(name="b", kind="s3", bucket="mine", prefix="openzev")
        fake = FakeS3()
        with mock.patch("backups.storage.s3_client", return_value=fake):
            self.assertTrue(storage.delete_from_destination(bucket, "s3://mine/openzev/a.zip"))
        self.assertEqual(fake.deletes, [{"Bucket": "mine", "Key": "openzev/a.zip"}])

    def test_a_provider_error_is_a_safe_message(self):
        from botocore.exceptions import ClientError

        bucket = BackupDestination.objects.create(name="b", kind="s3", bucket="mine")
        fake = mock.Mock()
        fake.delete_object.side_effect = ClientError({"Error": {"Code": "AccessDenied", "Message": "secret detail"}}, "Delete")
        with mock.patch("backups.storage.s3_client", return_value=fake), self.assertRaises(storage.DestinationError) as caught:
            storage.delete_from_destination(bucket, "s3://mine/a.zip")
        self.assertNotIn("secret detail", str(caught.exception))

    def test_a_missing_destination_says_so(self):
        with self.assertRaisesMessage(storage.DestinationError, "no longer exists"):
            storage.delete_from_destination(None, "/x")


class RunsAlongsideBackupsTests(SweepTestCase):
    def test_retention_runs_after_the_new_backup_exists_never_before(self):
        """With one to keep, deleting first would leave a window with no backup at all."""
        old = self.backup()
        BackupDestination.objects.filter(pk=self.destination.pk).update(retention_count=1)
        job = BackupJob.objects.create(destination=self.destination)
        seen = {}
        real = retention.sweep

        def spy(*, steps=retention.STEPS, **kwargs):
            if "retention" in steps:
                current = BackupJob.objects.get(pk=job.pk)
                seen["new_status"] = current.status
                seen["new_file_exists"] = self.exists(current)
                seen["old_file_exists"] = self.exists(old)
            return real(steps=steps, **kwargs)

        with mock.patch.object(retention, "sweep", spy):
            tasks.execute_backup_job(job.pk)
        self.assertEqual(seen, {"new_status": "completed", "new_file_exists": True, "old_file_exists": True})
        self.assertFalse(self.exists(old), "and only then does the old one go")

    def test_the_sweep_at_the_start_of_a_run_only_expires_and_recovers(self):
        calls = []
        real = retention.sweep

        def spy(*, steps=retention.STEPS, **kwargs):
            calls.append(tuple(steps))
            return real(steps=steps, **kwargs)

        job = BackupJob.objects.create(destination=self.destination)
        with mock.patch.object(retention, "sweep", spy):
            tasks.execute_backup_job(job.pk)
        self.assertEqual(calls, [("expired", "stalled"), ("retention",)])

    def test_a_failing_sweep_never_fails_the_backup(self):
        job = BackupJob.objects.create(destination=self.destination)
        with mock.patch.object(retention, "sweep", side_effect=RuntimeError("sweep broke")), \
                self.assertLogs("backups.tasks", "ERROR"):
            tasks.execute_backup_job(job.pk)
        job.refresh_from_db()
        self.assertEqual(job.status, BackupJobStatus.COMPLETED)


class StalledJobTests(SweepTestCase):
    def test_a_job_running_far_past_its_limit_is_failed(self):
        stuck = BackupJob.objects.create(
            destination=self.destination, status=BackupJobStatus.RUNNING,
            started_at=timezone.now() - timedelta(seconds=retention.hard_limit_s() + 60),
        )
        report = retention.sweep()
        stuck.refresh_from_db()
        self.assertEqual(report["stalled"], [str(stuck.pk)])
        self.assertEqual(stuck.status, BackupJobStatus.FAILED)
        self.assertIn("worker stopped", stuck.error_message)
        self.assertIsNotNone(stuck.completed_at)

    def test_a_job_still_within_its_limit_is_left_alone(self):
        running = BackupJob.objects.create(
            destination=self.destination, status=BackupJobStatus.RUNNING,
            started_at=timezone.now() - timedelta(seconds=retention.hard_limit_s() - 120),
        )
        self.assertEqual(retention.sweep()["stalled"], [])
        running.refresh_from_db()
        self.assertEqual(running.status, BackupJobStatus.RUNNING)

    def test_a_job_that_never_left_the_queue_is_failed_after_hours_not_minutes(self):
        old = BackupJob.objects.create(destination=self.destination)
        recent = BackupJob.objects.create(destination=self.destination)
        BackupJob.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(hours=5))
        BackupJob.objects.filter(pk=recent.pk).update(created_at=timezone.now() - timedelta(minutes=30))
        retention.sweep()
        old.refresh_from_db(), recent.refresh_from_db()
        self.assertEqual((old.status, recent.status), (BackupJobStatus.FAILED, BackupJobStatus.QUEUED))

    def test_a_stalled_restore_is_failed_too(self):
        stuck = RestoreJob.objects.create(
            target_zev_id=self.world.alpha.pk, status=BackupJobStatus.RUNNING,
            started_at=timezone.now() - timedelta(seconds=retention.hard_limit_s() + 60),
        )
        retention.sweep()
        stuck.refresh_from_db()
        self.assertEqual(stuck.status, BackupJobStatus.FAILED)
        self.assertIn("restore did not finish", stuck.error_message)

    def test_a_verification_that_never_reported_is_cleared_with_a_reason(self):
        job = self.backup()
        BackupJob.objects.filter(pk=job.pk).update(
            verify_started_at=timezone.now() - timedelta(seconds=retention.hard_limit_s() + 60),
        )
        retention.sweep()
        job.refresh_from_db()
        self.assertIsNone(job.verify_started_at)
        self.assertFalse(job.verification_ok)
        self.assertIn("did not finish", job.verification_message)

    def test_a_dry_run_changes_no_job(self):
        stuck = BackupJob.objects.create(
            destination=self.destination, status=BackupJobStatus.RUNNING,
            started_at=timezone.now() - timedelta(seconds=retention.hard_limit_s() + 60),
        )
        self.assertEqual(retention.sweep(dry_run=True)["stalled"], [str(stuck.pk)])
        stuck.refresh_from_db()
        self.assertEqual(stuck.status, BackupJobStatus.RUNNING)


class SweepCommandTests(SweepTestCase):
    def run_command(self, *args):
        out = io.StringIO()
        call_command("openzev_backup_sweep", *args, stdout=out, stderr=io.StringIO())
        return out.getvalue()

    def test_it_deletes_and_says_what(self):
        BackupDestination.objects.filter(pk=self.destination.pk).update(retention_count=1)
        old, _new = self.backup(), self.backup()
        out = self.run_command()
        self.assertIn(f"Deleted (beyond retention): {old.archive_name}", out)
        self.assertFalse(self.exists(old))
        self.assertEqual(AuditEvent.objects.get(action_type="backup.artifact_deleted").source, "management_command")

    def test_a_dry_run_previews_what_a_retention_setting_would_do(self):
        BackupDestination.objects.filter(pk=self.destination.pk).update(retention_count=1)
        old, _new = self.backup(), self.backup()
        out = self.run_command("--dry-run")
        self.assertIn(f"Would delete (beyond retention): {old.archive_name}", out)
        self.assertIn("Dry run: 1 item(s).", out)
        self.assertTrue(self.exists(old))

    def test_a_deletion_that_failed_exits_non_zero_after_doing_the_rest(self):
        BackupDestination.objects.filter(pk=self.destination.pk).update(retention_count=1)
        self.backup(), self.backup()
        with mock.patch.object(retention, "delete_from_destination", side_effect=storage.DestinationError("no")), \
                self.assertLogs("backups.retention", "WARNING"), self.assertRaisesMessage(CommandError, "could not be deleted"):
            self.run_command()

    def test_it_works_where_nothing_needs_doing(self):
        self.assertIn("0 item(s).", self.run_command())
        self.assertEqual(os.listdir(self.dest_dir.name), [])
