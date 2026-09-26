"""Time-of-use bands for percentage-of-energy tariffs.

See ``docs/specs/2026-09-percentage-tariff-bands.md``. A percentage tariff is
priced by the same ``TariffPeriod`` rows an energy tariff uses, keyed by
``percentage`` instead of ``price_chf_per_kwh``. The old single
``Tariff.percentage`` becomes one flat band (migration ``0018``), so an
existing tariff bills exactly as before.
"""
from datetime import date, datetime, time
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db import connection
from django.test import TestCase, TransactionTestCase
from rest_framework.test import APIClient

from tariffs.models import BillingMode, EnergyType, PeriodType, Tariff, TariffCategory, TariffPeriod
from tariffs.periods import average_percentage, resolve_band
from testing import factories
from testing.helpers import authenticate as auth

pytestmark = pytest.mark.django_db


def url(tariff, verb):
    return f"/api/v1/tariffs/tariffs/{tariff.pk}/{verb}/"


@pytest.fixture
def owner_client(db):
    owner = factories.OwnerFactory()
    zev = factories.ZevFactory(owner=owner)
    client = APIClient()
    auth(client, owner)
    return client, zev


# ---------------------------------------------------------------------------
# Model: TariffPeriod per-mode rules (§4.1)
# ---------------------------------------------------------------------------

class TariffPeriodModeRulesTests(TestCase):
    def setUp(self):
        self.owner = factories.OwnerFactory()
        self.zev = factories.ZevFactory(owner=self.owner)

    def _energy_tariff(self):
        return factories.TariffFactory(
            zev=self.zev, category=TariffCategory.ENERGY, billing_mode=BillingMode.ENERGY,
            energy_type=EnergyType.GRID, valid_from=date(2026, 1, 1),
        )

    def _percentage_tariff(self):
        return factories.TariffFactory(
            zev=self.zev, category=TariffCategory.LEVIES, billing_mode=BillingMode.PERCENTAGE_OF_ENERGY,
            energy_type=EnergyType.GRID, valid_from=date(2026, 1, 1),
        )

    def test_an_energy_band_without_a_price_is_rejected(self):
        tariff = self._energy_tariff()
        period = TariffPeriod(tariff=tariff, period_type=PeriodType.FLAT, price_chf_per_kwh=None)
        with self.assertRaises(ValidationError) as ctx:
            period.clean()
        self.assertIn("price_chf_per_kwh", ctx.exception.message_dict)

    def test_an_energy_band_with_a_percentage_is_rejected(self):
        tariff = self._energy_tariff()
        period = TariffPeriod(
            tariff=tariff, period_type=PeriodType.FLAT,
            price_chf_per_kwh=Decimal("0.20000"), percentage=Decimal("10.00"),
        )
        with self.assertRaises(ValidationError) as ctx:
            period.clean()
        self.assertIn("percentage", ctx.exception.message_dict)

    def test_a_percentage_band_without_a_percentage_is_rejected(self):
        tariff = self._percentage_tariff()
        period = TariffPeriod(tariff=tariff, period_type=PeriodType.FLAT, percentage=None)
        with self.assertRaises(ValidationError) as ctx:
            period.clean()
        self.assertIn("percentage", ctx.exception.message_dict)

    def test_a_percentage_band_with_a_price_is_rejected(self):
        tariff = self._percentage_tariff()
        period = TariffPeriod(
            tariff=tariff, period_type=PeriodType.FLAT,
            percentage=Decimal("10.00"), price_chf_per_kwh=Decimal("0.20000"),
        )
        with self.assertRaises(ValidationError) as ctx:
            period.clean()
        self.assertIn("price_chf_per_kwh", ctx.exception.message_dict)

    def test_the_db_constraint_rejects_both_null_bypassing_clean(self):
        tariff = self._energy_tariff()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                TariffPeriod.objects.create(
                    tariff=tariff, period_type=PeriodType.FLAT,
                    price_chf_per_kwh=None, percentage=None,
                )

    def test_the_db_constraint_rejects_both_set_bypassing_clean(self):
        tariff = self._percentage_tariff()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                TariffPeriod.objects.create(
                    tariff=tariff, period_type=PeriodType.FLAT,
                    price_chf_per_kwh=Decimal("0.20000"), percentage=Decimal("10.00"),
                )

    def test_a_negative_percentage_is_rejected(self):
        tariff = self._percentage_tariff()
        period = TariffPeriod(
            tariff=tariff, period_type=PeriodType.FLAT, percentage=Decimal("-5.00"),
        )
        with self.assertRaises(ValidationError) as ctx:
            period.full_clean()
        self.assertIn("percentage", ctx.exception.message_dict)

    def test_billing_mode_cannot_change_while_bands_exist(self):
        tariff = self._percentage_tariff()
        TariffPeriod.objects.create(
            tariff=tariff, period_type=PeriodType.FLAT, percentage=Decimal("10.00"),
        )
        tariff.billing_mode = BillingMode.ENERGY
        with self.assertRaises(ValidationError) as ctx:
            tariff.clean()
        self.assertIn("billing_mode", ctx.exception.message_dict)

    def test_billing_mode_can_change_once_bands_are_removed(self):
        tariff = self._percentage_tariff()
        period = TariffPeriod.objects.create(
            tariff=tariff, period_type=PeriodType.FLAT, percentage=Decimal("10.00"),
        )
        period.delete()
        tariff.billing_mode = BillingMode.ENERGY
        tariff.clean()  # does not raise


