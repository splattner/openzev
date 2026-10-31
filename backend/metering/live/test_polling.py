"""``poll_live_sources`` and ``pull_live_source`` (SPEC-2026-live-energy-data §6.2): demand-driven Solar Manager pulls."""

from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone

from audit.models import AuditEvent
from metering import tasks
from metering.live import store
from metering.live.testing import LiveTestCase, client_for, curve_url, enable_live, snapshot_url
from metering.models import SupplementarySource, SupplementaryStatus
from metering.supplementary.providers import PROVIDERS, ProviderRateLimited
from metering.supplementary.testing import INTEGRATION_KEY, StubSolarManager
from zev.models import MeteringPointAssignment


class PullSourceCase(LiveTestCase):
    def setUp(self):
        super().setUp()
        override = override_settings(INTEGRATION_ENCRYPTION_KEYS=[INTEGRATION_KEY])
        override.enable()
        self.addCleanup(override.disable)

    def sm_source(self, point=None, participant=..., **extra) -> SupplementarySource:
        """A live-only Solar Manager source of ``participant`` (default: the holder of flat 1); ``None`` makes it ZEV-held."""
        fields = dict(
            zev=self.zev, metering_point=point or self.flat1, participant=self.p1 if participant is ... else participant,
            held_by="participant", provider="solar_manager", external_id="ABC123",
            provides_history=False, provides_live=True,
        )
        fields.update(extra)
        source = SupplementarySource(**fields)
        source.set_credential("key-1")
        source.save()
        return source

    def poll(self):
        with mock.patch.object(tasks.pull_live_source, "delay") as delay:
            result = tasks.poll_live_sources()
        return result, [call.args[0] for call in delay.call_args_list]


class PollLiveSourcesTests(PullSourceCase):
    def test_only_a_watched_zev_is_polled(self):
        source = self.sm_source()

        result, queued = self.poll()
        self.assertEqual((result, queued), ({"queued": 0}, []))

        store.mark_watched(self.zev.pk)
        result, queued = self.poll()
        self.assertEqual((result, queued), ({"queued": 1}, [str(source.pk)]))

    def test_another_zevs_watch_does_not_count(self):
        from testing import factories

        other = factories.ZevFactory(owner=self.manager)
        self.sm_source()
        store.mark_watched(other.pk)

        self.assertEqual(self.poll()[1], [])

    def test_only_enabled_live_solar_manager_sources(self):
        store.mark_watched(self.zev.pk)
        wanted = self.sm_source()
        self.sm_source(self.flat2, self.p2, enabled=False)
        self.sm_source(self.flat3, self.quiet, provides_live=False, provides_history=True)
        self.live_source(self.pv)  # a push source: it pushes, nobody pulls it

        self.assertEqual(self.poll()[1], [str(wanted.pk)])

    def test_a_source_that_needs_a_new_key_is_skipped(self):
        store.mark_watched(self.zev.pk)
        self.sm_source(status=SupplementaryStatus.RECONNECT_REQUIRED)

        self.assertEqual(self.poll()[1], [])

    def test_a_disabled_zev_is_skipped(self):
        store.mark_watched(self.zev.pk)
        self.sm_source()
        self.zev.disabled_at = timezone.now()
        self.zev.save(update_fields=["disabled_at"])

        self.assertEqual(self.poll()[1], [])

    def test_a_source_is_not_queued_twice_within_the_interval(self):
        store.mark_watched(self.zev.pk)
        source = self.sm_source()

        self.assertEqual(self.poll()[1], [str(source.pk)])
        self.assertEqual(self.poll()[1], [])

        cache.delete(store._pull_floor_key(source.pk))  # the interval has passed
        self.assertEqual(self.poll()[1], [str(source.pk)])

    def test_the_floor_is_a_little_shorter_than_the_interval_so_a_slightly_early_tick_still_pulls(self):
        with mock.patch.object(store.cache, "add", return_value=True) as add:
            store.claim_pull_slot("x")
        self.assertEqual(add.call_args.kwargs["timeout"], 24)

    def test_a_source_in_backoff_is_skipped_until_it_ends(self):
        store.mark_watched(self.zev.pk)
        source = self.sm_source()
        store.set_backoff(source.pk, 300)

        self.assertEqual(self.poll()[1], [])

        cache.delete(store._backoff_key(source.pk))
        self.assertEqual(self.poll()[1], [str(source.pk)])

    def test_nothing_is_polled_while_the_live_flag_is_off(self):
        store.mark_watched(self.zev.pk)
        self.sm_source()
        enable_live(False)

        result, queued = self.poll()

        self.assertEqual((result, queued), ({"queued": 0, "skipped": "feature_off"}, []))

    def test_a_broker_error_does_not_stop_the_other_sources(self):
        store.mark_watched(self.zev.pk)
        first, second = self.sm_source(), self.sm_source(self.flat2, self.p2)
        with mock.patch.object(tasks.pull_live_source, "delay", side_effect=[OSError("broker down"), None]) as delay:
            result = tasks.poll_live_sources()

        self.assertEqual(result, {"queued": 1})
        self.assertEqual(delay.call_count, 2)
        self.assertEqual({first.pk, second.pk}, set(SupplementarySource.objects.values_list("pk", flat=True)))

    def test_the_beat_entry_runs_at_the_pull_interval(self):
        from django.conf import settings

        entry = settings.CELERY_BEAT_SCHEDULE["poll-live-sources"]
        self.assertEqual(entry["task"], "metering.tasks.poll_live_sources")
        self.assertEqual(entry["schedule"], float(settings.LIVE_PULL_INTERVAL_S))


