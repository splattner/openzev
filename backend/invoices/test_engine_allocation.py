"""Characterization tests for how solar production is allocated between
participants.

``generate_invoice`` splits each consumer's reading into a "local" (solar) and
a "grid" part in proportion to their share of the ZEV's total consumption at
that timestamp::

    participant_share = participant_kwh / zev_consumption_at_ts
    local_pool        = min(zev_production_at_ts, zev_consumption_at_ts)
    r_local           = min(participant_kwh, local_pool * participant_share)
    r_grid            = participant_kwh - r_local

The producer side of this (``producer_share``) is exercised by
``test_producer_gets_local_revenue_and_feed_in_only_for_export_share`` in
``test_engine.py``, which uses two producers. The *consumer* side was not: every
other engine test has exactly one consumer holding a reading at any given
timestamp, which makes ``participant_share`` always exactly 1 and collapses the
formula to ``min(a, b)``. The proportional split — the part that decides who
pays for what — was therefore never executed with a share other than 1.

These tests pin it before the pricing engine is refactored.
"""

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from metering.models import MeterReading, ReadingDirection
from tariffs.models import EnergyType
from testing import factories
from zev.models import MeteringPointType

from .engine import generate_invoice

pytestmark = pytest.mark.django_db

PERIOD_START = date(2026, 1, 1)
PERIOD_END = date(2026, 1, 31)
T1 = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)
T2 = datetime(2026, 1, 16, 12, 0, tzinfo=timezone.utc)


class Community:
    """A ZEV with priced local/grid energy, plus helpers to add readings."""

    def __init__(self):
        self.zev = factories.ZevFactory()
        factories.flat_tariff(self.zev, energy_type=EnergyType.LOCAL, price="0.10000")
        factories.flat_tariff(self.zev, energy_type=EnergyType.GRID, price="0.20000")
        self.zev.refresh_from_db()

    def _participant(self, meter_type):
        participant = factories.ParticipantFactory(zev=self.zev, valid_from=PERIOD_START)
        assignment = factories.assignment_for(participant, meter_type=meter_type)
        return participant, assignment.metering_point

    def consumer(self, *readings):
        """Create a consumer with ``(timestamp, kwh)`` IN readings."""
        participant, metering_point = self._participant(MeteringPointType.CONSUMPTION)
        for timestamp, kwh in readings:
            MeterReading.objects.create(
                metering_point=metering_point, timestamp=timestamp,
                energy_kwh=Decimal(kwh), direction=ReadingDirection.IN,
            )
        return participant

    def producer(self, *readings):
        """Create a producer with ``(timestamp, kwh)`` OUT readings."""
        participant, metering_point = self._participant(MeteringPointType.PRODUCTION)
        for timestamp, kwh in readings:
            MeterReading.objects.create(
                metering_point=metering_point, timestamp=timestamp,
                energy_kwh=Decimal(kwh), direction=ReadingDirection.OUT,
            )
        return participant

    def invoice(self, participant):
        return generate_invoice(participant, PERIOD_START, PERIOD_END)


def _local_credit(invoice) -> Decimal:
    """Total of the negative local-energy lines a producer is credited with."""
    return sum(
        (item.total_chf for item in invoice.items.filter(item_type="local_energy")),
        Decimal("0"),
    )


def test_two_consumers_split_a_scarce_local_pool_in_proportion_to_demand():
    """6 kWh of solar against 8 kWh of demand: each consumer gets solar in
    proportion to their share of that demand, not first-come-first-served."""
    community = Community()
    community.producer((T1, "6"))
    big = community.consumer((T1, "6"))     # 6/8 of demand
    small = community.consumer((T1, "2"))   # 2/8 of demand

    big_invoice = community.invoice(big)
    small_invoice = community.invoice(small)

    assert big_invoice.total_local_kwh == Decimal("4.5000")
    assert big_invoice.total_grid_kwh == Decimal("1.5000")
    assert small_invoice.total_local_kwh == Decimal("1.5000")
    assert small_invoice.total_grid_kwh == Decimal("0.5000")


def test_the_local_allocation_across_consumers_adds_up_to_the_available_solar():
    """Nothing is conjured or lost: the sum of everyone's local share equals the
    pool, and the sum of everyone's grid share equals the shortfall."""
    community = Community()
    community.producer((T1, "6"))
    consumers = [community.consumer((T1, "6")), community.consumer((T1, "2"))]

    invoices = [community.invoice(consumer) for consumer in consumers]

    assert sum(inv.total_local_kwh for inv in invoices) == Decimal("6.0000")
    assert sum(inv.total_grid_kwh for inv in invoices) == Decimal("2.0000")


def test_when_solar_covers_all_demand_every_consumer_is_fully_local():
    """The ``min(participant_kwh, ...)`` clamp can only ever tie, never bite:
    the pool is capped at total consumption, so a participant's proportional
    share can never exceed their own reading."""
    community = Community()
    community.producer((T1, "10"))
    big = community.consumer((T1, "6"))
    small = community.consumer((T1, "2"))

    big_invoice = community.invoice(big)
    small_invoice = community.invoice(small)

    assert big_invoice.total_local_kwh == Decimal("6.0000")
    assert big_invoice.total_grid_kwh == Decimal("0.0000")
    assert small_invoice.total_local_kwh == Decimal("2.0000")
    assert small_invoice.total_grid_kwh == Decimal("0.0000")


