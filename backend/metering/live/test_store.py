"""``metering.live.store``: latest sample, bucket means, rate floor (SPEC-2026-live-energy-data §4.4)."""

from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from metering.live import store

EPOCH = datetime(2026, 10, 30, 10, 0, tzinfo=dt_timezone.utc)


def make(ts, power, *, source="s1", production=None, consumption=None):
    return store.LiveSample(
        source_id=source, timestamp=ts, received_at=ts, meter_power_w=Decimal(power),
        production_w=None if production is None else Decimal(production),
        consumption_w=None if consumption is None else Decimal(consumption),
    )


class LiveStoreTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def test_the_latest_sample_round_trips_with_exact_decimals(self):
        store.put_sample(make(EPOCH, "-3120.5", production="5400", consumption="2279.5"))

        got = store.latest_many(["s1"])["s1"]

        self.assertEqual(got.meter_power_w, Decimal("-3120.5"))
        self.assertEqual((got.production_w, got.consumption_w), (Decimal("5400"), Decimal("2279.5")))
        self.assertEqual(got.timestamp, EPOCH)

    def test_the_latest_sample_expires_after_the_maximum_age(self):
        store.put_sample(make(EPOCH, "100"))
        with mock.patch.object(cache, "set", wraps=cache.set) as spy:
            store.put_sample(make(EPOCH + timedelta(seconds=1), "200"))
        latest_call = next(call for call in spy.call_args_list if "latest" in call.args[0])
        self.assertEqual(latest_call.kwargs["timeout"], 60)

    def test_an_older_sample_never_replaces_a_newer_latest(self):
        store.put_sample(make(EPOCH + timedelta(seconds=30), "300"))
        store.put_sample(make(EPOCH, "100"))

        self.assertEqual(store.latest_many(["s1"])["s1"].meter_power_w, Decimal("300"))

    def test_a_source_without_a_sample_is_absent(self):
        self.assertEqual(store.latest_many(["nobody"]), {})

    def test_freshness_is_judged_on_the_sample_timestamp(self):
        sample = make(EPOCH, "1")
        self.assertTrue(sample.is_fresh(EPOCH + timedelta(seconds=60)))
        self.assertFalse(sample.is_fresh(EPOCH + timedelta(seconds=61)))
        self.assertEqual(sample.age_s(EPOCH - timedelta(seconds=3)), 0.0)  # a clock a little ahead is not negative


class BucketTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def test_a_bucket_is_the_mean_of_its_samples(self):
        store.put_sample(make(EPOCH + timedelta(seconds=10), "100", production="10"))
        store.put_sample(make(EPOCH + timedelta(seconds=20), "300", production="30"))
        store.put_sample(make(EPOCH + timedelta(seconds=30), "-200"))

        bucket = store.buckets_many(["s1"], EPOCH, EPOCH + timedelta(minutes=5))["s1"][int(EPOCH.timestamp())]

        self.assertEqual(bucket.n, 3)
        self.assertEqual(bucket.meter_power_w, Decimal("200") / 3)
        # Gross values average over the samples that carried them.
        self.assertEqual(bucket.production_w, Decimal("20"))
        self.assertIsNone(bucket.consumption_w)

    def test_an_empty_bucket_is_a_gap(self):
        store.put_sample(make(EPOCH, "100"))

        found = store.buckets_many(["s1"], EPOCH, EPOCH + timedelta(minutes=15))["s1"]

        self.assertEqual(list(found), [int(EPOCH.timestamp())])

    def test_samples_land_in_the_bucket_of_their_timestamp(self):
        store.put_sample(make(EPOCH + timedelta(minutes=4, seconds=59), "1"))
        store.put_sample(make(EPOCH + timedelta(minutes=5), "2"))

        found = store.buckets_many(["s1"], EPOCH, EPOCH + timedelta(minutes=10))["s1"]

        self.assertEqual({start: b.meter_power_w for start, b in found.items()},
                         {int(EPOCH.timestamp()): Decimal("1"), int(EPOCH.timestamp()) + 300: Decimal("2")})

    def test_buckets_are_kept_for_the_retention_period(self):
        with mock.patch.object(cache, "set", wraps=cache.set) as spy:
            store.put_sample(make(EPOCH, "1"))
        bucket_call = next(call for call in spy.call_args_list if ":b:" in call.args[0])
        self.assertEqual(bucket_call.kwargs["timeout"], 48 * 3600)

    @override_settings(LIVE_CURVE_BUCKET_S=60)
    def test_the_bucket_width_is_a_setting(self):
        store.put_sample(make(EPOCH + timedelta(seconds=70), "5"))

        found = store.buckets_many(["s1"], EPOCH, EPOCH + timedelta(minutes=5))["s1"]

        self.assertEqual(list(found), [int(EPOCH.timestamp()) + 60])


class PushSlotTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def test_the_first_push_takes_the_slot_and_a_second_waits(self):
        self.assertEqual(store.claim_push_slot("s1", EPOCH), 0)
        self.assertEqual(store.claim_push_slot("s1", EPOCH + timedelta(seconds=2)), 3)

    def test_slots_are_per_source(self):
        store.claim_push_slot("s1", EPOCH)
        self.assertEqual(store.claim_push_slot("s2", EPOCH), 0)

    @override_settings(LIVE_MIN_PUSH_INTERVAL_S=0)
    def test_a_zero_window_disables_the_floor(self):
        store.claim_push_slot("s1", EPOCH)
        self.assertEqual(store.claim_push_slot("s1", EPOCH), 0)
