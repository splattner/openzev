"""Unit tests for the shared allocation service (ADR 0013).

``split_consumption`` and ``split_production`` decide how a community's solar
output is divided between its members. They were previously inline in
``generate_invoice`` and reachable only by building a ZEV, participants,
metering points, assignments, readings and tariffs — which is why the awkward
cases below had no coverage at all.

The end-to-end behaviour is pinned separately in
``invoices/test_engine_allocation.py``; these are the same rules stated as
arithmetic.
"""

import datetime
from decimal import Decimal

import pytest

from allocation.errors import (
    AllocationError,
    InvalidAllocationInputError,
    OverlappingAssignmentWindowsError,
)
from allocation.split import (
    local_pool_kwh,
    proportional_share,
    split_consumption,
    split_production,
)
from allocation.windows import AssignmentWindows


def D(value) -> Decimal:
    return Decimal(str(value))


# ---------------------------------------------------------------------------
# split_consumption
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("participant", "zev_consumption", "zev_production", "local", "grid"),
    [
        # Scarce pool: 6 kWh of solar shared across 8 kWh of demand.
        ("6", "8", "6", "4.5", "1.5"),
        ("2", "8", "6", "1.5", "0.5"),
        # Solar covers demand exactly -> everything local.
        ("6", "8", "8", "6", "0"),
        # Surplus solar: pool is capped at consumption, so still fully local.
        ("6", "8", "50", "6", "0"),
        # No solar at all.
        ("5", "5", "0", "0", "5"),
        # Solar exists but nobody is consuming (the caller's own reading is 0).
        ("0", "0", "10", "0", "0"),
        # Sole consumer takes the whole pool and grids the rest.
        ("10", "10", "3", "3", "7"),
    ],
)
def test_split_consumption_table(participant, zev_consumption, zev_production, local, grid):
    result = split_consumption(D(participant), D(zev_consumption), D(zev_production))

    assert result.local_kwh == D(local)
    assert result.grid_kwh == D(grid)


def test_local_and_grid_always_reconstruct_the_reading():
    """Exact by construction: grid is *defined* as the remainder after local,
    so no multiplication rounding can creep between them."""
    for participant, consumption, production in (
        ("7.3", "11.6", "4.2"), ("0.4", "0.4", "9"), ("15", "15", "0"), ("2.5", "9", "9"),
    ):
        result = split_consumption(D(participant), D(consumption), D(production))

        assert result.local_kwh + result.grid_kwh == D(participant)


def test_a_share_is_never_more_than_the_participants_own_draw():
    """The guard against an inconsistent caller: a pool larger than total
    consumption must not hand somebody more solar than they actually used."""
    result = split_consumption(D("2"), D("4"), D("999"))

    assert result.local_kwh == D("2")
    assert result.grid_kwh == D("0")


def test_zero_consumption_is_not_a_division_by_zero():
    assert split_consumption(D("0"), D("0"), D("0")) == (D("0"), D("0"))


@pytest.mark.parametrize(
    ("participant", "zev_consumption", "zev_production"),
    [
        ("-1", "10", "5"),
        ("5", "-1", "5"),
        ("5", "10", "-1"),
    ],
)
def test_split_consumption_rejects_negative_inputs(participant, zev_consumption, zev_production):
    with pytest.raises(ValueError, match="non-negative"):
        split_consumption(D(participant), D(zev_consumption), D(zev_production))


def test_split_consumption_rejects_a_draw_larger_than_the_community_total():
    """The ZEV total includes the participant's own reading, so a draw above
    it can only mean duplicate readings or the wrong metering-point scope."""
    with pytest.raises(ValueError, match="exceeds"):
        split_consumption(D("11"), D("10"), D("5"))


def test_decimal_arithmetic_is_exact_where_floats_would_drift():
    """The billing contract is Decimal end to end: a third-share that a float
    path would round to 16 digits stays exact to the 28-digit context, and
    the grid remainder reconstructs the draw exactly (a float path cannot
    reproduce 0.1 + 0.2 == 0.3-style identities)."""
    local, grid = split_consumption(D("0.1"), D("0.3"), D("0.1"))
    assert local == D("0.03333333333333333333333333333")
    assert grid == D("0.06666666666666666666666666667")
    assert local + grid == D("0.1")


