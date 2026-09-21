"""The built-in schedule, the scheduled run, its API, and the warning about unencrypted schedules."""

import tempfile
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase, override_settings
from django_celery_beat.models import CrontabSchedule, PeriodicTask, PeriodicTasks
from rest_framework.test import APIClient

from audit.models import AuditEvent
from backups import checks, schedule, tasks
from backups.fixtures import build_world
from backups.models import BackupDestination, BackupJob, BackupJobStatus
from testing.helpers import authenticate

BASE = "/api/v1/backups"


class ScheduleModelTests(TestCase):
    def test_before_anything_is_saved_the_schedule_reads_as_off_with_sensible_defaults(self):
        current = schedule.get_schedule()
        self.assertFalse(current["enabled"])
        self.assertEqual((current["frequency"], current["hour"], current["minute"]), ("daily", 2, 0))
        self.assertEqual(current["interval_hours"], 24)
        self.assertIsNone(current["last_run_at"])
        self.assertFalse(PeriodicTask.objects.filter(name=schedule.TASK_NAME).exists(), "nothing is created on read")

    def test_saving_creates_the_periodic_task_beat_will_run(self):
        schedule.set_schedule(enabled=True, frequency="daily", hour=3, minute=30, day_of_week=0)
        task = PeriodicTask.objects.get(name=schedule.TASK_NAME)
        self.assertEqual(task.task, "backups.tasks.scheduled_backup")
        self.assertTrue(task.enabled)
        cron = task.crontab
        self.assertEqual((cron.hour, cron.minute, cron.day_of_week), ("3", "30", "*"))
        self.assertEqual(str(cron.timezone), "Europe/Zurich")

    def test_weekly_carries_the_day_and_doubles_as_a_week_long_interval(self):
        result = schedule.set_schedule(enabled=True, frequency="weekly", hour=1, minute=0, day_of_week=6)
        self.assertEqual((result["frequency"], result["day_of_week"], result["interval_hours"]), ("weekly", 6, 168))

    def test_a_second_save_edits_the_one_task_rather_than_adding_another(self):
        schedule.set_schedule(enabled=True, frequency="daily", hour=2, minute=0, day_of_week=0)
        schedule.set_schedule(enabled=False, frequency="weekly", hour=5, minute=15, day_of_week=3)
        self.assertEqual(PeriodicTask.objects.filter(name=schedule.TASK_NAME).count(), 1)
        current = schedule.get_schedule()
        self.assertEqual(
            (current["enabled"], current["frequency"], current["hour"], current["minute"], current["day_of_week"]),
            (False, "weekly", 5, 15, 3),
        )

    def test_identical_times_share_a_crontab_row(self):
        schedule.set_schedule(enabled=True, frequency="daily", hour=2, minute=0, day_of_week=0)
        schedule.set_schedule(enabled=False, frequency="daily", hour=2, minute=0, day_of_week=0)
        self.assertEqual(CrontabSchedule.objects.filter(hour="2", minute="0", day_of_week="*").count(), 1)

    def test_a_save_notifies_beat_so_the_change_takes_effect_without_a_restart(self):
        schedule.set_schedule(enabled=True, frequency="daily", hour=2, minute=0, day_of_week=0)
        first = PeriodicTasks.last_change()
        schedule.set_schedule(enabled=True, frequency="daily", hour=4, minute=0, day_of_week=0)
        self.assertGreater(PeriodicTasks.last_change(), first)


class ScheduledRunTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.world = build_world()

    def setUp(self):
        self.dirs = []
        self.addCleanup(lambda: [d.cleanup() for d in self.dirs])

    def destination(self, name, **kwargs):
        directory = tempfile.TemporaryDirectory()
        self.dirs.append(directory)
        return BackupDestination.objects.create(name=name, kind="local", path=directory.name, **kwargs)

    def run_it(self):
        with mock.patch.object(tasks.run_backup_job, "delay") as delay:
            return tasks.run_scheduled_backup(), delay

    def test_one_whole_instance_backup_per_enabled_destination(self):
        a, b = self.destination("a"), self.destination("b")
        self.destination("off", enabled=False)
        result, delay = self.run_it()
        self.assertEqual(result, {"queued": ["a", "b"], "skipped": []})
        jobs = BackupJob.objects.order_by("destination__name")
        self.assertEqual([(j.destination_id, j.scope, j.trigger, j.status) for j in jobs],
                         [(a.pk, "instance", "scheduled", "queued"), (b.pk, "instance", "scheduled", "queued")])
        self.assertEqual(delay.call_count, 2)
        self.assertTrue(all(j.requester_id is None for j in jobs))

    def test_a_destination_that_is_still_busy_is_skipped_not_piled_on(self):
        busy = self.destination("busy")
        BackupJob.objects.create(destination=busy, status=BackupJobStatus.RUNNING)
        self.destination("free")
        result, _ = self.run_it()
        self.assertEqual(result, {"queued": ["free"], "skipped": ["busy"]})

    def test_a_finished_backup_does_not_block_the_next(self):
        done = self.destination("done")
        BackupJob.objects.create(destination=done, status=BackupJobStatus.COMPLETED)
        self.assertEqual(self.run_it()[0]["queued"], ["done"])

    def test_a_community_backup_in_flight_does_not_block_the_instance_backup(self):
        d = self.destination("d")
        BackupJob.objects.create(destination=d, scope="zev", zev=self.world.alpha, status=BackupJobStatus.RUNNING)
        self.assertEqual(self.run_it()[0]["queued"], ["d"])

    def test_with_nowhere_to_write_it_does_nothing(self):
        self.assertEqual(self.run_it()[0], {"queued": [], "skipped": []})
        self.assertFalse(BackupJob.objects.exists())

    def test_a_broker_outage_fails_that_job_visibly_instead_of_leaving_it_queued_forever(self):
        self.destination("d")
        with mock.patch.object(tasks.run_backup_job, "delay", side_effect=RuntimeError("broker down")), \
                self.assertLogs("backups.tasks", "ERROR"):
            tasks.run_scheduled_backup()
        job = BackupJob.objects.get()
        self.assertEqual(job.status, BackupJobStatus.FAILED)
        self.assertNotIn("broker down", job.error_message)

    def test_the_celery_task_runs_it(self):
        self.destination("d")
        with mock.patch.object(tasks.run_backup_job, "delay"):
            self.assertEqual(tasks.scheduled_backup()["queued"], ["d"])

    def test_a_scheduled_backup_executes_like_any_other(self):
        d = self.destination("d")
        with mock.patch.object(tasks.run_backup_job, "delay"):
            tasks.run_scheduled_backup()
        job = BackupJob.objects.get()
        tasks.execute_backup_job(job.pk)
        job.refresh_from_db()
        self.assertEqual((job.status, job.trigger, job.destination_id), ("completed", "scheduled", d.pk))


class ScheduleApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.world = build_world()

    def setUp(self):
        self.client = APIClient()
        authenticate(self.client, self.world.admin)

    def put(self, **overrides):
        body = {"enabled": True, "frequency": "daily", "hour": 2, "minute": 0, **overrides}
        return self.client.put(f"{BASE}/schedule/", body, format="json")

    def test_every_endpoint_refuses_anonymous_owners_and_participants(self):
        for client in (APIClient(), *(self._as(u) for u in (self.world.owner, self.world.member))):
            for method in ("get", "put"):
                with self.subTest(method=method):
                    code = getattr(client, method)(f"{BASE}/schedule/", {}, format="json").status_code
                    self.assertIn(code, (401, 403))

    def _as(self, user):
        client = APIClient()
        authenticate(client, user)
        return client

    def test_a_fresh_instance_reads_as_off(self):
        data = self.client.get(f"{BASE}/schedule/").data
        self.assertFalse(data["enabled"])
        self.assertEqual((data["timezone"], data["interval_hours"]), ("Europe/Zurich", 24))

    def test_saving_returns_the_new_schedule(self):
        response = self.put(frequency="weekly", hour=4, minute=45, day_of_week=2)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            {k: response.data[k] for k in ("enabled", "frequency", "hour", "minute", "day_of_week", "interval_hours")},
            {"enabled": True, "frequency": "weekly", "hour": 4, "minute": 45, "day_of_week": 2, "interval_hours": 168},
        )
        self.assertEqual(self.client.get(f"{BASE}/schedule/").data["hour"], 4)

    def test_validation(self):
        for label, overrides in {
            "hour too high": {"hour": 24}, "negative hour": {"hour": -1}, "minute too high": {"minute": 60},
            "unknown frequency": {"frequency": "hourly"}, "day out of range": {"frequency": "weekly", "day_of_week": 7},
        }.items():
            with self.subTest(label):
                self.assertEqual(self.put(**overrides).status_code, 400)
        self.assertFalse(PeriodicTask.objects.filter(name=schedule.TASK_NAME).exists())

    def test_a_change_is_audited_as_governance_with_what_changed(self):
        self.put(hour=3)
        self.put(enabled=False, hour=5)
        event = AuditEvent.objects.filter(action_type="backup_schedule.update").latest("created_at")
        self.assertEqual((event.action_category, event.summary), ("governance", "Backup schedule disabled."))
        self.assertEqual(event.changes_json["hour"], {"before": 3, "after": 5})
        self.assertEqual(event.changes_json["enabled"], {"before": True, "after": False})

    def test_the_status_reports_the_schedule_and_when_it_has_fallen_behind(self):
        self.put(enabled=True)
        data = self.client.get(f"{BASE}/status/").data
        self.assertTrue(data["schedule_enabled"])
        self.assertEqual(data["schedule_interval_hours"], 24)
        self.assertTrue(data["stale"], "a schedule with no backup yet is stale")


class UnencryptedScheduleWarningTests(TestCase):
    def check(self, databases=("default",)):
        return checks.scheduled_backup_is_encrypted(None, databases=databases)

    def test_no_warning_when_nothing_is_scheduled(self):
        self.assertEqual(self.check(), [])

    def test_a_schedule_without_a_key_warns(self):
        schedule.set_schedule(enabled=True, frequency="daily", hour=2, minute=0, day_of_week=0)
        (warning,) = self.check()
        self.assertEqual(warning.id, "backups.W001")
        self.assertIn("BACKUP_ENCRYPTION_KEYS", warning.msg)

    @override_settings(BACKUP_ENCRYPTION_KEYS=["K" * 40])
    def test_a_key_silences_it(self):
        schedule.set_schedule(enabled=True, frequency="daily", hour=2, minute=0, day_of_week=0)
        self.assertEqual(self.check(), [])

    def test_a_disabled_schedule_does_not_warn(self):
        schedule.set_schedule(enabled=False, frequency="daily", hour=2, minute=0, day_of_week=0)
        self.assertEqual(self.check(), [])

    def test_an_ordinary_check_needs_no_database_and_stays_silent(self):
        schedule.set_schedule(enabled=True, frequency="daily", hour=2, minute=0, day_of_week=0)
        self.assertEqual(self.check(databases=None), [])

    def test_it_is_wired_into_manage_py_check(self):
        schedule.set_schedule(enabled=True, frequency="daily", hour=2, minute=0, day_of_week=0)
        err = StringIO()
        call_command("check", "--database", "default", stdout=StringIO(), stderr=err)
        self.assertIn("backups.W001", err.getvalue())

    def test_unmigrated_database_does_not_break_the_check(self):
        from django.db import DatabaseError

        with mock.patch("backups.schedule.get_schedule", side_effect=DatabaseError("no such table")):
            self.assertEqual(self.check(), [])

