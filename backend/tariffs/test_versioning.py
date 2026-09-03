"""API tests for tariff versioning.

Versions of a tariff are the tariffs in a ZEV sharing its name — an invariant
the model already enforces by rejecting overlapping windows for one name. These
endpoints supply what was missing: grouping them for display, and moving the
timeline without hand-computing end dates, which is where the off-by-one that
silently unbills a month came from.
"""

from datetime import date
from decimal import Decimal

import pytest

from tariffs.models import BillingMode, EnergyType, PeriodType, SplitKey, Tariff, TariffCategory
from testing import factories
from testing.helpers import authenticate as auth
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

SERIES_URL = "/api/v1/tariffs/tariffs/series/"


def url(tariff, verb):
    return f"/api/v1/tariffs/tariffs/{tariff.pk}/{verb}/"


@pytest.fixture
def owner_client(db):
    owner = factories.OwnerFactory()
    zev = factories.ZevFactory(owner=owner)
    client = APIClient()
    auth(client, owner)
    return client, zev


def energy_version(zev, *, name="Local Energy", valid_from, valid_to=None, price="0.10000",
                   category=TariffCategory.ENERGY, energy_type=EnergyType.LOCAL):
    """One version of a flat-rate energy tariff."""
    tariff = factories.TariffFactory(
        zev=zev, name=name, category=category, billing_mode=BillingMode.ENERGY,
        energy_type=energy_type,
        valid_from=date.fromisoformat(valid_from),
        valid_to=date.fromisoformat(valid_to) if valid_to else None,
    )
    factories.TariffPeriodFactory(
        tariff=tariff, period_type=PeriodType.FLAT, price_chf_per_kwh=Decimal(price)
    )
    return tariff


# ---------------------------------------------------------------------------
# GET series
# ---------------------------------------------------------------------------

def test_versions_of_one_name_collapse_into_a_single_series(owner_client):
    client, zev = owner_client
    energy_version(zev, valid_from="2025-01-01", valid_to="2025-12-31", price="0.10000")
    energy_version(zev, valid_from="2026-01-01", price="0.11000")

    response = client.get(SERIES_URL)

    assert response.status_code == 200
    assert len(response.data) == 1
    series = response.data[0]
    assert series["name"] == "Local Energy"
    assert series["version_count"] == 2
    assert series["category"] == TariffCategory.ENERGY
    assert series["energy_type"] == EnergyType.LOCAL


def test_versions_come_back_newest_first(owner_client):
    client, zev = owner_client
    energy_version(zev, valid_from="2025-01-01", valid_to="2025-12-31")
    energy_version(zev, valid_from="2026-01-01", valid_to="2026-12-31")
    energy_version(zev, valid_from="2027-01-01")

    series = client.get(SERIES_URL).data[0]

    assert [v["valid_from"] for v in series["versions"]] == ["2027-01-01", "2026-01-01", "2025-01-01"]


def test_the_active_version_is_identified(owner_client):
    client, zev = owner_client
    energy_version(zev, valid_from="2020-01-01", valid_to="2020-12-31")
    current = energy_version(zev, valid_from="2021-01-01")

    series = client.get(SERIES_URL).data[0]

    assert series["active_version_id"] == str(current.pk)


def test_a_fully_retired_series_reports_no_active_version(owner_client):
    client, zev = owner_client
    energy_version(zev, valid_from="2020-01-01", valid_to="2020-12-31")

    series = client.get(SERIES_URL).data[0]

    assert series["active_version_id"] is None


def test_distinct_names_stay_separate_series(owner_client):
    client, zev = owner_client
    energy_version(zev, name="Netznutzung", valid_from="2026-01-01",
                   category=TariffCategory.GRID_FEES, energy_type=EnergyType.GRID)
    energy_version(zev, name="Systemdienstleistung", valid_from="2026-01-01",
                   category=TariffCategory.GRID_FEES, energy_type=EnergyType.GRID)

    response = client.get(SERIES_URL)

    assert {series["name"] for series in response.data} == {"Netznutzung", "Systemdienstleistung"}


