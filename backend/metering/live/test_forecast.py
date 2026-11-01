"""Production forecast (SPEC-2026-live-energy-data §4.2, §5.4, §6.3): hours, providers, refresh, API."""

from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from unittest import mock
from zoneinfo import ZoneInfo

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from metering import tasks
from metering.live import forecast as forecast_service
from metering.live import store
from metering.live.forecast_hours import ForecastHour, floor_hour, sum_hours, to_hours
from metering.live.testing import VALID_FROM, LiveTestCase, client_for, enable_live
from metering.models import ProductionForecastPoint, SupplementarySource, SupplementaryStatus
from metering.supplementary import forecast_solar
from metering.supplementary.forecast_solar import ForecastSolarProvider
from metering.supplementary.providers import (
    ForecastDeferred, ProviderAuthError, ProviderError, ProviderRateLimited,
)
from metering.supplementary.solar_manager import SolarManagerProvider, map_forecast
from metering.supplementary.testing import INTEGRATION_KEY, StubForecastSolar, StubSolarManager
from testing import factories
from zev.models import PvPlane

ZURICH = ZoneInfo("Europe/Zurich")
D = Decimal


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=dt_timezone.utc)


def hour(h: int, power, low=None, high=None, day=(2026, 6, 1)) -> ForecastHour:
    return ForecastHour(
        start=utc(*day, h), power_w=D(str(power)),
        min_w=None if low is None else D(str(low)), max_w=None if high is None else D(str(high)),
    )


class HourBucketTests(TestCase):
    def test_samples_are_averaged_into_utc_hours(self):
        hours = to_hours(
            [(utc(2026, 6, 1, 10, 0), D(100), None, None), (utc(2026, 6, 1, 10, 30), D(300), None, None),
             (utc(2026, 6, 1, 11, 0), D(50), None, None)],
            marks="start",
        )
        self.assertEqual([(h.start.hour, h.power_w) for h in hours], [(10, D("200.0")), (11, D("50.0"))])

    def test_a_key_that_marks_the_end_belongs_to_the_hour_before(self):
        hours = to_hours([(utc(2026, 6, 1, 11, 0), D(400), None, None)], marks="end")
        self.assertEqual([(h.start.hour, h.power_w) for h in hours], [(10, D("400.0"))])

    def test_negative_power_reads_as_zero(self):
        self.assertEqual(to_hours([(utc(2026, 6, 1, 10), D(-5), D(-9), D(-1))], marks="start")[0].power_w, D("0.0"))

    def test_a_band_is_claimed_only_when_every_value_has_one(self):
        both = to_hours([(utc(2026, 6, 1, 10), D(1), D(0), D(2)), (utc(2026, 6, 1, 10, 30), D(1), D(0), D(4))], marks="start")
        self.assertEqual((both[0].min_w, both[0].max_w), (D("0.0"), D("3.0")))
        partial = to_hours([(utc(2026, 6, 1, 10), D(1), D(0), D(2)), (utc(2026, 6, 1, 10, 30), D(1), None, None)], marks="start")
        self.assertEqual((partial[0].min_w, partial[0].max_w), (None, None))

    def test_planes_add_up_and_the_band_needs_every_plane(self):
        total = sum_hours([[hour(10, 100, 80, 120)], [hour(10, 50, 40, 60), hour(11, 20)]])
        self.assertEqual([(h.start.hour, h.power_w) for h in total], [(10, D(150)), (11, D(20))])
        self.assertEqual((total[0].min_w, total[0].max_w), (D(120), D(180)))
        self.assertIsNone(total[1].min_w)
        self.assertEqual(sum_hours([]), [])


