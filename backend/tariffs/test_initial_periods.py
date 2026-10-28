"""Creating a static energy tariff together with its bands (issue #1113).

One request writes the tariff and every band or nothing; a bad band is named by
its index in ``initial_periods``. See docs/specs/2026-03-tariffs-and-billing-engine.md.
"""
from datetime import date

import pytest
from rest_framework.test import APIClient

from audit.models import AuditEvent
from tariffs.dynamic.models import DynamicTariffSource
from tariffs.models import BillingMode, EnergyType, PeriodType, Tariff, TariffCategory, TariffPeriod
from testing import factories
from testing.helpers import authenticate as auth
from zev.models import ZevAccessGrant, ZevAccessRole

pytestmark = pytest.mark.django_db

URL = "/api/v1/tariffs/tariffs/"
WEEKDAYS = "0,1,2,3,4"

HT = {
    "period_type": PeriodType.HIGH, "label": "HT", "price_chf_per_kwh": "0.29500",
    "time_from": "07:00:00", "time_to": "21:00:00", "weekdays": WEEKDAYS,
}
NT = {"period_type": PeriodType.LOW, "label": "NT", "price_chf_per_kwh": "0.22500"}


@pytest.fixture
def owner_client(db):
    owner = factories.OwnerFactory()
    zev = factories.ZevFactory(owner=owner)
    client = APIClient()
    auth(client, owner)
    return client, zev


def payload(zev, **extra):
    return {
        "zev": str(zev.id), "name": "Grid", "category": TariffCategory.ENERGY,
        "billing_mode": BillingMode.ENERGY, "energy_type": EnergyType.GRID,
        "valid_from": "2026-01-01", **extra,
    }


def post(client, zev, **extra):
    return client.post(URL, payload(zev, **extra), format="json")


def nothing_written():
    return not Tariff.objects.exists() and not TariffPeriod.objects.exists()


def test_one_request_creates_the_tariff_and_its_bands(owner_client):
    client, zev = owner_client

    response = post(client, zev, initial_periods=[HT, NT])

    assert response.status_code == 201, response.data
    tariff = Tariff.objects.get(pk=response.data["id"])
    bands = {band.label: band for band in tariff.periods.all()}
    assert set(bands) == {"HT", "NT"}
    assert str(bands["HT"].price_chf_per_kwh) == "0.29500"
    assert bands["NT"].time_from is None
    assert [band["label"] for band in response.data["periods"]] == [b.label for b in tariff.periods.all()]
    assert "initial_periods" not in response.data


def test_a_bad_band_is_named_by_index_and_field_and_writes_nothing(owner_client):
    client, zev = owner_client

    response = post(client, zev, initial_periods=[HT, {**NT, "price_chf_per_kwh": None}])

    assert response.status_code == 400
    errors = response.data["initial_periods"]
    assert len(errors) == 2
    assert errors[0] == {}
    assert "price_chf_per_kwh" in errors[1]
    assert nothing_written()


def test_a_missing_price_key_is_reported_on_its_band(owner_client):
    client, zev = owner_client
    band = {key: value for key, value in NT.items() if key != "price_chf_per_kwh"}

    response = post(client, zev, initial_periods=[band])

    assert response.status_code == 400
    assert "price_chf_per_kwh" in response.data["initial_periods"][0]
    assert nothing_written()


def test_a_flat_band_beside_a_timed_band_is_reported_on_the_later_band(owner_client):
    client, zev = owner_client
    flat = {"period_type": PeriodType.FLAT, "price_chf_per_kwh": "0.25000"}

    response = post(client, zev, initial_periods=[HT, flat])

    assert response.status_code == 400
    errors = response.data["initial_periods"]
    assert errors[0] == {}
    assert "period_type" in errors[1]
    assert nothing_written()


def test_two_bands_without_a_window_on_the_same_hours_are_rejected(owner_client):
    client, zev = owner_client

    response = post(client, zev, initial_periods=[NT, {**NT, "label": "Other"}])

    assert response.status_code == 400
    errors = response.data["initial_periods"]
    assert errors[0] == {}
    assert "time_from" in errors[1]
    assert nothing_written()


def test_window_less_bands_in_different_seasons_are_fine(owner_client):
    client, zev = owner_client

    response = post(client, zev, initial_periods=[
        {**NT, "months": "1,2,3"}, {**NT, "label": "Summer NT", "months": "4,5,6"},
    ])

    assert response.status_code == 201, response.data


def test_a_band_with_only_one_of_the_times_is_rejected(owner_client):
    client, zev = owner_client

    response = post(client, zev, initial_periods=[{**NT, "time_from": "07:00:00"}])

    assert response.status_code == 400
    assert "time_to" in response.data["initial_periods"][0]
    assert nothing_written()