# ---------------------------------------------------------------------------
# Serializer (§5.5)
# ---------------------------------------------------------------------------

def test_a_band_can_be_created_on_a_percentage_tariff(owner_client):
    client, zev = owner_client
    tariff = factories.TariffFactory(
        zev=zev, billing_mode=BillingMode.PERCENTAGE_OF_ENERGY, energy_type=EnergyType.LOCAL,
        valid_from=date(2026, 1, 1),
    )

    response = client.post(
        "/api/v1/tariffs/periods/",
        {"tariff": str(tariff.id), "period_type": PeriodType.FLAT, "percentage": "60.00"},
        format="json",
    )

    assert response.status_code == 201, response.data
    assert response.data["percentage"] == "60.00"
    assert response.data["price_chf_per_kwh"] is None


def test_the_flat_beside_timed_rule_applies_to_percentage_tariffs(owner_client):
    client, zev = owner_client
    tariff = factories.TariffFactory(
        zev=zev, billing_mode=BillingMode.PERCENTAGE_OF_ENERGY, energy_type=EnergyType.LOCAL,
        valid_from=date(2026, 1, 1),
    )
    factories.TariffPeriodFactory(
        tariff=tariff, period_type=PeriodType.FLAT, price_chf_per_kwh=None, percentage=Decimal("60.00"),
    )

    response = client.post(
        "/api/v1/tariffs/periods/",
        {
            "tariff": str(tariff.id), "period_type": PeriodType.HIGH, "percentage": "90.00",
            "time_from": "10:00", "time_to": "16:00",
        },
        format="json",
    )

    assert response.status_code == 400
    assert "period_type" in response.data


def test_initial_percentage_creates_exactly_one_flat_band(owner_client):
    client, zev = owner_client

    response = client.post(
        "/api/v1/tariffs/tariffs/",
        {
            "zev": str(zev.id), "name": "Local Surcharge", "category": TariffCategory.LEVIES,
            "billing_mode": BillingMode.PERCENTAGE_OF_ENERGY, "energy_type": EnergyType.LOCAL,
            "initial_percentage": "42.00", "valid_from": "2026-01-01",
        },
        format="json",
    )

    assert response.status_code == 201, response.data
    tariff = Tariff.objects.get(pk=response.data["id"])
    periods = list(tariff.periods.all())
    assert len(periods) == 1
    assert periods[0].period_type == PeriodType.FLAT
    assert periods[0].percentage == Decimal("42.00")
    assert periods[0].price_chf_per_kwh is None