class PeakWindowTests(TestCase):
    def test_longest_run_at_half_of_the_days_top(self):
        hours = [hour(h, p) for h, p in ((6, 100), (7, 400), (8, 800), (9, 900), (10, 850), (11, 300), (12, 500), (13, 520))]
        (window,) = forecast_service.peak_windows(hours)
        self.assertEqual((window["from"], window["to"], window["peak_w"]), (utc(2026, 6, 1, 8), utc(2026, 6, 1, 11), 900.0))
        self.assertEqual(window["date"], "2026-06-01")

    def test_a_tie_goes_to_the_earliest_run(self):
        hours = [hour(h, p) for h, p in ((8, 500), (9, 500), (10, 0), (11, 500), (12, 500))]
        (window,) = forecast_service.peak_windows(hours)
        self.assertEqual(window["from"], utc(2026, 6, 1, 8))

    def test_one_window_per_swiss_day_and_none_for_a_dark_day(self):
        hours = [hour(10, 500), hour(10, 0, day=(2026, 6, 2)), hour(10, 700, day=(2026, 6, 3))]
        self.assertEqual([w["date"] for w in forecast_service.peak_windows(hours)], ["2026-06-01", "2026-06-03"])


def local_key(moment: datetime) -> str:
    return moment.astimezone(ZURICH).strftime("%Y-%m-%d %H:%M:%S")


class MapWattsTests(TestCase):
    def payload(self, watts, zone="Europe/Zurich"):
        return {"result": {"watts": watts}, "message": {"info": {"timezone": zone}}}

    def test_local_keys_become_utc_hours_ending_at_the_key(self):
        hours = forecast_solar.map_watts(self.payload({"2026-06-01 13:00:00": 3000, "2026-06-01 14:00:00": 4000}))
        # 13:00 CEST is 11:00 UTC and closes the hour 10:00-11:00 UTC.
        self.assertEqual([(h.start, h.power_w) for h in hours], [(utc(2026, 6, 1, 10), D("3000.0")), (utc(2026, 6, 1, 11), D("4000.0"))])

    def test_a_response_without_a_timezone_or_result_is_unreadable(self):
        for bad in ({"result": {"watts": {}}}, {"result": None}, [], self.payload({}, zone="Nowhere/Land")):
            with self.assertRaises(ProviderError):
                forecast_solar.map_watts(bad)

    def test_unreadable_values_are_skipped(self):
        hours = forecast_solar.map_watts(self.payload({"2026-06-01 13:00:00": "x", "bad": 1, "2026-06-01 14:00:00": 10**9, "2026-06-01 15:00:00": 5}))
        self.assertEqual([h.power_w for h in hours], [D("5.0")])


class SolarManagerForecastMapTests(TestCase):
    def test_power_and_band_in_hours(self):
        payload = {"data": [
            {"t": "2026-06-01T10:00:00.000Z", "pW": 1000, "pWmin": 800, "pWmax": 1200},
            {"t": "2026-06-01T10:30:00.000Z", "pW": 3000, "pWmin": 2800, "pWmax": 3200},
            {"t": "2026-06-01T11:00:00.000Z", "pW": 500},
        ]}
        first, second = map_forecast(payload)
        self.assertEqual((first.start, first.power_w, first.min_w, first.max_w), (utc(2026, 6, 1, 10), D("2000.0"), D("1800.0"), D("2200.0")))
        self.assertEqual((second.power_w, second.min_w), (D("500.0"), None))

    def test_rows_without_a_time_or_power_are_skipped_and_nothing_usable_is_an_error(self):
        self.assertEqual(len(map_forecast({"data": [{"pW": 1}, {"t": "2026-06-01T10:00:00Z"}, {"t": "2026-06-01T10:00:00Z", "pW": 7}]})), 1)
        for bad in ({"data": []}, {"data": "x"}, [], {"data": [{"t": "2026-06-01T10:00:00", "pW": 1}]}):
            with self.assertRaises(ProviderError):
                map_forecast(bad)