def test_every_bad_band_is_reported_in_one_response(owner_client):
    client, zev = owner_client

    response = post(client, zev, initial_periods=[
        {**NT, "price_chf_per_kwh": None}, HT, {**HT, "time_to": None},
    ])

    errors = response.data["initial_periods"]
    assert response.status_code == 400
    assert ["price_chf_per_kwh" in errors[0], errors[1], "time_to" in errors[2]] == [True, {}, True]


def test_an_empty_list_is_rejected(owner_client):
    client, zev = owner_client

    response = post(client, zev, initial_periods=[])

    assert response.status_code == 400
    assert "initial_periods" in response.data
    assert nothing_written()


def test_a_percentage_tariff_does_not_take_initial_bands(owner_client):
    client, zev = owner_client

    response = post(
        client, zev, billing_mode=BillingMode.PERCENTAGE_OF_ENERGY, energy_type=EnergyType.LOCAL,
        initial_periods=[{"period_type": PeriodType.FLAT, "percentage": "10.00"}],
    )

    assert response.status_code == 400
    assert "initial_periods" in response.data
    assert nothing_written()


def test_a_fee_tariff_does_not_take_initial_bands(owner_client):
    client, zev = owner_client

    response = post(
        client, zev, billing_mode=BillingMode.MONTHLY_FEE, energy_type=None,
        fixed_price_chf="12.00", initial_periods=[HT],
    )

    assert response.status_code == 400
    assert "initial_periods" in response.data
    assert nothing_written()


def test_a_dynamic_tariff_does_not_take_initial_bands(owner_client):
    client, zev = owner_client
    source = DynamicTariffSource.objects.create(
        label="Groupe E vario", url="https://api.tariffs.groupe-e.ch/v2/tariffs",
        api_version="v1_0_5", tariff_type="grid", tariff_name="vario",
    )

    response = post(client, zev, dynamic_source=str(source.pk), initial_periods=[HT])

    assert response.status_code == 400
    assert "initial_periods" in response.data
    assert nothing_written()


@pytest.mark.parametrize("method", ["patch", "put"])
def test_initial_periods_are_rejected_on_update(owner_client, method):
    client, zev = owner_client
    tariff = factories.TariffFactory(
        zev=zev, billing_mode=BillingMode.ENERGY, energy_type=EnergyType.GRID,
        valid_from=date(2026, 1, 1),
    )
    body = {"initial_periods": [HT]} if method == "patch" else {
        **payload(zev), "name": tariff.name, "initial_periods": [HT],
    }

    response = getattr(client, method)(f"{URL}{tariff.pk}/", body, format="json")

    assert response.status_code == 400
    assert "initial_periods" in response.data
    assert not tariff.periods.exists()


def test_percentage_creation_still_takes_initial_percentage_and_logs_no_band_event(owner_client):
    client, zev = owner_client

    response = post(
        client, zev, billing_mode=BillingMode.PERCENTAGE_OF_ENERGY, energy_type=EnergyType.LOCAL,
        initial_percentage="42.00",
    )

    assert response.status_code == 201, response.data
    assert Tariff.objects.get(pk=response.data["id"]).periods.count() == 1
    assert not AuditEvent.objects.filter(action_type="tariff_period.create").exists()


def test_one_audit_event_per_band_beside_the_tariffs(owner_client):
    client, zev = owner_client

    response = post(client, zev, initial_periods=[HT, NT])

    assert response.status_code == 201, response.data
    tariff = Tariff.objects.get(pk=response.data["id"])
    assert AuditEvent.objects.filter(action_type="tariff.create", target_id=str(tariff.pk)).count() == 1
    events = AuditEvent.objects.filter(action_type="tariff_period.create")
    assert events.count() == 2
    assert {event.target_id for event in events} == {str(band.pk) for band in tariff.periods.all()}
    assert all(event.metadata_json == {"tariff_id": str(tariff.pk)} for event in events)


def test_a_failed_request_logs_no_events(owner_client):
    client, zev = owner_client

    post(client, zev, initial_periods=[{**NT, "price_chf_per_kwh": None}])

    assert not AuditEvent.objects.filter(action_type__in=["tariff.create", "tariff_period.create"]).exists()


def test_a_viewer_cannot_create_a_tariff_with_bands(owner_client):
    _client, zev = owner_client
    viewer = factories.UserFactory()
    ZevAccessGrant.objects.create(zev=zev, user=viewer, role=ZevAccessRole.VIEWER, valid_from=date(2026, 1, 1))
    client = APIClient()
    auth(client, viewer)

    response = post(client, zev, initial_periods=[HT, NT])

    assert response.status_code in (403, 404)
    assert nothing_written()


def test_a_user_without_access_to_the_zev_cannot_create_one(owner_client):
    _client, zev = owner_client
    stranger = factories.OwnerFactory()
    client = APIClient()
    auth(client, stranger)

    response = post(client, zev, initial_periods=[HT])

    assert response.status_code in (400, 403, 404)
    assert nothing_written()
