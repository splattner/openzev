"""Verifying a stored backup, deleting its file, and what the API says about both."""

import io
import tempfile
import zipfile
from datetime import timedelta
from pathlib import Path
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from audit.models import AuditEvent
from backups import crypto, tasks
from backups.fixtures import build_world
from backups.models import BackupDestination, BackupJob, BackupJobStatus, RestoreJob
from testing.helpers import authenticate

BASE = "/api/v1/backups"
KEY = "V" * 40


class VerifyTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.world = build_world()

    def setUp(self):
        self.dest_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dest_dir.cleanup)
        self.destination = BackupDestination.objects.create(name="disk", kind="local", path=self.dest_dir.name)
        self.client = APIClient()
        authenticate(self.client, self.world.admin)

    def backup(self, **kwargs) -> BackupJob:
        job = BackupJob.objects.create(destination=self.destination, **kwargs)
        tasks.execute_backup_job(job.pk)
        job.refresh_from_db()
        return job

    def verify(self, job) -> dict | None:
        self.assertTrue(tasks.claim_verification(job.pk))
        return tasks.execute_verify(job.pk)

    def replace_file(self, job, data: bytes, *, update_checksum=True):
        import hashlib

        Path(job.archive_location).write_bytes(data)
        if update_checksum:
            BackupJob.objects.filter(pk=job.pk).update(archive_sha256=hashlib.sha256(data).hexdigest())


