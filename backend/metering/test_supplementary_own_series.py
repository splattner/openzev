"""``GET /supplementary/zevs/{id}/own-series/`` (SPEC-2026-live-energy-data §5.4)."""

from datetime import date, datetime, timedelta
from decimal import Decimal

from allocation.validity import period_start_dt
from metering.models import SupplementaryReading, SupplementarySource
from metering.supplementary import own_series
from metering.supplementary.testing import SupplementaryApiTestCase, client_for, enable_feature
from testing import factories
from zev.models import AllocationMode, MeteringPointType

QUARTER = timedelta(minutes=15)
ROW = dict(consumption_kwh=Decimal("0.4"), production_kwh=Decimal("1.2"), import_kwh=Decimal("0.1"), export_kwh=Decimal("0.9"))


class OwnSeriesCase(SupplementaryApiTestCase):
    def setUp(self):
        super().setUp()
        self.source = SupplementarySource.objects.create(
            metering_point=self.point, participant=self.holder, provider="solar_manager", external_id="ABC123"
        )

    def url(self, zev=None):
        return f"/api/v1/metering/supplementary/zevs/{(zev or self.zev).pk}/own-series/"

    def seed(self, day, *, source=None, point=None, intervals=None, row=None):
        source = source or self.source
        point = point or self.point
        start = period_start_dt(day)
        slots = intervals if intervals is not None else int((period_start_dt(day + timedelta(days=1)) - start) / QUARTER)
        for i in range(slots):
            SupplementaryReading.objects.create(
                source=source, metering_point=point, timestamp=start + QUARTER * i, **(row or ROW)
            )
        source.covers_from = min(filter(None, [source.covers_from, start]))
        source.synced_through = max(filter(None, [source.synced_through, start + QUARTER * slots]))
        source.save()

    def get(self, user, **params):
        params = {"date_from": "2026-07-01", "date_to": "2026-07-01", **params}
        return client_for(user).get(self.url(), params)


