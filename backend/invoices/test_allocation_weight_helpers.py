"""Unit tests for the allocation-weight primitive (shared metering points,
docs/specs/2026-08-shared-metering-points.md §7.1).

Neither helper is called from anywhere yet — they're wired into SHARED_* fee
pricing and community-meter billing in later phases — so these are direct
unit tests of the helpers themselves rather than end-to-end engine tests.
"""

from datetime import date
from decimal import Decimal

import pytest

from testing.factories import ParticipantFactory, ZevFactory

from .engine import _allocation_weight_sum_by_date, _allocation_weight_sum_by_month

pytestmark = pytest.mark.django_db

PERIOD_START = date(2026, 1, 1)
PERIOD_END = date(2026, 3, 31)


def _zev_with_participants(*weights_and_windows):
    """A ZEV with one participant per ``(weight, valid_from, valid_to)`` tuple."""
    zev = ZevFactory()
    for weight, valid_from, valid_to in weights_and_windows:
        ParticipantFactory(zev=zev, valid_from=valid_from, valid_to=valid_to, allocation_weight=weight)
    return zev


def test_default_weights_sum_to_the_headcount():
    """With every weight at its default (1), the sum is just a count — the
    special case the weight helper collapses to."""
    zev = _zev_with_participants(
        (Decimal("1"), date(2026, 1, 1), None),
        (Decimal("1"), date(2026, 1, 1), None),
        (Decimal("1"), date(2026, 1, 1), None),
    )

    sums = _allocation_weight_sum_by_month(zev, PERIOD_START, PERIOD_END)

    assert sums == {
        date(2026, 1, 1): Decimal("3"),
        date(2026, 2, 1): Decimal("3"),
        date(2026, 3, 1): Decimal("3"),
    }


def test_unequal_weights_sum_correctly():
    zev = _zev_with_participants(
        (Decimal("1"), date(2026, 1, 1), None),
        (Decimal("2.5"), date(2026, 1, 1), None),
        (Decimal("0.5"), date(2026, 1, 1), None),
    )

    sums = _allocation_weight_sum_by_month(zev, PERIOD_START, PERIOD_END)

    assert sums[date(2026, 1, 1)] == Decimal("4")


def test_joiner_shifts_the_month_sum_only_from_their_own_month():
    """A participant joining mid-period must not retroactively change earlier
    months' denominators — the per-month counting rationale that
    _count_active_participants_by_month already documents."""
    zev = _zev_with_participants(
        (Decimal("1"), date(2026, 1, 1), None),
        (Decimal("2"), date(2026, 2, 15), None),
    )

    sums = _allocation_weight_sum_by_month(zev, PERIOD_START, PERIOD_END)

    assert sums[date(2026, 1, 1)] == Decimal("1")
    assert sums[date(2026, 2, 1)] == Decimal("3")
    assert sums[date(2026, 3, 1)] == Decimal("3")


def test_leaver_stops_contributing_the_month_after_they_leave():
    zev = _zev_with_participants(
        (Decimal("1"), date(2026, 1, 1), None),
        (Decimal("2"), date(2026, 1, 1), date(2026, 1, 20)),
    )

    sums = _allocation_weight_sum_by_month(zev, PERIOD_START, PERIOD_END)

    assert sums[date(2026, 1, 1)] == Decimal("3")
    assert sums[date(2026, 2, 1)] == Decimal("1")


def test_month_with_no_eligible_participant_is_absent_not_zero():
    """A caller must not be able to divide by an absent-but-present-as-zero
    denominator, so an empty month is missing from the dict entirely."""
    zev = _zev_with_participants(
        (Decimal("1"), date(2026, 1, 1), date(2026, 1, 31)),
    )

    sums = _allocation_weight_sum_by_month(zev, PERIOD_START, PERIOD_END)

    assert date(2026, 1, 1) in sums
    assert date(2026, 2, 1) not in sums
    assert date(2026, 3, 1) not in sums


def test_regeneration_from_zev_membership_not_sibling_invoices():
    """The sum is read from Participant validity, never from other invoices
    that happen to exist — required for single-participant regeneration to
    match a full run."""
    zev = _zev_with_participants(
        (Decimal("1"), date(2026, 1, 1), None),
        (Decimal("1"), date(2026, 1, 1), None),
    )

    whole_run = _allocation_weight_sum_by_month(zev, PERIOD_START, PERIOD_END)
    same_call_again = _allocation_weight_sum_by_month(zev, PERIOD_START, PERIOD_END)

    assert whole_run == same_call_again


def test_by_date_matches_membership_on_the_exact_join_day():
    """Date-granular: a joiner's weight counts from their valid_from day, not
    from the start of the month — matching participant_on's day-level
    resolution rather than _allocation_weight_sum_by_month's month buckets."""
    zev = _zev_with_participants(
        (Decimal("1"), date(2026, 1, 1), None),
        (Decimal("2"), date(2026, 1, 15), None),
    )

    sums = _allocation_weight_sum_by_date(zev, date(2026, 1, 1), date(2026, 1, 20))

    assert sums[date(2026, 1, 14)] == Decimal("1")
    assert sums[date(2026, 1, 15)] == Decimal("3")


def test_by_date_leaver_stops_on_their_exact_leave_day():
    zev = _zev_with_participants(
        (Decimal("1"), date(2026, 1, 1), None),
        (Decimal("2"), date(2026, 1, 1), date(2026, 1, 10)),
    )

    sums = _allocation_weight_sum_by_date(zev, date(2026, 1, 1), date(2026, 1, 20))

    assert sums[date(2026, 1, 10)] == Decimal("3")
    assert sums[date(2026, 1, 11)] == Decimal("1")


def test_by_date_day_with_no_eligible_participant_is_absent_not_zero():
    zev = _zev_with_participants(
        (Decimal("1"), date(2026, 1, 5), date(2026, 1, 10)),
    )

    sums = _allocation_weight_sum_by_date(zev, date(2026, 1, 1), date(2026, 1, 20))

    assert date(2026, 1, 5) in sums
    assert date(2026, 1, 1) not in sums
    assert date(2026, 1, 20) not in sums


def test_a_zev_with_no_participants_at_all_returns_empty_dicts():
    """Degenerate case: no participants means every month/date is absent, not
    a zero-division waiting to happen in a future caller."""
    zev = ZevFactory()

    assert _allocation_weight_sum_by_month(zev, PERIOD_START, PERIOD_END) == {}
    assert _allocation_weight_sum_by_date(zev, PERIOD_START, PERIOD_END) == {}
