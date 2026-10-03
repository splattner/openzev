"""Who may view or manage a ZEV — the one place that question is answered.

Access is per ZEV (ADR 0027, SPEC-2026-10-zev-access-grants §5): an account
manages a ZEV through an active ``manager`` grant, views it through an active
``manager`` or ``viewer`` grant, and reaches its own rows as a participant
through ``Participant.user``. An account also manages a ZEV while a party it
belongs to — through ``Party.user`` or one of the party's participations —
holds the issuer or representative role there (``MANAGING_ROLES``, ADR 0028
amended, SPEC-2026-10-zev-parties §5.5). That access is derived from the dated
role, never stored as a grant, so it starts and ends with the role. An admin may do everything and needs no grant;
``can_manage``/``can_view`` say so, while the id-set helpers return only what
the account holds itself, so a caller that filters by them checks
``user.is_admin`` first (as every scoping branch already does).

"Today" is the Swiss civil date (``timezone.localdate()``, ADR 0026). Grant
lookups are memoised on the user instance, so a request costs one grant query,
one role query and one participant query however often it asks. The memo also
carries the day and a generation that every save or delete of a grant,
participant, party or party role bumps
(``bump_generation``, wired in ``ZevConfig.ready``), so a user object that lives
longer than one request — a test client's forced user, a task — never answers
from stale rows; ``invalidate`` drops it outright.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import date, timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from allocation.validity import active_on

from .models import MANAGING_ROLES, Participant, ZevAccessGrant, ZevAccessRole, ZevPartyRole

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
        role_zevs = frozenset(role_holdings(user, memo["day"]).values_list("zev_id", flat=True))
        memo["grants"] = (frozenset(managed) | role_zevs, frozenset(viewable) | role_zevs)
    return memo["grants"]


def _party_of_account_q(user, prefix: str = "") -> Q:
    """Parties the account belongs to: its own (``Party.user``) or through a participation."""
    return Q(**{f"{prefix}user": user}) | Q(**{f"{prefix}participations__user": user})


def role_holdings(user, day: date | None = None):
    """The account's managing role rows in effect on ``day`` (issuer, representative)."""
    rows = ZevPartyRole.objects.filter(role__in=MANAGING_ROLES).filter(_party_of_account_q(user, "party__"))
    return active_on(rows, day or _today()).distinct()


def holds_managing_role_ever(user) -> bool:
    """Whether the account has ever been issuer or representative of any ZEV."""
    return ZevPartyRole.objects.filter(role__in=MANAGING_ROLES).filter(_party_of_account_q(user, "party__")).exists()


def party_accounts(party) -> list:
    """The accounts that belong to ``party``: its own, then its participations'."""
    accounts = []
    if party.user_id is not None:
        accounts.append(party.user)
    for participation in party.participations.select_related("user").exclude(user=None).order_by("-valid_from", "id"):
        if participation.user not in accounts:
            accounts.append(participation.user)
    return accounts


def role_managers(zev, day: date | None = None) -> list[tuple]:
    """``(account, role_row)`` for every account managing ``zev`` through its party's role on ``day``."""
    rows = active_on(
        ZevPartyRole.objects.filter(zev_id=_zev_id(zev), role__in=MANAGING_ROLES).select_related("party__user"),
        day or _today(),
    )
    return [(account, row) for row in rows for account in party_accounts(row.party)]


def role_holdings_by_account(day: date | None = None) -> dict:
    """Every managing role row in effect on ``day``, by account id — for a list
    of accounts, in a fixed number of queries (``build_memberships(roles=…)``)."""
    rows = active_on(ZevPartyRole.objects.filter(role__in=MANAGING_ROLES), day or _today())
    by_account: dict = {}
    for row in rows.select_related("zev", "party").prefetch_related("party__participations"):
        accounts = {row.party.user_id} | {participation.user_id for participation in row.party.participations.all()}
        for account_id in accounts - {None}:
            by_account.setdefault(account_id, []).append(row)
    return by_account


