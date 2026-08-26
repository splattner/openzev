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

import logging
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from metering.models import MeterReading, ReadingDirection
from tariffs.models import EnergyType
from testing import factories
from zev.models import AllocationMode, MeteringPointType

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


def _transfer_consumer(community, *, valid_from_a, valid_to_a, valid_from_b, meter_type=MeteringPointType.CONSUMPTION):
    """A single metering point handed from participant A to participant B mid-period.

    Returns (participant_a, participant_b, metering_point).
    """
    participant_a = factories.ParticipantFactory(
        zev=community.zev, valid_from=PERIOD_START, valid_to=date(2026, 12, 31))
    participant_b = factories.ParticipantFactory(
        zev=community.zev, valid_from=valid_from_b, valid_to=date(2026, 12, 31))
    metering_point = factories.MeteringPointFactory(zev=community.zev, meter_type=meter_type)
    factories.MeteringPointAssignmentFactory(
        metering_point=metering_point, participant=participant_a,
        valid_from=valid_from_a, valid_to=valid_to_a)
    factories.MeteringPointAssignmentFactory(
        metering_point=metering_point, participant=participant_b,
        valid_from=valid_from_b, valid_to=None)
    return participant_a, participant_b, metering_point


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


# ─── Mid-period assignment transfers (ADR 0013) ───────────────────────────────


def test_a_mid_period_transfer_attributes_readings_to_each_holder():
    """A metering point handed over on January 16 bills the old holder for the
    first half and the new holder for the second half — readings are resolved
    against the assignment active at each reading's timestamp, not the period
    overlap."""
    community = Community()
    community.producer((T1, "10"), (T2, "10"))
    holder_a, holder_b, metering_point = _transfer_consumer(
        community, valid_from_a=PERIOD_START, valid_to_a=date(2026, 1, 15),
        valid_from_b=date(2026, 1, 16))
    MeterReading.objects.create(
        metering_point=metering_point, timestamp=T1,
        energy_kwh=Decimal("4"), direction=ReadingDirection.IN)
    MeterReading.objects.create(
        metering_point=metering_point, timestamp=T2,
        energy_kwh=Decimal("6"), direction=ReadingDirection.IN)

    a_invoice = community.invoice(holder_a)
    b_invoice = community.invoice(holder_b)

    # T1 (Jan 15) belongs to A, T2 (Jan 16) to B; solar covers both fully.
    assert a_invoice.total_local_kwh == Decimal("4.0000")
    assert a_invoice.total_grid_kwh == Decimal("0.0000")
    assert b_invoice.total_local_kwh == Decimal("6.0000")
    assert b_invoice.total_grid_kwh == Decimal("0.0000")

    # Golden franc values (local tariff 0.10 CHF/kWh, no fees, no VAT): the
    # transfer must move money, not just kWh. Holder A pays only for the
    # pre-transfer reading (4 kWh) and holder B only for the post-transfer one
    # (6 kWh). A regression to period-overlap attribution would bill holder A
    # for the whole meter and change these totals — the number a ZEV owner
    # actually phones about.
    assert a_invoice.total_chf == Decimal("0.40")
    assert b_invoice.total_chf == Decimal("0.60")


def test_a_reading_on_the_assignments_first_day_belongs_to_the_new_holder():
    """Assignment validity is date-granular: a reading at 00:30 on valid_from
    already belongs to the new holder."""
    community = Community()
    boundary = datetime(2026, 1, 16, 0, 30, tzinfo=timezone.utc)
    community.producer((boundary, "10"))
    holder_a, holder_b, metering_point = _transfer_consumer(
        community, valid_from_a=PERIOD_START, valid_to_a=date(2026, 1, 15),
        valid_from_b=date(2026, 1, 16))
    MeterReading.objects.create(
        metering_point=metering_point, timestamp=boundary,
        energy_kwh=Decimal("4"), direction=ReadingDirection.IN)

    assert community.invoice(holder_a).total_local_kwh == Decimal("0.0000")
    assert community.invoice(holder_b).total_local_kwh == Decimal("4.0000")


def test_readings_in_an_assignment_gap_are_billed_to_nobody():
    """Assignment A ends January 10, B starts January 20; the reading in between
    belongs to no participant and must not land on either invoice, while the
    community pool still counts it."""
    community = Community()
    community.producer((T1, "10"))
    jan5 = datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)
    community.producer((jan5, "10"))
    community.consumer((T1, "5"))  # keep the pool denominator honest at T1
    holder_a, holder_b, metering_point = _transfer_consumer(
        community, valid_from_a=PERIOD_START, valid_to_a=date(2026, 1, 10),
        valid_from_b=date(2026, 1, 20))
    for day in (date(2026, 1, 5), date(2026, 1, 15)):
        MeterReading.objects.create(
            metering_point=metering_point,
            timestamp=datetime(day.year, day.month, day.day, 12, 0, tzinfo=timezone.utc),
            energy_kwh=Decimal("2"), direction=ReadingDirection.IN)

    a_invoice = community.invoice(holder_a)
    b_invoice = community.invoice(holder_b)

    # Only the Jan 5 reading (2 kWh, fully local) is billed to A.
    assert a_invoice.total_local_kwh == Decimal("2.0000")
    assert a_invoice.total_grid_kwh == Decimal("0.0000")
    # The Jan 15 gap reading appears on neither invoice.
    assert b_invoice.total_local_kwh == Decimal("0.0000")
    assert b_invoice.total_grid_kwh == Decimal("0.0000")


