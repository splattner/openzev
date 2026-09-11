"""Linking a tariff to a dynamic source through the ordinary tariff API.

``TariffSerializer`` declares no field list of its own (``fields = "__all__"``),
so ``dynamic_source`` is exposed and writable exactly like ``energy_type`` —
these confirm that holds, and that the model's own validation
(``Tariff._dynamic_source_errors``, added alongside the source model) still
surfaces as an ordinary 400 through this API rather than a 500.
"""

from datetime import date

import pytest

from accounts.models import UserRole
from tariffs.dynamic.models import DynamicTariffSource
from tariffs.models import BillingMode, EnergyType, Tariff, TariffCategory
from testing import factories
from testing.helpers import authenticate, make_user

pytestmark = pytest.mark.django_db


def make_source(**overrides) -> DynamicTariffSource:
    defaults = {
        "label": "Groupe E vario — grid", "url": "https://api.tariffs.groupe-e.ch/v2/tariffs",
        "api_version": "v1_0_5", "tariff_type": "grid", "tariff_name": "vario",
    }
    return DynamicTariffSource.objects.create(**{**defaults, **overrides})


class TestPickingASourceThroughTheTariffApi:
    def test_an_owner_can_create_a_tariff_linked_to_an_existing_source(self, api_client):
        owner = make_user("dyn_link_owner", UserRole.ZEV_OWNER)
        zev = factories.ZevFactory(owner=owner)
        source = make_source()
        authenticate(api_client, owner)

        response = api_client.post("/api/v1/tariffs/tariffs/", {
            "zev": str(zev.id), "name": "Grid (dynamic)", "category": TariffCategory.GRID_FEES,
            "billing_mode": BillingMode.ENERGY, "energy_type": EnergyType.GRID,
            "dynamic_source": str(source.pk), "valid_from": "2026-01-01",
        }, format="json")

        assert response.status_code == 201, response.data
        tariff = Tariff.objects.get(pk=response.data["id"])
        assert tariff.dynamic_source_id == source.pk

    def test_a_mismatched_energy_type_is_a_400_not_a_500(self, api_client):
        # The model checks this in full_clean(); TariffSerializer.create()
        # already converts that into a DRF ValidationError for every other
        # field, and must for this one too.
        owner = make_user("dyn_link_owner2", UserRole.ZEV_OWNER)
        zev = factories.ZevFactory(owner=owner)
        source = make_source()  # tariff_type=grid -> implies energy_type=grid
        authenticate(api_client, owner)

        response = api_client.post("/api/v1/tariffs/tariffs/", {
            "zev": str(zev.id), "name": "Local (mismatched)", "category": TariffCategory.ENERGY,
            "billing_mode": BillingMode.ENERGY, "energy_type": EnergyType.LOCAL,
            "dynamic_source": str(source.pk), "valid_from": "2026-01-01",
        }, format="json")

        assert response.status_code == 400
        assert "energy_type" in response.data

    def test_a_fee_tariff_cannot_be_linked_to_a_source(self, api_client):
        owner = make_user("dyn_link_owner3", UserRole.ZEV_OWNER)
        zev = factories.ZevFactory(owner=owner)
        source = make_source()
        authenticate(api_client, owner)

        response = api_client.post("/api/v1/tariffs/tariffs/", {
            "zev": str(zev.id), "name": "Monthly fee", "category": TariffCategory.GRID_FEES,
            "billing_mode": BillingMode.MONTHLY_FEE, "fixed_price_chf": "5.00",
            "dynamic_source": str(source.pk), "valid_from": "2026-01-01",
        }, format="json")

        assert response.status_code == 400
        assert "dynamic_source" in response.data

    def test_the_series_endpoint_carries_dynamic_source_on_each_version(self, api_client):
        owner = make_user("dyn_link_owner4", UserRole.ZEV_OWNER)
        zev = factories.ZevFactory(owner=owner)
        source = make_source()
        Tariff.objects.create(
            zev=zev, name="Grid (dynamic)", category=TariffCategory.GRID_FEES,
            billing_mode=BillingMode.ENERGY, energy_type=EnergyType.GRID,
            valid_from="2026-01-01", dynamic_source=source,
        )
        authenticate(api_client, owner)

        response = api_client.get(f"/api/v1/tariffs/tariffs/series/?zev_id={zev.id}")

        assert response.status_code == 200
        series = next(s for s in response.data if s["name"] == "Grid (dynamic)")
        assert str(series["versions"][0]["dynamic_source"]) == str(source.pk)


