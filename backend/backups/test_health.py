"""Is the instance protected? The staleness rule, the status it maps to, and the two places it is shown."""

import tempfile
from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from backups import health, schedule
from backups.fixtures import build_world
from backups.models import BackupDestination, BackupJob, BackupJobStatus
from testing.helpers import authenticate

HEALTH_URL = "/api/v1/auth/system-health/"


class HealthTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.world = build_world()

    def setUp(self):
        self.dest_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dest_dir.cleanup)

    def destination(self, **kwargs):
        return BackupDestination.objects.create(name=kwargs.pop("name", "disk"), kind="local", path=self.dest_dir.name, **kwargs)

    def finished(self, hours_ago, **kwargs) -> BackupJob:
        job = BackupJob.objects.create(
            destination=BackupDestination.objects.first(), status=BackupJobStatus.COMPLETED, **kwargs,
        )
        BackupJob.objects.filter(pk=job.pk).update(completed_at=timezone.now() - timedelta(hours=hours_ago))
        return job

    def failed(self, hours_ago) -> BackupJob:
        job = BackupJob.objects.create(destination=BackupDestination.objects.first(), status=BackupJobStatus.FAILED)
        BackupJob.objects.filter(pk=job.pk).update(completed_at=timezone.now() - timedelta(hours=hours_ago))
        return job

    def schedule(self, enabled=True, frequency="daily"):
        schedule.set_schedule(enabled=enabled, frequency=frequency, hour=2, minute=0, day_of_week=0)


class StalenessTests(HealthTestCase):
    def test_without_a_schedule_nothing_is_ever_stale(self):
        self.destination()
        self.finished(hours_ago=24 * 90)
        self.assertFalse(health.backup_health()["stale"])

    def test_a_backup_within_twice_the_interval_is_fresh(self):
        self.destination()
        self.schedule()
        self.finished(hours_ago=47)
        self.assertFalse(health.backup_health()["stale"])

    def test_one_missed_run_is_tolerated_and_two_are_not(self):
        self.destination()
        self.schedule()
        self.finished(hours_ago=49)
        self.assertTrue(health.backup_health()["stale"])

    def test_a_weekly_schedule_has_a_weekly_yardstick(self):
        self.destination()
        self.schedule(frequency="weekly")
        self.finished(hours_ago=24 * 10)
        self.assertFalse(health.backup_health()["stale"])
        BackupJob.objects.all().update(completed_at=timezone.now() - timedelta(days=15))
        self.assertTrue(health.backup_health()["stale"])

    def test_a_schedule_that_has_never_produced_a_backup_is_stale(self):
        self.destination()
        self.schedule()
        result = health.backup_health()
        self.assertTrue(result["stale"])
        self.assertIsNone(result["age_hours"])

    def test_a_disabled_schedule_is_not_stale(self):
        self.destination()
        self.schedule(enabled=False)
        self.assertFalse(health.backup_health()["stale"])

    def test_a_safety_backup_or_a_community_backup_does_not_freshen_it(self):
        self.destination()
        self.schedule()
        self.finished(hours_ago=1, scope="zev", zev=self.world.alpha)
        self.finished(hours_ago=1, scope="zev", zev=self.world.beta, trigger="pre_restore")
        self.assertTrue(health.backup_health()["stale"])


class StatusMappingTests(HealthTestCase):
    def status(self):
        return health.backup_health()["status"]

    def test_no_enabled_destination_means_backups_are_not_set_up_which_is_not_a_fault(self):
        self.destination(enabled=False)
        self.assertEqual(self.status(), "unknown")

    def test_a_destination_that_has_never_been_used_is_degraded(self):
        self.destination()
        self.assertEqual(self.status(), "degraded")

    def test_a_recent_success_is_ok(self):
        self.destination()
        self.finished(hours_ago=3)
        self.assertEqual(self.status(), "ok")

    def test_a_failure_after_the_last_success_is_degraded(self):
        self.destination()
        self.finished(hours_ago=10)
        self.failed(hours_ago=2)
        result = health.backup_health()
        self.assertEqual(result["status"], "degraded")
        self.assertTrue(result["last_failed_after_success"])

    def test_an_old_failure_before_a_success_is_forgiven(self):
        self.destination()
        self.failed(hours_ago=10)
        self.finished(hours_ago=2)
        self.assertEqual(self.status(), "ok")

    def test_a_stale_schedule_is_degraded_even_without_a_failure(self):
        self.destination()
        self.schedule()
        self.finished(hours_ago=100)
        self.assertEqual(self.status(), "degraded")

    @override_settings(BACKUP_ENCRYPTION_KEYS=["K" * 40])
    def test_the_payload_reports_encryption_and_the_schedule(self):
        self.destination()
        self.schedule()
        self.finished(hours_ago=1)
        result = health.backup_health()
        self.assertTrue(result["encrypted"])
        self.assertEqual((result["schedule_enabled"], result["schedule_interval_hours"]), (True, 24))
        self.assertEqual(result["destinations_enabled"], 1)
        self.assertEqual(result["age_hours"], 1.0)

    @override_settings(BACKUP_ENCRYPTION_KEYS=["too-short"])
    def test_an_unusable_key_is_not_encrypted_and_not_an_error(self):
        self.assertFalse(health.backup_health()["encrypted"])


class SystemHealthEndpointTests(HealthTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        authenticate(self.client, self.world.admin)

    def probe(self):
        return self.client.get(HEALTH_URL).data["backups"]

    def test_the_health_snapshot_carries_a_backups_probe(self):
        self.assertEqual(self.probe()["status"], "unknown")

    def test_a_stale_schedule_shows_up_as_degraded_with_the_facts_the_card_needs(self):
        self.destination()
        self.schedule()
        self.finished(hours_ago=100)
        probe = self.probe()
        self.assertEqual((probe["status"], probe["stale"], probe["schedule_enabled"]), ("degraded", True, True))
        self.assertEqual(probe["age_hours"], 100.0)
        self.assertTrue(probe["last_successful_at"])

    def test_it_never_names_a_destination_or_a_path(self):
        self.destination(name="secret-offsite-bucket")
        self.finished(hours_ago=1)
        self.assertNotIn("secret-offsite-bucket", str(self.client.get(HEALTH_URL).data))
        self.assertNotIn(self.dest_dir.name, str(self.client.get(HEALTH_URL).data))

    def test_a_failing_probe_degrades_to_unknown_instead_of_breaking_the_tab(self):
        from unittest import mock

        with mock.patch("backups.health.backup_health", side_effect=RuntimeError("boom")):
            response = self.client.get(HEALTH_URL)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["backups"], {"status": "unknown"})