def test_a_gap_in_the_timeline_is_reported(owner_client):
    """The whole reason gaps matter: a day with no version bills its energy at
    nothing, and today that is invisible."""
    client, zev = owner_client
    energy_version(zev, valid_from="2026-01-01", valid_to="2026-06-30")
    energy_version(zev, valid_from="2026-08-01")

    series = client.get(SERIES_URL).data[0]

    assert series["gaps"] == [{"start": "2026-07-01", "end": "2026-07-31"}]


def test_a_contiguous_series_reports_no_gaps(owner_client):
    client, zev = owner_client
    energy_version(zev, valid_from="2026-01-01", valid_to="2026-12-31")
    energy_version(zev, valid_from="2027-01-01")

    assert client.get(SERIES_URL).data[0]["gaps"] == []


def test_series_are_scoped_to_the_callers_zevs(owner_client):
    client, zev = owner_client
    energy_version(zev, valid_from="2026-01-01")
    other = factories.ZevFactory()
    energy_version(other, name="Someone Elses Tariff", valid_from="2026-01-01")

    response = client.get(SERIES_URL)

    assert [series["name"] for series in response.data] == ["Local Energy"]


def test_series_can_be_filtered_to_one_zev(owner_client):
    client, zev = owner_client
    owner = zev.owner
    second = factories.ZevFactory(owner=owner)
    energy_version(zev, valid_from="2026-01-01")
    energy_version(second, name="Second ZEV Tariff", valid_from="2026-01-01")

    response = client.get(SERIES_URL, {"zev_id": str(second.pk)})

    assert [series["name"] for series in response.data] == ["Second ZEV Tariff"]


# ---------------------------------------------------------------------------
# new-version
# ---------------------------------------------------------------------------

def test_a_new_version_closes_the_previous_one_the_day_before(owner_client):
    client, zev = owner_client
    original = energy_version(zev, valid_from="2026-01-01", price="0.10000")

    response = client.post(url(original, "new-version"), {"valid_from": "2027-01-01"}, format="json")

    assert response.status_code == 201, response.data
    original.refresh_from_db()
    assert original.valid_to == date(2026, 12, 31)
    assert response.data["valid_from"] == "2027-01-01"
    assert response.data["valid_to"] is None


def test_a_new_version_keeps_each_band_in_its_own_season(owner_client):
    """A copy that dropped the months would keep the winter price and apply it
    to the whole year — a silent doubling of what summer costs."""
    client, zev = owner_client
    original = factories.TariffFactory(
        zev=zev, name="Seasonal Grid", category=TariffCategory.GRID_FEES,
        billing_mode=BillingMode.ENERGY, energy_type=EnergyType.GRID,
        valid_from=date(2026, 1, 1),
    )
    factories.TariffPeriodFactory(tariff=original, period_type=PeriodType.FLAT,
                                  price_chf_per_kwh=Decimal("0.25000"),
                                  months="1,2,3,10,11,12")
    factories.TariffPeriodFactory(tariff=original, period_type=PeriodType.FLAT,
                                  price_chf_per_kwh=Decimal("0.15000"),
                                  months="4,5,6,7,8,9")

    response = client.post(url(original, "new-version"), {"valid_from": "2027-01-01"}, format="json")

    created = Tariff.objects.get(pk=response.data["id"])
    assert {
        (period.months, period.price_chf_per_kwh) for period in created.periods.all()
    } == {
        ("1,2,3,10,11,12", Decimal("0.25000")),
        ("4,5,6,7,8,9", Decimal("0.15000")),
    }


def test_a_new_version_leaves_no_gap(owner_client):
    """Auto-closing removes the cause of the silently-unbilled month."""
    client, zev = owner_client
    original = energy_version(zev, valid_from="2026-01-01")

    client.post(url(original, "new-version"), {"valid_from": "2027-01-01"}, format="json")

    assert client.get(SERIES_URL).data[0]["gaps"] == []


