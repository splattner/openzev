"""Who may view or manage a ZEV — the one place that question is answered.

Access is per ZEV (ADR 0027, SPEC-2026-10-zev-access-grants §5): an account
manages a ZEV through an active ``manager`` grant, views it through an active
``manager`` or ``viewer`` grant, and reaches its own rows as a participant
through ``Participant.user``. An admin may do everything and needs no grant;
``can_manage``/``can_view`` say so, while the id-set helpers return only what
the account holds itself, so a caller that filters by them checks
``user.is_admin`` first (as every scoping branch already does).

"Today" is the Swiss civil date (``timezone.localdate()``, ADR 0026). Grant
lookups are memoised on the user instance per day, so a request costs one grant
query and one participant query however often it asks; ``invalidate`` drops the
memo after a write that changes the answer.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from allocation.validity import active_on

from .models import Participant, ZevAccessGrant, ZevAccessRole

_CACHE_ATTR = "_zev_access_cache"


def _today() -> date:
    return timezone.localdate()


def _memo(user) -> dict:
    today = _today()
    memo = getattr(user, _CACHE_ATTR, None)
    if memo is None or memo["day"] != today:
        memo = {"day": today}
        setattr(user, _CACHE_ATTR, memo)
    return memo


def invalidate(user) -> None:
    """Forget what was memoised for ``user`` (after granting or revoking)."""
    if user is not None and hasattr(user, _CACHE_ATTR):
        delattr(user, _CACHE_ATTR)


def _is_account(user) -> bool:
    return user is not None and getattr(user, "is_authenticated", False) and user.pk is not None


def _grant_sets(user) -> tuple[frozenset, frozenset]:
    memo = _memo(user)
    if "grants" not in memo:
        managed, viewable = set(), set()
        rows = active_on(ZevAccessGrant.objects.filter(user=user), memo["day"]).values_list("zev_id", "role")
        for zev_id, role in rows:
            viewable.add(zev_id)
            if role == ZevAccessRole.MANAGER:
                managed.add(zev_id)
        memo["grants"] = (frozenset(managed), frozenset(viewable))
    return memo["grants"]


def managed_zev_ids(user) -> frozenset:
    """ZEVs the account holds an active ``manager`` grant for."""
    return _grant_sets(user)[0] if _is_account(user) else frozenset()


def viewable_zev_ids(user) -> frozenset:
    """ZEVs the account holds an active ``manager`` or ``viewer`` grant for."""
    return _grant_sets(user)[1] if _is_account(user) else frozenset()


def live_participant_q(prefix: str = "") -> Q:
    """Participant rows still current today: ``valid_to`` open or not yet passed.

    Rows that start in the future count as current, as they always have, so a
    participant can be onboarded before their start date.
    """
    return Q(**{f"{prefix}valid_to__isnull": True}) | Q(**{f"{prefix}valid_to__gte": _today()})


def participant_zev_ids(user, *, include_ended: bool = False) -> frozenset:
    """ZEVs the account is linked to as a participant (current rows only by default)."""
    if not _is_account(user):
        return frozenset()
    memo = _memo(user)
    key = "participant_all" if include_ended else "participant_live"
    if key not in memo:
        rows = Participant.objects.filter(user=user)
        if not include_ended:
            rows = rows.filter(live_participant_q())
        memo[key] = frozenset(rows.values_list("zev_id", flat=True))
    return memo[key]


def _zev_id(zev):
    """A ``Zev``, a ``UUID`` or an id string (as query parameters carry it) → ``UUID``."""
    zev_id = getattr(zev, "pk", zev)
    if isinstance(zev_id, uuid.UUID):
        return zev_id
    try:
        return uuid.UUID(str(zev_id))
    except (ValueError, AttributeError, TypeError):
        return None


def can_manage(user, zev) -> bool:
    if not _is_account(user):
        return False
    return user.is_admin or _zev_id(zev) in managed_zev_ids(user)


def can_view(user, zev) -> bool:
    if not _is_account(user):
        return False
    return user.is_admin or _zev_id(zev) in viewable_zev_ids(user)


def active_grants(user):
    """The account's grants in effect today, oldest ZEV relationship first."""
    return active_on(ZevAccessGrant.objects.filter(user=user), _today()).select_related("zev")


