"""Backup API: admin-only access, destination CRUD, job lifecycle, download."""

import tempfile
import uuid
from pathlib import Path
from unittest import mock

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from accounts.models import UserRole
from audit.models import AuditEvent
from backups import tasks
from backups.fixtures import build_world
from backups.models import BackupDestination, BackupJob, BackupJobStatus
from testing.helpers import authenticate, make_user

BASE = "/api/v1/backups"
KEY = "A" * 40


class ApiTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.world = build_world()

    def setUp(self):
        self.dest_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dest_dir.cleanup)
        self.client = APIClient()
        authenticate(self.client, self.world.admin)

    def local_destination(self, **kwargs):
        defaults = {"name": "disk", "kind": "local", "path": self.dest_dir.name}
        return BackupDestination.objects.create(**{**defaults, **kwargs})


class PermissionTests(ApiTestCase):
    def endpoints(self):
        destination = self.local_destination()
        job = BackupJob.objects.create(destination=destination)
        return [
            ("get", f"{BASE}/destinations/"),
            ("post", f"{BASE}/destinations/"),
            ("get", f"{BASE}/destinations/{destination.pk}/"),
            ("patch", f"{BASE}/destinations/{destination.pk}/"),
            ("delete", f"{BASE}/destinations/{destination.pk}/"),
            ("post", f"{BASE}/destinations/{destination.pk}/test/"),
            ("get", f"{BASE}/jobs/"),
            ("post", f"{BASE}/jobs/"),
            ("get", f"{BASE}/jobs/{job.pk}/"),
            ("get", f"{BASE}/jobs/{job.pk}/download/"),
            ("get", f"{BASE}/status/"),
        ]

    def test_every_endpoint_refuses_anonymous_callers(self):
        anonymous = APIClient()
        for method, url in self.endpoints():
            with self.subTest(method=method, url=url):
                self.assertIn(getattr(anonymous, method)(url, {}, format="json").status_code, (401, 403))

    def test_every_endpoint_refuses_owners_and_participants(self):
        """A backup spans the instance: an owner acting on it would be acting on
        every other community's rows."""
        endpoints = self.endpoints()
        for user in (self.world.owner, self.world.member):
            client = APIClient()
            authenticate(client, user)
            for method, url in endpoints:
                with self.subTest(role=user.role, method=method, url=url):
                    self.assertEqual(getattr(client, method)(url, {}, format="json").status_code, 403)

    def test_an_owner_cannot_read_the_destination_list_to_learn_where_backups_go(self):
        self.local_destination()
        client = APIClient()
        authenticate(client, make_user("other_owner", UserRole.ZEV_OWNER))
        self.assertEqual(client.get(f"{BASE}/destinations/").status_code, 403)