def test_a_new_version_copies_the_price_bands(owner_client):
    """Prices live on TariffPeriod, so a copy without them would be free energy."""
    client, zev = owner_client
    original = factories.TariffFactory(
        zev=zev, name="Grid Energy", category=TariffCategory.ENERGY,
        billing_mode=BillingMode.ENERGY, energy_type=EnergyType.GRID,
        valid_from=date(2026, 1, 1),
    )
    factories.TariffPeriodFactory(tariff=original, period_type=PeriodType.HIGH,
                                  price_chf_per_kwh=Decimal("0.28000"),
                                  time_from="06:00", time_to="22:00")
    factories.TariffPeriodFactory(tariff=original, period_type=PeriodType.LOW,
                                  price_chf_per_kwh=Decimal("0.18000"),
                                  time_from="22:00", time_to="06:00")

    response = client.post(url(original, "new-version"), {"valid_from": "2027-01-01"}, format="json")

    created = Tariff.objects.get(pk=response.data["id"])
    copied = {period.period_type: period.price_chf_per_kwh for period in created.periods.all()}
    assert copied == {PeriodType.HIGH: Decimal("0.28000"), PeriodType.LOW: Decimal("0.18000")}
    assert created.periods.get(period_type=PeriodType.HIGH).time_from.hour == 6


def test_a_new_version_can_set_new_prices_in_one_call(owner_client):
    """A version almost always exists because the price changed, so requiring a
    second request to edit it would make the common case two steps."""
    client, zev = owner_client
    original = energy_version(zev, valid_from="2026-01-01", price="0.10000")

    response = client.post(
        url(original, "new-version"),
        {
            "valid_from": "2027-01-01",
            "periods": [{"period_type": PeriodType.FLAT, "price_chf_per_kwh": "0.12500"}],
        },
        format="json",
    )

    created = Tariff.objects.get(pk=response.data["id"])
    assert [p.price_chf_per_kwh for p in created.periods.all()] == [Decimal("0.12500")]
    # The source keeps its own price.
    assert [p.price_chf_per_kwh for p in original.periods.all()] == [Decimal("0.10000")]


def test_a_new_version_of_a_fixed_fee_can_override_the_amount(owner_client):
    client, zev = owner_client
    original = factories.TariffFactory(
        zev=zev, name="Metering Fee", category=TariffCategory.METERING,
        billing_mode=BillingMode.MONTHLY_FEE, energy_type=None,
        fixed_price_chf=Decimal("5.00"), valid_from=date(2026, 1, 1),
    )

    response = client.post(
        url(original, "new-version"),
        {"valid_from": "2027-01-01", "fixed_price_chf": "6.50"},
        format="json",
    )

    assert response.status_code == 201, response.data
    assert Tariff.objects.get(pk=response.data["id"]).fixed_price_chf == Decimal("6.50")


def test_inserting_a_version_mid_chain_bounds_it_against_the_successor(owner_client):
    client, zev = owner_client
    first = energy_version(zev, valid_from="2026-01-01", valid_to="2026-12-31")
    energy_version(zev, valid_from="2028-01-01")

    response = client.post(url(first, "new-version"), {"valid_from": "2027-01-01"}, format="json")

    assert response.status_code == 201, response.data
    assert response.data["valid_to"] == "2027-12-31"
    assert client.get(SERIES_URL).data[0]["gaps"] == []


def test_a_second_version_cannot_start_on_an_existing_start_date(owner_client):
    client, zev = owner_client
    original = energy_version(zev, valid_from="2026-01-01")

    response = client.post(url(original, "new-version"), {"valid_from": "2026-01-01"}, format="json")

    assert response.status_code == 400
    assert "already starts" in str(response.data["valid_from"])


