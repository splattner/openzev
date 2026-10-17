"""Who may read which part of a ZEV's analytics dataset (ADR 0039).

The answer is one :class:`~analytics.dataset.Visibility` per request and ZEV. The
rules reuse :mod:`zev.access`; nothing here widens what the same account sees
elsewhere in the API, and a token never exceeds the account that created it.
"""

from __future__ import annotations

from rest_framework.exceptions import PermissionDenied

from zev import access
from zev.models import Participant

from .dataset import Visibility
from .models import AnalyticsToken


def _own_participant_ids(user, zev) -> frozenset:
    """The account's current participant records in ``zev`` (none while the ZEV is disabled)."""
    if zev.disabled_at is not None:
        return frozenset()
    return frozenset(
        Participant.objects.filter(access.live_participant_q(), user=user, zev=zev).values_list("id", flat=True)
    )


def can_create_token(user, zev, participant=None) -> bool:
    """Whether ``user`` may mint a token for ``zev`` (or for one of its participants).

    A whole-ZEV token needs a view of the whole ZEV. A participant token also
    goes to the participant themself, or to a manager acting for them.
    """
    if participant is None:
        return access.can_view(user, zev)
    if participant.user_id == user.pk and participant.pk in _own_participant_ids(user, zev):
        return True
    return access.can_manage(user, zev)


def token_is_still_valid(token: AnalyticsToken) -> bool:
    """The token's creator can still reach what it is scoped to."""
    return can_create_token(token.created_by, token.zev, token.participant)


def resolve_visibility(request, zev) -> Visibility:
    """What ``request`` may see in ``zev``; raises 403 when nothing."""
    token = request.auth if isinstance(request.auth, AnalyticsToken) else None
    user = token.created_by if token is not None else request.user

    if token is not None:
        if token.zev_id != zev.pk:
            raise PermissionDenied("This token is not valid for that ZEV.")
        if zev.disabled_at is not None:
            # An admin switched the community off; no external tool reads it meanwhile.
            raise PermissionDenied("This ZEV is disabled.")
        if not token_is_still_valid(token):
            raise PermissionDenied("The account that created this token no longer has access.")
        if token.participant_id is None:
            return Visibility(full=True)
        return Visibility(full=False, participant_ids=frozenset({token.participant_id}))

    if access.can_view(user, zev):
        return Visibility(full=True)
    own = _own_participant_ids(user, zev)
    if own:
        return Visibility(full=False, participant_ids=own)
    raise PermissionDenied("You have no access to this ZEV's data.")
