"""How small a community may be before its ZEV-wide totals are withheld from a participant.

A participant can always read their own rows. With ``k`` participants,
"ZEV total minus mine" is the combined load of ``k - 1`` neighbours, so below a
floor it would be one neighbour's profile (``k = 2``) or close to it. The floor
is not configurable; above it, an administrator sets the value under Platform →
Settings, and an unset value follows ``ANALYTICS_MIN_PARTICIPANTS_FOR_ZEV_AGGREGATE``.
"""

from django.conf import settings

AGGREGATE_FLOOR = 3


def platform_default() -> int:
    """The value an unset setting resolves to: the environment's, never below the floor."""
    return max(AGGREGATE_FLOOR, settings.ANALYTICS_MIN_PARTICIPANTS_FOR_ZEV_AGGREGATE)


def min_participants_for_zev_aggregate() -> int:
    """Participants needed on every day of a range for a participant to see ZEV totals."""
    from accounts.models import AppSettings

    configured = AppSettings.load().analytics_min_participants_for_aggregate
    return max(AGGREGATE_FLOOR, configured) if configured is not None else platform_default()