def test_shares_are_recomputed_per_timestamp_not_over_the_period():
    """A consumer who draws nothing in an interval must not dilute the solar
    available to the others in that interval."""
    community = Community()
    community.producer((T1, "4"), (T2, "4"))
    both = community.consumer((T1, "4"), (T2, "4"))
    only_t1 = community.consumer((T1, "4"))

    both_invoice = community.invoice(both)
    only_t1_invoice = community.invoice(only_t1)

    # T1: pool 4 shared 50/50 -> 2 each. T2: pool 4, sole consumer -> 4.
    assert both_invoice.total_local_kwh == Decimal("6.0000")
    assert both_invoice.total_grid_kwh == Decimal("2.0000")
    assert only_t1_invoice.total_local_kwh == Decimal("2.0000")
    assert only_t1_invoice.total_grid_kwh == Decimal("2.0000")


def test_a_consumer_alone_in_an_interval_takes_the_whole_pool():
    community = Community()
    community.producer((T1, "3"))
    solo = community.consumer((T1, "10"))

    invoice = community.invoice(solo)

    assert invoice.total_local_kwh == Decimal("3.0000")
    assert invoice.total_grid_kwh == Decimal("7.0000")


def test_no_solar_in_an_interval_means_everything_is_grid():
    community = Community()
    community.producer((T2, "5"))  # produces, but not at T1
    consumer = community.consumer((T1, "4"))

    invoice = community.invoice(consumer)

    assert invoice.total_local_kwh == Decimal("0.0000")
    assert invoice.total_grid_kwh == Decimal("4.0000")


def test_an_indivisible_pool_leaves_a_rounding_remainder_unallocated():
    """Three equal consumers against 1 kWh of solar gives each 1/3, which does
    not terminate. Allocation does not force-balance to the pool, so the
    quantized shares sum to 0.9999 rather than 1.0000.

    Pinned as documented behaviour, not endorsed: the shortfall is 0.1 Wh per
    interval and lands on the grid side, where it is billed at the grid rate.
    """
    community = Community()
    community.producer((T1, "1"))
    consumers = [community.consumer((T1, "1")) for _ in range(3)]

    invoices = [community.invoice(consumer) for consumer in consumers]

    assert [inv.total_local_kwh for inv in invoices] == [Decimal("0.3333")] * 3
    assert sum(inv.total_local_kwh for inv in invoices) == Decimal("0.9999")
    assert sum(inv.total_grid_kwh for inv in invoices) == Decimal("2.0001")


def test_a_bidirectional_meter_is_counted_on_both_sides():
    """BIDIRECTIONAL points appear in the production *and* consumption
    querysets, so one participant can both feed the pool and draw from it."""
    community = Community()
    participant = factories.ParticipantFactory(zev=community.zev, valid_from=PERIOD_START)
    metering_point = factories.assignment_for(
        participant, meter_type=MeteringPointType.BIDIRECTIONAL
    ).metering_point
    MeterReading.objects.create(
        metering_point=metering_point, timestamp=T1,
        energy_kwh=Decimal("4"), direction=ReadingDirection.OUT,
    )
    MeterReading.objects.create(
        metering_point=metering_point, timestamp=T1,
        energy_kwh=Decimal("6"), direction=ReadingDirection.IN,
    )

    invoice = community.invoice(participant)

    assert invoice.total_local_kwh == Decimal("4.0000")
    assert invoice.total_grid_kwh == Decimal("2.0000")


def test_producers_split_both_the_local_pool_and_the_export_in_proportion():
    """Companion to the consumer-side tests: two producers, one consumer, so
    ``producer_share`` is 0.75/0.25 and both pools divide on it."""
    community = Community()
    factories.flat_tariff(community.zev, energy_type=EnergyType.FEED_IN, price="0.08000")
    big = community.producer((T1, "9"))
    small = community.producer((T1, "3"))
    community.consumer((T1, "4"))
    # production 12, consumption 4 -> local pool 4, export pool 8

    big_invoice = community.invoice(big)
    small_invoice = community.invoice(small)

    assert big_invoice.total_feed_in_kwh == Decimal("6.0000")
    assert small_invoice.total_feed_in_kwh == Decimal("2.0000")
    assert sum(inv.total_feed_in_kwh for inv in (big_invoice, small_invoice)) == Decimal("8.0000")

    # The local pool is capped at what the community actually consumed (4), not
    # at what was produced (12) — so the credits divide 3.0/1.0 kWh at 0.10,
    # never 9.0/3.0. Nothing on the consumer side can pin this: there the
    # per-participant min() already clamps a too-large pool away.
    assert _local_credit(big_invoice) == Decimal("-0.30")
    assert _local_credit(small_invoice) == Decimal("-0.10")
