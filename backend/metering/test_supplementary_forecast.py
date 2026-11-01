"""Forecast as a source capability (SPEC-2026-live-energy-data §4.1, §5): who may connect it, and what it needs."""

from decimal import Decimal
from unittest import mock

from django.core.cache import cache
from django.test import override_settings

from metering import tasks
from metering.models import ProductionForecastPoint, SupplementarySource
from metering.supplementary.providers import ProviderError
from metering.supplementary.testing import INTEGRATION_KEY, SOURCES_URL, client_for
from metering.test_supplementary_capabilities import CapabilityTestCase, ELIGIBLE_URL, ZEV_ELIGIBLE_URL, enable_live
from testing import factories
from zev.models import MeteringPointType, PvPlane

FORECAST = {"provider": "forecast_solar"}


class ForecastSourceTestCase(CapabilityTestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        # An unheld producing plant of the ZEV, with its roof plane and the building's coordinates.
        self.plant = factories.MeteringPointFactory(zev=self.zev, meter_type=MeteringPointType.PRODUCTION)
        building = self.plant.building
        building.latitude, building.longitude = Decimal("47.37691"), Decimal("8.54169")
        building.save()
        PvPlane.objects.create(metering_point=self.plant, peak_power_kwp=Decimal("8"), tilt_deg=25, azimuth_deg=-10)

    def post(self, user, point, **extra):
        return client_for(user).post(SOURCES_URL, {"metering_point": str(point.pk), **extra}, format="json")

    def make_planes(self, point):
        building = point.building
        building.latitude, building.longitude = Decimal("47.37691"), Decimal("8.54169")
        building.save()
        PvPlane.objects.create(metering_point=point, peak_power_kwp=Decimal("5"), tilt_deg=30, azimuth_deg=0)


class CreateForecastSolarTests(ForecastSourceTestCase):
    def test_a_manager_connects_the_zev_operated_plant_without_consent_or_a_token(self):
        with mock.patch.object(tasks.refresh_forecast_source, "delay") as delay, self.captureOnCommitCallbacks(execute=True):
            response = self.post(self.manager, self.plant, held_by="zev", **FORECAST)
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual((body["provides_forecast"], body["provides_history"], body["provides_live"]), (True, False, False))
        self.assertNotIn("push_token", body)
        source = SupplementarySource.objects.get(pk=body["id"])
        self.assertEqual((source.held_by, source.participant_id, source.push_token_prefix), ("zev", None, None))
        delay.assert_called_once_with(str(source.pk), force=False)

    def test_the_holder_connects_a_plant_they_hold(self):
        self.make_planes(self.point)
        response = self.post(self.holder_user, self.point, **FORECAST)
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["held_by"], "participant")

    def test_the_plants_roof_planes_and_the_buildings_coordinates_come_first(self):
        PvPlane.objects.filter(metering_point=self.plant).delete()
        response = self.post(self.manager, self.plant, held_by="zev", **FORECAST)
        self.assertEqual(response.status_code, 400)
        self.assertIn("provides_forecast", response.json())

        self.make_planes(self.plant)
        building = self.plant.building
        building.latitude = None
        building.save()
        self.assertEqual(self.post(self.manager, self.plant, held_by="zev", **FORECAST).status_code, 400)

    def test_only_a_producing_meter_has_a_forecast(self):
        response = self.post(self.manager, self.unheld, held_by="zev", **FORECAST)
        self.assertEqual(response.status_code, 400)

    def test_a_metering_point_has_one_forecast(self):
        self.assertEqual(self.post(self.manager, self.plant, held_by="zev", **FORECAST).status_code, 201)
        response = self.post(self.manager, self.plant, held_by="zev", **FORECAST)
        self.assertEqual(response.status_code, 400)
        self.assertIn("provides_forecast", response.json())

    def test_forecast_solar_provides_a_forecast_and_nothing_else(self):
        for extra in ({"provides_live": True}, {"provides_history": True}, {"provides_forecast": False}):
            response = self.post(self.manager, self.plant, held_by="zev", **FORECAST, **extra)
            self.assertEqual(response.status_code, 400, extra)
            self.assertIn("provider", response.json(), extra)

    def test_it_takes_neither_a_key_nor_an_id(self):
        for extra in ({"api_key": "x"}, {"external_id": "ABC123"}):
            self.assertEqual(self.post(self.manager, self.plant, held_by="zev", **FORECAST, **extra).status_code, 400)

    def test_a_manager_cannot_connect_a_plant_somebody_holds_and_a_stranger_cannot_connect_at_all(self):
        self.make_planes(self.point)
        self.assertEqual(self.post(self.manager, self.point, held_by="zev", **FORECAST).status_code, 403)
        self.assertEqual(self.post(self.stranger, self.plant, held_by="zev", **FORECAST).status_code, 400)

    def test_it_needs_the_live_flag(self):
        enable_live(False)
        response = self.post(self.manager, self.plant, held_by="zev", **FORECAST)
        self.assertEqual(response.status_code, 400)
        self.assertIn("provides_forecast", response.json())

    def test_a_push_source_never_provides_a_forecast(self):
        response = self.post(self.manager, self.plant, held_by="zev", provider="push", consent=True, provides_forecast=True,
                             provides_live=True, provides_history=False)
        self.assertEqual(response.status_code, 400)
        self.assertIn("provides_forecast", response.json())