class ForecastCase(LiveTestCase):
    """The base ZEV, with the PV plant given two roof planes and the building coordinates."""

    def setUp(self):
        super().setUp()
        cache.clear()
        building = self.pv.building
        building.latitude, building.longitude = D("47.37691"), D("8.54169")
        building.save()
        self.south = PvPlane.objects.create(metering_point=self.pv, label="South", peak_power_kwp=D("6.00"), tilt_deg=30, azimuth_deg=0)

    def forecast_source(self, point=None, **extra) -> SupplementarySource:
        fields = dict(
            zev=self.zev, metering_point=point or self.pv, held_by="zev", provider="forecast_solar",
            provides_history=False, provides_live=False, provides_forecast=True,
        )
        fields.update(extra)
        return SupplementarySource.objects.create(**fields)

    def points(self, source, *rows):
        """Store hours relative to the current UTC hour: ``(offset_hours, power)``."""
        current = floor_hour(self.now)
        for offset, power in rows:
            ProductionForecastPoint.objects.create(
                source=source, metering_point=source.metering_point, timestamp=current + timedelta(hours=offset),
                power_w=D(str(power)), fetched_at=self.now,
            )


class ForecastSolarProviderTests(ForecastCase):
    def setUp(self):
        super().setUp()
        self.vendor = StubForecastSolar().start()
        self.addCleanup(self.vendor.stop)
        override = override_settings(FORECAST_SOLAR_BASE_URL=self.vendor.url, FORECAST_SOLAR_API_KEY="")
        override.enable()
        self.addCleanup(override.disable)
        end = floor_hour(timezone.now()) + timedelta(hours=1)
        self.vendor.watts = {local_key(end): 3000, local_key(end + timedelta(hours=1)): 4000}
        self.end = end

    def test_one_call_per_plane_with_rounded_coordinates_and_the_summed_result(self):
        PvPlane.objects.create(metering_point=self.pv, label="West", peak_power_kwp=D("4.00"), tilt_deg=20, azimuth_deg=90)
        source = self.forecast_source()

        hours = ForecastSolarProvider().fetch_forecast(source)

        self.assertEqual(sorted(self.vendor.requests), ["/estimate/watts/47.38/8.54/20/90/4.00", "/estimate/watts/47.38/8.54/30/0/6.00"])
        self.assertEqual([h.power_w for h in hours], [D("6000.0"), D("8000.0")])

    def test_a_key_goes_into_the_path(self):
        source = self.forecast_source()
        with override_settings(FORECAST_SOLAR_API_KEY="secret"):
            ForecastSolarProvider().fetch_forecast(source)
        self.assertEqual(self.vendor.requests, ["/secret/estimate/watts/47.38/8.54/30/0/6.00"])

    def test_missing_planes_or_coordinates_are_an_error_without_a_call(self):
        source = self.forecast_source()
        building = self.pv.building
        building.latitude = None
        building.save()
        with self.assertRaises(ProviderError):
            ForecastSolarProvider().fetch_forecast(SupplementarySource.objects.get(pk=source.pk))
        self.assertEqual(self.vendor.requests, [])

    def test_calls_beyond_the_hourly_budget_are_deferred_not_made(self):
        source = self.forecast_source()
        with override_settings(FORECAST_SOLAR_MAX_CALLS_PER_HOUR=1):
            ForecastSolarProvider().fetch_forecast(source)
            with self.assertRaises(ForecastDeferred):
                ForecastSolarProvider().fetch_forecast(source)
        self.assertEqual(len(self.vendor.requests), 1)

    def test_more_planes_than_the_budget_can_ever_allow_is_an_error(self):
        source = self.forecast_source()
        with override_settings(FORECAST_SOLAR_MAX_CALLS_PER_HOUR=0):
            with self.assertRaises(ProviderError):
                ForecastSolarProvider().fetch_forecast(source)

    def test_a_429_backs_every_source_off(self):
        source = self.forecast_source()
        self.vendor.status = 429
        self.vendor.headers = {"Retry-After": "900"}
        with self.assertRaises(ProviderRateLimited) as caught:
            ForecastSolarProvider().fetch_forecast(source)
        self.assertEqual(caught.exception.retry_after, 900)
        self.assertFalse(store.take_forecast_solar_calls(1))

    def test_a_server_error_is_a_provider_error_without_vendor_text(self):
        source = self.forecast_source()
        self.vendor.status = 500
        with self.assertRaises(ProviderError) as caught:
            ForecastSolarProvider().fetch_forecast(source)
        self.assertIn("could not be reached", str(caught.exception))

    def test_the_budget_is_a_rolling_hour(self):
        with override_settings(FORECAST_SOLAR_MAX_CALLS_PER_HOUR=2):
            self.assertTrue(store.take_forecast_solar_calls(2, self.now))
            self.assertFalse(store.take_forecast_solar_calls(1, self.now + timedelta(minutes=59)))
            self.assertTrue(store.take_forecast_solar_calls(1, self.now + timedelta(minutes=61)))
            self.assertEqual(store.forecast_solar_calls_last_hour(self.now + timedelta(minutes=61)), 1)


