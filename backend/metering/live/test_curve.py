"""``GET /live/zevs/{id}/curve/`` (SPEC-2026-live-energy-data §5.3)."""

from datetime import date, datetime, timedelta, timezone as dt_timezone
from decimal import Decimal

from django.utils import timezone

from metering.live import curve, store
from metering.live.testing import LiveTestCase, client_for, curve_url

NOW = datetime(2026, 10, 30, 12, 0, tzinfo=dt_timezone.utc)  # 13:00 in Zurich, CET
DAY = date(2026, 10, 30)


class CurveCase(LiveTestCase):
    def setUp(self):
        super().setUp()
        self.now = NOW
        self.sources = {
            "pv": self.live_source(self.pv),
            "flat1": self.live_source(self.flat1, participant=self.p1),
            "flat2": self.live_source(self.flat2, participant=self.p2),
            "flat3": self.live_source(self.flat3, participant=self.quiet),
        }

    def put(self, name, minutes_ago, power, seconds=0):
        moment = NOW - timedelta(minutes=minutes_ago) + timedelta(seconds=seconds)
        store.put_sample(
            store.LiveSample(str(self.sources[name].pk), moment, moment, Decimal(str(power)))
        )

    def rows(self, user=None, day=DAY, now=NOW):
        payload = curve.zev_curve(self.zev, day, now=now, viewer=user or self.manager)
        return payload, {row["start"]: row for row in payload["buckets"]}

    @staticmethod
    def start(minutes_ago):
        epoch = int((NOW - timedelta(minutes=minutes_ago)).timestamp()) // 300 * 300
        return datetime.fromtimestamp(epoch, tz=dt_timezone.utc).isoformat().replace("+00:00", "Z")


