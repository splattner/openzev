"""In-memory index over metering-point assignment windows.

Readings carry a timestamp; assignments carry a date-granular validity window
(``valid_from``/``valid_to``, see ADR 0001). Attributing a reading to the
participant who held the metering point at that moment is a per-timestamp
lookup, which a period-level SQL overlap cannot express in one query. These
windows are fetched once per consumer call and resolved in Python, the same
"single fetch, then Python" pattern the billing engine already uses.

Overlapping assignments for one metering point are forbidden by model
validation, so at most one window can match a given timestamp. As a guard
against direct-DB edits or migration errors, the constructor fails fast on
overlaps instead of resolving them silently.

Matching is done on the *UTC civil date* of the reading's timestamp
(``ts.astimezone(timezone.utc).date()``), not on a local-timezone date. This is deliberate and
consistent with the rest of the system: periods, tariff validity, and daily
completeness are all matched on UTC dates (ADR 0007 — "all metering timestamps
are stored and queried in UTC"). A Zurich-local date would make the
attribution day disagree with the period day and tariff day for readings near
midnight; moving the whole system to local civil dates would be a separate,
cross-cutting decision.
"""

import itertools
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

from django.db.models import Q

from allocation.errors import OverlappingAssignmentWindowsError
from zev.models import MeteringPointAssignment


@dataclass(frozen=True)
class AssignmentResolution:
    """The assignment covering a metering point at a timestamp.

    ``holder_id`` is the literal holder (``MeteringPointAssignment.participant``)
    regardless of ``allocation_mode`` — a community meter keeps its holder of
    record for provenance, UI and data-quality purposes. Billing code decides
    what to do with ``allocation_mode``; this object only reports it.
    """

    holder_id: Any
    allocation_mode: str
    assignment_id: Any


class AssignmentWindows:
    """Resolve which participant held a metering point at a given timestamp."""

    def __init__(self, rows):
        """``rows``: iterable of ``(metering_point_id, valid_from, valid_to,
        participant_id, allocation_mode, assignment_id)``. Windows are sorted
        by ``valid_from``; two windows for the same metering point that
        overlap (an open-ended ``valid_to`` overlaps everything later) raise
        ``OverlappingAssignmentWindowsError`` rather than resolving in favour
        of one of them."""
        windows: dict = {}
        for mp_id, valid_from, valid_to, participant_id, allocation_mode, assignment_id in rows:
            windows.setdefault(mp_id, []).append(
                (valid_from, valid_to, participant_id, allocation_mode, assignment_id)
            )
        for mp_id, mp_windows in windows.items():
            mp_windows.sort(key=lambda w: w[0])
            for (prev_from, prev_to, *_), (cur_from, cur_to, *_) in itertools.pairwise(
                mp_windows
            ):
                if prev_to is None or cur_from <= prev_to:
                    raise OverlappingAssignmentWindowsError(
                        mp_id, (prev_from, prev_to), (cur_from, cur_to)
                    )
        self._windows = windows

    @classmethod
    def for_zev(cls, zev, start: date, end: date) -> "AssignmentWindows":
        """All assignments of the ZEV's metering points overlapping ``start``..``end``."""
        rows = MeteringPointAssignment.objects.filter(
            metering_point__zev=zev,
            valid_from__lte=end,
        ).filter(
            Q(valid_to__isnull=True) | Q(valid_to__gte=start),
        ).values_list(
            "metering_point_id", "valid_from", "valid_to", "participant_id",
            "allocation_mode", "id",
        )
        return cls(rows)

    @classmethod
    def for_participant(cls, participant, start: date, end: date) -> "AssignmentWindows":
        """The participant's own assignments overlapping ``start``..``end``."""
        rows = MeteringPointAssignment.objects.filter(
            participant=participant,
            valid_from__lte=end,
        ).filter(
            Q(valid_to__isnull=True) | Q(valid_to__gte=start),
        ).values_list(
            "metering_point_id", "valid_from", "valid_to", "participant_id",
            "allocation_mode", "id",
        )
        return cls(rows)

    def active_windows(self, metering_point_id) -> tuple:
        """``(valid_from, valid_to, participant_id, allocation_mode,
        assignment_id)`` windows for one metering point. Immutable: billing
        eligibility must not change mid-run."""
        return tuple(self._windows.get(metering_point_id, ()))

    @property
    def participant_ids(self):
        """All participant ids referenced by any window."""
        return {
            participant_id
            for mp_windows in self._windows.values()
            for _valid_from, _valid_to, participant_id, _mode, _aid in mp_windows
        }

    def _window_on(self, metering_point_id, day: date):
        """The raw window tuple covering ``metering_point_id`` on ``day``, or ``None``."""
        for window in self.active_windows(metering_point_id):
            valid_from, valid_to = window[0], window[1]
            if valid_from <= day and (valid_to is None or valid_to >= day):
                return window
        return None

    def participant_on(self, metering_point_id, day: date):
        """Participant id holding ``metering_point_id`` on ``day``, or ``None``.

        Assignment validity is date-granular, so matching a day directly is
        equivalent to matching any timestamp that falls on it. Callers that
        only need the day (e.g. data-quality checks) should resolve once per
        distinct day instead of once per reading. Literal holder semantics —
        unaffected by ``allocation_mode``: a community meter is not
        unassigned.
        """
        window = self._window_on(metering_point_id, day)
        return window[2] if window is not None else None

    def participant_at(self, metering_point_id, ts: datetime):
        """Participant id holding ``metering_point_id`` at ``ts``, or ``None``.

        The window is matched on the UTC civil date of the timestamp:
        assignment validity is date-granular, so a reading at 00:30 UTC on the
        day an assignment starts already belongs to the new holder. ``ts`` is
        always UTC in this codebase (ADR 0007); the explicit
        ``astimezone(timezone.utc)`` is a defensive guard so a non-UTC
        datetime cannot silently shift the civil date. Literal holder
        semantics — unaffected by ``allocation_mode``; see ``assignment_at``
        for a mode-aware resolution.
        """
        day = ts.astimezone(timezone.utc).date()
        return self.participant_on(metering_point_id, day)

    def assignment_at(self, metering_point_id, ts: datetime) -> AssignmentResolution | None:
        """The assignment covering ``metering_point_id`` at ``ts``, or ``None``.

        ``None`` only when no assignment covers the timestamp — a true gap.
        Unlike ``participant_at``, this reports the allocation mode, so
        billing code can distinguish "no assignment" (gap) from
        "community-allocated" (a valid assignment whose costs are
        distributed) instead of conflating the two under a bare ``None``.
        """
        day = ts.astimezone(timezone.utc).date()
        window = self._window_on(metering_point_id, day)
        if window is None:
            return None
        _valid_from, _valid_to, participant_id, allocation_mode, assignment_id = window
        return AssignmentResolution(
            holder_id=participant_id,
            allocation_mode=allocation_mode,
            assignment_id=assignment_id,
        )

    def is_held_by(self, participant_id, metering_point_id, ts: datetime) -> bool:
        """Whether ``participant_id`` holds ``metering_point_id`` at ``ts``.

        Convenience wrapper over ``participant_at`` for the common billing
        check "does this reading belong to this participant?". Readings in an
        assignment gap (or predating every window) belong to nobody, so this
        returns ``False`` for them. Literal holder semantics — ``True`` for a
        community meter's holder too; callers that must not bill the holder
        personally for community energy should use ``assignment_at`` instead.
        """
        return self.participant_at(metering_point_id, ts) == participant_id
