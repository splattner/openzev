"""API-level tests for the ZEV -> feasibility prefill endpoint."""
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from accounts.models import FeatureFlag
from tariffs.models import EnergyType, TariffCategory
from testing import factories
from testing.helpers import authenticate
from zev.models import MeteringPointType

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _feasibility_calculator_enabled():
    """See the identical fixture in ``test_views.py``: this module tests
    prefill *behaviour*, not the feature gate, and the gate defaults off."""
    FeatureFlag.objects.update_or_create(
        name=FeatureFlag.FEASIBILITY_CALCULATOR_ENABLED, defaults={"enabled": True}
    )


def _url(zev_id) -> str:
    return f"/api/v1/feasibility/prefill/{zev_id}/"


class TestFeasibilityPrefillAuth:
    def test_requires_authentication(self, api_client):
        zev = factories.ZevFactory()
        response = api_client.get(_url(zev.id))
        assert response.status_code == 401

    def test_participant_cannot_prefill(self, participant_client):
        zev = factories.ZevFactory()
        response = participant_client.get(_url(zev.id))
        assert response.status_code == 403

    def test_owner_of_a_different_zev_gets_not_found(self, owner_client):
        other_owner = factories.OwnerFactory()
        other_zev = factories.ZevFactory(owner=other_owner)
        response = owner_client.get(_url(other_zev.id))
        assert response.status_code == 404

    def test_unknown_zev_returns_not_found(self, owner_client):
        response = owner_client.get(_url("00000000-0000-0000-0000-000000000000"))
        assert response.status_code == 404

    def test_admin_can_prefill_any_zev(self, admin_client):
        other_owner = factories.OwnerFactory()
        zev = factories.ZevFactory(owner=other_owner)
        response = admin_client.get(_url(zev.id))
        assert response.status_code == 200


class TestFeasibilityPrefillHappyPath:
    def test_owner_prefills_their_own_zev(self):
        owner = factories.OwnerFactory()
        zev = factories.ZevFactory(owner=owner)
        participant = factories.ParticipantFactory(zev=zev)
        mp = factories.MeteringPointFactory(zev=zev, meter_type=MeteringPointType.CONSUMPTION)
        factories.MeteringPointAssignmentFactory(metering_point=mp, participant=participant)

        tariff = factories.TariffFactory(zev=zev, category=TariffCategory.ENERGY, energy_type=EnergyType.GRID)
        factories.TariffPeriodFactory(tariff=tariff, price_chf_per_kwh=Decimal("0.30000"))

        client = APIClient()
        authenticate(client, owner)
        response = client.get(_url(zev.id))

        assert response.status_code == 200
        body = response.json()
        assert len(body["participants"]) == 1
        assert body["participants"][0]["name"] == participant.full_name
        assert body["participants"][0]["has_metering_data"] is False
        assert body["retail_price_chf_per_kwh"] == "0.30000"
        assert body["feed_in_price_chf_per_kwh"] is None
        # No readings in this ZEV yet -> self-consumption rate cannot be measured.
        assert body["self_consumption_rate"] is None


class TestFeasibilityPrefillGate:
    def test_blocked_when_the_calculator_is_disabled(self, owner_client, zev):
        FeatureFlag.objects.filter(name=FeatureFlag.FEASIBILITY_CALCULATOR_ENABLED).update(enabled=False)
        response = owner_client.get(_url(zev.id))
        assert response.status_code == 403

    def test_disabled_check_runs_before_the_zev_lookup(self, owner_client):
        # A disabled calculator must not distinguish an accessible ZEV from a
        # nonexistent one — both are 403, not a 403/404 split that would leak
        # which ids exist to a caller who cannot use the feature at all.
        FeatureFlag.objects.filter(name=FeatureFlag.FEASIBILITY_CALCULATOR_ENABLED).update(enabled=False)
        response = owner_client.get(_url("00000000-0000-0000-0000-000000000000"))
        assert response.status_code == 403
