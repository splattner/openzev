"""Gross-energy figures as the statistics surfaces use them (SPEC §5.1).

The surfaces (dashboards, annual report, annual statement, MCP) all come through here,
and through ``stats.gross_energy`` below it, never the models directly (ADR 0030). Every
function answers ``None`` (or leaves a block ``None``) while the feature flag is off, so
a flagged-off instance behaves exactly as before.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone as dt_timezone
from typing import Callable, Iterable

from allocation.validity import business_tz, civil_date, period_start_dt

from zev import access
from zev.models import Participant

from ..models import SupplementarySource
from .permissions import feature_enabled
from .stats import civil_window, gross_energy

#: Wide enough to mean "no bound": ``gross_energy`` clips to what each source has ingested.
EARLIEST = datetime(2000, 1, 1, tzinfo=dt_timezone.utc)
LATEST = datetime(9000, 1, 1, tzinfo=dt_timezone.utc)

Window = tuple[datetime, datetime]


def window_for(date_from: date | None, date_to: date | None) -> Window:
    """UTC ``[start, end)`` for the inclusive civil dates a dashboard was asked for (either may be open)."""
    start = civil_window(date_from, date_from)[0] if date_from else EARLIEST
    end = civil_window(date_to, date_to)[1] if date_to else LATEST
    return start, end


def bucket_key_for(bucket: str) -> Callable[[datetime], str]:
    """Maps an interval start to the label the dashboards use for the same bucket (ADR 0026).

    Day and month buckets are civil, truncated in the business timezone; hour buckets
    are UTC. The labels are ``isoformat()`` strings, identical to ``Trunc*(...).isoformat()``,
    so a chart can lay this timeline over its own.
    """
    zone = business_tz()
    if bucket == "hour":
        return lambda ts: ts.astimezone(dt_timezone.utc).replace(minute=0, second=0, microsecond=0).isoformat()
    if bucket == "month":
        return lambda ts: period_start_dt(civil_date(ts).replace(day=1)).astimezone(zone).isoformat()
    return lambda ts: period_start_dt(civil_date(ts)).astimezone(zone).isoformat()


def participants_gross(participant_ids: Iterable, start: datetime, end: datetime, *,
                       bucket: str | None = None) -> dict[str, dict | None]:
    """``{participant_id: GrossEnergy | None}`` for each participant that has a source.

    Participants without a source are left out, so a ZEV with no net-metered households
    costs one query.
    """
    if not feature_enabled():
        return {}
    ids = list(participant_ids)
    with_source = SupplementarySource.objects.filter(participant_id__in=ids).values_list("participant_id", flat=True)
    key = bucket_key_for(bucket) if bucket else None
    return {
        str(pid): gross_energy([pid], start, end, bucket_key=key)
        for pid in set(with_source)
    }


def attach_owner_gross(summary: dict, window: Window, bucket: str, selected_participant_id: str | None,
                       *, user=None, zev_id=None) -> dict:
    """Adds ``gross_energy`` to each ``participant_stats`` entry and ``selected_gross_energy`` to ``summary``.

    With ``user`` and ``zev_id`` it also adds ``own_gross_energy``: the signed-in manager's own
    figures as a participant of that ZEV (with a timeline), independent of whom they selected. A
    manager is usually a participant too, and their own picture should not hide behind a dropdown.
    """
    stats = summary.get("participant_stats") or []
    start, end = window
    gross = participants_gross([item["participant_id"] for item in stats], start, end)
    for item in stats:
        item["gross_energy"] = gross.get(str(item["participant_id"]))
    selected = None
    if selected_participant_id:
        selected = participants_gross([selected_participant_id], start, end, bucket=bucket).get(
            str(selected_participant_id)
        )
    summary["selected_gross_energy"] = selected
    summary["own_gross_energy"] = None
    if user is not None and zev_id is not None and feature_enabled():
        own_ids = Participant.objects.filter(access.live_participant_q(), user=user, zev_id=zev_id).values_list("id", flat=True)
        summary["own_gross_energy"] = gross_energy(list(own_ids), start, end, bucket_key=bucket_key_for(bucket))
    return summary


def attach_participant_gross(summary: dict, participant_ids: Iterable, window: Window, bucket: str) -> dict:
    """Adds ``gross_energy`` (with a timeline) for the signed-in participant's own sources."""
    summary["gross_energy"] = None
    if feature_enabled():
        start, end = window
        summary["gross_energy"] = gross_energy(list(participant_ids), start, end, bucket_key=bucket_key_for(bucket))
    return summary


def statement_gross(participant_id, year: int):
    """Per-month and whole-year gross figures for the annual statement.

    Returns ``(months, year_total)``: twelve ``GrossEnergy | None`` entries (January first)
    and the year's, or ``(None, None)`` while the feature is off or the participant has no
    source.
    """
    if not feature_enabled() or not SupplementarySource.objects.filter(participant_id=participant_id).exists():
        return None, None
    months = []
    for month in range(1, 13):
        last = (date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1))
        months.append(gross_energy([participant_id], *civil_window(date(year, month, 1), last)))
    return months, gross_energy([participant_id], *civil_window(date(year, 1, 1), date(year, 12, 31)))
