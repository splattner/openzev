"""Unit tests for the allocation arithmetic in ``engine``.

``split_consumption`` and ``split_production`` decide how a community's solar
output is divided between its members. They were previously inline in
``generate_invoice`` and reachable only by building a ZEV, participants,
metering points, assignments, readings and tariffs — which is why the awkward
cases below had no coverage at all.

The end-to-end behaviour is pinned separately in ``test_engine_allocation.py``;
these are the same rules stated as arithmetic.
"""

from decimal import Decimal

import pytest

from .engine import split_consumption, split_production


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