class SourceActionTests(ForecastSourceTestCase):
    def connect(self):
        return self.post(self.manager, self.plant, held_by="zev", **FORECAST).json()["id"]

    def test_sync_queues_a_forecast_refresh_once_per_cooldown(self):
        source_id = self.connect()
        url = f"{SOURCES_URL}{source_id}/sync/"
        with mock.patch.object(tasks.refresh_forecast_source, "delay") as delay:
            first = client_for(self.manager).post(url)
            second = client_for(self.manager).post(url)
        self.assertEqual((first.status_code, second.status_code), (202, 429))
        delay.assert_called_once_with(source_id, force=True)

    def test_test_fetches_the_forecast_now(self):
        source_id = self.connect()
        url = f"{SOURCES_URL}{source_id}/test/"
        with mock.patch("metering.live.forecast.fetch_hours", return_value=[]):
            self.assertEqual(client_for(self.manager).post(url).json(), {"ok": True})
        with mock.patch("metering.live.forecast.fetch_hours", side_effect=ProviderError("Nope.")):
            response = client_for(self.manager).post(url)
        self.assertEqual(response.status_code, 400)
        self.assertIn("Nope.", str(response.json()))

    def test_switching_the_forecast_off_forgets_its_points(self):
        # A Solar Manager history source gains and loses the forecast on the same connection.
        sm = SupplementarySource(
            zev=self.zev, metering_point=self.point, participant=self.holder, provider="solar_manager", external_id="ABC123",
            provides_history=True, provides_forecast=False,
        )
        with override_settings(INTEGRATION_ENCRYPTION_KEYS=[INTEGRATION_KEY]):
            sm.set_credential("key-1")
        sm.save()
        url = f"{SOURCES_URL}{sm.pk}/"
        without = client_for(self.holder_user).patch(url, {"provides_forecast": True}, format="json")
        self.assertEqual(without.status_code, 400)
        self.assertIn("consent", without.json())

        with mock.patch.object(tasks.refresh_forecast_source, "delay") as delay, self.captureOnCommitCallbacks(execute=True):
            response = client_for(self.holder_user).patch(url, {"provides_forecast": True, "consent": True}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        delay.assert_called_once_with(str(sm.pk), force=True)

        ProductionForecastPoint.objects.create(
            source=sm, metering_point=self.point, timestamp=sm.created_at, power_w=Decimal(1), fetched_at=sm.created_at
        )
        response = client_for(self.holder_user).patch(url, {"provides_forecast": False}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(ProductionForecastPoint.objects.count(), 0)


class EligibleForecastTests(ForecastSourceTestCase):
    def test_a_held_producer_offers_a_forecast_and_a_consumer_does_not(self):
        rows = {r["metering_point"]: r for r in client_for(self.holder_user).get(ELIGIBLE_URL).json()}
        self.assertIn("forecast", rows[str(self.point.pk)]["eligible_capabilities"])
        self.assertNotIn("forecast", rows[str(self.plain.pk)]["eligible_capabilities"])

    def test_the_managers_list_offers_it_for_an_unheld_producer(self):
        body = client_for(self.manager).get(ZEV_ELIGIBLE_URL, {"zev_id": str(self.zev.pk)}).json()
        rows = {r["metering_point"]: r for r in body["metering_points"]}
        self.assertEqual(rows[str(self.plant.pk)]["eligible_capabilities"], ["live", "forecast"])
        self.assertEqual(rows[str(self.unheld.pk)]["eligible_capabilities"], ["live"])


class DisconnectForecastTests(ForecastSourceTestCase):
    def test_a_disconnected_source_drops_out_of_the_forecast(self):
        source_id = self.post(self.manager, self.plant, held_by="zev", **FORECAST).json()["id"]
        source = SupplementarySource.objects.get(pk=source_id)
        ProductionForecastPoint.objects.create(
            source=source, metering_point=self.plant, timestamp=source.created_at.replace(minute=0, second=0, microsecond=0),
            power_w=Decimal(100), fetched_at=source.created_at,
        )
        url = f"/api/v1/metering/live/zevs/{self.zev.pk}/forecast/"
        before = client_for(self.manager).get(url).json()
        self.assertEqual(before["plants_with_forecast"], 1)

        response = client_for(self.manager).post(f"{SOURCES_URL}{source_id}/disconnect/")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertFalse(response.json()["enabled"])
        self.assertEqual(client_for(self.manager).get(url).json()["plants_with_forecast"], 0)
