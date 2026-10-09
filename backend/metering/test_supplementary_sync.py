"""Sync tasks and the test/sync/reconciliation actions of SPEC §6.3 and §5."""

from datetime import timedelta
from decimal import Decimal
from unittest import mock

from celery.exceptions import Retry
from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone

from audit.models import AuditEvent
from metering import tasks
from metering.models import SupplementaryReading, SupplementarySource, SupplementaryStatus
from metering.supplementary import solar_manager, sync
from metering.supplementary.testing import (
    INTEGRATION_KEY,
    SOURCES_URL,
    StubSolarManager,
    SupplementaryApiTestCase,
    client_for,
    enable_feature,
    vendor_row,
)
from testing import factories


class SyncTestCase(SupplementaryApiTestCase):
    def setUp(self):
        super().setUp()
        self.vendor = StubSolarManager().start()
        self.addCleanup(self.vendor.stop)
        for override in (
            override_settings(
                SOLAR_MANAGER_BASE_URL=self.vendor.url,
                INTEGRATION_ENCRYPTION_KEYS=[INTEGRATION_KEY],
                SUPPLEMENTARY_BACKFILL_MAX_DAYS=30,
            ),
        ):
            override.enable()
            self.addCleanup(override.disable)
        pause = mock.patch.object(solar_manager, "PAUSE_BETWEEN_REQUESTS_S", 0)
        pause.start()
        self.addCleanup(pause.stop)
        # The holder took over the meter three days ago, so a first sync is a few requests, not hundreds.
        self.assignment.valid_from = timezone.localdate() - timedelta(days=3)
        self.assignment.save()
        self.source = self.make_source()

    def make_source(self, point=None, participant=None, token="key-1"):
        source = SupplementarySource(
            metering_point=point or self.point, participant=participant or self.holder,
            provider="solar_manager", external_id="ABC123", label="Solar Manager",
        )
        source.set_credential(token)
        source.save()
        return source

    def run_sync(self, **kwargs):
        return tasks.sync_supplementary_source_impl(str(self.source.pk), **kwargs)

    def stored(self):
        return SupplementaryReading.objects.filter(source=self.source)


