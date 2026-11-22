"""Billing's band for each shared sample; the frontend test checks the coverage warning on the same file."""
import json
from datetime import datetime, time
from pathlib import Path

import pytest

from tariffs.models import TariffPeriod
from tariffs.periods import resolve_band
from testing import factories

SCENARIOS = json.loads((Path(__file__).parent / "testdata/band-resolution.json").read_text())


@pytest.mark.django_db
@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda scenario: scenario["name"])
def test_billing_matches_shared_band_scenarios(scenario):
    tariff = factories.TariffFactory()
    for band in scenario["bands"]:
        times = {field: band[field] and time.fromisoformat(band[field]) for field in ("time_from", "time_to")}
        TariffPeriod.objects.create(tariff=tariff, price_chf_per_kwh="0.20", **(band | times))
    # Read back through the model's ordering: the fallback is periods[0] as billing receives them.
    periods = list(tariff.periods.all())
    for sample in scenario["samples"]:
        resolved = resolve_band(periods, datetime.fromisoformat(sample["at"]))
        assert str(resolved.pk) == sample["band_id"], sample