def has_manager(zev, *, exclude_grant=None, day: date | None = None) -> bool:
    """Whether ``zev`` has an account that manages it on ``day``, by grant or role."""
    grants = active_on(ZevAccessGrant.objects.filter(zev_id=_zev_id(zev), role=ZevAccessRole.MANAGER), day or _today())
    if exclude_grant is not None:
        grants = grants.exclude(pk=exclude_grant.pk)
    return grants.exists() or bool(role_managers(zev, day))


NO_MANAGER_LEFT = "This would leave the ZEV without a manager. Give someone manager access first."


class NoManagerLeft(Exception):
    """A change would leave a ZEV without any manager today."""


@contextmanager
def keeping_a_manager(*zevs):
    """Run a change that may take a ZEV's last manager away, and undo it if it does.

    Each of ``zevs`` that has a manager before the change must still have one
    after it, or the change's transaction is rolled back and ``NoManagerLeft``
    raised. Covers what manages without a grant of its own: unlinking or
    deleting the issuer's participant, deleting an account (its grants and its
    ``Party.user`` go with it).
    """
    zev_ids = {_zev_id(zev) for zev in zevs}
    with transaction.atomic():
        managed = [zev_id for zev_id in zev_ids if has_manager(zev_id)]
        yield
        if any(not has_manager(zev_id) for zev_id in managed):
            raise NoManagerLeft


def managed_zev_ids(user) -> frozenset:
    """ZEVs the account manages: an active ``manager`` grant, or a managing role."""
    return _grant_sets(user)[0] if _is_account(user) else frozenset()


def viewable_zev_ids(user) -> frozenset:
    """ZEVs the account may view: any active grant, or a managing role."""
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
    """Whether ending ``grant`` would leave its ZEV without a manager — no other
    manager grant and nobody managing through the issuer or representative role."""
    if grant.role != ZevAccessRole.MANAGER:
        return False
    return not has_manager(grant.zev_id, exclude_grant=grant)


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

    What a transfer import does for the importing account. The wizard and
    self-setup make the creator issuer instead (``grant_manager_until_role``). An open grant the account
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


def grant_manager_until_role(zev, user, role_start: date) -> ZevAccessGrant | None:
    """Bridge the days before ``user``'s managing role starts.

    Creating a ZEV makes the creator's party its issuer from the start date
    (ADR 0028, amended), and the role is all the access the creator needs. A
    ZEV that starts later would leave the creator locked out until then, so
    they get a manager grant from today that ends the day before the role
    starts. ``None`` when the role already applies today.
    """
    today = _today()
    if role_start <= today:
        return None
    return ZevAccessGrant.objects.create(
        zev_id=_zev_id(zev), user=user, role=ZevAccessRole.MANAGER,
        valid_from=today, valid_to=role_start - timedelta(days=1),
    )


def build_memberships(grants, participants, *, roles=(), today: date | None = None) -> list[dict]:
    """One entry per ZEV the account relates to, for ``/auth/me`` and the admin
    accounts list (spec §7.7).

    ``grants`` are the account's active grants and ``participants`` all its
    participant rows (current and ended, so a former participant can still
    reach its invoices), each with ``zev`` loaded — passed in rather than
    queried so a list of accounts can build this from prefetched rows.
    ``roles`` are its managing role rows in effect today (``role_holdings``,
    with ``zev``): each makes the entry's access ``manager`` and is listed
    under ``roles``.
    """
    today = today or _today()
    by_zev: dict = {}

    def entry(zev):
        return by_zev.setdefault(zev.pk, {
            "zev": str(zev.pk),
            "zev_name": zev.name,
            "zev_disabled": zev.disabled_at is not None,
            "access": None,
            "roles": [],
            "participants": [],
        })

    for grant in grants:
        entry(grant.zev)["access"] = grant.role
    for row in roles:
        item = entry(row.zev)
        item["access"] = ZevAccessRole.MANAGER
        if row.role not in item["roles"]:
            item["roles"].append(row.role)
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
        roles=role_holdings(user).select_related("zev").order_by("role"),
    )


def active_grants_prefetch():
    """``Prefetch`` of each account's active grants into ``active_zev_grants``."""
    from django.db.models import Prefetch

    return Prefetch(
        "zev_grants",
        queryset=active_on(ZevAccessGrant.objects.select_related("zev"), _today()),
        to_attr="active_zev_grants",
    )
