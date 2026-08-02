"""Local-pool allocation arithmetic, shared by every consumer.

How a community's solar output is divided between its members at a single
timestamp. Pure arithmetic, deliberately free of the ORM: this is the part of
the billing and charting code that decides who pays for what, and it must be
readable and testable without building a metering fixture.

Used by the billing engine, invoice PDFs, dashboards, annual statements, and
the feasibility calculator. Any formula change happens here and nowhere else.
"""

from decimal import Decimal
from typing import NamedTuple


class ConsumptionSplit(NamedTuple):
    local_kwh: Decimal
    grid_kwh: Decimal


class ProductionSplit(NamedTuple):
    local_sold_kwh: Decimal
    exported_kwh: Decimal


def _require_non_negative(value: Decimal, name: str) -> None:
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be a Decimal, got {type(value).__name__}")
    if value < 0:
        raise ValueError(f"{name} must be non-negative, got {value}")


def split_consumption(
    participant_kwh: Decimal,
    zev_consumption_kwh: Decimal,
    zev_production_kwh: Decimal,
) -> ConsumptionSplit:
    """Divide one consumer's draw into a solar part and a grid part.

    The community can only share what it both produced *and* consumed in the
    interval; that pool is handed out in proportion to each member's share of
    total consumption, and whatever is left over is drawn from the grid.

    Fail-fast contracts: every input must be non-negative, and a member's draw
    cannot exceed the community's total consumption (the ZEV total includes
    their own reading, so anything else indicates inconsistent inputs — a
    duplicate reading, or the wrong metering-point scope). Violations raise
    ``ValueError`` instead of producing silently clamped arithmetic. With the
    totals guaranteed consistent, the proportional slice can never exceed the
    member's own draw (the pool is capped at total consumption), so the local
    part needs no clamp and the grid part is exactly the remainder.

    ``zev_consumption_kwh`` and ``zev_production_kwh`` must be *physical*
    totals — every meter in the ZEV, including meters with no active
    assignment at this timestamp (ADR 0013 pool decision). Because the
    consumption total is the denominator of each member's share, restricting
    it to assigned meters would shrink that denominator and silently inflate
    every assigned consumer's local share — the opposite of under-crediting
    them — and diverge from the physical totals the dashboards report.
    """
    _require_non_negative(participant_kwh, "participant_kwh")
    _require_non_negative(zev_consumption_kwh, "zev_consumption_kwh")
    _require_non_negative(zev_production_kwh, "zev_production_kwh")
    if participant_kwh > zev_consumption_kwh:
        raise ValueError(
            "participant_kwh "
            f"({participant_kwh}) exceeds zev_consumption_kwh ({zev_consumption_kwh})"
        )
    local_pool = min(zev_production_kwh, zev_consumption_kwh)
    if zev_consumption_kwh > 0 and local_pool > 0:
        participant_share = participant_kwh / zev_consumption_kwh
        local_kwh = local_pool * participant_share
    else:
        local_kwh = Decimal("0")
    return ConsumptionSplit(local_kwh, participant_kwh - local_kwh)


def split_production(
    produced_kwh: Decimal,
    zev_production_kwh: Decimal,
    zev_consumption_kwh: Decimal,
) -> ProductionSplit:
    """Divide one producer's output into what the community used and what was exported.

    Both pools are shared on the producer's contribution to total production,
    so a member who supplied 30% of the solar earns 30% of the local sales and
    carries 30% of the export. Same fail-fast contracts as
    ``split_consumption``: non-negative inputs, and the producer's output
    cannot exceed the community's total production.

    ``zev_production_kwh`` and ``zev_consumption_kwh`` must be *physical*
    totals — every meter in the ZEV, including unassigned meters (ADR 0013
    pool decision). Restricting them to assigned meters would shrink both
    pools and under-credit producers.
    """
    _require_non_negative(produced_kwh, "produced_kwh")
    _require_non_negative(zev_production_kwh, "zev_production_kwh")
    _require_non_negative(zev_consumption_kwh, "zev_consumption_kwh")
    if produced_kwh > zev_production_kwh:
        raise ValueError(
            f"produced_kwh ({produced_kwh}) exceeds zev_production_kwh ({zev_production_kwh})"
        )
    if zev_production_kwh <= 0:
        return ProductionSplit(Decimal("0"), Decimal("0"))
    local_pool = min(zev_production_kwh, zev_consumption_kwh)
    export_pool = max(zev_production_kwh - zev_consumption_kwh, Decimal("0"))
    producer_share = produced_kwh / zev_production_kwh
    return ProductionSplit(local_pool * producer_share, export_pool * producer_share)


def local_pool_kwh(produced_kwh: Decimal, consumed_kwh: Decimal) -> Decimal:
    """The kWh the community both produced and consumed at one timestamp."""
    _require_non_negative(produced_kwh, "produced_kwh")
    _require_non_negative(consumed_kwh, "consumed_kwh")
    return min(produced_kwh, consumed_kwh)


def proportional_share(
    pool_kwh: Decimal,
    participant_kwh: Decimal,
    total_kwh: Decimal,
) -> Decimal:
    """A participant's proportional slice of a precomputed pool.

    The annual-aggregate variant of ``split_consumption`` used by the
    feasibility calculator: there the pool (annual self-consumed total) is
    computed separately, and each participant's slice is their share of total
    demand. ``total_kwh <= 0`` yields zero.

    Same fail-fast contracts as the split functions: all inputs must be
    ``Decimal`` and non-negative, and ``participant_kwh`` cannot exceed
    ``total_kwh`` (the total includes the participant, so exceeding it
    indicates inconsistent inputs).
    """
    _require_non_negative(pool_kwh, "pool_kwh")
    _require_non_negative(participant_kwh, "participant_kwh")
    _require_non_negative(total_kwh, "total_kwh")
    if total_kwh <= 0 or pool_kwh <= 0:
        return Decimal("0")
    if participant_kwh > total_kwh:
        raise ValueError(
            f"participant_kwh ({participant_kwh}) exceeds total_kwh ({total_kwh})"
        )
    return pool_kwh * (participant_kwh / total_kwh)
