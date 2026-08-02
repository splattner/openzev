"""Exception hierarchy for allocation failures.

Every allocation failure derives from ``AllocationError`` (itself a
``ValueError`` for backwards compatibility) so callers can distinguish
"the allocation could not be computed" from other ``ValueError``s — in
particular the invoice engine's "invoice already exists" error, which the
generate endpoint keeps reporting as a 409. All existing
``except ValueError`` guards keep working unchanged.
"""


class AllocationError(ValueError):
    """Base class for all allocation-service failures."""


class InvalidAllocationInputError(AllocationError):
    """A split input violates a fail-fast contract.

    Raised by ``allocation.split`` for negative inputs and inconsistent
    totals (a participant's reading exceeding the community total).
    Non-``Decimal`` inputs remain ``TypeError`` — those are programming
    errors, not data conditions.
    """


class OverlappingAssignmentWindowsError(AllocationError):
    """Two assignments for one metering point overlap in time."""

    def __init__(self, metering_point_id, first, second):
        self.metering_point_id = metering_point_id
        self.first = first
        self.second = second
        super().__init__(
            f"overlapping assignment windows for metering point {metering_point_id}: "
            f"{first[0]}..{first[1]} vs {second[0]}..{second[1]}"
        )
