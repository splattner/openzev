"""One normalized list of the account's bearer credentials (SPEC-2026-tokens-and-keys).

There are three kinds, each with its own model, prefix and lifecycle:

- ``api_key`` (``ozv_``): acts as its owner, read-only if so created;
- ``analytics`` (``oza_``): reads the analytics series of one ZEV or participant;
- ``energy_push`` (``ozs_``): delivers readings into one energy data source.

This module only *reads* them into one row shape. Creating, revoking and
rotating stay on each kind's own endpoint, so no rule is written twice. The
other apps are imported inside the functions: ``accounts`` is imported by every
app, and importing them at module level would be a cycle.
"""

from __future__ import annotations

from django.utils import timezone

KINDS = ("api_key", "analytics", "energy_push")
STATUSES = ("active", "expired", "revoked")


def _scope(*, zev=None, participant=None, metering_point=None) -> dict:
    return {
        "zev": str(zev.pk) if zev else None,
        "zev_name": zev.name if zev else None,
        "participant": str(participant.pk) if participant else None,
        "participant_name": participant.full_name if participant else None,
        "metering_point": str(metering_point.pk) if metering_point else None,
        "meter_id": metering_point.meter_id if metering_point else None,
    }


def _status(expires_at, revoked_at=None) -> str:
    if revoked_at is not None:
        return "revoked"
    if expires_at is not None and expires_at <= timezone.now():
        return "expired"
    return "active"


def _owner(user) -> dict:
    return {"id": user.pk, "username": user.username, "email": user.email}


def _api_key_rows(users=None):
    from .models import ApiKey

    keys = ApiKey.objects.select_related("user")
    if users is not None:
        keys = keys.filter(user=users)
    for key in keys:
        yield key.user, {
            "kind": "api_key",
            "id": str(key.pk),
            "name": key.name,
            "prefix": f"ozv_{key.prefix}",
            "access": "read_only" if key.read_only else "read_write",
            "held_by": "account",
            "scope": _scope(),
            "created_at": key.created_at,
            "expires_at": key.expires_at,
            "last_used_at": key.last_used_at,
            "revoked_at": key.revoked_at,
            "status": _status(key.expires_at, key.revoked_at),
            "actions": ["revoke"],
            "manage_url": None,
        }


def _analytics_rows(users=None):
    from analytics.authentication import tokens_enabled
    from analytics.models import TOKEN_NAMESPACE, AnalyticsToken

    if not tokens_enabled():
        return
    tokens = AnalyticsToken.objects.select_related("zev", "participant", "participant__party", "created_by")
    if users is not None:
        tokens = tokens.filter(created_by=users)
    for token in tokens:
        yield token.created_by, {
            "kind": "analytics",
            "id": str(token.pk),
            "name": token.name,
            "prefix": f"{TOKEN_NAMESPACE}_{token.prefix}",
            "access": "read",
            "held_by": "account",
            "scope": _scope(zev=token.zev, participant=token.participant),
            "created_at": token.created_at,
            "expires_at": token.expires_at,
            "last_used_at": token.last_used_at,
            "revoked_at": token.revoked_at,
            "status": _status(token.expires_at, token.revoked_at),
            "actions": ["revoke"],
            "manage_url": None,
        }


def _energy_rows(users=None):
    """Push tokens of energy data sources.

    A participant-held source's token belongs to the participant's account. A ZEV-held source
    (``held_by = zev``: a metering point nobody holds personally, or the grid connection point)
    has no participant; its token is listed for every manager of the ZEV, and in the admin list
    without an owner (SPEC-2026-live-energy-data §3).
    """
    from django.db.models import Q

    from metering.models import PUSH_TOKEN_NAMESPACE, SourceHolder, SupplementarySource
    from metering.supplementary.permissions import feature_enabled
    from zev import access

    if not feature_enabled():
        return
    sources = SupplementarySource.objects.filter(push_token_prefix__isnull=False).select_related(
        "zev", "metering_point", "participant", "participant__party", "participant__user",
    )
    zev_held = Q(held_by=SourceHolder.ZEV)
    if users is not None:
        sources = sources.filter(
            Q(participant__user=users) | (zev_held & Q(zev_id__in=access.managed_zev_ids(users)))
        )
    else:
        sources = sources.filter(Q(participant__user__isnull=False) | zev_held)
    for source in sources:
        point = source.metering_point
        held_by_zev = source.held_by == SourceHolder.ZEV
        yield (None if held_by_zev else source.participant.user), {
            "kind": "energy_push",
            "id": str(source.pk),
            "name": source.label or (point.meter_id if point else source.zev.name),
            "prefix": f"{PUSH_TOKEN_NAMESPACE}_{source.push_token_prefix}",
            "access": "write_readings",
            "held_by": "zev" if held_by_zev else "account",
            "scope": _scope(zev=source.zev, participant=source.participant, metering_point=point),
            "created_at": source.push_token_created_at,
            "expires_at": None,
            "last_used_at": source.push_token_last_used_at,
            "revoked_at": None,
            "status": "active",
            "actions": ["rotate", "revoke"],
            "manage_url": "/metering/points" if held_by_zev else "/me/metering-points",
        }


def list_credentials(user=None, *, kind=None, status=None, owner_id=None) -> list[dict]:
    """Rows for ``user``'s own credentials, or every account's when ``user`` is ``None``.

    Without ``user`` (the admin list) each row carries its ``owner`` and revoked
    credentials are included; the account's own list leaves revoked ones out.
    ``owner_id`` narrows the admin list to one account. A ZEV-held push token has no
    owner (``owner`` is ``None``), so an ``owner_id`` filter leaves it out.
    """
    builders = {"api_key": _api_key_rows, "analytics": _analytics_rows, "energy_push": _energy_rows}
    rows: list[dict] = []
    for name, build in builders.items():
        if kind and kind != name:
            continue
        for owner, row in build(user):
            if user is not None:
                if row["status"] == "revoked":
                    continue
            else:
                if owner_id is not None and (owner is None or owner.pk != owner_id):
                    continue
                row["owner"] = _owner(owner) if owner is not None else None
            if status and row["status"] != status:
                continue
            rows.append(row)

    # Newest first; rows without a creation time (older push tokens) last.
    rows.sort(key=lambda row: (row["created_at"] is None, -(row["created_at"].timestamp() if row["created_at"] else 0), row["kind"], row["id"]))
    return rows


def can_create(user) -> dict:
    """What the account may create from the Tokens & keys screen."""
    from analytics.authentication import tokens_enabled
    from zev import access

    analytics = tokens_enabled() and bool(
        user.is_admin or access.viewable_zev_ids(user) or access.participant_zev_ids(user)
    )
    return {"api_key": True, "analytics": analytics}
