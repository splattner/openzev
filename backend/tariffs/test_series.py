"""Unit tests for tariff-series arithmetic.

No database: ``series.py`` is deliberately ORM-free so the part that is easy to
get wrong by a single day can be stated as arithmetic. The API behaviour built
on top is covered in ``test_versioning.py``.
"""

from datetime import date

import pytest

from .series import Gap, active_version, find_gaps, plan_new_version, sort_versions


class FakeVersion:
    """Enough of a Tariff for the window arithmetic."""

    def __init__(self, pk, valid_from, valid_to=None):
        self.pk = pk
        self.valid_from = valid_from
        self.valid_to = valid_to

    def __repr__(self):
        return f"<{self.pk} {self.valid_from}..{self.valid_to}>"


def version(pk, valid_from, valid_to=None):
    return FakeVersion(pk, date.fromisoformat(valid_from),
                       date.fromisoformat(valid_to) if valid_to else None)


# ---------------------------------------------------------------------------
# sort_versions / active_version
# ---------------------------------------------------------------------------

def test_versions_sort_oldest_first_regardless_of_input_order():
    late = version("late", "2027-01-01")
    early = version("early", "2025-01-01", "2025-12-31")
    middle = version("middle", "2026-01-01", "2026-12-31")

    assert sort_versions([late, early, middle]) == [early, middle, late]


def test_the_active_version_is_the_one_covering_today():
    versions = [
        version("v1", "2025-01-01", "2025-12-31"),
        version("v2", "2026-01-01", "2026-12-31"),
        version("v3", "2027-01-01"),
    ]

    assert active_version(versions, date(2026, 6, 15)).pk == "v2"


@pytest.mark.parametrize("day", ["2026-01-01", "2026-12-31"])
def test_both_bounds_of_a_window_are_inclusive(day):
    versions = [version("v", "2026-01-01", "2026-12-31")]

    assert active_version(versions, date.fromisoformat(day)).pk == "v"


def test_an_open_ended_version_stays_active_indefinitely():
    versions = [version("v", "2026-01-01")]

    assert active_version(versions, date(2099, 1, 1)).pk == "v"


def test_a_day_inside_a_gap_has_no_active_version():
    """Which is exactly the state that bills consumed energy at nothing."""
    versions = [
        version("v1", "2026-01-01", "2026-06-30"),
        version("v2", "2026-08-01"),
    ]

    assert active_version(versions, date(2026, 7, 15)) is None


def test_a_day_before_the_series_begins_has_no_active_version():
    assert active_version([version("v", "2026-01-01")], date(2025, 12, 31)) is None


# ---------------------------------------------------------------------------
# find_gaps
# ---------------------------------------------------------------------------

def test_a_contiguous_timeline_has_no_gaps():
    versions = [
        version("v1", "2025-01-01", "2025-12-31"),
        version("v2", "2026-01-01", "2026-12-31"),
        version("v3", "2027-01-01"),
    ]

    assert find_gaps(versions) == []


def test_a_missing_month_is_reported_with_inclusive_bounds():
    versions = [
        version("v1", "2026-01-01", "2026-06-30"),
        version("v2", "2026-08-01"),
    ]

    assert find_gaps(versions) == [Gap(date(2026, 7, 1), date(2026, 7, 31))]


def test_a_single_missing_day_is_still_a_gap():
    """The off-by-one that a manual end date invites."""
    versions = [
        version("v1", "2026-01-01", "2026-12-30"),
        version("v2", "2027-01-01"),
    ]

    assert find_gaps(versions) == [Gap(date(2026, 12, 31), date(2026, 12, 31))]


def test_every_interior_gap_is_reported():
    versions = [
        version("v1", "2026-01-01", "2026-01-31"),
        version("v2", "2026-03-01", "2026-03-31"),
        version("v3", "2026-05-01"),
    ]

    assert find_gaps(versions) == [
        Gap(date(2026, 2, 1), date(2026, 2, 28)),
        Gap(date(2026, 4, 1), date(2026, 4, 30)),
    ]


def test_the_stretch_before_the_first_version_is_not_a_gap():
    assert find_gaps([version("v", "2026-06-01")]) == []


def test_a_retired_series_does_not_report_a_trailing_gap():
    """A tariff that has ended simply no longer applies; that is not a hole."""
    assert find_gaps([version("v", "2026-01-01", "2026-12-31")]) == []


def test_gaps_are_found_regardless_of_input_order():
    versions = [
        version("v2", "2026-08-01"),
        version("v1", "2026-01-01", "2026-06-30"),
    ]

    assert find_gaps(versions) == [Gap(date(2026, 7, 1), date(2026, 7, 31))]


# ---------------------------------------------------------------------------
# plan_new_version
# ---------------------------------------------------------------------------

def test_appending_closes_the_open_ended_predecessor_the_day_before():
    versions = [version("v1", "2026-01-01")]

    window = plan_new_version(versions, date(2027, 1, 1))

    assert window.predecessor_id == "v1"
    assert window.predecessor_valid_to == date(2026, 12, 31)
    assert window.valid_to is None


def test_appending_truncates_a_predecessor_that_ends_too_late():
    versions = [version("v1", "2026-01-01", "2027-12-31")]

    window = plan_new_version(versions, date(2027, 1, 1))

    assert window.predecessor_valid_to == date(2026, 12, 31)


def test_inserting_mid_chain_bounds_both_sides():
    """Without the upper bound the new version would swallow its successor's
    window and be rejected by the overlap guard for reasons the caller cannot
    see."""
    versions = [
        version("v1", "2026-01-01", "2026-12-31"),
        version("v3", "2028-01-01"),
    ]

    window = plan_new_version(versions, date(2027, 1, 1))

    assert window.predecessor_id == "v1"
    assert window.predecessor_valid_to is None  # already ends before the new start
    assert window.valid_to == date(2027, 12, 31)


def test_inserting_mid_chain_truncates_an_overlapping_predecessor():
    versions = [
        version("v1", "2026-01-01", "2027-06-30"),
        version("v3", "2028-01-01"),
    ]

    window = plan_new_version(versions, date(2027, 1, 1))

    assert window.predecessor_valid_to == date(2026, 12, 31)
    assert window.valid_to == date(2027, 12, 31)


def test_a_predecessor_that_already_ends_earlier_is_left_alone():
    """Extending a closed window would change what that period bills, and the
    resulting gap may well be deliberate."""
    versions = [version("v1", "2026-01-01", "2026-06-30")]

    window = plan_new_version(versions, date(2027, 1, 1))

    assert window.predecessor_id == "v1"
    assert window.predecessor_valid_to is None


def test_prepending_before_every_existing_version_has_no_predecessor():
    versions = [version("v1", "2026-01-01")]

    window = plan_new_version(versions, date(2025, 1, 1))

    assert window.predecessor_id is None
    assert window.predecessor_valid_to is None
    assert window.valid_to == date(2025, 12, 31)


def test_the_first_version_of_a_series_is_unbounded():
    window = plan_new_version([], date(2026, 1, 1))

    assert window.predecessor_id is None
    assert window.valid_to is None


def test_only_the_immediately_preceding_version_is_truncated():
    versions = [
        version("v1", "2025-01-01", "2025-12-31"),
        version("v2", "2026-01-01"),
    ]

    window = plan_new_version(versions, date(2027, 1, 1))

    assert window.predecessor_id == "v2"
    assert window.predecessor_valid_to == date(2026, 12, 31)
