"""``POST /api/v1/metering/live/ingest/`` (SPEC-2026-live-energy-data §5.1)."""

from datetime import timedelta
from decimal import Decimal

from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from audit.models import AuditEvent
from metering.live import store
from metering.live.testing import INGEST_URL, LiveTestCase, enable_live
from metering.live.permissions import LivePushThrottle
from metering.models import SupplementarySource


class IngestTestCase(LiveTestCase):
    def setUp(self):
        super().setUp()
        self.source = self.live_source(self.flat1, participant=self.p1)
        self.token = self.issue(self.source)

    @staticmethod
    def issue(source):
        token = source.issue_push_token()
        source.save()
        return token

    def push(self, payload, token=None):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token or self.token}")
        return client.post(INGEST_URL, payload, format="json")

    def stored(self, source=None):
        return store.latest_many([(source or self.source).pk]).get(str((source or self.source).pk))


class AcceptedSampleTests(IngestTestCase):
    def test_a_sample_is_accepted_and_becomes_the_latest_value(self):
        stamp = timezone.now().replace(microsecond=0) - timedelta(seconds=8)

        response = self.push({
            "timestamp": stamp.isoformat(), "meter_power_w": 1200.5, "production_w": 0, "consumption_w": 1200.5,
        })

        self.assertEqual(response.status_code, 202, response.content)
        self.assertEqual(response.json(), {"accepted": True})
        sample = self.stored()
        self.assertEqual(sample.meter_power_w, Decimal("1200.5"))
        self.assertEqual((sample.production_w, sample.consumption_w), (Decimal("0.0"), Decimal("1200.5")))
        self.assertEqual(sample.timestamp, stamp)

    def test_without_a_timestamp_the_receive_time_is_used(self):
        before = timezone.now()

        self.assertEqual(self.push({"meter_power_w": -300}).status_code, 202)

        sample = self.stored()
        self.assertGreaterEqual(sample.timestamp, before)
        self.assertEqual(sample.meter_power_w, Decimal("-300"))

    def test_the_sample_also_lands_in_its_bucket(self):
        self.push({"meter_power_w": 400})

        found = store.buckets_many([self.source.pk], timezone.now() - timedelta(minutes=10), timezone.now() + timedelta(minutes=1))
        self.assertEqual(sum(b.n for b in found[str(self.source.pk)].values()), 1)

    def test_powers_are_rounded_half_up_to_one_decimal(self):
        self.push({"meter_power_w": "1000.25", "production_w": "2.04"})

        sample = self.stored()
        self.assertEqual((sample.meter_power_w, sample.production_w), (Decimal("1000.3"), Decimal("2.0")))

    def test_a_connection_point_source_takes_samples_too(self):
        connection = self.live_source()
        token = self.issue(connection)

        self.assertEqual(self.push({"meter_power_w": -3000}, token=token).status_code, 202)
        self.assertEqual(self.stored(connection).meter_power_w, Decimal("-3000"))

    def test_a_zev_operated_point_nobody_holds_takes_samples(self):
        source = self.live_source(self.pv)
        token = self.issue(source)

        self.assertEqual(self.push({"meter_power_w": -8000}, token=token).status_code, 202)

    def test_a_sample_is_not_audited(self):
        before = AuditEvent.objects.count()

        self.push({"meter_power_w": 1})

        self.assertEqual(AuditEvent.objects.count(), before)

    def test_no_row_is_written_per_sample_beyond_the_last_seen_marker(self):
        self.push({"meter_power_w": 1})
        self.source.refresh_from_db()
        first_seen = self.source.live_last_seen_at
        self.assertIsNotNone(first_seen)

        cache.clear()  # lift the rate floor
        self.push({"meter_power_w": 2})

        self.source.refresh_from_db()
        self.assertEqual(self.source.live_last_seen_at, first_seen)

    @override_settings(LIVE_LAST_SEEN_RESOLUTION_S=30)
    def test_the_last_seen_marker_moves_on_after_its_resolution(self):
        old = timezone.now() - timedelta(seconds=45)
        SupplementarySource.objects.filter(pk=self.source.pk).update(live_last_seen_at=old)

        self.push({"meter_power_w": 1})

        self.source.refresh_from_db()
        self.assertGreater(self.source.live_last_seen_at, old + timedelta(seconds=40))


class ValidationTests(IngestTestCase):
    def assertRejected(self, payload, field):
        response = self.push(payload)
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn(field, response.json())
        self.assertIsNone(self.stored())
        return response.json()[field][0]

    def test_the_meter_power_is_required(self):
        self.assertRejected({"production_w": 5}, "meter_power_w")

    def test_a_naive_timestamp_is_refused(self):
        message = self.assertRejected({"meter_power_w": 1, "timestamp": "2026-10-30T11:02:10"}, "timestamp")
        self.assertIn("time zone", message)

    def test_a_future_timestamp_is_refused_beyond_ten_seconds(self):
        future = timezone.now() + timedelta(seconds=30)
        self.assertRejected({"meter_power_w": 1, "timestamp": future.isoformat()}, "timestamp")

    def test_a_timestamp_a_few_seconds_ahead_is_tolerated(self):
        near = timezone.now() + timedelta(seconds=4)
        self.assertEqual(self.push({"meter_power_w": 1, "timestamp": near.isoformat()}).status_code, 202)

    def test_a_sample_older_than_the_maximum_age_is_refused(self):
        stale = timezone.now() - timedelta(seconds=90)
        message = self.assertRejected({"meter_power_w": 1, "timestamp": stale.isoformat()}, "timestamp")
        self.assertEqual(message, "Sample is older than 60 seconds.")

    def test_non_finite_values_are_refused(self):
        for value in ("NaN", "Infinity", "-Infinity", "1e999"):
            with self.subTest(value=value):
                self.assertRejected({"meter_power_w": value}, "meter_power_w")

    def test_values_beyond_the_plausibility_cap_are_refused(self):
        self.assertRejected({"meter_power_w": 5_000_001}, "meter_power_w")
        self.assertRejected({"meter_power_w": -5_000_001}, "meter_power_w")

    def test_values_that_are_not_numbers_are_refused(self):
        for value in (True, None, [1], {"w": 1}, "abc"):
            with self.subTest(value=value):
                self.assertRejected({"meter_power_w": value}, "meter_power_w")

    def test_gross_values_cannot_be_negative(self):
        self.assertRejected({"meter_power_w": 1, "production_w": -1}, "production_w")
        self.assertRejected({"meter_power_w": 1, "consumption_w": -1}, "consumption_w")

    def test_a_rejected_request_does_not_use_up_the_rate_slot(self):
        self.push({"meter_power_w": "nope"})

        self.assertEqual(self.push({"meter_power_w": 1}).status_code, 202)


