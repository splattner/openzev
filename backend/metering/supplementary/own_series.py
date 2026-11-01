"""The viewer's own-system series, for the "My energy system" page (SPEC-2026-live-energy-data §5.4).

Display only, like every statistics surface (ADR 0030): the figures come from ``stats.gross_energy``,
so the inclusion rules, the coverage gate and the withheld rates are the dashboards' own. Nothing is
written, and nothing here feeds billing.

Who may read whose figures follows the dashboards: a participant reads their own, a manager, viewer
or admin of the ZEV those of any of its participants (and their own by default).
"""

from __future__ import annotations

from datetime import date, datetime

from django.http import Http404
from rest_framework.exceptions import PermissionDenied, ValidationError

from zev import access
from zev.models import Participant, Zev

from ..models import SupplementarySource
from .stats import INTERVAL_S, civil_window, gross_energy
from .surfaces import bucket_key_for

#: The longest range a bucket size may cover, in civil days: enough for a chart, never an export.
MAX_DAYS = {"quarter": 3, "hour": 31, "day": 400}
BUCKETS = tuple(MAX_DAYS)


def participant_ids_for(user, zev: Zev, participant_id) -> list:
    """The participants whose own system ``user`` asks for: the named one, else their own in ``zev``.

    A manager, viewer or admin may name any participant of the ZEV; anybody else only themselves
    (``403`` for another participant, never a figure). An unknown participant is ``404``.
    """
    own = list(
        Participant.objects.filter(access.live_participant_q(), user=user, zev=zev).values_list("pk", flat=True)
    )
    if not participant_id:
        return own
    named = Participant.objects.filter(pk=participant_id, zev=zev).first()
    if named is None:
        raise Http404
    if named.pk in own or access.can_view(user, zev):
        return [named.pk]
    raise PermissionDenied("You may only read your own energy data.")


def history_through(participant_ids) -> datetime | None:
    """Until when every history source of these participants has data: the earliest ``synced_through``.

    A source that never ingested anything has nothing to hand over from and is left out.
    """
    stamps = SupplementarySource.objects.filter(
        participant_id__in=list(participant_ids), provides_history=True, synced_through__isnull=False
    ).values_list("synced_through", flat=True)
    return min(stamps, default=None)


def own_series(participant_ids, date_from: date, date_to: date, bucket: str) -> dict:
    """``{bucket, date_from, date_to, history_through, gross}`` for the civil range, ``gross`` as in the dashboards.

    ``gross`` is ``None`` when none of the participants' sources expects data in the range.
    """
    if bucket not in MAX_DAYS:
        raise ValidationError({"bucket": [f"Use one of: {', '.join(BUCKETS)}."]})
    if date_to < date_from:
        raise ValidationError({"date_to": ["The end is before the start."]})
    if (date_to - date_from).days + 1 > MAX_DAYS[bucket]:
        raise ValidationError({"date_to": [f"At most {MAX_DAYS[bucket]} days per request in {bucket} buckets."]})
    ids = list(participant_ids)
    start, end = civil_window(date_from, date_to)
    return {
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "bucket": bucket,
        "history_through": history_through(ids),
        "gross": gross_energy(ids, start, end, bucket_key=bucket_key_for(bucket)),
    }


def own_history_of_day(participant_ids, day: date) -> list[dict]:
    """The day's 15-minute mean powers of the participants' own systems, in W (SPEC-live §5.3).

    One row per interval a source has data for, never one for a missing interval. Power is the
    interval's energy over its length (kWh x 4 for a quarter hour), summed over several sources.
    """
    ids = list(participant_ids)
    gross = gross_energy(ids, *civil_window(day, day), bucket_key=bucket_key_for("quarter"))
    if gross is None:
        return []
    per_kwh = 3_600_000 / INTERVAL_S  # kWh in a quarter hour -> W
    return [
        {
            "start": item["bucket"],
            "consumption_w": round(item["consumption_kwh"] * per_kwh, 1),
            "production_w": round(item["production_kwh"] * per_kwh, 1),
        }
        for item in gross["timeline"]
    ]