class SyncStorageTests(SyncTestCase):
    def test_a_first_sync_stores_the_tenancy_and_marks_the_source_ok(self):
        result = self.run_sync()
        self.assertGreater(result["accepted"], 96 * 3)
        self.source.refresh_from_db()
        self.assertEqual(self.source.status, SupplementaryStatus.OK)
        self.assertIsNotNone(self.source.last_success_at)
        self.assertEqual(self.source.last_error, "")
        self.assertEqual(self.source.covers_from, self.stored().order_by("timestamp").first().timestamp)
        self.assertEqual(self.source.synced_through, self.stored().order_by("-timestamp").first().timestamp + timedelta(minutes=15))

    def test_values_are_stored_in_kwh_from_the_four_measured_flows(self):
        self.run_sync()
        reading = self.stored().order_by("timestamp").first()
        row = vendor_row(reading.timestamp)
        self.assertEqual(reading.consumption_kwh, Decimal(row["cWh"]) / 1000)
        self.assertEqual(reading.production_kwh, Decimal(row["pWh"]) / 1000)
        self.assertEqual(reading.import_kwh, Decimal(row["iWh"]) / 1000)
        self.assertEqual(reading.export_kwh, Decimal(row["eWh"]) / 1000)

    def test_nothing_is_requested_or_stored_before_the_tenancy_started(self):
        self.run_sync()
        tenancy_start = sync.personal_windows(self.source)[0][0]
        self.assertGreaterEqual(self.stored().order_by("timestamp").first().timestamp, tenancy_start)
        asked = [r["query"]["from"] for r in self.vendor.range_requests]
        self.assertTrue(all(stamp >= tenancy_start.strftime("%Y-%m-%dT%H:%M:%S") for stamp in asked))

    def test_the_backfill_never_reaches_further_back_than_the_limit(self):
        self.assignment.valid_from = timezone.localdate() - timedelta(days=400)
        self.assignment.save()
        with override_settings(SUPPLEMENTARY_BACKFILL_MAX_DAYS=2):
            self.run_sync()
        oldest = self.stored().order_by("timestamp").first().timestamp
        self.assertGreaterEqual(oldest, timezone.now() - timedelta(days=2, minutes=1))

    def test_the_last_interval_stored_is_a_complete_one(self):
        self.run_sync()
        newest = self.stored().order_by("-timestamp").first().timestamp
        self.assertLessEqual(newest + timedelta(minutes=15), timezone.now())

    def test_a_second_sync_fetches_only_the_two_day_overlap_and_new_data(self):
        self.run_sync()
        self.source.refresh_from_db()
        before_through = self.source.synced_through
        self.vendor.range_requests.clear()
        count = self.stored().count()
        self.run_sync()
        first_request = self.vendor.range_requests[0]["query"]["from"]
        # Re-fetching starts two days before the previous end, rounded to its civil day, not at the beginning.
        self.assertGreaterEqual(first_request, (before_through - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%S"))
        self.assertLess(len(self.vendor.range_requests), 5)
        self.assertGreaterEqual(self.stored().count(), count)

    def test_revised_vendor_values_inside_the_overlap_are_upserted(self):
        self.run_sync()
        victim = self.stored().order_by("-timestamp").first()
        SupplementaryReading.objects.filter(pk=victim.pk).update(production_kwh=Decimal("9.9999"))
        self.run_sync()
        victim.refresh_from_db()
        self.assertEqual(victim.production_kwh, Decimal(vendor_row(victim.timestamp)["pWh"]) / 1000)

    def test_backfill_ignores_the_stored_progress(self):
        self.run_sync()
        self.vendor.range_requests.clear()
        self.run_sync(backfill=True)
        self.assertGreaterEqual(len(self.vendor.range_requests), 3)

    def test_each_day_is_stored_before_the_next_is_requested(self):
        def fail_on_third(number):
            return (500, {}, b"") if number == 3 else None

        self.vendor.range_response = fail_on_third
        with self.assertRaises(sync.ProviderError):
            self.run_sync()
        self.assertEqual(self.stored().count(), 96 * 2)
        self.source.refresh_from_db()
        self.assertEqual(self.source.status, SupplementaryStatus.ERROR)
        self.assertIsNotNone(self.source.synced_through)  # the next run resumes from here

    def test_a_vendor_value_that_fails_validation_is_rejected_without_failing_the_sync(self):
        original = vendor_row
        with mock.patch("metering.supplementary.testing.vendor_row", side_effect=lambda t: {**original(t), "pWh": -900}):
            result = self.run_sync()
        self.assertEqual(result["accepted"], 0)
        self.assertGreater(result["rejected"], 0)
        self.source.refresh_from_db()
        self.assertEqual(self.source.status, SupplementaryStatus.OK)

    def test_a_run_that_finds_nothing_new_still_succeeds(self):
        self.run_sync()
        self.vendor.range_response = lambda n: (200, {"Content-Type": "application/json"}, b'{"data": []}')
        self.source.refresh_from_db()
        self.source.mark_error("earlier problem")
        self.source.save()
        self.run_sync()
        self.source.refresh_from_db()
        self.assertEqual(self.source.status, SupplementaryStatus.OK)
        self.assertEqual(self.source.last_error, "")

    def test_the_rotated_key_is_stored(self):
        self.run_sync()
        self.source.refresh_from_db()
        self.assertEqual(self.source.credential, f"key-{self.vendor.exchanges + 1}")

    def test_readings_never_reach_the_official_meter_table(self):
        from metering.models import MeterReading

        self.run_sync()
        self.assertEqual(MeterReading.objects.count(), 0)


class SyncFailureTests(SyncTestCase):
    def test_a_rejected_key_needs_a_reconnect_and_is_not_retried(self):
        self.vendor.current_token = "someone-elses"
        result = self.run_sync()
        self.assertEqual(result["error"], "reconnect_required")
        self.source.refresh_from_db()
        self.assertEqual(self.source.status, SupplementaryStatus.RECONNECT_REQUIRED)
        self.assertTrue(self.source.last_error)
        self.assertNotIn("key-1", self.source.last_error)

    def test_the_task_does_not_retry_an_auth_failure(self):
        self.vendor.current_token = "someone-elses"
        with mock.patch.object(tasks.sync_supplementary_source, "retry") as retry:
            tasks.sync_supplementary_source(str(self.source.pk))
        retry.assert_not_called()

    def test_a_credential_that_cannot_be_decrypted_needs_a_reconnect(self):
        from cryptography.fernet import Fernet

        with override_settings(INTEGRATION_ENCRYPTION_KEYS=[Fernet.generate_key().decode()]):
            result = self.run_sync()
        self.assertEqual(result["error"], "reconnect_required")
        self.source.refresh_from_db()
        self.assertEqual(self.source.status, SupplementaryStatus.RECONNECT_REQUIRED)
        self.assertEqual(self.vendor.refresh_requests, [])

    def test_a_transient_failure_sets_error_and_retries(self):
        self.vendor.range_response = lambda n: (503, {}, b"")
        with mock.patch.object(tasks.sync_supplementary_source, "retry", side_effect=Retry()) as retry:
            with self.assertRaises(Retry):
                tasks.sync_supplementary_source(str(self.source.pk))
        retry.assert_called_once()
        self.source.refresh_from_db()
        self.assertEqual(self.source.status, SupplementaryStatus.ERROR)
        self.assertIn("could not be reached", self.source.last_error)

    def test_a_rate_limit_waits_at_least_as_long_as_the_vendor_asked(self):
        self.vendor.range_response = lambda n: (429, {"Retry-After": "1800"}, b"{}")
        with mock.patch.object(tasks.sync_supplementary_source, "retry", side_effect=Retry()) as retry:
            with self.assertRaises(Retry):
                tasks.sync_supplementary_source(str(self.source.pk))
        self.assertEqual(retry.call_args.kwargs["countdown"], 1800)

    def test_a_rate_limit_with_no_advice_uses_the_default_delay(self):
        self.vendor.range_response = lambda n: (429, {}, b"{}")
        with mock.patch.object(tasks.sync_supplementary_source, "retry", side_effect=Retry()) as retry:
            with self.assertRaises(Retry):
                tasks.sync_supplementary_source(str(self.source.pk))
        self.assertEqual(retry.call_args.kwargs["countdown"], 600)

    def disconnect_during_request(self, on_call, then=None):
        """Patch the client so the source is disconnected while request ``on_call`` is in flight.

        Done on the test's own thread: the stand-in vendor runs on another one, and SQLite would
        lock the database between them.
        """
        from metering.supplementary.providers import PROVIDERS

        client = PROVIDERS["solar_manager"].client
        original = client.range
        calls = []

        def range_(*args, **kwargs):
            calls.append(1)
            if len(calls) == on_call:
                source = SupplementarySource.objects.get(pk=self.source.pk)
                source.disconnect()
                source.save()
                if then:
                    then()
            return original(*args, **kwargs)

        return mock.patch.object(client, "range", side_effect=range_)

    def test_a_failed_run_does_not_overwrite_a_disconnect_that_happened_meanwhile(self):
        self.vendor.range_response = lambda n: (500, {}, b"")
        with self.disconnect_during_request(1), self.assertRaises(sync.ProviderError):
            self.run_sync()
        self.source.refresh_from_db()
        self.assertEqual(self.source.status, SupplementaryStatus.DISABLED)
        self.assertFalse(self.source.enabled)

    def test_a_disconnect_between_two_days_stops_the_run_and_keeps_the_stored_days(self):
        with self.disconnect_during_request(2):
            result = self.run_sync()
        self.assertEqual(result["skipped"], "disabled")
        self.assertEqual(self.stored().count(), 96)
        self.source.refresh_from_db()
        self.assertEqual(self.source.status, SupplementaryStatus.DISABLED)


class SyncSkipTests(SyncTestCase):
    def test_nothing_runs_while_the_flag_is_off(self):
        enable_feature(False)
        self.assertEqual(self.run_sync()["skipped"], "feature_off")
        self.assertEqual(self.vendor.refresh_requests, [])

    def test_a_disabled_source_is_skipped(self):
        self.source.enabled = False
        self.source.save()
        self.assertEqual(self.run_sync()["skipped"], "disabled")

    def test_a_source_that_needs_a_reconnect_is_skipped(self):
        self.source.mark_reconnect_required("enter the key")
        self.source.save()
        self.assertEqual(self.run_sync()["skipped"], "reconnect_required")

    def test_a_push_source_is_not_pulled(self):
        push = SupplementarySource.objects.create(
            metering_point=factories.MeteringPointFactory(zev=self.zev, has_behind_meter_generation=True),
            participant=self.holder, provider="push",
        )
        self.assertEqual(tasks.sync_supplementary_source_impl(str(push.pk))["skipped"], "not_a_pull_source")

    def test_a_deleted_source_is_not_an_error(self):
        pk = self.source.pk
        self.source.delete()
        self.assertEqual(tasks.sync_supplementary_source_impl(str(pk))["skipped"], "missing")

    def test_a_source_that_is_being_synced_is_left_alone(self):
        with tasks.source_lock(self.source.pk) as acquired:
            self.assertTrue(acquired)
            self.assertEqual(self.run_sync()["skipped"], "busy")
        self.assertNotIn("skipped", self.run_sync())  # the lease was released

    def test_a_participant_who_holds_no_tenancy_has_nothing_to_sync(self):
        self.assignment.delete()
        self.assertEqual(self.run_sync()["skipped"], "nothing_to_sync")
        self.assertEqual(self.vendor.refresh_requests, [])

    def test_community_mode_tenancy_is_not_synced(self):
        from zev.models import AllocationMode

        self.assignment.allocation_mode = AllocationMode.COMMUNITY
        self.assignment.save()
        self.assertEqual(self.run_sync()["skipped"], "nothing_to_sync")


class FanOutTests(SyncTestCase):
    def test_every_enabled_pull_source_is_queued(self):
        second_point = factories.MeteringPointFactory(zev=self.zev, has_behind_meter_generation=True)
        factories.MeteringPointAssignmentFactory(
            metering_point=second_point, participant=self.other, valid_from=timezone.localdate() - timedelta(days=3)
        )
        second = self.make_source(point=second_point, participant=self.other)
        with mock.patch.object(tasks.sync_supplementary_source, "delay") as delay:
            result = tasks.refresh_supplementary_sources()
        self.assertEqual(result, {"queued": 2})
        self.assertEqual({call.args[0] for call in delay.call_args_list}, {str(self.source.pk), str(second.pk)})

    def test_push_disabled_and_reconnect_required_sources_are_not_queued(self):
        push_point = factories.MeteringPointFactory(zev=self.zev, has_behind_meter_generation=True)
        SupplementarySource.objects.create(metering_point=push_point, participant=self.holder, provider="push")
        disabled_point = factories.MeteringPointFactory(zev=self.zev, has_behind_meter_generation=True)
        disabled = self.make_source(point=disabled_point)
        disabled.enabled = False
        disabled.save()
        self.source.mark_reconnect_required("enter the key")
        self.source.save()
        with mock.patch.object(tasks.sync_supplementary_source, "delay") as delay:
            self.assertEqual(tasks.refresh_supplementary_sources(), {"queued": 0})
        delay.assert_not_called()

    def test_nothing_is_queued_while_the_flag_is_off(self):
        enable_feature(False)
        with mock.patch.object(tasks.sync_supplementary_source, "delay") as delay:
            self.assertEqual(tasks.refresh_supplementary_sources()["queued"], 0)
        delay.assert_not_called()

    def test_the_beat_schedule_lists_both_tasks(self):
        from django.conf import settings

        names = {entry["task"] for entry in settings.CELERY_BEAT_SCHEDULE.values()}
        self.assertLessEqual(
            {"metering.tasks.refresh_supplementary_sources", "metering.tasks.disable_orphaned_supplementary_sources"}, names
        )


class OrphanTests(SyncTestCase):
    def test_a_source_whose_tenancy_ended_is_disconnected_and_keeps_its_readings(self):
        self.run_sync()
        count = self.stored().count()
        self.assignment.valid_to = timezone.localdate() - timedelta(days=1)
        self.assignment.save()
        self.assertEqual(tasks.disable_orphaned_supplementary_sources(), {"disabled": 1})
        self.source.refresh_from_db()
        self.assertFalse(self.source.enabled)
        self.assertEqual(self.source.status, SupplementaryStatus.DISABLED)
        self.assertFalse(self.source.has_credential)
        self.assertEqual(self.stored().count(), count)
        event = AuditEvent.objects.get(action_type="supplementary_source.disconnect")
        self.assertEqual(event.metadata_json["reason"], "assignment_ended")

    def test_a_current_tenancy_is_left_alone(self):
        self.assertEqual(tasks.disable_orphaned_supplementary_sources(), {"disabled": 0})
        self.source.refresh_from_db()
        self.assertTrue(self.source.enabled)

    def test_a_tenancy_that_ends_in_the_future_is_still_current(self):
        self.assignment.valid_to = timezone.localdate() + timedelta(days=5)
        self.assignment.save()
        self.assertEqual(tasks.disable_orphaned_supplementary_sources(), {"disabled": 0})

    def test_a_community_mode_tenancy_does_not_keep_a_source_alive(self):
        from zev.models import AllocationMode

        self.assignment.allocation_mode = AllocationMode.COMMUNITY
        self.assignment.save()
        self.assertEqual(tasks.disable_orphaned_supplementary_sources(), {"disabled": 1})

    def test_nothing_happens_while_the_flag_is_off(self):
        self.assignment.valid_to = timezone.localdate() - timedelta(days=1)
        self.assignment.save()
        enable_feature(False)
        self.assertEqual(tasks.disable_orphaned_supplementary_sources()["disabled"], 0)


class SyncAuditTests(SyncTestCase):
    def test_a_sync_is_audited_without_any_token(self):
        self.run_sync()
        event = AuditEvent.objects.get(action_type="supplementary_source.sync")
        self.assertEqual(event.status, "success")
        self.assertEqual(event.source, "celery")
        self.assertGreater(event.metadata_json["accepted"], 0)
        blob = f"{event.summary} {event.metadata_json} {event.changes_json}"
        for token in ("key-1", "key-2", "access-1"):
            self.assertNotIn(token, blob)

    def test_a_failure_is_audited_with_the_outcome(self):
        self.vendor.current_token = "someone-elses"
        self.run_sync()
        event = AuditEvent.objects.get(action_type="supplementary_source.sync")
        self.assertEqual(event.status, "failed")
        self.assertEqual(event.metadata_json["outcome"], "reconnect_required")

    def test_a_broken_audit_write_does_not_fail_a_good_sync(self):
        with mock.patch.object(tasks, "record_audit_event", side_effect=RuntimeError("db down")):
            result = self.run_sync()
        self.assertGreater(result["accepted"], 0)

    def test_the_sync_stores_the_reconciliation_when_official_data_exists(self):
        from metering.models import MeterReading

        self.run_sync()
        for reading in self.stored():
            for direction, value in (("out", reading.export_kwh), ("in", reading.import_kwh)):
                MeterReading.objects.create(
                    metering_point=self.point, timestamp=reading.timestamp, energy_kwh=value, direction=direction
                )
        self.run_sync()
        self.source.refresh_from_db()
        self.assertIn(self.source.reconciliation["state"], ("ok", "warn", "insufficient"))
        self.assertIn("checked_at", self.source.reconciliation)

    def test_a_broken_reconciliation_does_not_fail_a_good_sync(self):
        with mock.patch("metering.supplementary.sync.reconcile.reconcile_and_store", side_effect=RuntimeError("bug")):
            result = self.run_sync()
        self.assertGreater(result["accepted"], 0)
        self.source.refresh_from_db()
        self.assertEqual(self.source.status, SupplementaryStatus.OK)


class ActionTests(SyncTestCase):
    def setUp(self):
        super().setUp()
        self.url = f"{SOURCES_URL}{self.source.pk}/"
        cache.delete(f"supplementary-sync-requested:{self.source.pk}")

    def test_test_reports_ok_and_keeps_the_rotated_key(self):
        response = client_for(self.holder_user).post(f"{self.url}test/")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json(), {"ok": True})
        self.source.refresh_from_db()
        self.assertEqual(self.source.credential, "key-2")

    def test_test_with_a_dead_key_is_a_safe_400_and_asks_for_a_reconnect(self):
        self.vendor.current_token = "someone-elses"
        response = client_for(self.holder_user).post(f"{self.url}test/")
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("key-1", response.content.decode())
        self.source.refresh_from_db()
        self.assertEqual(self.source.status, SupplementaryStatus.RECONNECT_REQUIRED)

    def test_test_with_the_vendor_down_is_a_400_that_keeps_the_status(self):
        self.vendor.range_response = lambda n: (503, {}, b"secret vendor text")
        response = client_for(self.holder_user).post(f"{self.url}test/")
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("secret vendor text", response.content.decode())
        self.source.refresh_from_db()
        self.assertEqual(self.source.status, SupplementaryStatus.PENDING)

    def test_only_the_owner_or_an_admin_may_test_or_sync(self):
        for user, expected in ((self.manager, 403), (self.viewer, 403), (self.other_user, 404),
                               (self.stranger, 404), (self.holder_user, 200), (self.admin, 200)):
            cache.delete(f"supplementary-sync-requested:{self.source.pk}")
            test = client_for(user).post(f"{self.url}test/")
            self.assertEqual(test.status_code, expected, (user.username, "test", test.content))
        with mock.patch.object(tasks.sync_supplementary_source, "delay"):
            for user, expected in ((self.manager, 403), (self.viewer, 403), (self.other_user, 404),
                                   (self.holder_user, 202)):
                cache.delete(f"supplementary-sync-requested:{self.source.pk}")
                self.assertEqual(client_for(user).post(f"{self.url}sync/").status_code, expected, user.username)

    def test_sync_queues_a_task_and_a_second_request_within_five_minutes_is_429(self):
        with mock.patch("metering.supplementary.views.sync_supplementary_source.delay") as delay:
            first = client_for(self.holder_user).post(f"{self.url}sync/")
            second = client_for(self.holder_user).post(f"{self.url}sync/")
        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 429)
        self.assertEqual(second["Retry-After"], "300")
        delay.assert_called_once_with(str(self.source.pk))

    def test_sync_is_refused_for_a_push_source(self):
        point = factories.MeteringPointFactory(zev=self.zev, has_behind_meter_generation=True)
        factories.MeteringPointAssignmentFactory(metering_point=point, participant=self.holder, valid_from=timezone.localdate())
        push = self.create_push_source(point=point).json()
        cache.clear()
        response = client_for(self.holder_user).post(f"{SOURCES_URL}{push['id']}/sync/")
        self.assertEqual(response.status_code, 400)

    def test_sync_and_test_are_refused_for_a_source_that_needs_a_new_key(self):
        self.source.mark_reconnect_required("enter the key")
        self.source.save()
        self.assertEqual(client_for(self.holder_user).post(f"{self.url}sync/").status_code, 400)

    def test_sync_and_test_are_refused_for_a_disconnected_source(self):
        self.source.disconnect()
        self.source.save()
        self.assertEqual(client_for(self.holder_user).post(f"{self.url}sync/").status_code, 400)
        self.assertEqual(client_for(self.holder_user).post(f"{self.url}test/").status_code, 400)

    def test_both_answer_404_while_the_flag_is_off(self):
        enable_feature(False)
        for action in ("test", "sync", "reconciliation"):
            method = "get" if action == "reconciliation" else "post"
            self.assertEqual(getattr(client_for(self.holder_user), method)(f"{self.url}{action}/").status_code, 404)

    def test_reconciliation_is_readable_by_the_owner_manager_and_viewer_but_not_a_stranger(self):
        for user, expected in ((self.holder_user, 200), (self.manager, 200), (self.viewer, 200),
                               (self.admin, 200), (self.other_user, 404), (self.stranger, 404)):
            self.assertEqual(client_for(user).get(f"{self.url}reconciliation/").status_code, expected, user.username)

    def test_reconciliation_without_official_data_says_insufficient(self):
        body = client_for(self.holder_user).get(f"{self.url}reconciliation/").json()
        self.assertEqual(body["state"], "insufficient")
        self.assertEqual(body["days"], [])