class CurveTests(CurveCase):
    def test_the_tier_rule_is_applied_per_bucket(self):
        for name, power in (("pv", -8000), ("flat1", 1000), ("flat2", 2000), ("flat3", 500)):
            self.put(name, 30, power)  # exact
        self.put("pv", 20, -6000)  # production only
        self.put("flat1", 10, 900)  # no producer: none

        payload, rows = self.rows()

        self.assertEqual(payload["bucket_s"], 300)
        exact, production, none = rows[self.start(30)], rows[self.start(20)], rows[self.start(10)]
        self.assertEqual(
            exact,
            {"start": self.start(30), "tier": "exact", "production_w": 8000.0, "consumption_w": 3500.0,
             "surplus_w": 4500.0, "points": exact["points"]},
        )
        self.assertEqual((production["tier"], production["production_w"]), ("production", 6000.0))
        self.assertNotIn("consumption_w", production)
        self.assertEqual(none, {"start": self.start(10), "tier": "none"})

    def test_a_bucket_is_the_mean_of_its_samples(self):
        self.put("pv", 30, -8000, seconds=0)
        self.put("pv", 30, -6000, seconds=20)
        for name in ("flat1", "flat2", "flat3"):
            self.put(name, 30, 0)

        _, rows = self.rows()

        self.assertEqual(rows[self.start(30)]["production_w"], 7000.0)

    def test_the_curve_runs_from_the_start_of_the_civil_day_up_to_now(self):
        payload, _ = self.rows()

        starts = [row["start"] for row in payload["buckets"]]
        self.assertEqual(starts[0], "2026-10-29T23:00:00Z")  # midnight in Zurich
        self.assertEqual(starts[-1], self.start(5))  # `now` sits on a boundary: the bucket starting then is empty
        self.assertEqual(len(starts), len(set(starts)))
        self.assertTrue(all(row["tier"] == "none" for row in payload["buckets"]))

    def test_a_past_day_is_complete_and_has_no_future_buckets(self):
        payload, _ = self.rows(day=date(2026, 10, 29), now=NOW)

        self.assertEqual(len(payload["buckets"]), 24 * 12)
        self.assertEqual(payload["buckets"][-1]["start"], "2026-10-29T22:55:00Z")

    def test_the_day_after_the_clocks_go_back_has_25_hours(self):
        payload, _ = self.rows(day=date(2026, 10, 25), now=NOW)

        self.assertEqual(len(payload["buckets"]), 25 * 12)
        self.assertEqual(payload["buckets"][0]["start"], "2026-10-24T22:00:00Z")  # CEST midnight

    def test_the_day_the_clocks_go_forward_has_23_hours(self):
        now = datetime(2026, 4, 2, 12, 0, tzinfo=dt_timezone.utc)

        payload, _ = self.rows(day=date(2026, 3, 29), now=now)

        self.assertEqual(len(payload["buckets"]), 23 * 12)

    def test_the_connection_point_makes_a_bucket_exact(self):
        connection = self.live_source()
        self.put("pv", 20, -8000)
        store.put_sample(
            store.LiveSample(str(connection.pk), NOW - timedelta(minutes=20), NOW, Decimal("-3000"))
        )

        _, rows = self.rows()

        self.assertEqual(rows[self.start(20)]["tier"], "exact")
        self.assertEqual(rows[self.start(20)]["surplus_w"], 3000.0)

    def test_participants_get_their_own_consumption_and_local_part(self):
        for name, power in (("pv", -1000), ("flat1", 1500), ("flat2", 2500), ("flat3", 1000)):
            self.put(name, 30, power)
        self.put("flat1", 20, 1500)  # the others are missing here: production tier

        payload, rows = curve.zev_curve(self.zev, DAY, now=NOW, viewer=self.user1), None
        rows = {row["start"]: row for row in payload["buckets"]}

        exact = rows[self.start(30)]
        self.assertEqual((exact["own_consumption_w"], exact["own_local_w"]), (1500.0, 300.0))
        self.assertNotIn("points", exact)
        self.assertNotIn("own_consumption_w", rows[self.start(40)])  # tier none: only start and tier

    def test_no_own_figures_without_a_live_source(self):
        for name, power in (("pv", -1000), ("flat1", 1500), ("flat2", 2500), ("flat3", 1000)):
            self.put(name, 30, power)

        payload = curve.zev_curve(self.zev, DAY, now=NOW, viewer=self.outsider)

        row = next(row for row in payload["buckets"] if row["start"] == self.start(30))
        self.assertNotIn("own_consumption_w", row)

    def test_managers_get_the_value_per_point_in_every_bucket(self):
        self.put("pv", 30, -8000)
        self.put("flat2", 30, 2222.2)

        _, rows = self.rows()

        points = {p["metering_point_id"]: p["meter_power_w"] for p in rows[self.start(30)]["points"]}
        self.assertEqual(points, {str(self.pv.pk): -8000.0, str(self.flat2.pk): 2222.2})

    def test_a_participant_never_gets_another_points_value(self):
        self.put("pv", 30, -8000)
        self.put("flat2", 30, 2222.2)

        payload = curve.zev_curve(self.zev, DAY, now=NOW, viewer=self.user1)

        self.assertNotIn("2222.2", str(payload))


class CurveEndpointTests(LiveTestCase):
    def get(self, user, **params):
        return client_for(user).get(curve_url(self.zev), params)

    def test_the_default_day_is_today(self):
        response = self.get(self.user1)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["date"], timezone.localdate().isoformat())

    def test_a_day_older_than_the_retention_is_refused(self):
        old = timezone.localdate() - timedelta(days=4)

        response = self.get(self.user1, date=old.isoformat())

        self.assertEqual(response.status_code, 400)
        self.assertIn("48 hours", response.json()["date"][0])

    def test_yesterday_is_still_available(self):
        yesterday = timezone.localdate() - timedelta(days=1)

        self.assertEqual(self.get(self.user1, date=yesterday.isoformat()).status_code, 200)

    def test_a_future_day_and_a_malformed_date_are_refused(self):
        tomorrow = timezone.localdate() + timedelta(days=1)

        self.assertEqual(self.get(self.user1, date=tomorrow.isoformat()).status_code, 400)
        self.assertEqual(self.get(self.user1, date="30.10.2026").status_code, 400)

    def test_visibility_follows_the_snapshot(self):
        self.assertEqual(self.get(self.outsider).status_code, 404)
        self.assertEqual(self.get(self.manager).status_code, 200)

    def test_the_flag_off_answers_404(self):
        from metering.live.testing import enable_live

        enable_live(False)

        self.assertEqual(self.get(self.manager).status_code, 404)