def test_a_producer_transferred_mid_period_keeps_its_export_credit():
    """The production loop resolves the same way: a producer handing a metering
    point over mid-period only earns credit for output while it held it."""
    community = Community()
    community.consumer((T1, "5"), (T2, "5"))
    holder_a, holder_b, metering_point = _transfer_consumer(
        community, valid_from_a=PERIOD_START, valid_to_a=date(2026, 1, 15),
        valid_from_b=date(2026, 1, 16), meter_type=MeteringPointType.PRODUCTION)
    MeterReading.objects.create(
        metering_point=metering_point, timestamp=T1,
        energy_kwh=Decimal("3"), direction=ReadingDirection.OUT)
    MeterReading.objects.create(
        metering_point=metering_point, timestamp=T2,
        energy_kwh=Decimal("5"), direction=ReadingDirection.OUT)

    a_invoice = community.invoice(holder_a)
    b_invoice = community.invoice(holder_b)

    assert a_invoice.total_feed_in_kwh == Decimal("0.0000")
    assert a_invoice.total_local_kwh == Decimal("0.0000")
    # 3 kWh at T1 (covered by demand) sold locally by A.
    assert _local_credit(a_invoice) == Decimal("-0.30")
    assert b_invoice.total_feed_in_kwh == Decimal("0.0000")
    assert _local_credit(b_invoice) == Decimal("-0.50")


def test_gap_readings_on_community_meters_land_in_their_own_counters(caplog):
    """§4.3 'gap visibility' covers shared meters: a reading falling into a
    hole between two COMMUNITY windows of a meter the billed member does not
    hold increments the community counter (count + kWh), and the personal
    counters stay untouched."""
    community = Community()
    community.producer((T1, "10"))  # keeps the ZEV pool honest
    holder = factories.ParticipantFactory(zev=community.zev, valid_from=PERIOD_START)
    other_holder = factories.ParticipantFactory(
        zev=community.zev, valid_from=PERIOD_START)
    shared_meter = factories.MeteringPointFactory(
        zev=community.zev, meter_type=MeteringPointType.CONSUMPTION)
    factories.MeteringPointAssignmentFactory(
        metering_point=shared_meter, participant=holder,
        valid_from=date(2026, 1, 1), valid_to=date(2026, 1, 10),
        allocation_mode=AllocationMode.COMMUNITY)
    factories.MeteringPointAssignmentFactory(
        metering_point=shared_meter, participant=other_holder,
        valid_from=date(2026, 1, 20), valid_to=None,
        allocation_mode=AllocationMode.COMMUNITY)
    MeterReading.objects.create(
        metering_point=shared_meter,
        timestamp=datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc),
        energy_kwh=Decimal("2"), direction=ReadingDirection.IN)
    billed = factories.ParticipantFactory(zev=community.zev, valid_from=PERIOD_START)

    with caplog.at_level(logging.WARNING, logger="invoices.engine"):
        generate_invoice(billed, PERIOD_START, PERIOD_END)

    assert "0 personal consumption reading(s)" in caplog.text
    assert "1 community consumption reading(s) / 2.0000 kWh" in caplog.text
    assert "0 community production reading(s)" in caplog.text


def test_a_gap_reading_on_a_mixed_mode_meter_is_counted_only_once(caplog):
    """A meter held personally AND community-wide in the same period appears
    in both reading querysets; its gap readings must be counted exactly once
    (personal side wins), so the four counters partition the gaps (§4.3)."""
    community = Community()
    community.producer((T1, "10"))
    member = factories.ParticipantFactory(zev=community.zev, valid_from=PERIOD_START)
    shared_meter = factories.MeteringPointFactory(
        zev=community.zev, meter_type=MeteringPointType.CONSUMPTION)
    factories.MeteringPointAssignmentFactory(
        metering_point=shared_meter, participant=member,
        valid_from=date(2026, 1, 1), valid_to=date(2026, 1, 10),
        allocation_mode=AllocationMode.PERSONAL)
    factories.MeteringPointAssignmentFactory(
        metering_point=shared_meter, participant=member,
        valid_from=date(2026, 1, 20), valid_to=None,
        allocation_mode=AllocationMode.COMMUNITY)
    MeterReading.objects.create(
        metering_point=shared_meter,
        timestamp=datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc),
        energy_kwh=Decimal("2"), direction=ReadingDirection.IN)

    with caplog.at_level(logging.WARNING, logger="invoices.engine"):
        generate_invoice(member, PERIOD_START, PERIOD_END)

    assert "1 personal consumption reading(s) / 2.0000 kWh" in caplog.text
    assert "0 community consumption reading(s)" in caplog.text