def test_a_percentage_tariff_without_initial_percentage_is_valid(owner_client):
    client, zev = owner_client

    response = client.post(
        "/api/v1/tariffs/tariffs/",
        {
            "zev": str(zev.id), "name": "Local Surcharge", "category": TariffCategory.LEVIES,
            "billing_mode": BillingMode.PERCENTAGE_OF_ENERGY, "energy_type": EnergyType.LOCAL,
            "valid_from": "2026-01-01",
        },
        format="json",
    )

    assert response.status_code == 201, response.data
    assert Tariff.objects.get(pk=response.data["id"]).periods.count() == 0


def test_initial_percentage_is_rejected_on_update(owner_client):
    client, zev = owner_client
    tariff = factories.TariffFactory(
        zev=zev, billing_mode=BillingMode.PERCENTAGE_OF_ENERGY, energy_type=EnergyType.LOCAL,
        valid_from=date(2026, 1, 1),
    )

    response = client.patch(
        f"/api/v1/tariffs/tariffs/{tariff.pk}/",
        {"initial_percentage": "10.00"},
        format="json",
    )

    assert response.status_code == 400
    assert "initial_percentage" in response.data


def test_initial_percentage_is_rejected_on_an_energy_tariff(owner_client):
    client, zev = owner_client

    response = client.post(
        "/api/v1/tariffs/tariffs/",
        {
            "zev": str(zev.id), "name": "Grid", "category": TariffCategory.ENERGY,
            "billing_mode": BillingMode.ENERGY, "energy_type": EnergyType.GRID,
            "initial_percentage": "10.00", "valid_from": "2026-01-01",
        },
        format="json",
    )

    assert response.status_code == 400
    assert "initial_percentage" in response.data


def test_initial_percentage_is_rejected_on_a_fee_tariff(owner_client):
    client, zev = owner_client

    response = client.post(
        "/api/v1/tariffs/tariffs/",
        {
            "zev": str(zev.id), "name": "Fee", "category": TariffCategory.METERING,
            "billing_mode": BillingMode.MONTHLY_FEE, "fixed_price_chf": "5.00",
            "initial_percentage": "10.00", "valid_from": "2026-01-01",
        },
        format="json",
    )

    assert response.status_code == 400
    assert "initial_percentage" in response.data


def test_percentage_is_gone_from_responses(owner_client):
    client, zev = owner_client
    tariff = factories.TariffFactory(
        zev=zev, billing_mode=BillingMode.PERCENTAGE_OF_ENERGY, energy_type=EnergyType.LOCAL,
        valid_from=date(2026, 1, 1),
    )

    response = client.get(f"/api/v1/tariffs/tariffs/{tariff.pk}/")

    assert response.status_code == 200
    assert "percentage" not in response.data


# ---------------------------------------------------------------------------
# new-version / duplicate (§5.5)
# ---------------------------------------------------------------------------

def test_new_version_copies_band_percentages(owner_client):
    client, zev = owner_client
    original = factories.TariffFactory(
        zev=zev, name="Local Surcharge", category=TariffCategory.LEVIES,
        billing_mode=BillingMode.PERCENTAGE_OF_ENERGY, energy_type=EnergyType.LOCAL,
        valid_from=date(2026, 1, 1),
    )
    factories.TariffPeriodFactory(
        tariff=original, period_type=PeriodType.HIGH, price_chf_per_kwh=None,
        percentage=Decimal("90.00"), time_from="10:00", time_to="16:00",
    )
    factories.TariffPeriodFactory(
        tariff=original, period_type=PeriodType.LOW, price_chf_per_kwh=None,
        percentage=Decimal("60.00"), time_from="16:00", time_to="10:00",
    )

    response = client.post(url(original, "new-version"), {"valid_from": "2027-01-01"}, format="json")

    assert response.status_code == 201, response.data
    created = Tariff.objects.get(pk=response.data["id"])
    copied = {p.period_type: p.percentage for p in created.periods.all()}
    assert copied == {PeriodType.HIGH: Decimal("90.00"), PeriodType.LOW: Decimal("60.00")}
    assert all(p.price_chf_per_kwh is None for p in created.periods.all())