def test_an_indivisible_pool_leaves_a_remainder_on_the_grid_side():
    """Three equal consumers against 1 kWh: each share is 1/3, which does not
    terminate, so the local parts do not sum back to the pool. The shortfall
    stays on the grid side rather than being silently absorbed."""
    shares = [split_consumption(D("1"), D("3"), D("1")) for _ in range(3)]

    total_local = sum((s.local_kwh for s in shares), Decimal("0"))
    assert total_local < D("1")
    assert D("1") - total_local < D("0.000000000000000000000000001")


# ---------------------------------------------------------------------------
# split_production
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("produced", "zev_production", "zev_consumption", "local_sold", "exported"),
    [
        # Two producers (9 and 3) against 4 kWh of demand: pool 4, export 8.
        ("9", "12", "4", "3", "6"),
        ("3", "12", "4", "1", "2"),
        # Demand exceeds production -> everything is sold locally, nothing exported.
        ("6", "6", "10", "6", "0"),
        # Nobody consuming -> all of it is exported.
        ("5", "5", "0", "0", "5"),
        # Producer contributed nothing.
        ("0", "10", "4", "0", "0"),
    ],
)
def test_split_production_table(produced, zev_production, zev_consumption, local_sold, exported):
    result = split_production(D(produced), D(zev_production), D(zev_consumption))

    assert result.local_sold_kwh == D(local_sold)
    assert result.exported_kwh == D(exported)


def test_no_production_is_not_a_division_by_zero():
    assert split_production(D("0"), D("0"), D("5")) == (D("0"), D("0"))


@pytest.mark.parametrize(
    ("produced", "zev_production", "zev_consumption"),
    [
        ("-1", "10", "5"),
        ("5", "-1", "5"),
        ("5", "10", "-1"),
    ],
)
def test_split_production_rejects_negative_inputs(produced, zev_production, zev_consumption):
    with pytest.raises(ValueError, match="non-negative"):
        split_production(D(produced), D(zev_production), D(zev_consumption))


def test_split_production_rejects_output_larger_than_the_community_total():
    with pytest.raises(ValueError, match="exceeds"):
        split_production(D("11"), D("10"), D("5"))


def test_local_sold_is_capped_by_what_the_community_consumed():
    """Not by what was produced — this is the cap that is invisible from the
    consumer side, where the per-participant clamp hides it."""
    result = split_production(D("12"), D("12"), D("4"))

    assert result.local_sold_kwh == D("4")
    assert result.exported_kwh == D("8")


def test_the_two_pools_reconstruct_the_producers_output_when_the_share_is_exact():
    for produced, production, consumption in (
        ("9", "12", "4"), ("0.1", "10", "10"), ("5", "5", "0"),
    ):
        result = split_production(D(produced), D(production), D(consumption))

        assert result.local_sold_kwh + result.exported_kwh == D(produced)


def test_a_recurring_share_reconstructs_only_to_within_decimal_precision():
    """Unlike the consumption split — where grid is *defined* as the remainder
    and so reconstruction is exact by construction — both production pools are
    computed by multiplying a share. When that share does not terminate, the
    two parts sum to slightly less than the producer's output.

    Asserted with a tolerance rather than exact equality, because exact
    equality here holds only for inputs that happen to round favourably, and a
    test that passes by luck is worse than no test.
    """
    for produced, production, consumption in (("1", "3", "1"), ("7.3", "11.6", "4.2")):
        result = split_production(D(produced), D(production), D(consumption))
        total = result.local_sold_kwh + result.exported_kwh

        assert total != D(produced)
        assert abs(total - D(produced)) < D("1e-26")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def test_local_pool_kwh_is_the_lesser_of_production_and_consumption():
    assert local_pool_kwh(D("5"), D("3")) == D("3")
    assert local_pool_kwh(D("0"), D("3")) == D("0")
    assert local_pool_kwh(D("9"), D("9")) == D("9")


def test_split_consumption_rejects_non_decimal_inputs():
    """The chart paths were the only float callers; with them on Decimal, the
    billing contract is Decimal end to end and other types are rejected."""
    with pytest.raises(TypeError, match="must be a Decimal"):
        split_consumption(4.0, 10.0, 6.0)
    with pytest.raises(TypeError, match="must be a Decimal"):
        split_consumption(D("4"), 10, D("6"))


def test_local_pool_kwh_and_proportional_share_reject_negatives():
    with pytest.raises(ValueError, match="non-negative"):
        local_pool_kwh(D("-1"), D("5"))
    with pytest.raises(ValueError, match="non-negative"):
        local_pool_kwh(D("5"), D("-1"))
    with pytest.raises(ValueError, match="non-negative"):
        proportional_share(D("100"), D("-10"), D("50"))
    with pytest.raises(TypeError, match="must be a Decimal"):
        local_pool_kwh(5.0, D("5"))