class WatchTests(PullSourceCase):
    def test_the_snapshot_and_the_curve_mark_the_zev_watched(self):
        for url in (snapshot_url(self.zev), curve_url(self.zev)):
            cache.clear()
            self.assertFalse(store.is_watched(self.zev.pk))

            response = client_for(self.manager).get(url)

            self.assertEqual(response.status_code, 200, url)
            self.assertTrue(store.is_watched(self.zev.pk), url)

    def test_a_refused_request_marks_nothing(self):
        self.assertEqual(client_for(self.outsider).get(snapshot_url(self.zev)).status_code, 404)
        self.assertFalse(store.is_watched(self.zev.pk))

    def test_the_watch_lasts_live_watch_ttl_s(self):
        with override_settings(LIVE_WATCH_TTL_S=77), mock.patch.object(store.cache, "set") as cache_set:
            store.mark_watched(self.zev.pk)
        self.assertEqual(cache_set.call_args.kwargs["timeout"], 77)

    def test_the_live_me_endpoint_does_not_keep_a_zev_watched(self):
        client_for(self.user1).get("/api/v1/metering/live/me/")
        self.assertFalse(store.is_watched(self.zev.pk))


class PullLiveSourceTests(PullSourceCase):
    """The task body, against a stand-in for the vendor."""

    def setUp(self):
        super().setUp()
        self.vendor = StubSolarManager().start()
        self.addCleanup(self.vendor.stop)
        override = override_settings(SOLAR_MANAGER_BASE_URL=self.vendor.url)
        override.enable()
        self.addCleanup(override.disable)

    def latest(self, source):
        return store.latest_many([source.pk]).get(str(source.pk))

    def test_a_pulled_sample_is_stored_and_the_source_is_marked_seen(self):
        source = self.sm_source()

        result = tasks.pull_live_source_impl(source.pk)

        self.assertEqual(result, {"source_id": str(source.pk), "stored": True})
        sample = self.latest(source)
        self.assertEqual((sample.meter_power_w, sample.production_w, sample.consumption_w),
                         (Decimal("300.0"), Decimal("900.0"), Decimal("1200.0")))
        source.refresh_from_db()
        self.assertIsNotNone(source.live_last_seen_at)
        self.assertEqual(source.status, SupplementaryStatus.OK)  # live-only: a reading is its "ok"

    def test_the_pulled_sample_reaches_the_zev_snapshot(self):
        from metering.live.snapshot import zev_snapshot

        self.vendor.stream_payload = {"iW": 0, "eW": 8000, "pW": 8000, "cW": 0}
        tasks.pull_live_source_impl(self.sm_source(self.pv, None, held_by="zev").pk)

        snapshot = zev_snapshot(self.zev, now=timezone.now(), viewer=self.manager)

        self.assertEqual(snapshot["production_w"], 8000)

    def test_a_poll_pulls_while_the_zev_is_watched(self):
        source = self.sm_source()
        store.mark_watched(self.zev.pk)

        with mock.patch.object(tasks.pull_live_source, "delay", side_effect=lambda i: tasks.pull_live_source_impl(i)):
            self.assertEqual(tasks.poll_live_sources(), {"queued": 1})

        self.assertIsNotNone(self.latest(source))

    def test_a_history_error_text_is_not_overwritten_by_a_live_pull(self):
        source = self.sm_source(provides_history=True, status=SupplementaryStatus.ERROR, last_error="history sync failed")
        self.vendor.stream_response = lambda n: (503, {}, b"down")

        tasks.pull_live_source_impl(source.pk)

        source.refresh_from_db()
        self.assertEqual((source.status, source.last_error), (SupplementaryStatus.ERROR, "history sync failed"))

    def test_a_successful_live_pull_leaves_a_history_sources_status_alone(self):
        source = self.sm_source(provides_history=True, status=SupplementaryStatus.ERROR, last_error="history sync failed")

        tasks.pull_live_source_impl(source.pk)

        source.refresh_from_db()
        self.assertEqual((source.status, source.last_error), (SupplementaryStatus.ERROR, "history sync failed"))
        self.assertIsNotNone(source.live_last_seen_at)

    def test_an_auth_failure_makes_the_whole_source_reconnect_required_and_is_audited_once(self):
        source = self.sm_source(provides_history=True)
        self.vendor.current_token = "someone-else"

        result = tasks.pull_live_source_impl(source.pk)
        again = tasks.pull_live_source_impl(source.pk)

        self.assertEqual(result["error"], "reconnect_required")
        self.assertEqual(again["skipped"], "reconnect_required")
        source.refresh_from_db()
        self.assertEqual(source.status, SupplementaryStatus.RECONNECT_REQUIRED)
        self.assertEqual(AuditEvent.objects.filter(action_type="supplementary_source.sync").count(), 1)
        self.assertIsNone(self.latest(source))

    def test_a_rate_limit_backs_the_source_off_for_the_retry_after_capped_at_15_minutes(self):
        source = self.sm_source()
        for retry_after, expected in ((120, 120), (5000, 900), (0, 30), (10, 30)):
            cache.clear()
            error = ProviderRateLimited("slow down", retry_after=retry_after)
            with mock.patch.dict(PROVIDERS, {"solar_manager": mock.Mock(fetch_live=mock.Mock(side_effect=error))}), \
                    mock.patch.object(store, "set_backoff", wraps=store.set_backoff) as backoff:
                result = tasks.pull_live_source_impl(source.pk)

            self.assertEqual(result["error"], "rate_limited", retry_after)
            backoff.assert_called_once_with(source.pk, expected)
            self.assertTrue(store.in_backoff(source.pk))
        source.refresh_from_db()
        self.assertEqual(source.status, SupplementaryStatus.PENDING)

    def test_a_429_from_the_vendor_backs_the_source_off(self):
        source = self.sm_source()
        self.vendor.stream_response = lambda n: (429, {"Retry-After": "5000"}, b"{}")

        self.assertEqual(tasks.pull_live_source_impl(source.pk)["backoff_s"], 900)
        self.assertTrue(store.in_backoff(source.pk))

    def test_a_transient_error_is_a_missed_sample_only(self):
        source = self.sm_source()
        self.vendor.stream_response = lambda n: (503, {}, b"down")

        with self.assertLogs("metering.tasks", level="WARNING"):
            result = tasks.pull_live_source_impl(source.pk)

        self.assertEqual(result["error"], "unavailable")
        source.refresh_from_db()
        self.assertEqual((source.status, source.last_error, source.live_last_seen_at), ("pending", "", None))
        self.assertFalse(AuditEvent.objects.filter(action_type="supplementary_source.sync").exists())

    def test_nothing_is_pulled_for_a_source_that_cannot_be_pulled(self):
        cases = {
            "disabled": self.sm_source(enabled=False),
            "reconnect_required": self.sm_source(self.flat2, self.p2, status=SupplementaryStatus.RECONNECT_REQUIRED),
            "disabled_live": self.sm_source(self.flat3, self.quiet, provides_live=False, provides_history=True),
        }
        zev_off = self.sm_source(self.pv, None, held_by="zev")
        for source in cases.values():
            tasks.pull_live_source_impl(source.pk)
        self.zev.disabled_at = timezone.now()
        self.zev.save(update_fields=["disabled_at"])
        self.assertEqual(tasks.pull_live_source_impl(zev_off.pk)["skipped"], "zev_disabled")
        self.assertEqual(self.vendor.stream_requests, [])
        self.assertEqual(self.vendor.refresh_requests, [])

    def test_a_holder_who_lost_the_meter_gets_no_pull(self):
        source = self.sm_source()
        MeteringPointAssignment.objects.filter(participant=self.p1).update(valid_to=timezone.localdate() - timedelta(days=1))

        self.assertEqual(tasks.pull_live_source_impl(source.pk)["skipped"], "holder_gone")
        self.assertEqual(self.vendor.stream_requests, [])

    def test_a_deleted_source_and_a_flag_that_went_off_are_skipped(self):
        source = self.sm_source()
        self.assertEqual(tasks.pull_live_source_impl("00000000-0000-0000-0000-000000000000")["skipped"], "missing")
        enable_live(False)
        self.assertEqual(tasks.pull_live_source_impl(source.pk)["skipped"], "feature_off")

    def test_an_unusable_payload_is_a_missed_sample(self):
        source = self.sm_source()
        self.vendor.stream_payload = {"eW": 5}

        with self.assertLogs("metering.tasks", level="WARNING"):
            self.assertEqual(tasks.pull_live_source_impl(source.pk)["error"], "unavailable")
        self.assertIsNone(self.latest(source))

    def test_the_task_does_not_retry(self):
        self.assertEqual(tasks.pull_live_source.max_retries, 0)
