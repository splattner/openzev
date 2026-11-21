"""Storage and wire readers use the same bounded diagnostic contract."""

import json
from pathlib import Path

import pytest

from tariffs.dynamic.diagnostics import FETCH_ERROR_PARAMETERS, normalize_fetch_diagnostics
from tariffs.dynamic.models import DynamicTariffSource
from tariffs.serializers import DynamicTariffSourceSerializer


FIXTURE = Path(__file__).resolve().parents[2] / "frontend/tests/fixtures/dynamic-fetch-diagnostics.json"
if not FIXTURE.exists():
    pytest.skip(f"shared frontend fixture not available at {FIXTURE} (backend-only checkout)", allow_module_level=True)
CONTRACT = json.loads(FIXTURE.read_text())


def test_stored_fetch_diagnostics_follow_the_shared_contract():
    assert {entry["code"] for entry in CONTRACT["valid"]} == set(FETCH_ERROR_PARAMETERS)
    for entry in CONTRACT["valid"]:
        assert set(entry["params"]) == set(FETCH_ERROR_PARAMETERS[entry["code"]])
        assert normalize_fetch_diagnostics([entry]) == [entry]
    assert normalize_fetch_diagnostics(CONTRACT["mixed"]) == CONTRACT["expected"]


def test_source_serialization_keeps_usable_causes_and_strips_old_envelopes():
    for value, expected in [(CONTRACT["mixed"], CONTRACT["expected"]), ([None], []), ("broken", [])]:
        source = DynamicTariffSource(last_fetch_diagnostics=value)
        assert DynamicTariffSourceSerializer(source).data["last_fetch_diagnostics"] == expected
