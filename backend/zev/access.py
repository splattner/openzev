"""Who may view or manage a ZEV — the one place that question is answered.

Access is per ZEV (ADR 0027, SPEC-2026-10-zev-access-grants §5): an account
manages a ZEV through an active ``manager`` grant, views it through an active
``manager`` or ``viewer`` grant, and reaches its own rows as a participant
through ``Participant.user``. An admin may do everything and needs no grant;
``can_manage``/``can_view`` say so, while the id-set helpers return only what
the account holds itself, so a caller that filters by them checks
``user.is_admin`` first (as every scoping branch already does).

"Today" is the Swiss civil date (``timezone.localdate()``, ADR 0026). Grant
lookups are memoised on the user instance, so a request costs one grant query
and one participant query however often it asks. The memo also carries the day
and a generation that every save or delete of a grant or participant row bumps
(``bump_generation``, wired in ``ZevConfig.ready``), so a user object that lives
longer than one request — a test client's forced user, a task — never answers
from stale rows; ``invalidate`` drops it outright.
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
_generation = 0


def bump_generation(**_kwargs) -> None:
    """Invalidate every memo: a grant or participant row changed."""
    global _generation
    _generation += 1


def _today() -> date:
    return timezone.localdate()


def _memo(user) -> dict:
    today = _today()
    memo = getattr(user, _CACHE_ATTR, None)
    if memo is None or memo["day"] != today or memo["generation"] != _generation:
        memo = {"day": today, "generation": _generation}
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


def grant_manager(zev, user, *, by=None) -> ZevAccessGrant:
    """Give ``user`` an active manager grant on ``zev`` from today.

    What creating a ZEV for an account does (wizard, self-setup, transfer
    import): the creator manages what it created. An open grant the account
    already holds is promoted rather than duplicated.
    """
    today = _today()
    grants = ZevAccessGrant.objects.filter(zev_id=_zev_id(zev), user=user)
    current = active_on(grants.filter(role=ZevAccessRole.MANAGER), today).first()
    if current is not None:
        return current
    open_grant = grants.filter(valid_to__isnull=True).first()
    if open_grant is not None:
        return change_role(open_grant, ZevAccessRole.MANAGER, by=by)
    return ZevAccessGrant.objects.create(
        zev_id=_zev_id(zev), user=user, role=ZevAccessRole.MANAGER, valid_from=today, granted_by=by,
    )


def build_memberships(grants, participants, *, today: date | None = None) -> list[dict]:
    """One entry per ZEV the account relates to, for ``/auth/me`` and the admin
    accounts list (spec §7.7).

    ``grants`` are the account's active grants and ``participants`` all its
    participant rows (current and ended, so a former participant can still
    reach its invoices), each with ``zev`` loaded — passed in rather than
    queried so a list of accounts can build this from prefetched rows.
    """
    today = today or _today()
    by_zev: dict = {}

    def entry(zev):
        return by_zev.setdefault(zev.pk, {
            "zev": str(zev.pk),
            "zev_name": zev.name,
            "zev_disabled": zev.disabled_at is not None,
            "access": None,
            "participants": [],
        })

    for grant in grants:
        entry(grant.zev)["access"] = grant.role
    for participant in participants:
        entry(participant.zev)["participants"].append({
            "id": str(participant.pk),
            "valid_from": participant.valid_from.isoformat(),
            "valid_to": participant.valid_to.isoformat() if participant.valid_to else None,
            "live": participant.valid_to is None or participant.valid_to >= today,
        })
    return sorted(by_zev.values(), key=lambda item: (item["zev_name"].lower(), item["zev"]))


def memberships_for(user) -> list[dict]:
    """``build_memberships`` for one account, with its own queries."""
    return build_memberships(
        active_grants(user),
        Participant.objects.filter(user=user).select_related("zev").order_by("valid_from", "id"),
    )


def active_grants_prefetch():
    """``Prefetch`` of each account's active grants into ``active_zev_grants``."""
    from django.db.models import Prefetch

    return Prefetch(
        "zev_grants",
        queryset=active_on(ZevAccessGrant.objects.select_related("zev"), _today()),
        to_attr="active_zev_grants",
    )