class RefreshTests(ForecastCase):
    def setUp(self):
        super().setUp()
        self.source = self.forecast_source()

    def refresh(self, hours=None, **kwargs):
        hours = [ForecastHour(floor_hour(self.now) + timedelta(hours=1), D(1000))] if hours is None else hours
        with mock.patch.object(forecast_service, "fetch_hours", return_value=hours):
            return tasks.refresh_forecast_source_impl(self.source.pk, **kwargs)

    def test_future_points_are_replaced_and_old_ones_dropped(self):
        self.points(self.source, (-30, 10), (-3, 20), (1, 99), (2, 98))
        result = self.refresh(force=True)
        self.assertEqual(result["stored"], 1)
        stored = dict(ProductionForecastPoint.objects.values_list("timestamp", "power_w"))
        current = floor_hour(self.now)
        self.assertEqual(stored, {current - timedelta(hours=3): D("20.0"), current + timedelta(hours=1): D("1000.0")})

    def test_hours_beyond_the_horizon_are_not_kept(self):
        far = floor_hour(self.now) + timedelta(hours=100)
        self.refresh([ForecastHour(far, D(5)), ForecastHour(floor_hour(self.now), D(7))])
        self.assertEqual(ProductionForecastPoint.objects.count(), 1)

    def test_a_forecast_only_source_records_ok_and_an_error(self):
        self.refresh()
        self.source.refresh_from_db()
        self.assertEqual(self.source.status, SupplementaryStatus.OK)
        self.assertIsNotNone(self.source.last_success_at)

        with mock.patch.object(forecast_service, "fetch_hours", side_effect=ProviderError("It broke.")):
            result = tasks.refresh_forecast_source_impl(self.source.pk, force=True)
        self.source.refresh_from_db()
        self.assertEqual((result["error"], self.source.status, self.source.last_error), ("provider", SupplementaryStatus.ERROR, "It broke."))

    def test_a_source_with_other_capabilities_keeps_its_own_status(self):
        sm = SupplementarySource(
            zev=self.zev, metering_point=self.flat1, participant=self.p1, provider="solar_manager", external_id="ABC123",
            provides_history=False, provides_live=True, provides_forecast=True, status=SupplementaryStatus.OK,
        )
        sm.set_credential("k")
        sm.save()
        with mock.patch.object(forecast_service, "fetch_hours", side_effect=ProviderError("It broke.")):
            tasks.refresh_forecast_source_impl(sm.pk)
        sm.refresh_from_db()
        self.assertEqual((sm.status, sm.last_error), (SupplementaryStatus.OK, ""))

    def test_an_auth_failure_needs_a_new_key_and_is_audited_once(self):
        with mock.patch.object(forecast_service, "fetch_hours", side_effect=ProviderAuthError("Enter the key again.")):
            result = tasks.refresh_forecast_source_impl(self.source.pk)
        self.source.refresh_from_db()
        self.assertEqual((result["error"], self.source.status), ("reconnect_required", SupplementaryStatus.RECONNECT_REQUIRED))

    def test_a_forecast_solar_source_is_not_refreshed_again_within_the_minimum_interval(self):
        self.refresh()
        self.assertEqual(self.refresh()["skipped"], "recent")
        self.assertEqual(self.refresh(force=True)["stored"], 1)

    def test_a_deferred_refresh_changes_nothing(self):
        with mock.patch.object(forecast_service, "fetch_hours", side_effect=ForecastDeferred()):
            result = tasks.refresh_forecast_source_impl(self.source.pk)
        self.source.refresh_from_db()
        self.assertEqual((result["skipped"], self.source.status), ("budget", SupplementaryStatus.PENDING))

    def test_nothing_happens_while_the_live_flag_is_off(self):
        enable_live(False)
        self.assertEqual(self.refresh()["skipped"], "feature_off")
        self.assertEqual(ProductionForecastPoint.objects.count(), 0)

    def test_a_disabled_source_is_left_alone(self):
        SupplementarySource.objects.filter(pk=self.source.pk).update(enabled=False)
        self.assertEqual(self.refresh()["skipped"], "missing")

    def test_the_beat_queues_enabled_sources_oldest_first(self):
        other = self.forecast_source(self._second_plant())
        self.points(self.source, (1, 100))
        with mock.patch.object(tasks.refresh_forecast_source, "delay") as delay:
            result = tasks.refresh_production_forecasts()
        self.assertEqual(result, {"queued": 2})
        self.assertEqual([call.args[0] for call in delay.call_args_list], [str(other.pk), str(self.source.pk)])

    def _second_plant(self):
        return factories.MeteringPointFactory(zev=self.zev, meter_type="production", building=self.pv.building)

    def test_the_beat_skips_sources_that_need_a_key_or_a_flag(self):
        SupplementarySource.objects.filter(pk=self.source.pk).update(status=SupplementaryStatus.RECONNECT_REQUIRED)
        with mock.patch.object(tasks.refresh_forecast_source, "delay") as delay:
            self.assertEqual(tasks.refresh_production_forecasts(), {"queued": 0})
            enable_live(False)
            self.assertEqual(tasks.refresh_production_forecasts()["skipped"], "feature_off")
        delay.assert_not_called()


