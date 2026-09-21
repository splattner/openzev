"""Restore API: admin-only, per-ZEV only, dry-run by default, and honest about what it refuses."""

import tempfile
import uuid
from unittest import mock

from django.test import TestCase
from rest_framework.test import APIClient

from audit.models import AuditEvent
from backups import tasks
from backups.fixtures import build_world
from backups.models import BackupDestination, BackupJob, BackupJobStatus, RestoreJob
from testing.helpers import authenticate

BASE = "/api/v1/backups"


class RestoreApiTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.world = build_world()

    def setUp(self):
        self.dest_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dest_dir.cleanup)
        self.client = APIClient()
        authenticate(self.client, self.world.admin)
        self.destination = BackupDestination.objects.create(name="disk", kind="local", path=self.dest_dir.name)
        self.backup = self.completed_backup()

    def completed_backup(self, **kwargs) -> BackupJob:
        job = BackupJob.objects.create(destination=self.destination, **kwargs)
        tasks.execute_backup_job(job.pk)
        job.refresh_from_db()
        return job

    def create(self, payload, *, base=None):
        """Post, then run the callback the view registered for after commit."""
        body = {"source_backup_id": str(self.backup.pk), "target_zev_id": str(self.world.alpha.pk), **(base or {}), **payload}
        with mock.patch("backups.views.transaction.on_commit") as on_commit, \
                mock.patch.object(tasks.run_restore_job, "delay") as delay:
            response = self.client.post(f"{BASE}/restores/", body, format="json")
            for call in on_commit.call_args_list:
                call.args[0]()
        return response, delay


class PermissionTests(RestoreApiTestCase):
    def endpoints(self):
        job = RestoreJob.objects.create(target_zev_id=self.world.alpha.pk, source_backup=self.backup)
        return [("get", f"{BASE}/restores/"), ("post", f"{BASE}/restores/"), ("get", f"{BASE}/restores/{job.pk}/")]

    def test_every_endpoint_refuses_anonymous_callers(self):
        anonymous = APIClient()
        for method, url in self.endpoints():
            with self.subTest(method=method, url=url):
                self.assertIn(getattr(anonymous, method)(url, {}, format="json").status_code, (401, 403))

    def test_every_endpoint_refuses_owners_and_participants(self):
        """An owner restoring "their" community would act on rows from a snapshot of every community."""
        endpoints = self.endpoints()
        for user in (self.world.owner, self.world.member):
            client = APIClient()
            authenticate(client, user)
            for method, url in endpoints:
                with self.subTest(role=user.role, method=method, url=url):
                    self.assertEqual(getattr(client, method)(url, {}, format="json").status_code, 403)


