"""Unit tests for ``TariffResolver`` and ``ItemAccumulator``.

Both were closures inside ``generate_invoice``, capturing mutable state that
nothing outside the function could reach. As objects their behaviour can be
stated directly — in particular the two properties the caller silently depends
on: that the resolver's memoisation is keyed on day as well as energy type, and
that the accumulator preserves first-seen order, which the caller's stable sort
uses to break ties between lines from the same tariff.
"""

from datetime import date
from decimal import Decimal

import pytest

from tariffs.models import BillingMode, EnergyType, TariffCategory
from testing import factories

from .engine import ItemAccumulator, TariffResolver

pytestmark = pytest.mark.django_db

JAN = date(2026, 1, 15)
JUN = date(2026, 6, 15)


def energy_tariff(zev, *, energy_type=EnergyType.GRID, valid_from=date(2026, 1, 1), valid_to=None):
    return factories.TariffFactory(
        zev=zev, category=TariffCategory.ENERGY, billing_mode=BillingMode.ENERGY,
        energy_type=energy_type, valid_from=valid_from, valid_to=valid_to,
    )


def percentage_tariff(zev, *, percentage="25", energy_type=EnergyType.LOCAL):
    tariff = factories.TariffFactory(
        zev=zev, category=TariffCategory.LEVIES,
        billing_mode=BillingMode.PERCENTAGE_OF_ENERGY,
        energy_type=energy_type, valid_from=date(2026, 1, 1),
    )
    tariff.percentage = Decimal(percentage) if percentage is not None else None
    tariff.save()
    return tariff


# ---------------------------------------------------------------------------
# TariffResolver
# ---------------------------------------------------------------------------

def test_energy_and_percentage_tariffs_land_in_separate_buckets():
    zev = factories.ZevFactory()
    energy = energy_tariff(zev, energy_type=EnergyType.LOCAL)
    percentage = percentage_tariff(zev, energy_type=EnergyType.LOCAL)

    resolver = TariffResolver([energy, percentage])

    assert resolver.energy(EnergyType.LOCAL, JAN) == [energy]
    assert resolver.percentage(EnergyType.LOCAL, JAN) == [percentage]


def test_tariffs_are_separated_by_energy_type():
    zev = factories.ZevFactory()
    local = energy_tariff(zev, energy_type=EnergyType.LOCAL)
    grid = energy_tariff(zev, energy_type=EnergyType.GRID)

    resolver = TariffResolver([local, grid])

    assert resolver.energy(EnergyType.LOCAL, JAN) == [local]
    assert resolver.energy(EnergyType.GRID, JAN) == [grid]
    assert resolver.energy(EnergyType.FEED_IN, JAN) == []


def test_validity_is_evaluated_per_day_not_once():
    """The cache is keyed on the day too. Getting this wrong would price a
    whole period at whatever tariffs happened to be live on the first day."""
    zev = factories.ZevFactory()
    expiring = energy_tariff(zev, valid_to=date(2026, 3, 31))
    later = energy_tariff(zev, valid_from=date(2026, 4, 1))

    resolver = TariffResolver([expiring, later])

    assert resolver.energy(EnergyType.GRID, JAN) == [expiring]
    assert resolver.energy(EnergyType.GRID, JUN) == [later]


def test_repeated_lookups_return_the_same_answer():
    zev = factories.ZevFactory()
    tariff = energy_tariff(zev)

    resolver = TariffResolver([tariff])

    assert resolver.energy(EnergyType.GRID, JAN) == [tariff]
    assert resolver.energy(EnergyType.GRID, JAN) == [tariff]


def test_a_percentage_tariff_without_a_percentage_is_ignored():
    """A half-configured surcharge would otherwise price everything at zero."""
    zev = factories.ZevFactory()
    unconfigured = percentage_tariff(zev, percentage=None)

    resolver = TariffResolver([unconfigured])

    assert resolver.percentage(EnergyType.LOCAL, JAN) == []


@pytest.mark.parametrize("billing_mode", [
    BillingMode.MONTHLY_FEE,
    BillingMode.YEARLY_FEE,
    BillingMode.PER_METERING_POINT_MONTHLY_FEE,
    BillingMode.PER_METERING_POINT_YEARLY_FEE,
    BillingMode.SHARED_MONTHLY_FEE,
    BillingMode.SHARED_YEARLY_FEE,
])
def test_fixed_fee_tariffs_are_not_bucketed_at_all(billing_mode):
    """They are billed once per period, not per reading, so the per-reading
    loops must never see them."""
    zev = factories.ZevFactory()
    fee = factories.TariffFactory(
        zev=zev, category=TariffCategory.METERING, billing_mode=billing_mode,
        fixed_price_chf=Decimal("5.00"), valid_from=date(2026, 1, 1),
    )

    resolver = TariffResolver([fee])

    assert resolver.energy(fee.energy_type, JAN) == []
    assert resolver.percentage(fee.energy_type, JAN) == []