class SolarManagerForecastFetchTests(ForecastCase):
    def setUp(self):
        super().setUp()
        self.vendor = StubSolarManager().start()
        self.addCleanup(self.vendor.stop)
        override = override_settings(SOLAR_MANAGER_BASE_URL=self.vendor.url, INTEGRATION_ENCRYPTION_KEYS=[INTEGRATION_KEY])
        override.enable()
        self.addCleanup(override.disable)
        self.pv_owner = factories.ParticipantFactory(zev=self.zev, valid_from=VALID_FROM)
        self.sm = SupplementarySource(
            zev=self.zev, metering_point=self.pv, participant=self.pv_owner, provider="solar_manager", external_id="ABC123",
            provides_history=False, provides_live=False, provides_forecast=True,
        )
        self.sm.set_credential("key-1")
        self.sm.save()

    def test_the_forecast_is_read_with_the_stored_key_and_the_bearer_token_is_reused(self):
        current = floor_hour(timezone.now()) + timedelta(hours=1)
        self.vendor.forecast_payload = {"data": [{"t": current.strftime("%Y-%m-%dT%H:%M:%S.000Z"), "pW": 2500, "pWmin": 2000, "pWmax": 3000}]}
        provider = SolarManagerProvider()

        hours = provider.fetch_forecast(self.sm)
        provider.fetch_forecast(self.sm)

        self.assertEqual((hours[0].start, hours[0].power_w, hours[0].min_w, hours[0].max_w), (current, D("2500.0"), D("2000.0"), D("3000.0")))
        self.assertEqual(self.vendor.exchanges, 1)
        self.assertEqual(len(self.vendor.forecast_requests), 2)
        self.assertTrue(self.vendor.forecast_requests[0]["path"].endswith("/v3/users/ABC123/data/forecast"))

    def test_fetch_hours_picks_the_provider_of_the_source(self):
        self.vendor.forecast_payload = {"data": [{"t": "2026-06-01T10:00:00.000Z", "pW": 1}]}
        self.assertEqual(len(forecast_service.fetch_hours(self.sm)), 1)


