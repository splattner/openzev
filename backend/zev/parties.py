"""Dated roles of a ZEV's parties — who holds which role on a given day (#761).

The issuer, the representative toward the grid operator and the landowners of
a ZEV are ``ZevPartyRole`` rows (ADR 0028, SPEC-2026-10-zev-parties §4.5). A
document asks who held a role on its own date: an invoice on its
``period_end``, a contract on its ``rendered_on``, an annual statement on
31 December of its year. Writes go through ``assign_role`` / ``end_role``,
which keep the windows of a single-holder role from overlapping.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.core.exceptions import ValidationError
from django.db import transaction

from allocation.validity import active_on

from .access import NO_MANAGER_LEFT
from .models import MANAGING_ROLES, SINGLE_HOLDER_ROLES, Party, PartyRole, ZevPartyRole


def holders_on(zev, role: str, day: date):
    """Parties holding ``role`` in ``zev`` on ``day``."""
    rows = active_on(ZevPartyRole.objects.filter(zev=zev, role=role), day)
    return Party.objects.filter(pk__in=rows.values("party_id"))


def holder_on(zev, role: str, day: date) -> Party | None:
    """The party holding a single-holder ``role`` on ``day``, or ``None``."""
    row = (
        active_on(ZevPartyRole.objects.filter(zev=zev, role=role), day)
        .select_related("party")
        .order_by("-valid_from")
        .first()
    )
    return row.party if row else None


def issuer_on(zev, day: date) -> Party | None:
    """Whom ``zev``'s documents dated ``day`` are from, or ``None``."""
    return holder_on(zev, PartyRole.ISSUER, day)


def representative_on(zev, day: date) -> Party | None:
    return holder_on(zev, PartyRole.REPRESENTATIVE, day)


def _create(zev, party, role, valid_from, valid_to, building=None) -> ZevPartyRole:
    row = ZevPartyRole(zev=zev, party=party, role=role, valid_from=valid_from, valid_to=valid_to, building=building)
    row.full_clean()
    row.save()
    return row


def _keeps_a_manager(zev, had_manager: bool) -> None:
    """Refuse a role change that leaves a managed ZEV without any manager today.

    The issuer and the representative manage the ZEV through their role (ADR
    0028, amended); handing a role to a party without an account, or ending it,
    can take the last manager away. Called inside the change's transaction, so
    raising rolls it back.
    """
    from .access import has_manager

    if had_manager and not has_manager(zev):
        raise ValidationError({"party": NO_MANAGER_LEFT})


@transaction.atomic
def assign_role(
    zev, party, role: str, valid_from: date, *, valid_to: date | None = None, building=None
) -> ZevPartyRole:
    """Give ``party`` ``role`` from ``valid_from``.

    For the issuer and the representative, the holder on ``valid_from`` is
    ended the day before (a window that would become empty is deleted); a
    holder starting after ``valid_from`` must be ended first. A landowner is
    simply added, once per party and building (``building`` names the one it
    owns and is accepted for landowners only).
    """
    if party.zev_id != zev.pk:
        raise ValidationError({"party": "The party belongs to another ZEV."})
    if valid_to is not None and valid_to < valid_from:
        raise ValidationError({"valid_to": "The role cannot end before it starts."})
    if building is not None:
        if role != PartyRole.LANDOWNER:
            raise ValidationError({"building": "Only a landowner role names a building."})
        if building.zev_id != zev.pk:
            raise ValidationError({"building": "The building belongs to another ZEV."})
    rows = list(ZevPartyRole.objects.select_for_update().filter(zev=zev, role=role).order_by("valid_from"))

    if role in MANAGING_ROLES:
        from .access import has_manager

        had_manager = has_manager(zev)

    if role not in SINGLE_HOLDER_ROLES:
        building_id = building.pk if building is not None else None
        if any(row.party_id == party.pk and row.valid_to is None and row.building_id == building_id for row in rows):
            if building is not None:
                raise ValidationError({"party": "The party already owns this building."})
            raise ValidationError({"party": "The party already holds this role."})
        return _create(zev, party, role, valid_from, valid_to, building)

    if any(row.valid_from > valid_from for row in rows):
        raise ValidationError({"valid_from": "A later holder exists; end it first."})
    for row in rows:
        if row.valid_to is not None and row.valid_to < valid_from:
            continue
        if row.party_id == party.pk and row.valid_to is None and valid_to is None:
            return row
        _end(row, valid_from - timedelta(days=1))
    created = _create(zev, party, role, valid_from, valid_to)
    if role in MANAGING_ROLES:
        _keeps_a_manager(zev, had_manager)
    return created


@transaction.atomic
def set_landowner_building(row: ZevPartyRole, building) -> ZevPartyRole:
    """Point a landowner row at the building it owns (``None``: not specified).

    The row's dates are unchanged. Refuses other roles and a building the
    party already owns through another open row."""
    if row.role != PartyRole.LANDOWNER:
        raise ValidationError({"building": "Only a landowner role names a building."})
    if building is not None and building.zev_id != row.zev_id:
        raise ValidationError({"building": "The building belongs to another ZEV."})
    if row.valid_to is None and ZevPartyRole.objects.filter(
        zev_id=row.zev_id, party_id=row.party_id, role=row.role, valid_to__isnull=True, building=building
    ).exclude(pk=row.pk).exists():
        raise ValidationError({"party": "The party already owns this building." if building else "The party already holds this role."})
    row.building = building
    row.save(update_fields=["building", "updated_at"])
    return row


def _end(row: ZevPartyRole, last_day: date) -> ZevPartyRole | None:
    if last_day < row.valid_from:
        row.delete()
        return None
    row.valid_to = last_day
    row.save(update_fields=["valid_to", "updated_at"])
    return row


@transaction.atomic
def end_role(row: ZevPartyRole, last_day: date) -> ZevPartyRole | None:
    """End ``row`` on ``last_day``; a row that would end before it starts is deleted.

    Ending the issuer or representative role must not leave the ZEV without a
    manager (``ValidationError``)."""
    managing = row.role in MANAGING_ROLES
    if managing:
        from .access import has_manager

        had_manager = has_manager(row.zev_id)
    ended = _end(row, last_day)
    if managing:
        _keeps_a_manager(row.zev_id, had_manager)
    return ended


def ensure_initial_roles(zev, party, valid_from: date) -> None:
    """Make ``party`` the issuer and a landowner from ``valid_from``, unless the
    ZEV already has an issuer — what creating a ZEV with its owner sets up."""
    if ZevPartyRole.objects.filter(zev=zev, role=PartyRole.ISSUER).exists():
        return
    _create(zev, party, PartyRole.ISSUER, valid_from, None)
    _create(zev, party, PartyRole.LANDOWNER, valid_from, None)
