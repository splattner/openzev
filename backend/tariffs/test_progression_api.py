"""``GET /api/v1/tariffs/tariffs/progression/`` (docs/specs/2026-11-tariff-progression.md §6).

The numbers are covered in ``invoices/test_tariff_progression.py``; this file
checks the contract: parameters, scope, errors and the response shape.
"""
import uuid
from datetime import date
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from invoices import tariff_progression
from tariffs.models import BillingMode, EnergyType, PeriodType, TariffCategory
from testing import factories
from testing.helpers import authenticate as auth
from zev.models import ZevAccessGrant, ZevAccessRole

pytestmark = pytest.mark.django_db

URL = "/api/v1/tariffs/tariffs/progression/"


def make_tariff(zev, name="Energie", price="0.20", **kwargs):
    tariff = factories.TariffFactory(
        zev=zev, name=name, billing_mode=BillingMode.ENERGY, energy_type=EnergyType.GRID,
        category=kwargs.pop("category", TariffCategory.ENERGY), valid_from=date(2025, 1, 1), **kwargs,
    )
    factories.TariffPeriodFactory(tariff=tariff, period_type=PeriodType.FLAT, price_chf_per_kwh=Decimal(price))
    return tariff


@pytest.fixture
def owner_client():
    owner = factories.OwnerFactory()
    zev = factories.ZevFactory(owner=owner)
    client = APIClient()
    auth(client, owner)
    return client, zev


def get(client, zev, **params):
    query = {"zev_id": str(zev.pk), "energy_type": "grid", **params}
    return client.get(URL, {key: value for key, value in query.items() if value is not None})


class TestProgressionApi:
    def test_requires_authentication(self):
        zev = factories.ZevFactory()

        assert get(APIClient(), zev).status_code == 401

    def test_zev_id_is_required(self, owner_client):
        client, zev = owner_client

        response = get(client, zev, zev_id=None)

        assert response.status_code == 400
        assert "zev_id" in response.json()

    def test_an_unknown_energy_type_is_rejected(self, owner_client):
        client, zev = owner_client

        response = get(client, zev, energy_type="solar")

        assert response.status_code == 400
        assert "energy_type" in response.json()

    def test_from_after_to_is_rejected(self, owner_client):
        client, zev = owner_client

        response = get(client, zev, **{"from": "2025-06-01", "to": "2025-01-01"})

        assert response.status_code == 400
        assert "from" in response.json()

    def test_a_malformed_date_is_named_by_its_query_parameter(self, owner_client):
        client, zev = owner_client

        response = get(client, zev, **{"from": "tomorrow"})

        assert response.status_code == 400
        assert "from" in response.json()

    def test_a_zev_outside_the_callers_scope_is_a_404(self, owner_client):
        client, _ = owner_client
        other = factories.ZevFactory()
        make_tariff(other)

        assert get(client, other).status_code == 404

    def test_an_unknown_zev_is_a_404(self):
        client = APIClient()
        auth(client, factories.AdminFactory())

        response = client.get(URL, {"zev_id": str(uuid.uuid4()), "energy_type": "grid"})

        assert response.status_code == 404

    def test_a_viewer_can_read(self):
        zev = factories.ZevFactory()
        make_tariff(zev)
        viewer = factories.UserFactory()
        ZevAccessGrant.objects.create(
            zev=zev, user=viewer, role=ZevAccessRole.VIEWER, valid_from=date(2020, 1, 1),
        )
        client = APIClient()
        auth(client, viewer)

        response = get(client, zev)

        assert response.status_code == 200
        assert response.json()["intervals"][0]["slots"][0]["net"] == "0.20000"

    def test_a_user_with_no_access_is_refused(self):
        zev = factories.ZevFactory()
        client = APIClient()
        auth(client, factories.UserFactory())

        assert get(client, zev).status_code in (403, 404)

    def test_an_admin_can_read_any_zev(self):
        zev = factories.ZevFactory()
        make_tariff(zev)
        client = APIClient()
        auth(client, factories.AdminFactory())

        assert get(client, zev).status_code == 200

    def test_the_response_shape(self, owner_client):
        client, zev = owner_client
        tariff = make_tariff(zev)
        make_tariff(zev, "Netz", "0.05", category=TariffCategory.GRID_FEES)

        body = get(client, zev, **{"from": "2025-01-01", "to": "2025-12-31"}).json()

        assert set(body) == {
            "zev", "energy_type", "vat_mode", "from", "to", "expected_categories",
            "lines", "intervals", "fixed_fees",
        }
        assert (body["zev"], body["energy_type"], body["vat_mode"]) == (
            str(zev.pk), "grid", "not_registered",
        )
        assert body["expected_categories"] == ["energy", "grid_fees"]
        assert body["lines"][0]["key"] == "line-1"
        interval = body["intervals"][0]
        assert set(interval) == {"from", "to", "vat_rate", "missing_categories", "incomplete", "slots"}
        slot = interval["slots"][0]
        assert set(slot) == {"line", "net", "gross", "categories"}
        assert slot["net"] == "0.25000"
        component = slot["categories"][0]["components"][0]
        assert component == {
            "tariff_id": str(tariff.pk), "name": "Energie", "billing_mode": "energy",
            "band_period_id": str(tariff.periods.get().pk), "net": "0.20000", "gross": None,
            "percentage": None, "base_net": None,
        }

    def test_too_many_bands_is_a_422(self, owner_client, monkeypatch):
        client, zev = owner_client
        tariff = factories.TariffFactory(
            zev=zev, name="Energie", billing_mode=BillingMode.ENERGY, energy_type=EnergyType.GRID,
            category=TariffCategory.ENERGY, valid_from=date(2025, 1, 1),
        )
        factories.TariffPeriodFactory(
            tariff=tariff, period_type=PeriodType.HIGH, price_chf_per_kwh=Decimal("0.30"),
            time_from="07:00", time_to="20:00", weekdays="0,1,2,3,4",
        )
        factories.TariffPeriodFactory(tariff=tariff, period_type=PeriodType.LOW, price_chf_per_kwh=Decimal("0.20"))
        monkeypatch.setattr(tariff_progression, "MAX_SLOTS_PER_INTERVAL", 1)

        response = get(client, zev)

        assert response.status_code == 422
        assert response.json()["code"] == "too_many_bands"

    def test_only_the_requested_zevs_tariffs_are_used(self, owner_client):
        client, zev = owner_client
        make_tariff(zev, "Energie", "0.20")
        second = factories.ZevFactory(owner=ZevAccessGrant.objects.get(zev=zev).user)
        make_tariff(second, "Energie", "0.90")

        slots = get(client, zev).json()["intervals"][0]["slots"]

        assert [slot["net"] for slot in slots] == ["0.20000"]

    def test_the_query_count_is_bounded(self, owner_client, django_assert_max_num_queries):
        client, zev = owner_client
        for index in range(12):
            make_tariff(zev, f"Tariff {index}", "0.01")

        with django_assert_max_num_queries(8):
            response = get(client, zev)

        assert response.status_code == 200
        assert response.json()["intervals"][0]["slots"][0]["net"] == "0.12000"

    def test_the_default_range_runs_to_today(self, owner_client):
        client, zev = owner_client
        make_tariff(zev)

        body = get(client, zev).json()

        assert (body["from"], body["to"]) == ("2025-01-01", timezone.localdate().isoformat())
