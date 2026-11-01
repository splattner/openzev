"""PV planes and building coordinates (SPEC-2026-live-energy-data §4.3)."""

from datetime import date
from decimal import Decimal
from unittest import mock

from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import UserRole
from audit.models import AuditEvent
from testing import factories
from testing.helpers import authenticate, make_user

from .geocoding import footprint_centroid
from .models import Building, MeteringPointType, PvPlane, ZevAccessGrant, ZevAccessRole

BUILDINGS = "/api/v1/zev/buildings/"


def planes_url(point, plane=None):
    base = f"/api/v1/zev/metering-points/{point.pk}/pv-planes/"
    return base + (f"{plane.pk}/" if plane else "")


def client_for(user):
    client = APIClient()
    authenticate(client, user)
    return client


class PvPlaneApiTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = make_user("pv_admin", UserRole.ADMIN)
        self.manager = make_user("pv_manager", UserRole.USER)
        self.viewer = make_user("pv_viewer", UserRole.USER)
        self.tenant_user = make_user("pv_tenant", UserRole.USER)
        self.stranger = make_user("pv_stranger", UserRole.USER)
        self.zev = factories.ZevFactory(owner=self.manager)
        ZevAccessGrant.objects.create(zev=self.zev, user=self.viewer, role=ZevAccessRole.VIEWER)
        self.tenant = factories.ParticipantFactory(zev=self.zev, user=self.tenant_user, valid_from=date(2025, 1, 1))
        self.pv = factories.MeteringPointFactory(zev=self.zev, meter_type=MeteringPointType.PRODUCTION)
        self.flat = factories.MeteringPointFactory(zev=self.zev, meter_type=MeteringPointType.CONSUMPTION)
        factories.MeteringPointAssignmentFactory(metering_point=self.pv, participant=self.tenant, valid_from=date(2025, 1, 1))

    payload = {"label": "South roof", "peak_power_kwp": "8.50", "tilt_deg": 30, "azimuth_deg": 0}

    def test_a_manager_adds_changes_and_removes_a_plane_and_each_is_audited(self):
        client = client_for(self.manager)
        created = client.post(planes_url(self.pv), self.payload, format="json")
        self.assertEqual(created.status_code, 201, created.content)
        body = created.json()
        self.assertEqual((body["metering_point"], body["peak_power_kwp"], body["azimuth_deg"]), (str(self.pv.pk), "8.50", 0))

        plane = PvPlane.objects.get(pk=body["id"])
        changed = client.patch(planes_url(self.pv, plane), {"azimuth_deg": -90}, format="json")
        self.assertEqual(changed.status_code, 200, changed.content)
        self.assertEqual(client.delete(planes_url(self.pv, plane)).status_code, 204)

        actions = list(AuditEvent.objects.filter(target_type="zev.PvPlane").order_by("created_at").values_list("action_type", flat=True))
        self.assertEqual(actions, ["pv_plane.create", "pv_plane.update", "pv_plane.delete"])

    def test_everyone_who_reads_the_metering_point_reads_the_planes(self):
        PvPlane.objects.create(metering_point=self.pv, peak_power_kwp=Decimal(5), tilt_deg=20, azimuth_deg=0)
        for user in (self.manager, self.viewer, self.tenant_user, self.admin):
            response = client_for(user).get(planes_url(self.pv))
            self.assertEqual(response.status_code, 200, user.username)
            rows = response.json()
            rows = rows["results"] if isinstance(rows, dict) else rows
            self.assertEqual(len(rows), 1, user.username)
        rows = client_for(self.stranger).get(planes_url(self.pv)).json()
        self.assertEqual(rows["results"] if isinstance(rows, dict) else rows, [])

    def test_viewers_participants_and_strangers_do_not_write(self):
        for user in (self.viewer, self.tenant_user, self.stranger):
            self.assertIn(client_for(user).post(planes_url(self.pv), self.payload, format="json").status_code, (400, 403, 404), user.username)
        self.assertEqual(PvPlane.objects.count(), 0)

    def test_the_url_decides_the_metering_point(self):
        other = factories.MeteringPointFactory(zev=self.zev, meter_type=MeteringPointType.PRODUCTION)
        body = client_for(self.manager).post(planes_url(self.pv), {**self.payload, "metering_point": str(other.pk)}, format="json").json()
        self.assertEqual(body["metering_point"], str(self.pv.pk))

    def test_only_a_producing_meter_has_planes(self):
        response = client_for(self.manager).post(planes_url(self.flat), self.payload, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("metering_point", response.json())

    def test_a_plane_cannot_be_moved(self):
        plane = PvPlane.objects.create(metering_point=self.pv, peak_power_kwp=Decimal(5), tilt_deg=20, azimuth_deg=0)
        other = factories.MeteringPointFactory(zev=self.zev, meter_type=MeteringPointType.PRODUCTION)
        response = client_for(self.manager).patch(planes_url(self.pv, plane), {"metering_point": str(other.pk)}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_at_most_four_planes_per_metering_point(self):
        client = client_for(self.manager)
        for _ in range(4):
            self.assertEqual(client.post(planes_url(self.pv), self.payload, format="json").status_code, 201)
        response = client.post(planes_url(self.pv), self.payload, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("metering_point", response.json())

    def test_values_are_bounded(self):
        client = client_for(self.manager)
        for bad in ({"tilt_deg": 91}, {"azimuth_deg": 181}, {"peak_power_kwp": "0"}, {"peak_power_kwp": "10001"}, {"tilt_deg": -1}):
            self.assertEqual(client.post(planes_url(self.pv), {**self.payload, **bad}, format="json").status_code, 400, bad)

    def test_a_manager_of_another_zev_cannot_write(self):
        other_manager = make_user("pv_other", UserRole.USER)
        factories.ZevFactory(owner=other_manager)
        response = client_for(other_manager).post(planes_url(self.pv), self.payload, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(PvPlane.objects.count(), 0)


class BuildingCoordinatesTests(TestCase):
    def setUp(self):
        cache.clear()
        self.manager = make_user("co_manager", UserRole.USER)
        self.zev = factories.ZevFactory(owner=self.manager)
        self.building = Building.objects.create(zev=self.zev, name="Haus A")

    def test_a_manager_sets_and_clears_the_coordinates_and_the_update_is_audited(self):
        client = client_for(self.manager)
        url = f"{BUILDINGS}{self.building.pk}/"
        response = client.patch(url, {"latitude": "47.37691", "longitude": "8.54169"}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual((response.json()["latitude"], response.json()["longitude"]), ("47.37691", "8.54169"))
        event = AuditEvent.objects.filter(action_type="building.update").latest("created_at")
        self.assertIn("latitude", str(event.changes_json))

        cleared = client.patch(url, {"latitude": None, "longitude": None}, format="json")
        self.assertIsNone(cleared.json()["latitude"])

    def test_the_coordinates_are_bounded(self):
        url = f"{BUILDINGS}{self.building.pk}/"
        client = client_for(self.manager)
        self.assertEqual(client.patch(url, {"latitude": "91"}, format="json").status_code, 400)
        self.assertEqual(client.patch(url, {"longitude": "-181"}, format="json").status_code, 400)

    def test_locate_returns_the_centre_of_the_outline_without_saving(self):
        footprint = {"type": "Polygon", "coordinates": [[[8.5, 47.3], [8.6, 47.3], [8.6, 47.4], [8.5, 47.4], [8.5, 47.3]]]}
        with mock.patch("zev.views.geocode_building_footprint", return_value=footprint):
            response = client_for(self.manager).post(
                BUILDINGS + "locate/", {"address_line1": "Bahnhofstrasse 1", "postal_code": "8001", "city": "Zürich"}, format="json"
            )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json(), {"latitude": 47.35, "longitude": 8.55})
        self.building.refresh_from_db()
        self.assertIsNone(self.building.latitude)

    def test_locate_says_so_when_nothing_matches_or_the_address_is_incomplete(self):
        client = client_for(self.manager)
        with mock.patch("zev.views.geocode_building_footprint", return_value=None):
            response = client.post(BUILDINGS + "locate/", {"address_line1": "Nowhere 1", "city": "X"}, format="json")
        self.assertEqual(response.status_code, 400)
        cache.clear()
        self.assertEqual(client.post(BUILDINGS + "locate/", {"city": "X"}, format="json").status_code, 400)

    def test_locate_is_for_managers_and_rate_limited(self):
        stranger = make_user("co_stranger", UserRole.USER)
        self.assertEqual(client_for(stranger).post(BUILDINGS + "locate/", {"address_line1": "a", "city": "b"}, format="json").status_code, 403)
        footprint = {"type": "Polygon", "coordinates": [[[8.5, 47.3], [8.6, 47.3], [8.6, 47.4], [8.5, 47.3]]]}
        with mock.patch("zev.views.geocode_building_footprint", return_value=footprint):
            client = client_for(self.manager)
            body = {"address_line1": "a", "city": "b"}
            self.assertEqual(client.post(BUILDINGS + "locate/", body, format="json").status_code, 200)
            self.assertEqual(client.post(BUILDINGS + "locate/", body, format="json").status_code, 429)


class FootprintCentroidTests(TestCase):
    def test_polygon_and_multipolygon(self):
        ring = [[8.0, 47.0], [8.2, 47.0], [8.2, 47.2], [8.0, 47.2], [8.0, 47.0]]
        self.assertEqual(footprint_centroid({"type": "Polygon", "coordinates": [ring]}), (47.1, 8.1))
        self.assertEqual(footprint_centroid({"type": "MultiPolygon", "coordinates": [[ring]]}), (47.1, 8.1))

    def test_a_broken_geometry_has_no_centre(self):
        for bad in ({}, {"type": "Polygon", "coordinates": []}, {"type": "Polygon", "coordinates": [[]]},
                    {"type": "Polygon", "coordinates": [[["x", "y"]]]}, {"type": "Polygon", "coordinates": [[[500, 500]]]}):
            self.assertIsNone(footprint_centroid(bad), bad)