def test_new_version_with_periods_overrides_band_percentages(owner_client):
    client, zev = owner_client
    original = factories.TariffFactory(
        zev=zev, name="Local Surcharge", category=TariffCategory.LEVIES,
        billing_mode=BillingMode.PERCENTAGE_OF_ENERGY, energy_type=EnergyType.LOCAL,
        valid_from=date(2026, 1, 1),
    )
    factories.TariffPeriodFactory(
        tariff=original, period_type=PeriodType.FLAT, price_chf_per_kwh=None,
        percentage=Decimal("60.00"),
    )

    response = client.post(
        url(original, "new-version"),
        {
            "valid_from": "2027-01-01",
            "periods": [{"period_type": PeriodType.FLAT, "percentage": "75.00"}],
        },
        format="json",
    )

    assert response.status_code == 201, response.data
    created = Tariff.objects.get(pk=response.data["id"])
    assert [p.percentage for p in created.periods.all()] == [Decimal("75.00")]
    # The source keeps its own percentage.
    assert [p.percentage for p in original.periods.all()] == [Decimal("60.00")]


def test_duplicate_copies_band_percentages(owner_client):
    client, zev = owner_client
    original = factories.TariffFactory(
        zev=zev, name="Local Surcharge", category=TariffCategory.LEVIES,
        billing_mode=BillingMode.PERCENTAGE_OF_ENERGY, energy_type=EnergyType.LOCAL,
        valid_from=date(2026, 1, 1),
    )
    factories.TariffPeriodFactory(
        tariff=original, period_type=PeriodType.FLAT, price_chf_per_kwh=None,
        percentage=Decimal("60.00"),
    )

    response = client.post(url(original, "duplicate"), {"name": "Local Surcharge Copy"}, format="json")

    assert response.status_code == 201, response.data
    copy = Tariff.objects.get(pk=response.data["id"])
    assert [p.percentage for p in copy.periods.all()] == [Decimal("60.00")]


# ---------------------------------------------------------------------------
# average_percentage / resolve_band (§5.4, §5.1)
# ---------------------------------------------------------------------------

class AveragePercentageTests(TestCase):
    def setUp(self):
        self.owner = factories.OwnerFactory()
        self.zev = factories.ZevFactory(owner=self.owner)

    def _tariff(self):
        return factories.TariffFactory(
            zev=self.zev, category=TariffCategory.LEVIES, billing_mode=BillingMode.PERCENTAGE_OF_ENERGY,
            energy_type=EnergyType.LOCAL, valid_from=date(2026, 1, 1),
        )

    def test_a_flat_band_gives_its_own_value(self):
        tariff = self._tariff()
        TariffPeriod.objects.create(tariff=tariff, period_type=PeriodType.FLAT, percentage=Decimal("42.00"))

        self.assertEqual(average_percentage(tariff), Decimal("42.00"))

    def test_a_tariff_without_bands_averages_to_zero(self):
        tariff = self._tariff()

        self.assertEqual(average_percentage(tariff), Decimal("0"))

    def test_a_time_weighted_average_across_two_bands(self):
        """60% for 10:00-16:00 (6h) and 90% otherwise (18h) over one day:
        (6 * 60 + 18 * 90) / 24 = 82.50.

        Band windows never wrap past midnight (matching §5.1's plain
        ``time_from <= t < time_to`` rule), so "otherwise" is two bands:
        00:00-10:00 and 16:00-23:59:59, both at 90%.
        """
        tariff = self._tariff()
        TariffPeriod.objects.create(
            tariff=tariff, period_type=PeriodType.LOW, percentage=Decimal("90.00"),
            time_from=time(0, 0), time_to=time(10, 0),
        )
        TariffPeriod.objects.create(
            tariff=tariff, period_type=PeriodType.HIGH, percentage=Decimal("60.00"),
            time_from=time(10, 0), time_to=time(16, 0),
        )
        TariffPeriod.objects.create(
            tariff=tariff, period_type=PeriodType.BAND, percentage=Decimal("90.00"),
            time_from=time(16, 0), time_to=time(23, 59, 59),
        )

        self.assertEqual(average_percentage(tariff), Decimal("82.50"))

    def test_resolve_band_matches_the_engines_own_rule(self):
        tariff = self._tariff()
        high = TariffPeriod.objects.create(
            tariff=tariff, period_type=PeriodType.HIGH, percentage=Decimal("60.00"),
            time_from=time(10, 0), time_to=time(16, 0),
        )
        evening = TariffPeriod.objects.create(
            tariff=tariff, period_type=PeriodType.BAND, percentage=Decimal("90.00"),
            time_from=time(16, 0), time_to=time(23, 59, 59),
        )
        periods = list(tariff.periods.all())

        self.assertEqual(resolve_band(periods, datetime(2026, 1, 15, 12, 0)).pk, high.pk)
        self.assertEqual(resolve_band(periods, datetime(2026, 1, 15, 20, 0)).pk, evening.pk)