class OwnSeriesPermissionTests(OwnSeriesCase):
    def setUp(self):
        super().setUp()
        self.seed(date(2026, 7, 1))

    def test_a_participant_reads_their_own_series(self):
        response = self.get(self.holder_user, bucket="hour")

        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body["participant_id"], str(self.holder.pk))
        self.assertEqual(len(body["gross"]["timeline"]), 24)
        self.assertAlmostEqual(body["gross"]["timeline"][0]["consumption_kwh"], 1.6, places=3)

    def test_a_participant_cannot_read_another_participant(self):
        response = self.get(self.other_user, participant_id=str(self.holder.pk))

        self.assertEqual(response.status_code, 403)
        self.assertNotIn("gross", response.json())

    def test_a_participant_may_name_themselves(self):
        self.assertEqual(self.get(self.holder_user, participant_id=str(self.holder.pk)).status_code, 200)

    def test_a_participant_without_a_source_gets_no_figures(self):
        body = self.get(self.other_user).json()

        self.assertIsNone(body["gross"])
        self.assertIsNone(body["history_through"])

    def test_a_manager_and_a_viewer_read_a_selected_participant(self):
        for user in (self.manager, self.viewer, self.admin):
            response = self.get(user, participant_id=str(self.holder.pk))
            self.assertEqual(response.status_code, 200, user)
            self.assertAlmostEqual(response.json()["gross"]["consumption_kwh"], 38.4, places=3)

    def test_a_manager_without_a_selection_gets_their_own_not_everybody_s(self):
        body = self.get(self.manager).json()

        self.assertIsNone(body["participant_id"])
        self.assertIsNone(body["gross"])

    def test_a_participant_of_another_zev_and_a_stranger_see_nothing(self):
        other_zev = factories.ZevFactory(owner=self.manager)
        stranger_participant = factories.ParticipantFactory(zev=other_zev, user=self.stranger, valid_from=date(2025, 1, 1))
        self.assertEqual(self.get(self.stranger).status_code, 404)
        # A participant of another ZEV cannot name a participant of this one either.
        response = client_for(self.stranger).get(
            self.url(other_zev),
            {"date_from": "2026-07-01", "date_to": "2026-07-01", "participant_id": str(self.holder.pk)},
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(stranger_participant.zev_id, other_zev.pk)

    def test_an_unknown_participant_is_404_and_a_malformed_id_400(self):
        self.assertEqual(self.get(self.manager, participant_id="00000000-0000-0000-0000-000000000000").status_code, 404)
        self.assertEqual(self.get(self.manager, participant_id="nope").status_code, 400)

    def test_anonymous_callers_are_refused(self):
        self.assertIn(client_for(None).get(self.url(), {"date_from": "2026-07-01", "date_to": "2026-07-01"}).status_code, (401, 403))

    def test_the_supplementary_flag_off_answers_404_whatever_the_live_flag(self):
        enable_feature(False)

        self.assertEqual(self.get(self.holder_user).status_code, 404)

    def test_the_live_flag_is_not_needed(self):
        from accounts.models import FeatureFlag

        FeatureFlag.objects.update_or_create(name=FeatureFlag.LIVE_ENERGY_DATA_ENABLED, defaults={"enabled": False})

        self.assertEqual(self.get(self.holder_user).status_code, 200)

    def test_community_mode_points_are_excluded(self):
        self.assignment.allocation_mode = AllocationMode.COMMUNITY
        self.assignment.save()

        self.assertIsNone(self.get(self.holder_user).json()["gross"])

    def test_a_former_participant_has_no_view(self):
        self.holder.valid_to = date(2026, 1, 1)
        self.holder.save()

        self.assertEqual(self.get(self.holder_user).status_code, 404)


class OwnSeriesShapeTests(OwnSeriesCase):
    def test_buckets_and_the_totals_match_the_dashboards_definition(self):
        self.seed(date(2026, 7, 1))
        self.seed(date(2026, 7, 2))

        daily = self.get(self.holder_user, date_to="2026-07-02", bucket="day").json()["gross"]
        quarter = self.get(self.holder_user, bucket="quarter").json()["gross"]

        self.assertEqual(len(daily["timeline"]), 2)
        self.assertAlmostEqual(daily["consumption_kwh"], 76.8, places=3)
        self.assertEqual(daily["self_sufficiency_rate"], 75.0)
        self.assertEqual(len(quarter["timeline"]), 96)
        self.assertEqual(quarter["timeline"][0]["bucket"], "2026-06-30T22:00:00+00:00")  # CEST midnight, UTC label
        self.assertEqual(
            {key for key in quarter["timeline"][0]},
            {"bucket", "production_kwh", "consumption_kwh", "import_kwh", "export_kwh", "self_consumption_kwh"},
        )

    def test_history_through_is_the_end_of_the_last_ingested_interval(self):
        self.seed(date(2026, 7, 1), intervals=40)

        body = self.get(self.holder_user, bucket="quarter").json()

        expected = period_start_dt(date(2026, 7, 1)) + QUARTER * 40
        self.assertEqual(datetime.fromisoformat(body["history_through"]), expected)

    def test_history_through_is_the_earliest_of_several_sources(self):
        second_point = factories.MeteringPointFactory(
            zev=self.zev, meter_type=MeteringPointType.BIDIRECTIONAL, has_behind_meter_generation=True
        )
        factories.MeteringPointAssignmentFactory(metering_point=second_point, participant=self.holder, valid_from=date(2025, 1, 1))
        second = SupplementarySource.objects.create(
            metering_point=second_point, participant=self.holder, provider="solar_manager", external_id="DEF456"
        )
        self.seed(date(2026, 7, 1), intervals=40)
        self.seed(date(2026, 7, 1), source=second, point=second_point, intervals=20)

        through = own_series.history_through([self.holder.pk])

        self.assertEqual(through, period_start_dt(date(2026, 7, 1)) + QUARTER * 20)

    def test_the_day_the_clocks_go_back_has_100_quarters_and_the_one_going_forward_92(self):
        self.seed(date(2026, 10, 25))
        self.seed(date(2026, 3, 29))

        back = self.get(self.holder_user, date_from="2026-10-25", date_to="2026-10-25", bucket="quarter").json()["gross"]
        forward = self.get(self.holder_user, date_from="2026-03-29", date_to="2026-03-29", bucket="quarter").json()["gross"]

        self.assertEqual((len(back["timeline"]), back["coverage_pct"]), (100, 100.0))
        self.assertEqual((len(forward["timeline"]), forward["coverage_pct"]), (92, 100.0))

    def test_a_gappy_day_withholds_the_rates_like_the_dashboard(self):
        self.seed(date(2026, 7, 1), intervals=96)
        for reading in SupplementaryReading.objects.all()[:60]:
            reading.delete()

        gross = self.get(self.holder_user).json()["gross"]

        self.assertEqual(gross["rates_withheld_reason"], "low_coverage")
        self.assertIsNone(gross["self_sufficiency_rate"])
        self.assertLess(gross["coverage_pct"], 50)


class OwnSeriesRangeTests(OwnSeriesCase):
    def test_range_limits_per_bucket(self):
        self.seed(date(2026, 7, 1))
        ok = [("quarter", "2026-07-03"), ("hour", "2026-07-31"), ("day", "2027-08-04")]
        too_long = [("quarter", "2026-07-04"), ("hour", "2026-08-01"), ("day", "2027-08-05")]
        for bucket, end in ok:
            self.assertEqual(self.get(self.holder_user, date_to=end, bucket=bucket).status_code, 200, (bucket, end))
        for bucket, end in too_long:
            response = self.get(self.holder_user, date_to=end, bucket=bucket)
            self.assertEqual(response.status_code, 400, (bucket, end))
            self.assertIn("date_to", response.json())

    def test_malformed_dates_missing_dates_and_a_reversed_range_are_refused(self):
        self.assertEqual(self.get(self.holder_user, date_from="01.07.2026").status_code, 400)
        self.assertEqual(client_for(self.holder_user).get(self.url(), {"date_from": "2026-07-01"}).status_code, 400)
        self.assertEqual(self.get(self.holder_user, date_from="2026-07-02", date_to="2026-07-01").status_code, 400)

    def test_an_unknown_bucket_is_refused(self):
        self.assertEqual(self.get(self.holder_user, bucket="minute").status_code, 400)

    def test_default_bucket_is_day(self):
        self.seed(date(2026, 7, 1))

        self.assertEqual(self.get(self.holder_user).json()["bucket"], "day")


class OwnHistoryOfDayTests(OwnSeriesCase):
    def test_power_is_energy_over_the_interval_in_watts(self):
        self.seed(date(2026, 7, 1), intervals=4)

        rows = own_series.own_history_of_day([self.holder.pk], date(2026, 7, 1))

        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0], {"start": "2026-06-30T22:00:00+00:00", "consumption_w": 1600.0, "production_w": 4800.0})

    def test_nothing_is_invented_for_a_missing_interval(self):
        self.seed(date(2026, 7, 1), intervals=4)
        SupplementaryReading.objects.filter(timestamp=period_start_dt(date(2026, 7, 1)) + QUARTER).delete()

        rows = own_series.own_history_of_day([self.holder.pk], date(2026, 7, 1))

        self.assertEqual(len(rows), 3)

    def test_a_day_without_data_or_without_a_source_is_empty(self):
        self.assertEqual(own_series.own_history_of_day([self.holder.pk], date(2026, 7, 1)), [])
        self.assertEqual(own_series.own_history_of_day([self.other.pk], date(2026, 7, 1)), [])
