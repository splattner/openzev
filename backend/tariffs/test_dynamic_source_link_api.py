"""Linking a tariff to a dynamic source through the ordinary tariff API.

``TariffSerializer`` declares no field list of its own (``fields = "__all__"``),
so ``dynamic_source`` is exposed and writable exactly like ``energy_type`` —
these confirm that holds, and that the model's own validation
(``Tariff._dynamic_source_errors``, added alongside the source model) still
surfaces as an ordinary 400 through this API rather than a 500.
"""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

import pytest

from accounts.models import UserRole
from tariffs.dynamic.models import DynamicPricePoint, DynamicTariffSource
from tariffs.models import BillingMode, EnergyType, Tariff, TariffCategory, TariffPeriod
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
    def test_series_and_detail_return_the_same_historical_percentage_base(self, api_client):
        owner = make_user("percentage_owner", UserRole.ZEV_OWNER)
        zev = factories.ZevFactory(owner=owner)
        source = make_source()
        factories.TariffFactory(zev=zev, dynamic_source=source, energy_type="grid", valid_from=date(2026, 1, 1))
        percentage = factories.TariffFactory(
            zev=zev, name="Local", billing_mode="percentage_of_energy", energy_type="local",
            percentage=50, valid_from=date(2026, 1, 1), valid_to=date(2026, 6, 30),
        )
        for month, day, price in [(6, 30, "0.1"), (9, 12, "0.9")]:
            start = datetime(2026, month, day, tzinfo=timezone.utc)
            source.points.create(valid_from=start, valid_to=start + timedelta(minutes=15), price_chf_per_kwh=price)
        authenticate(api_client, owner)
        with patch("django.utils.timezone.localdate", return_value=date(2026, 9, 12)):
            series = api_client.get(f"/api/v1/tariffs/tariffs/series/?zev_id={zev.pk}")
            detail = api_client.get(f"/api/v1/tariffs/tariffs/{percentage.pk}/")
        assert series.status_code == detail.status_code == 200
        version = next(item for item in series.data if item["name"] == "Local")["versions"][0]
        assert version["percentage_base_summary"] == detail.data["percentage_base_summary"] == {
            "price_chf_per_kwh": "0.10000", "dynamic_status": "partial", "reference_date": "2026-06-30",
        }

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

    def test_linking_a_source_to_a_banded_tariff_is_refused(self, api_client):
        owner = make_user("dyn_link_owner_bands", UserRole.ZEV_OWNER)
        zev = factories.ZevFactory(owner=owner)
        source = make_source()
        tariff = factories.TariffFactory(
            zev=zev, category=TariffCategory.GRID_FEES,
            billing_mode=BillingMode.ENERGY, energy_type=EnergyType.GRID,
            valid_from=date(2026, 1, 1),
        )
        TariffPeriod.objects.create(
            tariff=tariff, period_type="flat", price_chf_per_kwh="0.10000",
        )
        authenticate(api_client, owner)

        response = api_client.patch(
            f"/api/v1/tariffs/tariffs/{tariff.pk}/",
            {"dynamic_source": str(source.pk)}, format="json",
        )

        assert response.status_code == 400
        assert "dynamic_source" in response.data
        tariff.refresh_from_db()
        assert tariff.dynamic_source_id is None
        assert tariff.periods.count() == 1

    def test_the_series_endpoint_carries_dynamic_source_on_each_version(self, api_client):
        owner = make_user("dyn_link_owner4", UserRole.ZEV_OWNER)
        zev = factories.ZevFactory(owner=owner)
        source = make_source()
        tariff = Tariff.objects.create(
            zev=zev, name="Grid (dynamic)", category=TariffCategory.GRID_FEES,
            billing_mode=BillingMode.ENERGY, energy_type=EnergyType.GRID,
            valid_from="2026-01-01", dynamic_source=source,
        )
        today = date.today()
        tariff.valid_from = today
        tariff.save(update_fields=["valid_from"])
        point_start = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)
        DynamicPricePoint.objects.create(
            source=source,
            valid_from=point_start,
            valid_to=point_start + timedelta(hours=1),
            price_chf_per_kwh=Decimal("0.20000"),
        )
        authenticate(api_client, owner)

        response = api_client.get(f"/api/v1/tariffs/tariffs/series/?zev_id={zev.id}")

        assert response.status_code == 200
        series = next(s for s in response.data if s["name"] == "Grid (dynamic)")
        assert str(series["versions"][0]["dynamic_source"]) == str(source.pk)
        assert series["versions"][0]["dynamic_price_summary"] == {
            "status": "partial",
            "average_chf_per_kwh": "0.20000",
            "reference_from": today.isoformat(),
            "reference_to": today.isoformat(),
        }


class TestPreservingTheEvidenceLink:
    """Conservative API workflow guards alongside frozen invoice provenance."""

    def _billed_dynamic_tariff(self, owner):
        zev = factories.ZevFactory(owner=owner)
        source = make_source()
        tariff = Tariff.objects.create(
            zev=zev, name="Grid (dynamic)", category=TariffCategory.GRID_FEES,
            billing_mode=BillingMode.ENERGY, energy_type=EnergyType.GRID,
            valid_from="2026-01-01", dynamic_source=source,
        )
        factories.InvoiceFactory(
            zev=zev,
            period_start="2026-01-01",
            period_end="2026-01-31",
            status="approved",
        )
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


class TestDynamicTariffVersioning:
    def test_duplicate_and_new_version_keep_dynamic_pricing_without_bands(self, api_client):
        owner = make_user("dyn_version_owner", UserRole.ZEV_OWNER)
        zev = factories.ZevFactory(owner=owner)
        source = make_source()
        tariff = Tariff.objects.create(
            zev=zev, name="Grid (dynamic)", category=TariffCategory.GRID_FEES,
            billing_mode=BillingMode.ENERGY, energy_type=EnergyType.GRID,
            valid_from=date(2026, 1, 1), dynamic_source=source,
        )
        authenticate(api_client, owner)

        duplicate = api_client.post(
            f"/api/v1/tariffs/tariffs/{tariff.pk}/duplicate/",
            {"name": "Grid copy", "valid_from": "2026-01-01"}, format="json",
        )
        assert duplicate.status_code == 201, duplicate.data
        duplicate_tariff = Tariff.objects.get(pk=duplicate.data["id"])
        assert duplicate_tariff.dynamic_source_id == source.pk
        assert duplicate_tariff.periods.count() == 0

        version = api_client.post(
            f"/api/v1/tariffs/tariffs/{tariff.pk}/new-version/",
            {"valid_from": "2027-01-01"}, format="json",
        )
        assert version.status_code == 201, version.data
        new_version = Tariff.objects.get(pk=version.data["id"])
        assert new_version.dynamic_source_id == source.pk
        assert new_version.periods.count() == 0