def test_conservation_invariants_hold_across_participants():
    """The energy a community hands out never exceeds what it has, and the
    two sides of the allocation reconcile exactly: what consumers take locally
    is what producers sold locally, per timestamp."""
    consumers = [(D("4"), D("7"), D("2")), (D("3"), D("7"), D("2"))]  # (draw, zev_cons, zev_prod)
    producers = [(D("1"), D("2"), D("7")), (D("1"), D("2"), D("7"))]  # (output, zev_prod, zev_cons)

    consumer_local = D("0")
    for draw, zev_cons, zev_prod in consumers:
        local, grid = split_consumption(draw, zev_cons, zev_prod)
        consumer_local += local
        assert local + grid == draw

    producer_sold = D("0")
    for output, zev_prod, zev_cons in producers:
        sold, exported = split_production(output, zev_prod, zev_cons)
        producer_sold += sold

    pool = D("2")  # min(zev_cons, zev_prod) at the shared timestamp
    assert consumer_local == pool
    assert producer_sold == pool


def test_proportional_share_is_zero_for_an_empty_denominator():
    assert proportional_share(D("100"), D("10"), D("0")) == D("0")
    assert proportional_share(D("0"), D("10"), D("50")) == D("0")


def test_proportional_share_splits_a_pool_by_demand():
    assert proportional_share(D("100"), D("25"), D("100")) == D("25")
    assert proportional_share(D("50"), D("30"), D("90")) == D("50") * (D("30") / D("90"))


def test_proportional_share_rejects_non_decimal_total():
    """The Decimal-only contract covers every parameter, including the
    denominator that is only used in a division."""
    with pytest.raises(TypeError, match="must be a Decimal"):
        proportional_share(D("100"), D("10"), 50.0)


def test_proportional_share_rejects_participant_above_total():
    """The total includes the participant, so exceeding it indicates
    inconsistent inputs — same contract as split_consumption."""
    with pytest.raises(ValueError, match="exceeds"):
        proportional_share(D("100"), D("60"), D("50"))


# ---------------------------------------------------------------------------
# AssignmentWindows
# ---------------------------------------------------------------------------

TS = datetime.datetime(2026, 6, 20, 12, 0, tzinfo=datetime.timezone.utc)


def test_participant_at_resolves_the_holder_on_the_boundary_day():
    """Assignment validity is date-granular: a reading at 00:30 on the day an
    assignment starts already belongs to the new holder."""
    windows = AssignmentWindows([
        ("mp1", datetime.date(2026, 6, 1), datetime.date(2026, 6, 15), 11),
        ("mp1", datetime.date(2026, 6, 16), None, 22),
    ])

    assert windows.participant_at("mp1", TS.replace(month=6, day=15, hour=23)) == 11
    assert windows.participant_at("mp1", TS.replace(month=6, day=16, hour=0)) == 22


def test_gap_readings_resolve_to_no_participant():
    windows = AssignmentWindows([
        ("mp1", datetime.date(2026, 6, 1), datetime.date(2026, 6, 15), 11),
        ("mp1", datetime.date(2026, 7, 1), None, 22),
    ])

    assert windows.participant_at("mp1", TS.replace(month=6, day=20)) is None


def test_open_ended_assignment_covers_everything_after_valid_from():
    windows = AssignmentWindows([("mp1", datetime.date(2026, 6, 1), None, 11)])

    assert windows.participant_at("mp1", TS) == 11


def test_unknown_metering_point_has_no_holder():
    windows = AssignmentWindows([("mp1", datetime.date(2026, 6, 1), None, 11)])

    assert windows.participant_at("mp9", TS) is None


def test_is_held_by_matches_only_the_current_holder():
    """``is_held_by`` is the billing eligibility check: true only for the
    participant holding the metering point at the reading's timestamp, false
    for any other participant, for gap readings, and for unknown points."""
    windows = AssignmentWindows([
        ("mp1", datetime.date(2026, 6, 1), datetime.date(2026, 6, 15), 11),
        ("mp1", datetime.date(2026, 7, 1), None, 22),
    ])

    assert windows.is_held_by(11, "mp1", TS.replace(month=6, day=10)) is True
    assert windows.is_held_by(22, "mp1", TS.replace(month=6, day=10)) is False
    # Gap reading (Jun 16–30): belongs to nobody.
    assert windows.is_held_by(11, "mp1", TS.replace(month=6, day=20)) is False
    assert windows.is_held_by(22, "mp1", TS.replace(month=6, day=20)) is False
    assert windows.is_held_by(22, "mp1", TS.replace(month=7, day=5)) is True
    assert windows.is_held_by(11, "mp9", TS) is False