class ForecastApiTests(ForecastCase):
    def url(self, zev=None):
        return f"/api/v1/metering/live/zevs/{(zev or self.zev).pk}/forecast/"

    def setUp(self):
        super().setUp()
        self.source = self.forecast_source()
        self.points(self.source, (1, 1000), (2, 3000), (3, 3200), (4, 800))

    def get(self, user, **kw):
        return client_for(user).get(self.url(**kw))

    def test_a_manager_sees_the_sum_the_bands_the_windows_and_every_plant(self):
        body = self.get(self.manager).json()
        self.assertEqual((body["plants"], body["plants_with_forecast"], body["complete"]), (1, 1, True))
        self.assertEqual([h["power_w"] for h in body["hours"]], [1000.0, 3000.0, 3200.0, 800.0])
        self.assertEqual(body["horizon_h"], 72)
        self.assertIsNotNone(body["fetched_at"])
        self.assertEqual(body["per_plant"][0]["meter_id"], self.pv.meter_id)
        self.assertEqual(len(body["per_plant"][0]["hours"]), 4)

    def test_a_participant_sees_totals_but_no_plants(self):
        body = self.get(self.user1).json()
        self.assertEqual(len(body["hours"]), 4)
        self.assertNotIn("per_plant", body)

    def test_a_viewer_sees_the_plants(self):
        self.assertIn("per_plant", self.get(self.viewer).json())

    def test_an_outsider_and_the_flag_off_answer_404(self):
        self.assertEqual(self.get(self.outsider).status_code, 404)
        enable_live(False)
        self.assertEqual(self.get(self.manager).status_code, 404)

    def test_a_plant_without_a_forecast_makes_it_incomplete(self):
        factories.MeteringPointFactory(zev=self.zev, meter_type="bidirectional")
        body = self.get(self.manager).json()
        self.assertEqual((body["plants"], body["plants_with_forecast"], body["complete"]), (2, 1, False))

    def test_a_disabled_source_is_not_part_of_the_forecast(self):
        SupplementarySource.objects.filter(pk=self.source.pk).update(enabled=False)
        body = self.get(self.manager).json()
        self.assertEqual((body["hours"], body["complete"]), ([], False))

    def test_the_sum_of_two_plants_carries_a_band_only_when_both_have_one(self):
        second = self._plant()
        self.points(second, (1, 500))
        ProductionForecastPoint.objects.filter(source=self.source).update(power_min_w=D(1), power_max_w=D(2))
        body = self.get(self.manager).json()
        self.assertEqual(body["hours"][0]["power_w"], 1500.0)
        self.assertEqual((body["hours"][0]["min_w"], body["hours"][0]["max_w"]), (None, None))

    def _plant(self):
        point = factories.MeteringPointFactory(zev=self.zev, meter_type="production", building=self.pv.building)
        return self.forecast_source(point)

    def test_me_names_the_next_peak_window(self):
        entry = client_for(self.user1).get("/api/v1/metering/live/me/").json()["zevs"][0]
        peak = entry["forecast_next_peak"]
        self.assertEqual(peak["peak_w"], 3200.0)
        self.assertTrue(peak["from"] < peak["to"])

    def test_me_has_no_peak_without_a_forecast(self):
        ProductionForecastPoint.objects.all().delete()
        entry = client_for(self.user1).get("/api/v1/metering/live/me/").json()["zevs"][0]
        self.assertIsNone(entry["forecast_next_peak"])