class CreateTests(RestoreApiTestCase):
    def test_a_restore_defaults_to_a_dry_run(self):
        response, delay = self.create({})
        self.assertEqual(response.status_code, 202, response.content)
        self.assertTrue(response.data["dry_run"])
        self.assertFalse(response.data["force"])
        self.assertEqual(response.data["status"], "queued")
        self.assertEqual(response.data["target_zev_name"], "Alpha")
        job = RestoreJob.objects.get(pk=response.data["id"])
        self.assertEqual(job.requester_id, self.world.admin.pk)
        delay.assert_called_once_with(str(job.pk))

    def test_a_real_restore_takes_the_safety_backup_destination_from_the_source_backup(self):
        response, _ = self.create({"dry_run": False})
        self.assertEqual(response.status_code, 202, response.content)
        job = RestoreJob.objects.get(pk=response.data["id"])
        self.assertFalse(job.dry_run)
        self.assertEqual(job.safety_destination_id, self.destination.pk)

    def test_the_response_says_which_backup_it_came_from(self):
        response, _ = self.create({})
        self.assertEqual(response.data["source_archive_name"], self.backup.archive_name)
        self.assertEqual(response.data["source_created_at"], self.backup.manifest_json["created_at"])

    def test_force_is_recorded(self):
        response, _ = self.create({"dry_run": False, "force": True})
        self.assertTrue(RestoreJob.objects.get(pk=response.data["id"]).force)

    def test_creation_is_audited_as_queued_on_the_community(self):
        self.create({"dry_run": False})
        event = AuditEvent.objects.get(action_type="restore.created")
        self.assertEqual((event.status, event.action_category), ("queued", "system"))
        self.assertEqual(event.zev_id, self.world.alpha.pk)
        self.assertFalse(event.metadata_json["dry_run"])

    def test_naming_the_whole_instance_is_an_error_not_a_downgrade(self):
        response, delay = self.create({"mode": "instance"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("management command", str(response.data["mode"]))
        delay.assert_not_called()
        self.assertFalse(RestoreJob.objects.exists())

    def test_validation(self):
        failed = self.completed_backup()
        BackupJob.objects.filter(pk=failed.pk).update(status=BackupJobStatus.FAILED)
        other = BackupDestination.objects.create(name="off", kind="local", path=self.dest_dir.name, enabled=False)
        cases = {
            "unknown backup": ({"source_backup_id": str(uuid.uuid4())}, "source_backup_id"),
            "backup that did not complete": ({"source_backup_id": str(failed.pk)}, "source_backup_id"),
            "community the backup lacks": ({"target_zev_id": str(uuid.uuid4())}, "target_zev_id"),
            "no backup": ({"source_backup_id": None}, "source_backup_id"),
            "unknown safety destination": ({"dry_run": False, "safety_destination_id": str(uuid.uuid4())}, "safety_destination_id"),
            "disabled safety destination": ({"dry_run": False, "safety_destination_id": str(other.pk)}, "safety_destination_id"),
        }
        for label, (payload, field) in cases.items():
            with self.subTest(label):
                response, delay = self.create(payload)
                self.assertEqual(response.status_code, 400, response.content)
                self.assertIn(field, response.data)
                delay.assert_not_called()
        self.assertFalse(RestoreJob.objects.exists())

    def test_a_backup_of_another_community_cannot_restore_this_one(self):
        raw_backup = self.completed_backup(scope="zev", zev=self.world.beta)
        response, _ = self.create({"source_backup_id": str(raw_backup.pk)})
        self.assertEqual(response.status_code, 400)
        self.assertIn("target_zev_id", response.data)
        response, _ = self.create({"source_backup_id": str(raw_backup.pk), "target_zev_id": str(self.world.beta.pk)})
        self.assertEqual(response.status_code, 202)

    def test_a_real_restore_needs_a_safety_destination_when_the_backups_own_is_gone(self):
        BackupDestination.objects.filter(pk=self.destination.pk).delete()
        response, _ = self.create({"dry_run": False})
        self.assertEqual(response.status_code, 400)
        self.assertIn("safety_destination_id", response.data)

    def test_a_preview_needs_no_safety_destination(self):
        BackupDestination.objects.filter(pk=self.destination.pk).delete()
        response, _ = self.create({"dry_run": True})
        self.assertEqual(response.status_code, 202, response.content)

    def test_a_safety_destination_can_be_chosen(self):
        chosen = BackupDestination.objects.create(name="other", kind="local", path=self.dest_dir.name)
        response, _ = self.create({"dry_run": False, "safety_destination_id": str(chosen.pk)})
        self.assertEqual(RestoreJob.objects.get(pk=response.data["id"]).safety_destination_id, chosen.pk)

    def test_a_second_restore_of_the_same_community_is_a_conflict_while_one_is_active(self):
        first, _ = self.create({})
        self.assertEqual(first.status_code, 202)
        second, delay = self.create({})
        self.assertEqual(second.status_code, 409)
        delay.assert_not_called()
        # Another community is unaffected.
        third, _ = self.create({"target_zev_id": str(self.world.beta.pk)})
        self.assertEqual(third.status_code, 202)

    def test_a_finished_restore_does_not_block_the_next(self):
        first, _ = self.create({})
        RestoreJob.objects.filter(pk=first.data["id"]).update(status=BackupJobStatus.COMPLETED)
        second, _ = self.create({})
        self.assertEqual(second.status_code, 202)

    def test_a_broker_outage_fails_the_job_and_returns_503_never_a_202(self):
        with mock.patch("backups.views.transaction.on_commit", side_effect=lambda fn: fn()), \
                mock.patch.object(tasks.run_restore_job, "delay", side_effect=RuntimeError("broker down")), \
                self.assertLogs("backups.views", level="ERROR"):
            response = self.client.post(
                f"{BASE}/restores/",
                {"source_backup_id": str(self.backup.pk), "target_zev_id": str(self.world.alpha.pk)},
                format="json",
            )
        self.assertEqual(response.status_code, 503)
        job = RestoreJob.objects.get()
        self.assertEqual(job.status, BackupJobStatus.FAILED)
        self.assertNotIn("broker down", job.error_message)
        self.assertTrue(AuditEvent.objects.filter(action_type="restore.failed").exists())


class ReadTests(RestoreApiTestCase):
    def test_the_list_is_newest_first_and_can_be_filtered_by_community(self):
        old = RestoreJob.objects.create(target_zev_id=self.world.alpha.pk, source_backup=self.backup)
        new = RestoreJob.objects.create(target_zev_id=self.world.beta.pk, source_backup=self.backup)
        rows = self.client.get(f"{BASE}/restores/").data
        self.assertEqual([r["id"] for r in rows], [str(new.pk), str(old.pk)])
        only_alpha = self.client.get(f"{BASE}/restores/", {"zev_id": str(self.world.alpha.pk)}).data
        self.assertEqual([r["id"] for r in only_alpha], [str(old.pk)])

    def test_the_limit_is_clamped(self):
        for _ in range(3):
            RestoreJob.objects.create(target_zev_id=self.world.alpha.pk)
        self.assertEqual(len(self.client.get(f"{BASE}/restores/", {"limit": 2}).data), 2)
        self.assertEqual(len(self.client.get(f"{BASE}/restores/", {"limit": "junk"}).data), 3)
        self.assertEqual(len(self.client.get(f"{BASE}/restores/", {"limit": 0}).data), 1)

    def test_the_detail_carries_the_plan_for_polling(self):
        job = RestoreJob.objects.create(
            target_zev_id=self.world.alpha.pk, source_backup=self.backup, status="completed",
            plan_json={"blocked": False, "conflicts": []},
        )
        data = self.client.get(f"{BASE}/restores/{job.pk}/").data
        self.assertEqual(data["plan_json"], {"blocked": False, "conflicts": []})
        self.assertEqual(data["status"], "completed")

    def test_an_unknown_job_is_a_404(self):
        self.assertEqual(self.client.get(f"{BASE}/restores/{uuid.uuid4()}/").status_code, 404)

    def test_a_restore_can_be_run_end_to_end_from_the_api_created_job(self):
        response, _ = self.create({"dry_run": True})
        tasks.execute_restore_job(response.data["id"])
        data = self.client.get(f"{BASE}/restores/{response.data['id']}/").data
        self.assertEqual(data["status"], "completed")
        self.assertEqual(data["plan_json"]["zev"]["name"], "Alpha")
        self.assertFalse(data["plan_json"]["blocked"])