def test_matching_uses_the_utc_civil_date_of_the_timestamp():
    """Assignment validity is matched on the UTC civil date of the timestamp.
    A reading at 22:30 UTC on 15 June (already 00:30 on 16 June in Zurich
    CEST) still belongs to the 15 June holder, keeping the attribution day
    aligned with the period and tariff day. ``participant_at`` defensively
    converts to UTC via ``astimezone``, so even a non-UTC datetime resolves
    to the correct UTC date instead of silently shifting the civil date."""
    windows = AssignmentWindows([
        ("mp1", datetime.date(2026, 6, 15), datetime.date(2026, 6, 15), 11),
        ("mp1", datetime.date(2026, 6, 16), None, 22),
    ])
    tz_utc = datetime.timezone.utc
    tz_zurich = datetime.timezone(datetime.timedelta(hours=2))  # CEST in June

    before = datetime.datetime(2026, 6, 14, 23, 30, tzinfo=tz_utc)
    midnight = datetime.datetime(2026, 6, 15, 0, 30, tzinfo=tz_utc)
    late_evening_utc = datetime.datetime(2026, 6, 15, 22, 30, tzinfo=tz_utc)
    same_moment_in_zurich = datetime.datetime(2026, 6, 16, 0, 30, tzinfo=tz_zurich)

    assert windows.participant_at("mp1", before) is None
    assert windows.participant_at("mp1", midnight) == 11
    assert windows.participant_at("mp1", late_evening_utc) == 11
    # The same instant expressed in Zurich local time (civil date 16 June)
    # still resolves to the UTC date (15 June) thanks to the defensive
    # astimezone(utc) conversion — participant 11, not 22.
    assert windows.participant_at("mp1", same_moment_in_zurich) == 11


def test_allocation_failures_share_a_common_base():
    """Billing callers catch ``AllocationError`` to distinguish allocation
    failures from the engine's 'invoice already exists' ``ValueError``
    (ADR 0013 follow-up); existing ``pytest.raises(ValueError)`` guards keep
    working because the base class stays a ``ValueError``."""
    assert issubclass(InvalidAllocationInputError, AllocationError)
    assert issubclass(OverlappingAssignmentWindowsError, AllocationError)
    assert issubclass(AllocationError, ValueError)

    with pytest.raises(AllocationError):
        split_consumption(D(5), D(4), D(1))  # participant exceeds total

    with pytest.raises(AllocationError):
        AssignmentWindows([
            ("mp1", datetime.date(2026, 6, 1), datetime.date(2026, 6, 20), 11),
            ("mp1", datetime.date(2026, 6, 15), None, 22),
        ])


def test_overlapping_windows_fail_fast():
    """Model validation forbids overlaps; the index still refuses to resolve
    them silently, so direct-DB edits or migration errors surface loudly."""
    with pytest.raises(OverlappingAssignmentWindowsError):
        AssignmentWindows([
            ("mp1", datetime.date(2026, 6, 1), datetime.date(2026, 6, 20), 11),
            ("mp1", datetime.date(2026, 6, 15), None, 22),
        ])


def test_open_ended_window_overlaps_any_later_window():
    with pytest.raises(OverlappingAssignmentWindowsError):
        AssignmentWindows([
            ("mp1", datetime.date(2026, 6, 1), None, 11),
            ("mp1", datetime.date(2026, 7, 1), None, 22),
        ])


def test_adjacent_windows_are_not_an_overlap():
    """valid_to is inclusive, so handing over on 16 June means the previous
    window legitimately ends on 15 June."""
    windows = AssignmentWindows([
        ("mp1", datetime.date(2026, 6, 1), datetime.date(2026, 6, 15), 11),
        ("mp1", datetime.date(2026, 6, 16), None, 22),
    ])

    assert windows.participant_at("mp1", TS.replace(month=6, day=15, hour=23)) == 11
    assert windows.participant_at("mp1", TS.replace(month=6, day=16, hour=0)) == 22
