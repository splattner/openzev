"""What a live source needs to know about its holder and its own bookkeeping (SPEC-2026-live-energy-data §5.1).

Shared by the push endpoint and the Solar Manager pull task.
"""

from __future__ import annotations

from datetime import date

from django.conf import settings

from allocation.validity import active_on
from zev.models import AllocationMode, MeteringPointAssignment

from ..models import SourceHolder, SourceTarget, SupplementarySource
from ..supplementary.permissions import personally_held_today


def holder_gone(source: SupplementarySource, today: date) -> bool:
    """Has the person this source was consented by lost the right to its meter (SPEC §5.1)?

    A participant-held source needs its participant to hold the metering point personally today. A
    ZEV-held one stops when somebody does: a household's live value must not keep flowing to the
    manager without its consent. The connection point has no holder to lose.
    """
    if source.target == SourceTarget.CONNECTION_POINT:
        return False
    if source.held_by == SourceHolder.ZEV:
        return personally_held_today(source.metering_point, today)
    return not active_on(
        MeteringPointAssignment.objects.filter(
            metering_point_id=source.metering_point_id,
            participant_id=source.participant_id,
            allocation_mode=AllocationMode.PERSONAL,
        ),
        today,
    ).exists()


def touch_last_seen(source: SupplementarySource, now) -> None:
    """Record that a live value arrived, at ``LIVE_LAST_SEEN_RESOLUTION_S`` resolution (status only)."""
    last = source.live_last_seen_at
    if last is not None and (now - last).total_seconds() < settings.LIVE_LAST_SEEN_RESOLUTION_S:
        return
    SupplementarySource.objects.filter(pk=source.pk).update(live_last_seen_at=now)
    source.live_last_seen_at = now