class QueueOnWriteTests(SyncTestCase):
    def test_creating_a_pull_source_queues_a_backfill(self):
        self.source.delete()
        with mock.patch("metering.tasks.sync_supplementary_source.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                response = client_for(self.holder_user).post(SOURCES_URL, {
                    "metering_point": str(self.point.pk), "provider": "solar_manager", "external_id": "ABC123",
                    "api_key": "key-1", "consent": True,
                }, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        delay.assert_called_once_with(response.json()["id"], backfill=True)
        self.assertEqual(SupplementarySource.objects.get(pk=response.json()["id"]).credential, "key-2")

    def test_creating_a_push_source_queues_nothing(self):
        self.source.delete()
        with mock.patch("metering.tasks.sync_supplementary_source.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                self.create_push_source()
        delay.assert_not_called()

    def test_a_new_key_queues_a_sync(self):
        self.source.mark_reconnect_required("enter the key")
        self.source.save()
        with mock.patch("metering.tasks.sync_supplementary_source.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                response = client_for(self.holder_user).patch(
                    f"{SOURCES_URL}{self.source.pk}/", {"api_key": "key-1"}, format="json"
                )
        self.assertEqual(response.status_code, 200, response.content)
        delay.assert_called_once_with(str(self.source.pk), backfill=False)

    def test_switching_a_source_back_on_queues_a_sync_but_a_label_change_does_not(self):
        url = f"{SOURCES_URL}{self.source.pk}/"
        client = client_for(self.holder_user)
        with mock.patch("metering.tasks.sync_supplementary_source.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                client.patch(url, {"label": "Renamed"}, format="json")
            delay.assert_not_called()
            with self.captureOnCommitCallbacks(execute=True):
                client.patch(url, {"enabled": False}, format="json")
            delay.assert_not_called()
            with self.captureOnCommitCallbacks(execute=True):
                client.patch(url, {"enabled": True}, format="json")
            delay.assert_called_once()

    def test_a_broker_outage_does_not_fail_the_request(self):
        self.source.delete()
        with mock.patch("metering.tasks.sync_supplementary_source.delay", side_effect=OSError("broker down")):
            with self.captureOnCommitCallbacks(execute=True):
                response = client_for(self.holder_user).post(SOURCES_URL, {
                    "metering_point": str(self.point.pk), "provider": "solar_manager", "external_id": "ABC123",
                    "api_key": "key-1", "consent": True,
                }, format="json")
        self.assertEqual(response.status_code, 201)