def test_new_version_requires_a_date(owner_client):
    client, zev = owner_client
    original = energy_version(zev, valid_from="2026-01-01")

    response = client.post(url(original, "new-version"), {}, format="json")

    assert response.status_code == 400
    assert "valid_from" in response.data


def test_new_version_rejects_a_malformed_date(owner_client):
    client, zev = owner_client
    original = energy_version(zev, valid_from="2026-01-01")

    response = client.post(url(original, "new-version"), {"valid_from": "01.01.2027"}, format="json")

    assert response.status_code == 400
    assert "valid_from" in response.data


def test_new_version_is_refused_on_another_owners_tariff(owner_client):
    client, _ = owner_client
    foreign = energy_version(factories.ZevFactory(), valid_from="2026-01-01")

    response = client.post(url(foreign, "new-version"), {"valid_from": "2027-01-01"}, format="json")

    assert response.status_code == 404


def _shared_fee(zev, *, name="Lift Electricity", split_key):
    return factories.TariffFactory(
        zev=zev, name=name, category=TariffCategory.METERING,
        billing_mode=BillingMode.SHARED_MONTHLY_FEE, energy_type=None,
        fixed_price_chf=Decimal("80.00"), valid_from=date(2026, 1, 1),
        split_key=split_key,
    )


def test_a_new_version_preserves_weight_split_key(owner_client):
    """Without this copy, a weight-split shared fee silently reverts to
    headcount on every invoice issued under the new version."""
    client, zev = owner_client
    original = _shared_fee(zev, split_key=SplitKey.WEIGHT)

    response = client.post(url(original, "new-version"), {"valid_from": "2027-01-01"}, format="json")

    assert response.status_code == 201, response.data
    assert response.data["split_key"] == SplitKey.WEIGHT
    assert Tariff.objects.get(pk=response.data["id"]).split_key == SplitKey.WEIGHT


def test_a_new_version_preserves_equal_split_key(owner_client):
    client, zev = owner_client
    original = _shared_fee(zev, split_key=SplitKey.EQUAL)

    response = client.post(url(original, "new-version"), {"valid_from": "2027-01-01"}, format="json")

    assert response.status_code == 201, response.data
    assert response.data["split_key"] == SplitKey.EQUAL
    assert Tariff.objects.get(pk=response.data["id"]).split_key == SplitKey.EQUAL


# ---------------------------------------------------------------------------
# duplicate
# ---------------------------------------------------------------------------

def test_duplicate_creates_a_separate_series_without_touching_the_source(owner_client):
    client, zev = owner_client
    original = energy_version(zev, valid_from="2026-01-01", price="0.10000")

    response = client.post(url(original, "duplicate"), {"name": "Local Energy Reduced"}, format="json")

    assert response.status_code == 201, response.data
    original.refresh_from_db()
    assert original.valid_to is None  # timeline untouched
    copy = Tariff.objects.get(pk=response.data["id"])
    assert copy.name == "Local Energy Reduced"
    assert [p.price_chf_per_kwh for p in copy.periods.all()] == [Decimal("0.10000")]


def test_duplicate_requires_a_name(owner_client):
    client, zev = owner_client
    original = energy_version(zev, valid_from="2026-01-01")

    response = client.post(url(original, "duplicate"), {"name": "   "}, format="json")

    assert response.status_code == 400
    assert "name" in response.data


def test_duplicate_refuses_the_source_name(owner_client):
    """That request means "another version", which has its own endpoint and very
    different timeline semantics."""
    client, zev = owner_client
    original = energy_version(zev, valid_from="2026-01-01")

    response = client.post(url(original, "duplicate"), {"name": "Local Energy"}, format="json")

    assert response.status_code == 400
    assert "new-version" in str(response.data["name"])