class TestPreservingTheEvidenceLink:
    """A tariff's ``dynamic_source`` link is the only thing that ties an
    issued invoice back to the fetched prices behind it (invoice items store
    rendered amounts, not a tariff FK). Deleting or repointing the link is a
    second door into the same evidence the source-level clear/delete guards
    protect, and it must be guarded the same way."""

    def _billed_dynamic_tariff(self, owner):
        zev = factories.ZevFactory(owner=owner)
        source = make_source()
        tariff = Tariff.objects.create(
            zev=zev, name="Grid (dynamic)", category=TariffCategory.GRID_FEES,
            billing_mode=BillingMode.ENERGY, energy_type=EnergyType.GRID,
            valid_from="2026-01-01", dynamic_source=source,
        )
        factories.InvoiceFactory(zev=zev, period_start="2026-01-01", period_end="2026-01-31")
        return zev, source, tariff

    def test_deleting_a_billed_dynamic_tariff_is_refused(self, api_client):
        owner = make_user("dyn_link_owner5", UserRole.ZEV_OWNER)
        _zev, _source, tariff = self._billed_dynamic_tariff(owner)
        authenticate(api_client, owner)

        response = api_client.delete(f"/api/v1/tariffs/tariffs/{tariff.pk}/")

        assert response.status_code == 400
        assert Tariff.objects.filter(pk=tariff.pk).exists()

    def test_repointing_a_billed_dynamic_tariff_is_refused(self, api_client):
        owner = make_user("dyn_link_owner6", UserRole.ZEV_OWNER)
        _zev, _source, tariff = self._billed_dynamic_tariff(owner)
        other_source = make_source(
            url="https://api.tariffs.groupe-e.ch/v2/tariffs", tariff_name="double",
        )
        authenticate(api_client, owner)

        response = api_client.patch(
            f"/api/v1/tariffs/tariffs/{tariff.pk}/",
            {"dynamic_source": str(other_source.pk)}, format="json",
        )

        assert response.status_code == 400
        assert "dynamic_source" in response.data
        tariff.refresh_from_db()
        assert tariff.dynamic_source_id != other_source.pk

    def test_clearing_a_billed_dynamic_tariffs_source_is_refused(self, api_client):
        # Unsetting it entirely (e.g. converting to a static tariff) loses
        # the link exactly as much as repointing it does.
        owner = make_user("dyn_link_owner7", UserRole.ZEV_OWNER)
        _zev, _source, tariff = self._billed_dynamic_tariff(owner)
        authenticate(api_client, owner)

        response = api_client.patch(
            f"/api/v1/tariffs/tariffs/{tariff.pk}/",
            {"dynamic_source": None}, format="json",
        )

        assert response.status_code == 400
        assert "dynamic_source" in response.data

    def test_an_unbilled_dynamic_tariff_can_still_be_deleted_and_repointed(self, api_client):
        # No invoice overlaps this one — nothing at risk, so both mutations
        # that are refused above must stay ordinary here.
        owner = make_user("dyn_link_owner8", UserRole.ZEV_OWNER)
        zev = factories.ZevFactory(owner=owner)
        source = make_source()
        other_source = make_source(
            url="https://api.tariffs.groupe-e.ch/v2/tariffs", tariff_name="double",
        )
        tariff = Tariff.objects.create(
            zev=zev, name="Grid (dynamic, unbilled)", category=TariffCategory.GRID_FEES,
            billing_mode=BillingMode.ENERGY, energy_type=EnergyType.GRID,
            valid_from="2026-01-01", dynamic_source=source,
        )
        authenticate(api_client, owner)

        response = api_client.patch(
            f"/api/v1/tariffs/tariffs/{tariff.pk}/",
            {"dynamic_source": str(other_source.pk)}, format="json",
        )
        assert response.status_code == 200, response.data

        delete_response = api_client.delete(f"/api/v1/tariffs/tariffs/{tariff.pk}/")
        assert delete_response.status_code == 204

    def test_setting_a_dynamic_source_for_the_first_time_is_unaffected(self, api_client):
        # There is no prior link to lose, billed or not.
        owner = make_user("dyn_link_owner9", UserRole.ZEV_OWNER)
        zev = factories.ZevFactory(owner=owner)
        source = make_source()
        tariff = factories.TariffFactory(
            zev=zev, category=TariffCategory.GRID_FEES, billing_mode=BillingMode.ENERGY,
            energy_type=EnergyType.GRID, valid_from=date(2026, 1, 1),
        )
        factories.InvoiceFactory(zev=zev, period_start="2026-01-01", period_end="2026-01-31")
        authenticate(api_client, owner)

        response = api_client.patch(
            f"/api/v1/tariffs/tariffs/{tariff.pk}/",
            {"dynamic_source": str(source.pk)}, format="json",
        )

        assert response.status_code == 200, response.data
