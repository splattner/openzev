"""UI notices carry codes without changing the English diagnostic or import identity."""

import copy
from decimal import Decimal

import pytest

from config.ui_notices import UiNotice, notice_data
from tariffs.importers.vse_json import parse_document
from tariffs.serializers import VseTariffCandidateSerializer
from tariffs.test_vse_import import document, entry
from tariffs.views_import import _candidate_payload
from tariffs.importers.planner import plan_import


def test_notice_survives_response_copying_and_serializes_decimal_parameters():
    notice = UiNotice("Price rounded from 0.123456 to 0.12346.", "price_rounded",
                      value=Decimal("0.123456"), rounded=Decimal("0.12346"))
    assert str(copy.deepcopy(notice)) == str(notice)
    assert notice_data(copy.deepcopy(notice)) == {
        "code": "price_rounded", "params": {"value": "0.123456", "rounded": "0.12346"},
    }
    assert notice_data("Unclassified parser detail") is None


@pytest.mark.django_db
def test_preview_keeps_identity_prices_and_diagnostics_independent_of_language(admin_client, zev):
    from unittest.mock import patch

    payload = document(entry(prices={"energy": [{
        "from": "08:00", "to": "18:00", "price": 0.123456, "priceUnit": "CHF/kWh",
    }]}))
    with patch("tariffs.views_import.fetch_tariff_document", return_value=(payload, "a" * 64)):
        responses = [admin_client.post("/api/v1/tariffs/imports/vse/preview/", {
            "zev": str(zev.pk), "url": "https://operator.example/tariffs.json",
        }, HTTP_ACCEPT_LANGUAGE=language) for language in ["de", "fr", "it", "en"]]
    assert all(response.status_code == 200 for response in responses)
    result = responses[0].json()
    assert all(response.json() == result for response in responses)
    assert result["document_digest"] == "a" * 64
    candidate = result["candidates"][0]
    assert candidate["detail"] == "Creates a new tariff."
    assert candidate["detail_diagnostic"] == {"code": "tariff_new", "params": {}}
    assert {item["code"] for item in candidate["warning_diagnostics"]} == {"hours_missing", "price_rounded"}
    parsed = parse_document(payload).candidates[0]
    assert (candidate["key"], candidate["name"]) == (parsed.key, parsed.name)
    assert candidate["periods"][0]["price_chf_per_kwh"] == "0.12346"


@pytest.mark.django_db
def test_unknown_import_details_remain_english_without_inventing_a_ui_code(zev):
    payload = document(entry(prices={"energy": [{"price": "invalid"}]}))
    planned = plan_import(zev.pk, parse_document(payload))[0]
    data = VseTariffCandidateSerializer(_candidate_payload(planned)).data
    assert data["status"] == "unsupported"
    assert data["detail_diagnostic"] is None
    assert "number" in data["detail"]


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_nonfinite_document_prices_are_unsupported_instead_of_crashing(value):
    parsed = parse_document(document(entry(prices={"energy": [{"price": value}]})))
    assert parsed.candidates[0].blocked_reason
    assert "number" in parsed.candidates[0].blocked_reason


@pytest.mark.parametrize("refund,code", [({"price": 0.01}, "storage_omitted"), ({"price": "bad"}, "storage_unreadable")])
def test_a_storage_refund_that_cannot_be_read_has_its_own_code(refund, code):
    from tariffs.importers.vse_json import _dropped_component_warnings

    assert [notice_data(warning)["code"] for warning in _dropped_component_warnings({"refundStorage": refund})] == [code]