def test_duplicate_preserves_weight_split_key(owner_client):
    client, zev = owner_client
    original = _shared_fee(zev, split_key=SplitKey.WEIGHT)

    response = client.post(url(original, "duplicate"), {"name": "Lift Electricity Copy"}, format="json")

    assert response.status_code == 201, response.data
    assert response.data["split_key"] == SplitKey.WEIGHT
    copy = Tariff.objects.get(pk=response.data["id"])
    assert copy.split_key == SplitKey.WEIGHT
    original.refresh_from_db()
    assert original.split_key == SplitKey.WEIGHT


def test_duplicate_preserves_equal_split_key(owner_client):
    client, zev = owner_client
    original = _shared_fee(zev, split_key=SplitKey.EQUAL)

    response = client.post(url(original, "duplicate"), {"name": "Lift Electricity Copy"}, format="json")

    assert response.status_code == 201, response.data
    assert response.data["split_key"] == SplitKey.EQUAL
    assert Tariff.objects.get(pk=response.data["id"]).split_key == SplitKey.EQUAL


# ---------------------------------------------------------------------------
# rename-series
# ---------------------------------------------------------------------------

def test_renaming_a_series_renames_every_version(owner_client):
    """The name is what groups versions, so renaming one would fork the chain."""
    client, zev = owner_client
    first = energy_version(zev, valid_from="2025-01-01", valid_to="2025-12-31")
    second = energy_version(zev, valid_from="2026-01-01")

    response = client.post(url(second, "rename-series"), {"name": "ZEV Solar"}, format="json")

    assert response.status_code == 200, response.data
    first.refresh_from_db()
    second.refresh_from_db()
    assert (first.name, second.name) == ("ZEV Solar", "ZEV Solar")
    assert client.get(SERIES_URL).data[0]["version_count"] == 2


def test_renaming_onto_an_existing_name_is_refused(owner_client):
    client, zev = owner_client
    energy_version(zev, name="Grid Energy", valid_from="2026-01-01", energy_type=EnergyType.GRID)
    local = energy_version(zev, name="Local Energy", valid_from="2026-01-01")

    response = client.post(url(local, "rename-series"), {"name": "Grid Energy"}, format="json")

    assert response.status_code == 400
    assert "already exists" in str(response.data["name"])


def test_renaming_to_the_same_name_is_a_no_op(owner_client):
    client, zev = owner_client
    original = energy_version(zev, valid_from="2026-01-01")

    response = client.post(url(original, "rename-series"), {"name": "Local Energy"}, format="json")

    assert response.status_code == 200
    assert Tariff.objects.filter(zev=zev, name="Local Energy").count() == 1


# ---------------------------------------------------------------------------
# Series coherence
# ---------------------------------------------------------------------------

def test_a_version_cannot_change_what_the_tariff_is(owner_client):
    """Versions sharing a name must agree on category/mode/energy type, or
    comparing them would compare a local rate against a grid fee."""
    client, zev = owner_client
    energy_version(zev, valid_from="2026-01-01", valid_to="2026-12-31")

    response = client.post(
        "/api/v1/tariffs/tariffs/",
        {
            "zev": str(zev.pk),
            "name": "Local Energy",
            "category": TariffCategory.GRID_FEES,
            "billing_mode": BillingMode.ENERGY,
            "energy_type": EnergyType.GRID,
            "valid_from": "2027-01-01",
        },
        format="json",
    )

    assert response.status_code == 400
    assert "category" in response.data or "energy_type" in response.data


def test_a_matching_new_version_is_accepted(owner_client):
    client, zev = owner_client
    energy_version(zev, valid_from="2026-01-01", valid_to="2026-12-31")

    response = client.post(
        "/api/v1/tariffs/tariffs/",
        {
            "zev": str(zev.pk),
            "name": "Local Energy",
            "category": TariffCategory.ENERGY,
            "billing_mode": BillingMode.ENERGY,
            "energy_type": EnergyType.LOCAL,
            "valid_from": "2027-01-01",
        },
        format="json",
    )

    assert response.status_code == 201, response.data