# ---------------------------------------------------------------------------
# Migration 0018_percentage_bands
# ---------------------------------------------------------------------------

PREDECESSOR = ("tariffs", "0017_bfe_reference_price_api_version")
# The constraint and the RemoveField live in 0019, a separate transaction from
# 0018's RunPython — see the deviation note at the top of 0018's migration
# file. TARGET is the pair's final state.
TARGET = ("tariffs", "0019_percentage_bands_constraint")


def _migrate_to_latest():
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(executor.loader.graph.leaf_nodes())


class PercentageBandsMigrationTests(TransactionTestCase):
    """Drives the real migration against historical models, per the pattern in
    ``accounts/test_vat_rate_seed.py``."""

    def test_a_percentage_tariff_becomes_one_flat_band(self):
        # Only the `tariffs` app steps back; `accounts`/`zev` stay on their
        # real, currently-migrated schema, so the ZEV and its owner are built
        # through the live models (unaffected by this migration) and only the
        # `Tariff` row goes through the historical model, by zev_id rather
        # than by FK instance (the historical Zev model would otherwise
        # disagree with the physically-applied accounts/zev schema).
        owner = factories.OwnerFactory()
        zev = factories.ZevFactory(owner=owner)

        executor = MigrationExecutor(connection)
        executor.migrate([PREDECESSOR])
        self.addCleanup(_migrate_to_latest)
        HistoricalTariff = executor.loader.project_state([PREDECESSOR]).apps.get_model("tariffs", "Tariff")

        tariff = HistoricalTariff.objects.create(
            zev_id=zev.pk, name="Levy", category="levies", billing_mode="percentage_of_energy",
            energy_type="grid", percentage=Decimal("18.00"), valid_from=date(2026, 1, 1),
            split_key="equal",
        )
        no_percentage = HistoricalTariff.objects.create(
            zev_id=zev.pk, name="Levy without value", category="levies", billing_mode="percentage_of_energy",
            energy_type="local", percentage=None, valid_from=date(2026, 1, 1),
            split_key="equal",
        )

        executor.loader.build_graph()
        executor.migrate([TARGET])

        NewTariff = executor.loader.project_state([TARGET]).apps.get_model("tariffs", "Tariff")
        NewPeriod = executor.loader.project_state([TARGET]).apps.get_model("tariffs", "TariffPeriod")

        self.assertNotIn("percentage", [f.name for f in NewTariff._meta.get_fields()])
        migrated = NewPeriod.objects.get(tariff_id=tariff.pk)
        self.assertEqual(migrated.period_type, "flat")
        self.assertEqual(migrated.percentage, Decimal("18.00"))
        self.assertIsNone(migrated.price_chf_per_kwh)
        self.assertEqual(NewPeriod.objects.filter(tariff_id=no_percentage.pk).count(), 0)

    def test_tariff_percentage_field_is_gone(self):
        self.assertNotIn("percentage", [f.name for f in Tariff._meta.get_fields()])