def test_an_empty_tariff_list_resolves_to_nothing():
    resolver = TariffResolver([])

    assert resolver.energy(EnergyType.GRID, JAN) == []
    assert resolver.percentage(EnergyType.LOCAL, JAN) == []


# ---------------------------------------------------------------------------
# ItemAccumulator
# ---------------------------------------------------------------------------

def test_repeated_adds_for_one_tariff_accumulate_into_a_single_entry():
    zev = factories.ZevFactory()
    tariff = energy_tariff(zev)
    accumulator = ItemAccumulator()

    accumulator.add(tariff=tariff, quantity=Decimal("2"), total=Decimal("0.40"), unit="kWh")
    accumulator.add(tariff=tariff, quantity=Decimal("3"), total=Decimal("0.60"), unit="kWh")

    entry, = list(accumulator)
    assert entry["quantity"] == Decimal("5")
    assert entry["total"] == Decimal("1.00")


def test_buckets_keep_a_charge_and_a_credit_apart():
    """A bidirectional participant is billed and credited under one tariff."""
    zev = factories.ZevFactory()
    tariff = energy_tariff(zev, energy_type=EnergyType.LOCAL)
    accumulator = ItemAccumulator()

    accumulator.add(tariff=tariff, quantity=Decimal("6"), total=Decimal("0.78"), unit="kWh")
    accumulator.add(tariff=tariff, quantity=Decimal("3"), total=Decimal("-0.39"), unit="kWh",
                    bucket="producer_credit")

    assert len(accumulator) == 2
    assert [entry["total"] for entry in accumulator] == [Decimal("0.78"), Decimal("-0.39")]


def test_different_tariffs_never_share_an_entry():
    zev = factories.ZevFactory()
    accumulator = ItemAccumulator()

    for energy_type in (EnergyType.LOCAL, EnergyType.GRID):
        accumulator.add(tariff=energy_tariff(zev, energy_type=energy_type),
                        quantity=Decimal("1"), total=Decimal("0.2"), unit="kWh")

    assert len(accumulator) == 2


def test_entries_come_back_in_first_seen_order():
    """The caller sorts these with a stable sort and relies on this order to
    break ties between lines that are otherwise indistinguishable."""
    zev = factories.ZevFactory()
    first = energy_tariff(zev, energy_type=EnergyType.LOCAL)
    second = energy_tariff(zev, energy_type=EnergyType.GRID)
    accumulator = ItemAccumulator()

    accumulator.add(tariff=second, quantity=Decimal("1"), total=Decimal("1"), unit="kWh")
    accumulator.add(tariff=first, quantity=Decimal("1"), total=Decimal("2"), unit="kWh")
    accumulator.add(tariff=second, quantity=Decimal("1"), total=Decimal("3"), unit="kWh")

    assert [entry["tariff"] for entry in accumulator] == [second, first]


def test_a_wholly_empty_add_is_dropped():
    """Keeps zero-value lines off the invoice."""
    zev = factories.ZevFactory()
    accumulator = ItemAccumulator()

    accumulator.add(tariff=energy_tariff(zev), quantity=Decimal("0"), total=Decimal("0"), unit="kWh")

    assert len(accumulator) == 0


def test_a_zero_quantity_carrying_a_total_is_kept():
    """A fee can be charged without a metered quantity behind it."""
    zev = factories.ZevFactory()
    accumulator = ItemAccumulator()

    accumulator.add(tariff=energy_tariff(zev), quantity=Decimal("0"), total=Decimal("5"), unit="month")

    assert len(accumulator) == 1


def test_base_total_accumulates_only_when_supplied():
    """Percentage tariffs carry the grid rate they were derived from; energy
    tariffs pass nothing and must not be given a spurious base."""
    zev = factories.ZevFactory()
    tariff = percentage_tariff(zev)
    accumulator = ItemAccumulator()

    accumulator.add(tariff=tariff, quantity=Decimal("2"), total=Decimal("0.1"), unit="kWh",
                    base_total=Decimal("0.4"))
    accumulator.add(tariff=tariff, quantity=Decimal("2"), total=Decimal("0.1"), unit="kWh")

    entry, = list(accumulator)
    assert entry["base_total"] == Decimal("0.4")
    assert entry["quantity"] == Decimal("4")


def test_the_unit_of_the_first_add_wins():
    zev = factories.ZevFactory()
    tariff = energy_tariff(zev)
    accumulator = ItemAccumulator()

    accumulator.add(tariff=tariff, quantity=Decimal("1"), total=Decimal("1"), unit="kWh")
    accumulator.add(tariff=tariff, quantity=Decimal("1"), total=Decimal("1"), unit="month")

    entry, = list(accumulator)
    assert entry["unit"] == "kWh"
