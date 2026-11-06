"""The rendered tariff contract, also consumed by frontend translation tests."""

import io
import json
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import (
    DecimalValidator,
    MaxLengthValidator,
    MaxValueValidator,
    MinLengthValidator,
    MinValueValidator,
    URLValidator,
)
from django.http import FileResponse
from drf_spectacular.generators import SchemaGenerator
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.renderers import JSONRenderer
from rest_framework.test import APIClient, APIRequestFactory
from rest_framework.views import APIView

from tariffs.dynamic.models import DynamicTariffSource
from tariffs.errors import TariffErrorResponseMixin, TariffValidationMixin, model_validation_error
from tariffs.importers.remote import TariffFetchError
from tariffs.model_errors import model_error
from tariffs.models import Tariff, TariffPeriod
from testing import factories
from testing.helpers import authenticate

BASE = "/api/v1/tariffs/"
CONTRACT = {
    case["code"]: case
    for case in json.loads(
        (
            Path(__file__).parents[2]
            / "frontend/tests/fixtures/tariff-validation-errors.json"
        ).read_text()
    )
}


@pytest.fixture
def world(db):
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


def test_shared_required_contract(world):
    client, zev, payload = world
    missing = {key: value for key, value in payload.items() if key != "valid_from"}
    assert errors(client.post(BASE + "tariffs/", missing, format="json")) == [
        CONTRACT["required"]
    ]


def test_shared_number_contract(world):
    client, _, payload = world
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
    assert errors(response) == [CONTRACT["invalid_number"]]


def test_shared_time_pair_contract(world):
    client, _, payload = world
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
    assert errors(response) == [CONTRACT["band_time_pair"]]


def test_shared_months_contract(world):
    client, zev, payload = world
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
    assert errors(response) == [CONTRACT["flat_timed_conflict"]]
    assert not Tariff.objects.filter(zev=zev).exists()
    assert not TariffPeriod.objects.filter(tariff__zev=zev).exists()


def test_shared_duplicate_date_contract(world):
    client, _, payload = world
    created = client.post(BASE + "tariffs/", payload, format="json")
    response = client.post(
        BASE + f"tariffs/{created.data['id']}/new-version/",
        {"valid_from": payload["valid_from"]},
        format="json",
    )
    assert errors(response) == [CONTRACT["duplicate_date"]]
    assert response.json()["valid_from"] == [CONTRACT["duplicate_date"]["message"]]


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


def test_openapi_keeps_success_and_describes_additive_errors(db):
    schema = SchemaGenerator().get_schema(public=True)
    responses = schema["paths"][BASE + "tariffs/"]["post"]["responses"]
    assert "201" in responses
    assert responses["400"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/TariffErrorResponse"
    }
    properties = schema["components"]["schemas"]["TariffError"]["properties"]
    assert set(properties) == {"code", "field", "path", "params", "message"}
    envelope = schema["components"]["schemas"]["TariffErrorResponse"]
    assert "detail" in envelope["properties"]
    assert envelope.get("additionalProperties", True)
    assert "503" not in responses
    for path, method, extra in [
        ("imports/vse/apply/", "post", "409"),
        ("dynamic-sources/{id}/fetch/", "post", "503"),
        ("dynamic-sources/{id}/", "delete", "409"),
        ("tariffs/progression/", "get", "404"),
        ("tariffs/progression/", "get", "422"),
    ]:
        action = schema["paths"][BASE + path][method]["responses"]
        assert (
            action[extra]["content"]["application/json"]["schema"]
            == responses["400"]["content"]["application/json"]["schema"]
        )
    history = schema["paths"][BASE + "dynamic-sources/{id}/prices/"]["get"]["responses"]
    assert "503" not in history
    assert "409" not in history


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


def test_duplicate_name_length_uses_shared_contract(world):
    client, _, payload = world
    created = client.post(BASE + "tariffs/", payload, format="json")
    response = client.post(
        BASE + f"tariffs/{created.data['id']}/duplicate/",
        {"name": "x" * 201},
        format="json",
    )
    assert errors(response) == [CONTRACT["max_length"]]


def test_empty_import_selections_preserve_context(world):
    client, _, payload = world
    response = client.post(
        BASE + "imports/vse/apply/",
        {
            "zev": payload["zev"],
            "document_digest": "a" * 64,
            "selections": [],
        },
        format="json",
    )
    entry = errors(response)[0]
    assert entry["code"] == "empty"
    assert entry["path"] == ["selections", "non_field_errors"]


@pytest.mark.parametrize("field", ["date_from", "date_to"])
def test_invalid_history_dates_have_field_codes(world, field):
    client, _, _ = world
    authenticate(client, factories.AdminFactory())
    source = DynamicTariffSource.objects.create(
        label="Source",
        url="https://example.test",
        api_version="v1_0_5",
        tariff_type="grid",
    )
    response = client.get(
        BASE + f"dynamic-sources/{source.pk}/prices/",
        {
            "date_from": "2026-01-01",
            "date_to": "2026-01-02",
            field: "2026-02-30",
        },
    )
    assert errors(response)[0]["code"] == "invalid_date"
    assert errors(response)[0]["field"] == field