def is_last_manager(grant: ZevAccessGrant) -> bool:
    """Whether ``grant`` is the only active manager grant of its ZEV."""
    if grant.role != ZevAccessRole.MANAGER:
        return False
    managers = active_on(ZevAccessGrant.objects.filter(zev_id=grant.zev_id, role=ZevAccessRole.MANAGER), _today())
    return not managers.exclude(pk=grant.pk).exists()


def revoke(grant: ZevAccessGrant, *, today: date | None = None) -> ZevAccessGrant | None:
    """End ``grant`` so it no longer applies today.

    The window is inclusive, so ending it *today* would leave today's access in
    place: it ends yesterday instead. A grant that has not taken effect yet
    (starts today or later) never applied and is deleted. An already-ended grant
    is left alone. Returns the ended row, or ``None`` when it was deleted.
    """
    today = today or _today()
    if grant.valid_to is not None and grant.valid_to < today:
        return grant
    if grant.valid_from >= today:
        grant.delete()
        return None
    grant.valid_to = today - timedelta(days=1)
    grant.save(update_fields=["valid_to", "updated_at"])
    return grant


@transaction.atomic
def change_role(grant: ZevAccessGrant, role: str, *, by=None) -> ZevAccessGrant:
    """End ``grant`` and open a new one with ``role`` from today.

    Two rows rather than an edit, so the history shows when the role changed.
    """
    zev_id, user_id = grant.zev_id, grant.user_id
    revoke(grant)
    return ZevAccessGrant.objects.create(
        zev_id=zev_id, user_id=user_id, role=role, valid_from=_today(), granted_by=by,
    )


@transaction.atomic
def sync_owner_grant(zev, previous_owner_id=None) -> None:
    """Make ``zev.owner`` hold an active manager grant; revoke the previous owner's.

    The transitional invariant of #761 phase 1 (spec §4.7): until the party
    layer replaces ``Zev.owner``, owning a ZEV implies managing it, as the old
    ``owner == user`` checks did, and handing ownership on takes that away from
    the previous owner. Called from ``Zev.save`` on create and on owner change.
    Not enforced afterwards: a manager may revoke the owner's grant (a legal
    owner handing management to a Verwaltung).
    """
    today = _today()
    grants = ZevAccessGrant.objects.select_for_update().filter(zev_id=zev.pk)
    if previous_owner_id is not None and previous_owner_id != zev.owner_id:
        for grant in active_on(grants.filter(user_id=previous_owner_id, role=ZevAccessRole.MANAGER), today):
            revoke(grant, today=today)
    if active_on(grants.filter(user_id=zev.owner_id, role=ZevAccessRole.MANAGER), today).exists():
        return
    open_grant = grants.filter(user_id=zev.owner_id, valid_to__isnull=True).first()
    if open_grant is not None:
        # A viewer grant, or a manager grant that starts later: promote it now.
        change_role(open_grant, ZevAccessRole.MANAGER)
    else:
        ZevAccessGrant.objects.create(
            zev_id=zev.pk, user_id=zev.owner_id, role=ZevAccessRole.MANAGER, valid_from=today,
        )


def ensure_a_manager(zev) -> None:
    """Give ``zev.owner`` a manager grant when the ZEV has no active manager at all.

    For paths that write a ZEV without ``Zev.save`` — a per-ZEV backup restore
    recreating a deleted community loads it raw and keeps (does not restore)
    grants. A ZEV that still has managers is left exactly as it is.
    """
    managers = ZevAccessGrant.objects.filter(zev_id=zev.pk, role=ZevAccessRole.MANAGER)
    if not active_on(managers, _today()).exists():
        sync_owner_grant(zev)