class DestinationCrudTests(ApiTestCase):
    def test_create_a_local_destination(self):
        response = self.client.post(
            f"{BASE}/destinations/", {"name": "nightly", "kind": "local", "path": self.dest_dir.name}, format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.data["name"], "nightly")
        self.assertEqual(response.data["credential_mode"], "instance_role")
        self.assertFalse(response.data["has_secret_access_key"])

    @override_settings(BACKUP_ENCRYPTION_KEYS=[KEY])
    def test_create_an_s3_destination_with_a_secret_and_never_see_it_again(self):
        response = self.client.post(
            f"{BASE}/destinations/",
            {
                "name": "cloud", "kind": "s3", "bucket": "b", "endpoint_url": "https://minio.internal:9000",
                "access_key_id": "AKIA", "secret_access_key": "TOP-SECRET-VALUE",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertTrue(response.data["has_secret_access_key"])
        self.assertEqual(response.data["credential_mode"], "stored")
        self.assertNotIn("secret_access_key", response.data)
        self.assertNotIn("TOP-SECRET-VALUE", response.content.decode())

        listed = self.client.get(f"{BASE}/destinations/")
        self.assertNotIn("TOP-SECRET-VALUE", listed.content.decode())
        detail = self.client.get(f"{BASE}/destinations/{response.data['id']}/")
        self.assertNotIn("TOP-SECRET-VALUE", detail.content.decode())

        stored = BackupDestination.objects.get(pk=response.data["id"])
        self.assertNotIn(b"TOP-SECRET-VALUE", bytes(stored.secret_access_key_encrypted))
        self.assertEqual(stored.secret_access_key, "TOP-SECRET-VALUE")

    @override_settings(BACKUP_ENCRYPTION_KEYS=[])
    def test_a_secret_cannot_be_stored_without_an_encryption_key_and_the_reason_is_given(self):
        response = self.client.post(
            f"{BASE}/destinations/",
            {"name": "cloud", "kind": "s3", "bucket": "b", "access_key_id": "AKIA", "secret_access_key": "x"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("BACKUP_ENCRYPTION_KEYS", str(response.data["secret_access_key"]))
        self.assertFalse(BackupDestination.objects.filter(name="cloud").exists())

    def test_a_path_inside_media_root_is_rejected(self):
        from django.conf import settings

        response = self.client.post(
            f"{BASE}/destinations/", {"name": "bad", "kind": "local", "path": settings.MEDIA_ROOT}, format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("MEDIA_ROOT", str(response.data["path"]))

    def test_invalid_combinations_are_reported_per_field(self):
        response = self.client.post(f"{BASE}/destinations/", {"name": "x", "kind": "s3"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("bucket", response.data)

    def test_names_must_be_unique(self):
        self.local_destination(name="dup")
        response = self.client.post(
            f"{BASE}/destinations/", {"name": "dup", "kind": "local", "path": self.dest_dir.name}, format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("name", response.data)

    def test_list_is_ordered_by_name(self):
        self.local_destination(name="b")
        self.local_destination(name="a")
        # Paginated like every other admin list; the frontend reads it with fetchAllPages.
        listing = self.client.get(f"{BASE}/destinations/").data
        self.assertEqual([d["name"] for d in listing["results"]], ["a", "b"])

    @override_settings(BACKUP_ENCRYPTION_KEYS=[KEY])
    def test_a_patch_without_a_secret_keeps_the_stored_one(self):
        destination = self.local_destination(name="cloud", kind="s3", path="", bucket="b", access_key_id="AKIA")
        destination.set_secret_access_key("kept")
        destination.save()
        response = self.client.patch(f"{BASE}/destinations/{destination.pk}/", {"region": "eu-west-1"}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        destination.refresh_from_db()
        self.assertEqual(destination.secret_access_key, "kept")
        self.assertEqual(destination.region, "eu-west-1")

    @override_settings(BACKUP_ENCRYPTION_KEYS=[KEY])
    def test_a_patch_with_a_new_secret_replaces_it(self):
        destination = self.local_destination(name="cloud", kind="s3", path="", bucket="b", access_key_id="AKIA")
        destination.set_secret_access_key("old")
        destination.save()
        self.client.patch(f"{BASE}/destinations/{destination.pk}/", {"secret_access_key": "new"}, format="json")
        destination.refresh_from_db()
        self.assertEqual(destination.secret_access_key, "new")

    @override_settings(BACKUP_ENCRYPTION_KEYS=[KEY])
    def test_an_empty_secret_clears_it_but_then_the_credential_pair_is_incomplete(self):
        destination = self.local_destination(name="cloud", kind="s3", path="", bucket="b", access_key_id="AKIA")
        destination.set_secret_access_key("old")
        destination.save()
        response = self.client.patch(f"{BASE}/destinations/{destination.pk}/", {"secret_access_key": ""}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("access_key_id", response.data)
        destination.refresh_from_db()
        self.assertTrue(destination.has_stored_secret)  # unchanged: the edit was refused

    @override_settings(BACKUP_ENCRYPTION_KEYS=[KEY])
    def test_clearing_both_halves_switches_to_an_instance_role(self):
        destination = self.local_destination(name="cloud", kind="s3", path="", bucket="b", access_key_id="AKIA")
        destination.set_secret_access_key("old")
        destination.save()
        response = self.client.patch(
            f"{BASE}/destinations/{destination.pk}/", {"secret_access_key": "", "access_key_id": ""}, format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.data["credential_mode"], "instance_role")

    def test_delete_removes_the_destination_but_keeps_the_jobs_and_their_locations(self):
        destination = self.local_destination()
        job = BackupJob.objects.create(
            destination=destination, status=BackupJobStatus.COMPLETED, archive_location="/backups/a.zip",
        )
        self.assertEqual(self.client.delete(f"{BASE}/destinations/{destination.pk}/").status_code, 204)
        job.refresh_from_db()
        self.assertIsNone(job.destination)
        self.assertEqual(job.archive_location, "/backups/a.zip")

    def test_the_test_endpoint_reports_a_working_destination(self):
        destination = self.local_destination()
        response = self.client.post(f"{BASE}/destinations/{destination.pk}/test/")
        self.assertEqual((response.status_code, response.data), (200, {"ok": True}))

    def test_the_test_endpoint_reports_a_broken_one_with_a_message_not_a_traceback(self):
        blocker = Path(self.dest_dir.name) / "file"
        blocker.write_text("x")
        destination = self.local_destination(path=str(blocker / "child"))
        response = self.client.post(f"{BASE}/destinations/{destination.pk}/test/")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Could not write", response.data["detail"])
        self.assertNotIn("Traceback", response.content.decode())

    def test_the_test_endpoint_404s_an_unknown_destination(self):
        self.assertEqual(self.client.post(f"{BASE}/destinations/{uuid.uuid4()}/test/").status_code, 404)


class DestinationAuditTests(ApiTestCase):
    def events(self, action_type):
        return AuditEvent.objects.filter(action_type=action_type)

    def test_create_update_and_delete_are_audited_as_governance(self):
        response = self.client.post(
            f"{BASE}/destinations/", {"name": "nightly", "kind": "local", "path": self.dest_dir.name}, format="json",
        )
        pk = response.data["id"]
        self.client.patch(f"{BASE}/destinations/{pk}/", {"enabled": False}, format="json")
        self.client.delete(f"{BASE}/destinations/{pk}/")
        for action in ("backup_destination.create", "backup_destination.update", "backup_destination.delete"):
            event = self.events(action).get()
            self.assertEqual(event.action_category, "governance", action)
            self.assertEqual(event.actor_user_id, self.world.admin.pk)
        self.assertEqual(self.events("backup_destination.update").get().changes_json["enabled"], {"before": True, "after": False})

    @override_settings(BACKUP_ENCRYPTION_KEYS=[KEY])
    def test_a_secret_never_reaches_the_audit_log_only_the_fact_it_changed(self):
        response = self.client.post(
            f"{BASE}/destinations/",
            {"name": "cloud", "kind": "s3", "bucket": "b", "access_key_id": "AKIA-DISTINCTIVE",
             "secret_access_key": "SECRET-DISTINCTIVE-VALUE"},
            format="json",
        )
        pk = response.data["id"]
        self.client.patch(f"{BASE}/destinations/{pk}/", {"secret_access_key": "ROTATED-DISTINCTIVE-VALUE"}, format="json")
        everything = repr(list(AuditEvent.objects.values("changes_json", "metadata_json", "summary")))
        self.assertNotIn("SECRET-DISTINCTIVE-VALUE", everything)
        self.assertNotIn("ROTATED-DISTINCTIVE-VALUE", everything)
        self.assertTrue(self.events("backup_destination.update").get().metadata_json["secret_changed"])


class JobCreateTests(ApiTestCase):
    def create(self, payload):
        """Post, then run any callback the view registered for after commit.

        A ``TestCase`` runs inside a transaction, so ``on_commit`` is deferred
        and would otherwise never fire; the callback is invoked by hand while
        the task is still patched.
        """
        with mock.patch("backups.views.transaction.on_commit") as on_commit, \
                mock.patch.object(tasks.run_backup_job, "delay") as delay:
            response = self.client.post(f"{BASE}/jobs/", payload, format="json")
            for call in on_commit.call_args_list:
                call.args[0]()
        return response, delay

    def test_a_backup_is_queued_and_enqueued_after_the_row_is_committed(self):
        destination = self.local_destination()
        response, delay = self.create({"scope": "instance", "destination_id": str(destination.pk)})
        self.assertEqual(response.status_code, 202, response.content)
        self.assertEqual(response.data["status"], "queued")
        self.assertEqual(response.data["destination_name"], "disk")
        job = BackupJob.objects.get(pk=response.data["id"])
        self.assertEqual(job.requester_id, self.world.admin.pk)
        delay.assert_called_once_with(str(job.pk))

    def test_a_zev_backup_names_its_zev(self):
        destination = self.local_destination()
        response, _ = self.create(
            {"scope": "zev", "zev_id": str(self.world.alpha.pk), "destination_id": str(destination.pk)},
        )
        self.assertEqual(response.status_code, 202, response.content)
        self.assertEqual(response.data["zev_name"], "Alpha")

    def test_creation_is_audited_as_queued(self):
        destination = self.local_destination()
        self.create({"scope": "instance", "destination_id": str(destination.pk)})
        event = AuditEvent.objects.get(action_type="backup.created")
        self.assertEqual((event.status, event.action_category), ("queued", "system"))

    def test_a_broker_outage_fails_the_job_and_returns_503_never_a_202(self):
        destination = self.local_destination()
        # Run the callback inline, as autocommit does in production, so the
        # view's own try/except sees the broker error.
        with mock.patch("backups.views.transaction.on_commit", side_effect=lambda fn: fn()), \
                mock.patch.object(tasks.run_backup_job, "delay", side_effect=RuntimeError("broker down")), \
                self.assertLogs("backups.views", level="ERROR"):
            response = self.client.post(
                f"{BASE}/jobs/", {"scope": "instance", "destination_id": str(destination.pk)}, format="json",
            )
        self.assertEqual(response.status_code, 503)
        job = BackupJob.objects.get()
        self.assertEqual(job.status, BackupJobStatus.FAILED)
        self.assertNotIn("broker down", job.error_message)
        self.assertTrue(AuditEvent.objects.filter(action_type="backup.failed").exists())

    def test_validation(self):
        destination = self.local_destination()
        disabled = self.local_destination(name="off", enabled=False)
        cases = {
            "unknown destination": ({"scope": "instance", "destination_id": str(uuid.uuid4())}, "destination_id"),
            "disabled destination": ({"scope": "instance", "destination_id": str(disabled.pk)}, "destination_id"),
            "no destination": ({"scope": "instance"}, "destination_id"),
            "bad scope": ({"scope": "galaxy", "destination_id": str(destination.pk)}, "scope"),
            "zev scope without a zev": ({"scope": "zev", "destination_id": str(destination.pk)}, "zev_id"),
            "unknown zev": ({"scope": "zev", "zev_id": str(uuid.uuid4()), "destination_id": str(destination.pk)}, "zev_id"),
            "instance scope with a zev": (
                {"scope": "instance", "zev_id": str(self.world.alpha.pk), "destination_id": str(destination.pk)}, "zev_id",
            ),
        }
        for label, (payload, field) in cases.items():
            with self.subTest(label):
                response, delay = self.create(payload)
                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.data)
                delay.assert_not_called()
        self.assertFalse(BackupJob.objects.exists())


class JobReadTests(ApiTestCase):
    def test_list_is_newest_first_and_filterable(self):
        destination = self.local_destination()
        old = BackupJob.objects.create(destination=destination, status=BackupJobStatus.FAILED)
        new = BackupJob.objects.create(destination=destination, scope="zev", zev=self.world.alpha)
        ids = [j["id"] for j in self.client.get(f"{BASE}/jobs/").data]
        self.assertEqual(ids, [str(new.pk), str(old.pk)])
        self.assertEqual([j["id"] for j in self.client.get(f"{BASE}/jobs/?status=failed").data], [str(old.pk)])
        self.assertEqual([j["id"] for j in self.client.get(f"{BASE}/jobs/?scope=zev").data], [str(new.pk)])

    def test_limit_is_clamped(self):
        destination = self.local_destination()
        for _ in range(3):
            BackupJob.objects.create(destination=destination)
        self.assertEqual(len(self.client.get(f"{BASE}/jobs/?limit=2").data), 2)
        self.assertEqual(len(self.client.get(f"{BASE}/jobs/?limit=0").data), 1)
        self.assertEqual(len(self.client.get(f"{BASE}/jobs/?limit=nonsense").data), 3)

    def test_detail_returns_the_manifest_summary(self):
        destination = self.local_destination()
        job = BackupJob.objects.create(destination=destination)
        tasks.execute_backup_job(job.pk)
        data = self.client.get(f"{BASE}/jobs/{job.pk}/").data
        self.assertEqual(data["status"], "completed")
        self.assertEqual(data["manifest_json"]["kind"], "backup")
        self.assertNotIn("requester", data)

    def test_an_unknown_job_is_a_404(self):
        self.assertEqual(self.client.get(f"{BASE}/jobs/{uuid.uuid4()}/").status_code, 404)


class DownloadTests(ApiTestCase):
    def completed_job(self):
        destination = self.local_destination()
        job = BackupJob.objects.create(destination=destination)
        tasks.execute_backup_job(job.pk)
        job.refresh_from_db()
        return job

    def test_a_local_archive_is_streamed_with_its_own_name(self):
        job = self.completed_job()
        response = self.client.get(f"{BASE}/jobs/{job.pk}/download/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(job.archive_name, response["Content-Disposition"])
        self.assertEqual(b"".join(response.streaming_content), Path(job.archive_location).read_bytes())

    def test_a_job_with_no_artifact_is_a_409(self):
        job = BackupJob.objects.create(destination=self.local_destination())
        self.assertEqual(self.client.get(f"{BASE}/jobs/{job.pk}/download/").status_code, 409)

    def test_an_s3_archive_is_fetched_from_the_bucket_not_proxied(self):
        bucket = BackupDestination.objects.create(name="cloud", kind="s3", bucket="b")
        job = BackupJob.objects.create(
            destination=bucket, status=BackupJobStatus.COMPLETED, archive_location="s3://b/a.zip",
        )
        response = self.client.get(f"{BASE}/jobs/{job.pk}/download/")
        self.assertEqual(response.status_code, 409)
        self.assertIn("s3://b/a.zip", response.data["detail"])

    def test_a_deleted_file_is_gone(self):
        job = self.completed_job()
        Path(job.archive_location).unlink()
        self.assertEqual(self.client.get(f"{BASE}/jobs/{job.pk}/download/").status_code, 410)

    def test_a_deleted_destination_is_gone(self):
        job = self.completed_job()
        job.destination.delete()
        self.assertEqual(self.client.get(f"{BASE}/jobs/{job.pk}/download/").status_code, 410)

    def test_a_location_outside_the_destination_is_never_served(self):
        """The location is read from the database; it must not be a way to read any file."""
        job = self.completed_job()
        BackupJob.objects.filter(pk=job.pk).update(archive_location="/etc/passwd")
        response = self.client.get(f"{BASE}/jobs/{job.pk}/download/")
        self.assertEqual(response.status_code, 410)

    def test_a_dotdot_location_that_escapes_the_destination_is_never_served(self):
        job = self.completed_job()
        outside = Path(self.dest_dir.name).parent / "outside.txt"
        outside.write_text("secret")
        self.addCleanup(outside.unlink)
        BackupJob.objects.filter(pk=job.pk).update(archive_location=f"{self.dest_dir.name}/../outside.txt")
        self.assertEqual(self.client.get(f"{BASE}/jobs/{job.pk}/download/").status_code, 410)


class StatusTests(ApiTestCase):
    def status(self):
        return self.client.get(f"{BASE}/status/").data

    def test_a_fresh_instance_reports_no_backups_and_no_key(self):
        data = self.status()
        self.assertFalse(data["encrypted"])
        self.assertEqual(data["encryption_key_fingerprint"], "")
        self.assertEqual((data["last_successful"], data["last_failed"], data["age_hours"]), (None, None, None))
        self.assertEqual(data["destinations_enabled"], 0)

    @override_settings(BACKUP_ENCRYPTION_KEYS=[KEY])
    def test_a_configured_key_is_reported_by_fingerprint_never_by_value(self):
        from backups import crypto

        data = self.status()
        self.assertTrue(data["encrypted"])
        self.assertEqual(data["encryption_key_fingerprint"], crypto.key_fingerprint(KEY))
        self.assertNotIn(KEY, str(data))

    @override_settings(BACKUP_ENCRYPTION_KEYS=["too-short"])
    def test_a_key_that_is_set_but_unusable_is_called_out_not_read_as_unset(self):
        data = self.status()
        self.assertFalse(data["encrypted"])
        self.assertIn("shorter than", data["encryption_key_problem"])

    @override_settings(BACKUP_S3_ACCESS_KEY_ID="ENV", BACKUP_S3_SECRET_ACCESS_KEY="envsecret")
    def test_environment_credentials_are_reported_without_their_values(self):
        data = self.status()
        self.assertTrue(data["environment_credentials"])
        self.assertNotIn("envsecret", str(data))

    def test_last_successful_and_last_failed_and_age(self):
        destination = self.local_destination()
        ok = BackupJob.objects.create(destination=destination)
        tasks.execute_backup_job(ok.pk)
        failed = BackupJob.objects.create(destination=destination, status=BackupJobStatus.FAILED, error_message="boom")
        data = self.status()
        self.assertEqual(data["last_successful"]["id"], str(ok.pk))
        self.assertEqual(data["last_failed"]["id"], str(failed.pk))
        self.assertLess(data["age_hours"], 0.1)
        self.assertEqual(data["destinations_enabled"], 1)

    def test_disabled_destinations_are_not_counted(self):
        self.local_destination(enabled=False)
        self.assertEqual(self.status()["destinations_enabled"], 0)