class ExecuteVerifyTests(VerifyTestCase):
    def test_an_intact_backup_is_recorded_as_such(self):
        job = self.backup()
        result = self.verify(job)
        job.refresh_from_db()
        self.assertTrue(result["ok"])
        self.assertTrue(job.verification_ok)
        self.assertIsNotNone(job.verified_at)
        self.assertIsNone(job.verify_started_at, "the claim is released")
        self.assertRegex(job.verification_message, r"Intact: \d+ files, [\d,]+ records\.")

    def test_a_file_that_rotted_at_rest_fails_on_the_recorded_checksum(self):
        job = self.backup()
        data = bytearray(Path(job.archive_location).read_bytes())
        data[len(data) // 2] ^= 0xFF
        Path(job.archive_location).write_bytes(bytes(data))
        self.verify(job)
        job.refresh_from_db()
        self.assertFalse(job.verification_ok)
        self.assertIn("does not match the checksum", job.verification_message)

    def test_a_file_with_the_right_checksum_but_a_broken_content_lists_what_is_wrong(self):
        job = self.backup()
        with zipfile.ZipFile(job.archive_location) as zf:
            members = {n: zf.read(n) for n in zf.namelist()}
        members["stowaway.txt"] = b"not vouched for"
        rebuilt = io.BytesIO()
        with zipfile.ZipFile(rebuilt, "w") as zf:
            for name, data in members.items():
                zf.writestr(name, data)
        self.replace_file(job, rebuilt.getvalue())
        self.verify(job)
        job.refresh_from_db()
        self.assertFalse(job.verification_ok)
        self.assertIn("failed verification", job.verification_message)
        self.assertIn("stowaway.txt", job.verification_message)

    def test_a_long_list_of_problems_is_capped_and_says_how_many_more(self):
        job = self.backup()
        with zipfile.ZipFile(job.archive_location) as zf:
            members = {n: zf.read(n) for n in zf.namelist()}
        for n in range(6):
            members[f"extra-{n}.txt"] = b"x"
        rebuilt = io.BytesIO()
        with zipfile.ZipFile(rebuilt, "w") as zf:
            for name, data in members.items():
                zf.writestr(name, data)
        self.replace_file(job, rebuilt.getvalue())
        self.verify(job)
        job.refresh_from_db()
        self.assertIn("more)", job.verification_message)
        self.assertLessEqual(len(job.verification_message), 500)

    def test_a_file_that_is_not_an_archive_at_all(self):
        job = self.backup()
        self.replace_file(job, b"this is not a zip")
        self.verify(job)
        job.refresh_from_db()
        self.assertFalse(job.verification_ok)
        self.assertIn("not a readable ZIP", job.verification_message)

    def test_a_missing_file_says_so(self):
        job = self.backup()
        Path(job.archive_location).unlink()
        self.verify(job)
        job.refresh_from_db()
        self.assertFalse(job.verification_ok)
        self.assertEqual(job.verification_message, "The backup file is no longer available.")

    def test_an_encrypted_backup_is_checked_with_its_key_and_refused_without_it(self):
        with override_settings(BACKUP_ENCRYPTION_KEYS=[KEY]):
            job = self.backup()
            self.assertTrue(job.encrypted)
            self.assertTrue(self.verify(job)["ok"])
        BackupJob.objects.filter(pk=job.pk).update(verified_at=None, verification_ok=None)
        with override_settings(BACKUP_ENCRYPTION_KEYS=[]):
            self.verify(job)
        job.refresh_from_db()
        self.assertFalse(job.verification_ok)
        self.assertIn(crypto.key_fingerprint(KEY), job.verification_message)

    def test_an_unexpected_error_is_generic_on_the_row_and_detailed_only_in_the_log(self):
        job = self.backup()
        with mock.patch.object(tasks.archive, "verify_archive", side_effect=RuntimeError("secret internal detail")), \
                self.assertLogs("backups.tasks", "ERROR"):
            self.verify(job)
        job.refresh_from_db()
        self.assertFalse(job.verification_ok)
        self.assertNotIn("secret internal detail", job.verification_message)
        self.assertIn("could not be completed", job.verification_message)

    def test_without_the_claim_nothing_runs(self):
        job = self.backup()
        self.assertIsNone(tasks.execute_verify(job.pk))
        job.refresh_from_db()
        self.assertIsNone(job.verified_at)

    def test_a_result_does_not_overwrite_a_claim_someone_else_now_holds(self):
        job = self.backup()
        self.assertTrue(tasks.claim_verification(job.pk))
        real = tasks.archive.verify_archive

        def steal(handle):
            BackupJob.objects.filter(pk=job.pk).update(verify_started_at=timezone.now() + timedelta(seconds=5))
            return real(handle)

        with mock.patch.object(tasks.archive, "verify_archive", steal):
            self.assertIsNone(tasks.execute_verify(job.pk))
        job.refresh_from_db()
        self.assertIsNone(job.verified_at)

    def test_a_local_check_leaves_no_copy_behind(self):
        with tempfile.TemporaryDirectory() as work, override_settings(BACKUP_WORK_DIR=work):
            job = self.backup()
            self.verify(job)
            self.assertEqual(list(Path(work).iterdir()), [])

    def test_it_is_audited_either_way(self):
        job = self.backup()
        self.verify(job)
        self.assertEqual(AuditEvent.objects.get(action_type="backup.verified").target_id, str(job.pk))
        BackupJob.objects.filter(pk=job.pk).update(verify_started_at=None)
        Path(job.archive_location).unlink()
        self.verify(job)
        failed = AuditEvent.objects.get(action_type="backup.verify_failed")
        self.assertEqual(failed.status, "failed")

    def test_the_latest_result_replaces_the_previous_one(self):
        job = self.backup()
        Path(job.archive_location).write_bytes(b"broken")
        self.verify(job)
        job.refresh_from_db()
        self.assertFalse(job.verification_ok)


class ClaimTests(VerifyTestCase):
    def test_only_one_check_runs_at_a_time(self):
        job = self.backup()
        self.assertTrue(tasks.claim_verification(job.pk))
        self.assertFalse(tasks.claim_verification(job.pk))

    def test_a_backup_that_did_not_complete_or_whose_file_is_gone_cannot_be_claimed(self):
        failed = BackupJob.objects.create(destination=self.destination, status=BackupJobStatus.FAILED)
        gone = self.backup()
        BackupJob.objects.filter(pk=gone.pk).update(artifact_deleted_at=timezone.now())
        self.assertFalse(tasks.claim_verification(failed.pk))
        self.assertFalse(tasks.claim_verification(gone.pk))


class VerifyApiTests(VerifyTestCase):
    def post(self, job, *, run=False):
        with mock.patch("backups.views.transaction.on_commit") as on_commit, \
                mock.patch.object(tasks.run_verify_job, "delay") as delay:
            response = self.client.post(f"{BASE}/jobs/{job.pk}/verify/")
            if run:
                for call in on_commit.call_args_list:
                    call.args[0]()
        return response, delay

    def test_it_queues_a_check_and_returns_the_job_as_verifying(self):
        job = self.backup()
        response, delay = self.post(job, run=True)
        self.assertEqual(response.status_code, 202, response.content)
        self.assertTrue(response.data["verifying"])
        delay.assert_called_once_with(str(job.pk))

    def test_a_second_request_while_one_runs_is_a_conflict(self):
        job = self.backup()
        self.post(job)
        response, delay = self.post(job, run=True)
        self.assertEqual(response.status_code, 409)
        delay.assert_not_called()

    def test_a_backup_without_a_file_is_a_conflict(self):
        job = self.backup()
        BackupJob.objects.filter(pk=job.pk).update(artifact_deleted_at=timezone.now())
        self.assertEqual(self.post(job)[0].status_code, 409)
        failed = BackupJob.objects.create(destination=self.destination, status=BackupJobStatus.FAILED)
        self.assertEqual(self.post(failed)[0].status_code, 409)

    def test_a_broker_outage_releases_the_claim_and_says_so(self):
        job = self.backup()
        with mock.patch("backups.views.transaction.on_commit", side_effect=lambda fn: fn()), \
                mock.patch.object(tasks.run_verify_job, "delay", side_effect=RuntimeError("broker down")), \
                self.assertLogs("backups.views", "ERROR"):
            response = self.client.post(f"{BASE}/jobs/{job.pk}/verify/")
        self.assertEqual(response.status_code, 503)
        job.refresh_from_db()
        self.assertIsNone(job.verify_started_at)

    def test_the_result_shows_up_on_the_job(self):
        job = self.backup()
        self.post(job)
        tasks.execute_verify(job.pk)
        data = self.client.get(f"{BASE}/jobs/{job.pk}/").data
        self.assertTrue(data["verification_ok"])
        self.assertFalse(data["verifying"])
        self.assertTrue(data["verified_at"])

    def test_unknown_job_is_a_404(self):
        import uuid

        self.assertEqual(self.client.post(f"{BASE}/jobs/{uuid.uuid4()}/verify/").status_code, 404)


class DeleteArtifactApiTests(VerifyTestCase):
    def test_it_deletes_the_file_keeps_the_row_and_audits_who_did_it(self):
        job = self.backup()
        response = self.client.delete(f"{BASE}/jobs/{job.pk}/artifact/")
        self.assertEqual(response.status_code, 204)
        self.assertFalse(Path(job.archive_location).exists())
        job.refresh_from_db()
        self.assertEqual((job.status, job.artifact_deleted_reason), ("completed", "manual"))
        event = AuditEvent.objects.get(action_type="backup.artifact_deleted")
        self.assertEqual((event.actor_user_id, event.source), (self.world.admin.pk, "api"))

    def test_a_deleted_backup_can_no_longer_be_downloaded_verified_deleted_or_restored_from(self):
        job = self.backup()
        self.client.delete(f"{BASE}/jobs/{job.pk}/artifact/")
        self.assertEqual(self.client.get(f"{BASE}/jobs/{job.pk}/download/").status_code, 410)
        self.assertEqual(self.client.post(f"{BASE}/jobs/{job.pk}/verify/").status_code, 409)
        self.assertEqual(self.client.delete(f"{BASE}/jobs/{job.pk}/artifact/").status_code, 409)
        response = self.client.post(
            f"{BASE}/restores/",
            {"source_backup_id": str(job.pk), "target_zev_id": str(self.world.alpha.pk)}, format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("deleted", str(response.data["source_backup_id"]))

    def test_a_backup_a_restore_is_reading_cannot_be_deleted(self):
        job = self.backup()
        RestoreJob.objects.create(
            target_zev_id=self.world.alpha.pk, source_backup=job, status=BackupJobStatus.RUNNING, dry_run=False,
        )
        response = self.client.delete(f"{BASE}/jobs/{job.pk}/artifact/")
        self.assertEqual(response.status_code, 409)
        self.assertTrue(Path(job.archive_location).exists())

    def test_a_backup_being_checked_cannot_be_deleted(self):
        job = self.backup()
        tasks.claim_verification(job.pk)
        self.assertEqual(self.client.delete(f"{BASE}/jobs/{job.pk}/artifact/").status_code, 409)

    def test_an_unreachable_destination_is_a_bad_gateway_and_leaves_the_row_alone(self):
        job = self.backup()
        with mock.patch("backups.retention.delete_from_destination", side_effect=__import__("backups.storage", fromlist=["x"]).DestinationError("could not reach it")):
            response = self.client.delete(f"{BASE}/jobs/{job.pk}/artifact/")
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.data["detail"], "could not reach it")
        job.refresh_from_db()
        self.assertIsNone(job.artifact_deleted_at)

    def test_a_backup_that_did_not_complete_has_nothing_to_delete(self):
        failed = BackupJob.objects.create(destination=self.destination, status=BackupJobStatus.FAILED)
        self.assertEqual(self.client.delete(f"{BASE}/jobs/{failed.pk}/artifact/").status_code, 409)

    def test_the_destination_can_be_deleted_once_its_files_are_gone(self):
        job = self.backup()
        self.assertEqual(self.client.delete(f"{BASE}/destinations/{self.destination.pk}/").status_code, 409)
        self.client.delete(f"{BASE}/jobs/{job.pk}/artifact/")
        self.assertEqual(self.client.delete(f"{BASE}/destinations/{self.destination.pk}/").status_code, 204)

    def test_owners_and_participants_cannot_touch_any_of_it(self):
        job = self.backup()
        for user in (self.world.owner, self.world.member):
            client = APIClient()
            authenticate(client, user)
            self.assertEqual(client.delete(f"{BASE}/jobs/{job.pk}/artifact/").status_code, 403)
            self.assertEqual(client.post(f"{BASE}/jobs/{job.pk}/verify/").status_code, 403)
        self.assertTrue(Path(job.archive_location).exists())


class RetentionSettingApiTests(VerifyTestCase):
    def test_the_count_is_part_of_the_destination_and_defaults_to_keeping_everything(self):
        data = self.client.get(f"{BASE}/destinations/{self.destination.pk}/").data
        self.assertEqual(data["retention_count"], 0)

    def test_it_can_be_set_and_the_change_is_audited(self):
        response = self.client.patch(f"{BASE}/destinations/{self.destination.pk}/", {"retention_count": 7}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        event = AuditEvent.objects.get(action_type="backup_destination.update")
        self.assertEqual(event.changes_json["retention_count"], {"before": 0, "after": 7})

    def test_it_cannot_be_negative_or_absurd(self):
        for value in (-1, 10_001):
            with self.subTest(value):
                response = self.client.patch(
                    f"{BASE}/destinations/{self.destination.pk}/", {"retention_count": value}, format="json",
                )
                self.assertEqual(response.status_code, 400)

    def test_a_new_destination_can_be_created_with_one(self):
        response = self.client.post(
            f"{BASE}/destinations/",
            {"name": "new", "kind": "local", "path": self.dest_dir.name + "/new", "retention_count": 3}, format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.data["retention_count"], 3)