@pytest.mark.parametrize(
    "code,limit,value,key",
    [
        ("max_length", 200, "x" * 201, "count"),
        ("min_length", 2, "x", "count"),
        ("min_value", "0.1234567890123456789", "0", "value"),
        ("max_value", "0.00001", "1", "value"),
    ],
)
def test_model_validator_parameters(code, limit, value, key):
    validators = {
        "max_length": MaxLengthValidator,
        "min_length": MinLengthValidator,
        "min_value": MinValueValidator,
        "max_value": MaxValueValidator,
    }
    with pytest.raises(DjangoValidationError) as caught:
        validators[code](Decimal(limit) if key == "value" else limit)(
            Decimal(value) if key == "value" else value
        )
    detail = model_validation_error(caught.value).detail[0]
    assert json.loads(JSONRenderer().render(detail.code.params)) == {key: limit}
    explicit = model_validation_error(
        model_error("Readable", code, **{key: limit}, diagnostic_only=object())
    ).detail[0]
    assert explicit.code.params == {key: limit}


def test_decimal_serializer_parameters_survive_nested_response():
    class Input(TariffValidationMixin, serializers.Serializer):
        value = serializers.DecimalField(
            max_digits=24,
            decimal_places=20,
            min_value=Decimal("0.1234567890123456789"),
        )

    class NestedView(TariffErrorResponseMixin, APIView):
        authentication_classes = []
        permission_classes = []

        def post(self, request):
            serializer = Input(data=request.data)
            assert not serializer.is_valid()
            raise ValidationError({"outer": [serializer.errors]})

    response = NestedView.as_view()(
        APIRequestFactory().post("/", {"value": "0"}, format="json")
    )
    response.render()
    entry = json.loads(response.content)["validation_errors"][0]
    assert entry["code"] == "min_value"
    assert entry["path"] == ["outer", 0, "value"]
    assert entry["params"] == {"value": "0.1234567890123456789"}


@pytest.mark.parametrize("status", [200, 400])
def test_file_responses_skip_error_enrichment(status, db):
    class Parent:
        def finalize_response(self, request, response, *args, **kwargs):
            return response

    class View(TariffErrorResponseMixin, Parent):
        pass

    response = FileResponse(io.BytesIO(b"file"), status=status)
    try:
        assert View().finalize_response(None, response) is response
    finally:
        response.close()


@pytest.mark.parametrize("kind", ["decimal", "url"])
def test_model_conversion_excludes_native_validator_input(kind):
    validator, value = (
        (DecimalValidator(4, 2), Decimal("123456.7"))
        if kind == "decimal"
        else (URLValidator(), "bad")
    )
    with pytest.raises(DjangoValidationError) as caught:
        validator(value)
    detail = model_validation_error(caught.value).detail[0]
    assert detail.code.params == ({"count": 4} if kind == "decimal" else {})


def test_source_range_code_describes_the_exact_url_configuration():
    source = DynamicTariffSource(
        label="Source",
        url="https://example.test/prices",
        api_version="v1_0_5",
        tariff_type="grid",
        request_mode="exact_url",
        supports_range=True,
    )
    with pytest.raises(DjangoValidationError) as caught:
        source.clean()
    error = model_validation_error(caught.value).detail["supports_range"][0]
    assert error.code == "source_range"
    assert "exact-URL" in str(error)
    source.supports_range = False
    source.clean()


@pytest.mark.parametrize("action", ["duplicate", "new-version"])
@pytest.mark.parametrize(
    "value,code,params",
    [
        ("bad", "invalid_number", {}),
        ("1.234", "max_decimal_places", {"count": 2}),
    ],
)
def test_custom_action_prices_use_field_codes_and_copied_billing_mode(
    world, action, value, code, params
):
    client, zev, _ = world
    source = factories.TariffFactory(
        zev=zev,
        billing_mode="yearly_fee",
        energy_type=None,
        fixed_price_chf="15",
        valid_from="2026-01-01",
        valid_to=None,
    )
    data = {"name": "Copy", "valid_from": "2027-01-01", "fixed_price_chf": value}
    response = client.post(BASE + f"tariffs/{source.pk}/{action}/", data, format="json")
    entry = errors(response)[0]
    assert entry["code"] == code
    assert entry["path"] == ["fixed_price_chf"]
    assert entry["params"] == {**params, "billing_mode": "yearly_fee"}
    source.refresh_from_db()
    assert source.valid_to is None
    assert Tariff.objects.filter(zev=zev).count() == 1


@pytest.mark.parametrize("action", ["duplicate", "new-version"])
def test_custom_action_impossible_dates_are_validation_errors(world, action):
    client, zev, _ = world
    source = factories.TariffFactory(zev=zev)
    response = client.post(
        BASE + f"tariffs/{source.pk}/{action}/",
        {
            "name": "Copy",
            "valid_from": "2026-02-30",
        },
        format="json",
    )
    entry = errors(response)[0]
    assert entry["code"] == "invalid_date"
    assert entry["path"] == ["valid_from"]
    assert "valid ISO date" in entry["message"]


def test_top_level_messages_are_wrapped_with_original_root_path(world):
    client, zev, _ = world
    source = DynamicTariffSource.objects.create(
        label="Source",
        url="https://example.test/prices",
        api_version="v1_0_5",
        tariff_type="grid",
    )
    tariff = factories.TariffFactory(
        zev=zev,
        energy_type="grid",
        dynamic_source=source,
        valid_from="2026-01-01",
        valid_to=None,
    )
    response = client.post(
        BASE + f"tariffs/{tariff.pk}/new-version/",
        {
            "valid_from": "2027-01-01",
            "periods": [{"price_chf_per_kwh": "0.1"}],
        },
        format="json",
    )
    entry = errors(response)[0]
    assert response.json()["detail"] == [entry["message"]]
    assert entry["code"] == "dynamic_bands"
    assert entry["field"] is None
    assert entry["path"] == []
    tariff.refresh_from_db()
    assert tariff.valid_to is None
    assert Tariff.objects.filter(zev=zev).count() == 1
