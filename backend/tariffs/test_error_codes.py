"""The rendered tariff contract, also consumed by frontend translation tests."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from tariffs.importers.remote import TariffFetchError
from tariffs.models import Tariff, TariffPeriod
from testing import factories
from testing.helpers import authenticate

pytestmark = pytest.mark.django_db
BASE = "/api/v1/tariffs/"
CONTRACT = json.loads(
    (
        Path(__file__).parents[2]
        / "frontend/tests/fixtures/tariff-validation-errors.json"
    ).read_text()
)


@pytest.fixture
def world():
    owner = factories.OwnerFactory()
    zev = factories.ZevFactory(owner=owner)
    client = APIClient()
    authenticate(client, owner)
    payload = {
        "zev": str(zev.pk),
        "name": "Grid",
        "billing_mode": "energy",
        "energy_type": "grid",
        "valid_from": "2026-01-01",
    }
    return client, zev, payload


def errors(response, status=400):
    assert response.status_code == status, response.data
    # JSON rendering, not Python ErrorDetail.code, is the client contract.
    return response.json()["validation_errors"]


def test_shared_contract(world):
    client, zev, payload = world
    missing = {key: value for key, value in payload.items() if key != "valid_from"}
    assert errors(client.post(BASE + "tariffs/", missing, format="json")) == [
        CONTRACT[0]
    ]
    response = client.post(
        BASE + "tariffs/",
        {
            **payload,
            "initial_periods": [
                {"price_chf_per_kwh": "0.25"},
                {
                    "period_type": "band",
                    "price_chf_per_kwh": "bad",
                    "time_from": "07:00",
                    "time_to": "22:00",
                },
            ],
        },
        format="json",
    )
    assert errors(response) == [CONTRACT[1]]
    response = client.post(
        BASE + "tariffs/",
        {
            **payload,
            "initial_periods": [
                {
                    "period_type": "band",
                    "price_chf_per_kwh": "0.25",
                    "time_from": "00:00",
                    "time_to": "07:00",
                },
                {
                    "period_type": "band",
                    "price_chf_per_kwh": "0.25",
                    "time_from": "07:00",
                },
            ],
        },
        format="json",
    )
    assert errors(response) == [CONTRACT[2]]
    response = client.post(
        BASE + "tariffs/",
        {
            **payload,
            "initial_periods": [
                {"period_type": "flat", "price_chf_per_kwh": "0.25", "months": "1,3"},
                {
                    "period_type": "band",
                    "price_chf_per_kwh": "0.25",
                    "months": "1,2,3",
                    "time_from": "07:00",
                    "time_to": "22:00",
                },
            ],
        },
        format="json",
    )
    assert errors(response) == [CONTRACT[3]]
    assert not Tariff.objects.filter(zev=zev).exists()
    assert not TariffPeriod.objects.filter(tariff__zev=zev).exists()
    created = client.post(BASE + "tariffs/", payload, format="json")
    response = client.post(
        BASE + f"tariffs/{created.data['id']}/new-version/",
        {"valid_from": payload["valid_from"]},
        format="json",
    )
    assert errors(response) == [CONTRACT[4]]
    assert response.json()["valid_from"] == [CONTRACT[4]["message"]]


@pytest.mark.parametrize(
    ("field", "value", "code", "params"),
    [
        ("valid_from", "bad", "invalid_date", {}),
        ("valid_from", "2026-02-30", "invalid_date", {}),
        ("name", "", "blank", {}),
        ("name", "x" * 201, "max_length", {"count": 200}),
        ("energy_type", "bad", "invalid_choice", {}),
        (
            "dynamic_source",
            "00000000-0000-0000-0000-000000000000",
            "does_not_exist",
            {},
        ),
        ("valid_to", "2025-01-01", "date_range", {}),
    ],
)
def test_standard_field_codes(world, field, value, code, params):
    client, _, payload = world
    response = client.post(BASE + "tariffs/", {**payload, field: value}, format="json")
    entry = next(item for item in errors(response) if item["field"] == field)
    assert entry["code"] == code
    assert entry["params"] == params
    assert entry["path"] == [field]


@pytest.mark.parametrize(
    ("field", "value", "code", "params"),
    [
        ("price_chf_per_kwh", "0.123456", "max_decimal_places", {"count": 5}),
        ("price_chf_per_kwh", "123456789", "max_digits", {"count": 8}),
        ("price_chf_per_kwh", "1234", "max_whole_digits", {"count": 3}),
        ("time_from", "bad", "invalid_time", {}),
        ("weekdays", "7", "invalid_weekdays", {}),
        ("months", "13", "invalid_months", {}),
    ],
)
def test_nested_field_codes(world, field, value, code, params):
    client, _, payload = world
    band = {
        "period_type": "band",
        "price_chf_per_kwh": "0.25",
        "time_from": "07:00",
        "time_to": "22:00",
        field: value,
    }
    response = client.post(
        BASE + "tariffs/", {**payload, "initial_periods": [band]}, format="json"
    )
    entry = next(item for item in errors(response) if item["field"] == field)
    assert entry["code"] == code
    assert entry["params"] == params
    assert entry["path"] == ["initial_periods", 0, field]


def test_fixed_fee_label_context_survives_partial_update(world):
    client, _, payload = world
    created = client.post(
        BASE + "tariffs/",
        {**payload, "billing_mode": "yearly_fee", "fixed_price_chf": "15"},
        format="json",
    )
    response = client.patch(
        BASE + f"tariffs/{created.data['id']}/",
        {"fixed_price_chf": "1.234"},
        format="json",
    )
    assert errors(response)[0]["params"] == {"count": 2, "billing_mode": "yearly_fee"}


def test_nested_replacement_band_path_and_rollback(world):
    client, _, payload = world
    created = client.post(BASE + "tariffs/", payload, format="json")
    response = client.post(
        BASE + f"tariffs/{created.data['id']}/new-version/",
        {
            "valid_from": "2027-01-01",
            "periods": [
                {"price_chf_per_kwh": "0.25"},
                {"price_chf_per_kwh": "bad"},
            ],
        },
        format="json",
    )
    assert errors(response)[0]["path"] == ["periods", 1, "price_chf_per_kwh"]
    assert Tariff.objects.get(pk=created.data["id"]).valid_to is None


def test_permission_not_found_and_fetch_codes(world):
    client, _, payload = world
    missing = client.get(BASE + "tariffs/00000000-0000-0000-0000-000000000000/")
    assert errors(missing, 404)[0]["code"] == "not_found"
    outsider = factories.ZevFactory()
    response = client.post(
        BASE + "imports/vse/preview/", {"zev": str(outsider.pk)}, format="json"
    )
    assert errors(response, 403)[0]["code"] == "permission"
    with patch(
        "tariffs.views_import.fetch_tariff_document",
        side_effect=TariffFetchError(
            "New safe wording",
            code="http_status",
            params={"status": 404},
            log_detail="PRIVATE SECRET",
        ),
    ):
        response = client.post(
            BASE + "imports/vse/preview/",
            {"zev": payload["zev"], "url": "https://example.test/prices"},
            format="json",
        )
    assert errors(response)[0] == {
        "code": "http_status",
        "field": None,
        "path": ["detail"],
        "params": {"status": 404},
        "message": "New safe wording",
    }
    assert "PRIVATE SECRET" not in response.content.decode()


def test_dynamic_history_parameters_and_admin_guard(world):
    from tariffs.dynamic.models import DynamicTariffSource

    client, zev, _ = world
    source = DynamicTariffSource.objects.create(
        label="Source",
        url="https://example.test/prices",
        api_version="v1_0_5",
        tariff_type="grid",
    )
    factories.TariffFactory(zev=zev, energy_type="grid", dynamic_source=source)
    response = client.get(
        BASE
        + f"dynamic-sources/{source.pk}/prices/?date_from=2026-01-01&date_to=2026-02-02"
    )
    assert errors(response)[0]["params"] == {"count": 31}
    assert errors(response)[0]["code"] == "history_limit"
    response = client.post(
        BASE + f"dynamic-sources/{source.pk}/fetch/", {}, format="json"
    )
    assert errors(response, 403)[0]["code"] == "admin_source"


def test_non_tariff_errors_are_unchanged(world):
    client, _, _ = world
    response = client.get(
        "/api/v1/zev/participants/00000000-0000-0000-0000-000000000000/"
    )
    assert response.status_code == 404
    assert "validation_errors" not in response.json()


def test_openapi_keeps_success_and_describes_additive_errors():
    from drf_spectacular.generators import SchemaGenerator

    schema = SchemaGenerator().get_schema(public=True)
    responses = schema["paths"][BASE + "tariffs/"]["post"]["responses"]
    assert "201" in responses
    assert responses["400"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/TariffErrorResponse"
    }
    properties = schema["components"]["schemas"]["TariffError"]["properties"]
    assert set(properties) == {"code", "field", "path", "params", "message"}


def test_model_codes_preserve_percent_in_user_names(world):
    client, _, payload = world
    payload = {**payload, "name": "100% Grid %(unknown)s"}
    assert client.post(BASE + "tariffs/", payload, format="json").status_code == 201
    response = client.post(BASE + "tariffs/", payload, format="json")
    entry = errors(response)[0]
    assert entry["code"] == "overlap"
    assert entry["params"] == {"name": payload["name"]}
    assert payload["name"] in entry["message"]


def test_remote_http_failure_serializes_real_producer_code(world):
    from urllib.error import HTTPError

    client, _, payload = world
    with (
        patch("tariffs.importers.remote._check_public_host"),
        patch("tariffs.importers.remote.urllib.request.build_opener") as opener,
    ):
        opener.return_value.open.side_effect = HTTPError(
            "https://example.test/prices", 410, "PRIVATE DETAILS", {}, None
        )
        response = client.post(
            BASE + "imports/vse/preview/",
            {"zev": payload["zev"], "url": "https://example.test/prices"},
            format="json",
        )
    assert errors(response)[0]["code"] == "http_status"
    assert errors(response)[0]["params"] == {"status": 410}
    assert "PRIVATE DETAILS" not in response.content.decode()


def test_catch_all_bands_remain_valid_and_conflicts_have_codes(world):
    client, _, payload = world
    created = client.post(
        BASE + "tariffs/",
        {
            **payload,
            "initial_periods": [
                {"period_type": "band", "price_chf_per_kwh": "0.25", "months": "1,3"},
            ],
        },
        format="json",
    )
    assert created.status_code == 201, created.data
    response = client.post(
        BASE + "periods/",
        {
            "tariff": created.data["id"],
            "period_type": "band",
            "price_chf_per_kwh": "0.30",
            "months": "1,2,3",
        },
        format="json",
    )
    entry = errors(response)[0]
    assert entry["code"] == "catch_all_conflict"
    assert entry["params"] == {"months": [1, 3]}