class RefusalTests(IngestTestCase):
    def test_a_bad_token_answers_401_with_one_message(self):
        unknown = self.push({"meter_power_w": 1}, token="ozs_abcdefgh_" + "x" * 32)
        garbage = self.push({"meter_power_w": 1}, token="not-a-token")

        self.assertEqual((unknown.status_code, garbage.status_code), (401, 401))
        self.assertEqual(unknown.json(), garbage.json())

    def test_a_missing_token_is_refused(self):
        self.assertEqual(APIClient().post(INGEST_URL, {"meter_power_w": 1}, format="json").status_code, 401)

    def test_a_disabled_source_is_refused(self):
        SupplementarySource.objects.filter(pk=self.source.pk).update(enabled=False)

        self.assertEqual(self.push({"meter_power_w": 1}).status_code, 403)
        self.assertIsNone(self.stored())

    def test_a_source_without_the_live_capability_is_refused(self):
        history_only = SupplementarySource.objects.create(
            zev=self.zev, metering_point=self.pv, held_by="zev", provider="push", provides_history=True,
            provides_live=False,
        )
        # History needs behind-the-meter generation, which a production point need not have; bypass clean().
        token = self.issue(history_only)

        response = self.push({"meter_power_w": 1}, token=token)

        self.assertEqual(response.status_code, 403)
        self.assertIn("live", response.json()["detail"])

    def test_a_participant_whose_tenancy_ended_is_refused(self):
        from zev.models import MeteringPointAssignment

        MeteringPointAssignment.objects.filter(metering_point=self.flat1).update(
            valid_to=timezone.localdate() - timedelta(days=1)
        )

        response = self.push({"meter_power_w": 1})

        self.assertEqual(response.status_code, 403)
        self.assertIsNone(self.stored())

    def test_a_zev_held_source_is_refused_once_a_participant_holds_the_point(self):
        source = self.live_source(self.flat3)  # held_by zev, while a participant holds the point
        token = self.issue(source)

        self.assertEqual(self.push({"meter_power_w": 1}, token=token).status_code, 403)

    def test_a_disabled_zev_accepts_nothing(self):
        from zev.models import Zev

        Zev.objects.filter(pk=self.zev.pk).update(disabled_at=timezone.now())

        self.assertEqual(self.push({"meter_power_w": 1}).status_code, 403)

    def test_a_user_session_cannot_post_samples(self):
        from metering.live.testing import client_for

        response = client_for(self.user1).post(INGEST_URL, {"meter_power_w": 1}, format="json")

        self.assertIn(response.status_code, (401, 403))

    def test_the_flag_off_answers_404_even_with_a_valid_token(self):
        enable_live(False)

        self.assertEqual(self.push({"meter_power_w": 1}).status_code, 404)

    def test_the_live_flag_alone_is_not_enough_without_the_energy_data_flag(self):
        from accounts.models import FeatureFlag

        FeatureFlag.objects.filter(name=FeatureFlag.SUPPLEMENTARY_ENERGY_DATA_ENABLED).update(enabled=False)

        self.assertEqual(self.push({"meter_power_w": 1}).status_code, 404)


class RateLimitTests(IngestTestCase):
    def test_a_second_push_within_the_floor_is_throttled_with_retry_after(self):
        self.assertEqual(self.push({"meter_power_w": 1}).status_code, 202)

        response = self.push({"meter_power_w": 2})

        self.assertEqual(response.status_code, 429)
        self.assertTrue(1 <= int(response["Retry-After"]) <= 5)
        self.assertEqual(self.stored().meter_power_w, Decimal("1"))

    def test_the_floor_is_per_source(self):
        other = self.live_source(self.flat2, participant=self.p2)
        self.push({"meter_power_w": 1})

        self.assertEqual(self.push({"meter_power_w": 1}, token=self.issue(other)).status_code, 202)

    @override_settings(LIVE_MIN_PUSH_INTERVAL_S=0)
    def test_the_hourly_throttle_applies_on_top(self):
        rates = dict(LivePushThrottle.THROTTLE_RATES)
        LivePushThrottle.THROTTLE_RATES = {**rates, "live_push": "2/hour"}
        try:
            statuses = [self.push({"meter_power_w": n}).status_code for n in range(3)]
        finally:
            LivePushThrottle.THROTTLE_RATES = rates

        self.assertEqual(statuses, [202, 202, 429])
