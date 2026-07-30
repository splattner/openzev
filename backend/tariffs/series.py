"""Tariff versioning: grouping, gap detection, and validity-window arithmetic.

A *series* is every tariff in a ZEV sharing a name. That grouping is not a
convention layered on top of the data — it is the invariant the model already
enforces: two tariffs with the same name in one ZEV may not have overlapping
validity windows (see ``Tariff.clean``). So the versions of a series form a
non-overlapping timeline by construction, and the billing engine already picks
the right one because it resolves tariffs per day.

The pure functions here are kept free of the ORM so the window arithmetic — the
part that is easy to get wrong by a day — can be tested directly.
"""

from datetime import date, timedelta
from typing import Iterable, NamedTuple

# Fields that identify what a tariff *is*, as opposed to when it applies or what
# it costs. Every version of one series must agree on all of them; otherwise
# "the same tariff over time" is not a meaningful claim and comparing versions
# would mean comparing a local-energy rate against a grid fee.
SERIES_FIELDS = ("category", "billing_mode", "energy_type")

#: Series are keyed on name alone. Category is deliberately excluded: two
#: tariffs sharing a name would be indistinguishable on an invoice line anyway,
#: and the overlap guard already treats them as the same thing.
SERIES_KEY_FIELDS = ("zev_id", "name")


class Gap(NamedTuple):
    """An uncovered stretch between two versions of a series.

    Gaps are a billing hazard rather than a modelling curiosity: the engine
    prices energy only against tariffs active on the day, so a day inside a gap
    yields consumed kWh with no line item and no charge at all.
    """

    start: date
    end: date


class VersionWindow(NamedTuple):
    """Where a new version fits into an existing timeline."""

    #: Version whose window must be truncated to make room, if any.
    predecessor_id: object | None
    #: New end date for that predecessor (``None`` when nothing to truncate).
    predecessor_valid_to: date | None
    #: End date the new version must take so it stops before the next one.
    valid_to: date | None


def series_key(tariff) -> tuple:
    return tuple(getattr(tariff, field) for field in SERIES_KEY_FIELDS)


def sort_versions(versions: Iterable) -> list:
    """Oldest first. ``valid_from`` is unique within a series, so this is total."""
    return sorted(versions, key=lambda version: version.valid_from)


def active_version(versions: Iterable, today: date):
    """The version in force on ``today``, or ``None`` if the series has a gap there."""
    for version in versions:
        if version.valid_from <= today and (version.valid_to is None or version.valid_to >= today):
            return version
    return None


def find_gaps(versions: Iterable) -> list[Gap]:
    """Uncovered stretches between consecutive versions, oldest first.

    Only interior gaps are reported. The stretch before the first version and
    after an end-dated last version are not gaps — they are simply periods the
    series does not cover, which is normal for a tariff that started late or
    has been retired.
    """
    ordered = sort_versions(versions)
    gaps = []
    for earlier, later in zip(ordered, ordered[1:]):
        if earlier.valid_to is None:
            # Open-ended followed by another version would be an overlap, which
            # the model rejects. Nothing to report.
            continue
        expected_next = earlier.valid_to + timedelta(days=1)
        if later.valid_from > expected_next:
            gaps.append(Gap(expected_next, later.valid_from - timedelta(days=1)))
    return gaps


def plan_new_version(versions: Iterable, valid_from: date) -> VersionWindow:
    """Work out how a version starting on ``valid_from`` slots into the timeline.

    The predecessor is truncated to the day before, and the new version is
    capped at the day before whichever version follows it — so inserting into
    the middle of a chain bounds *both* sides. Without the second half the new
    version would swallow its successor's window and be rejected by the overlap
    guard with a message that explains nothing.

    A predecessor that already ends before ``valid_from`` is left alone: the
    resulting gap may well be deliberate, and silently extending a closed
    window would change what that period bills.
    """
    ordered = sort_versions(versions)

    predecessor = None
    successor = None
    for version in ordered:
        if version.valid_from < valid_from:
            predecessor = version
        elif version.valid_from > valid_from and successor is None:
            successor = version

    truncate_to = None
    if predecessor is not None:
        day_before = valid_from - timedelta(days=1)
        if predecessor.valid_to is None or predecessor.valid_to > day_before:
            truncate_to = day_before

    return VersionWindow(
        predecessor_id=predecessor.pk if predecessor is not None else None,
        predecessor_valid_to=truncate_to,
        valid_to=(successor.valid_from - timedelta(days=1)) if successor is not None else None,
    )
