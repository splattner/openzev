"""Validity-window and civil-time helpers (dependency-free).

These predicates express ``valid_from``/``valid_to`` overlap and the
conversions between civil dates and stored instants. They deliberately live
outside :mod:`allocation.read_model`, which imports ``zev``/``metering``
models: model layers (``accounts``, ``tariffs``, ``zev``) need the predicates
in ``clean()``/query code, and importing them from the read model would force
deferred imports to dodge app-loading cycles. This module depends only on
Django's settings and ORM expressions and the stdlib, so every consumer
imports it at module level.

Timestamps are stored as UTC instants; every calendar question — which day,
hour, weekday or month a reading belongs to, where a billing period starts —
is answered in the business timezone, ``settings.TIME_ZONE``
(Europe/Zurich). This module is the one place that converts between the two
(ADR 0026). A civil day runs from local midnight to the next local midnight,
so it is 23, 24 or 25 hours long: never add ``timedelta(days=1)`` to an
instant to reach the next day.
"""

from datetime import date, datetime, timedelta, timezone
from functools import cache
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import models


def active_during(queryset, start: date, end: date):
    """Rows with ``valid_from <= end`` and (``valid_to`` null or ``>= start``)."""
    return queryset.filter(valid_from__lte=end).filter(
        models.Q(valid_to__isnull=True) | models.Q(valid_to__gte=start)
    )


def active_on(queryset, day: date):
    """Rows active on exactly ``day``."""
    return active_during(queryset, day, day)


@cache
def business_tz() -> ZoneInfo:
    """The timezone every civil date and wall-clock time is read in."""
    return ZoneInfo(settings.TIME_ZONE)


def period_start_dt(day: date) -> datetime:
    """Inclusive UTC lower bound for a civil date: its local midnight.

    Swiss DST changes happen at 02:00/03:00, so local midnight is never
    ambiguous or missing.
    """
    local = datetime(day.year, day.month, day.day, tzinfo=business_tz())
    return local.astimezone(timezone.utc)


def period_end_exclusive_dt(day: date) -> datetime:
    """Exclusive UTC upper bound for a civil date: the next local midnight."""
    return period_start_dt(day + timedelta(days=1))


def period_window(period_start: date, period_end: date) -> tuple[datetime, datetime]:
    """UTC bounds for a civil-date period: [start 00:00, end+1d 00:00), local.

    Use the half-open helpers above for one-sided ranges. Never use
    ``timestamp__date__`` lookups: they depend on the connection timezone
    instead of these helpers (ADR 0026).
    """
    return period_start_dt(period_start), period_end_exclusive_dt(period_end)


def day_length(day: date) -> timedelta:
    """How long ``day`` is in civil time: 23 h, 24 h or 25 h."""
    return period_end_exclusive_dt(day) - period_start_dt(day)


def civil_date(ts: datetime) -> date:
    """The civil date an instant falls on.

    A naive datetime is refused: every timestamp that reaches this comes from
    the ORM or an importer and is aware, and guessing a zone here is how a
    reading silently moves to the neighbouring day.
    """
    if ts.tzinfo is None:
        raise ValueError(f"civil_date() needs an aware datetime, got {ts!r}.")
    return ts.astimezone(business_tz()).date()


def wall_clock(ts: datetime) -> datetime:
    """An instant as local wall-clock time.

    A naive datetime is returned unchanged: callers that walk synthetic time
    (``tariffs.periods.average_percentage``) already work on a wall clock.
    """
    if ts.tzinfo is None:
        return ts
    return ts.astimezone(business_tz())
