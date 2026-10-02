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
from django.db.models import Exists

from allocation.validity import active_on

from .models import SINGLE_HOLDER_ROLES, Party, PartyRole, ZevPartyRole


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
    """Whom ``zev``'s documents dated ``day`` are from, or ``None``.

    A ZEV that has never had an issuer falls back to the owner account's own
    participation, as before the roles existed — the case of a ZEV created
    without its owner as a participant, who is added later. The fallback goes
    with ``Zev.owner`` (SPEC-2026-10-zev-parties §11, PR 5).
    """
    party = holder_on(zev, PartyRole.ISSUER, day)
    if party is not None or zev.owner_id is None:
        return party
    any_issuer = ZevPartyRole.objects.filter(zev=zev, role=PartyRole.ISSUER)
    return (
        Party.objects.filter(zev=zev, participations__user_id=zev.owner_id)
        .exclude(Exists(any_issuer))
        .first()
    )


def representative_on(zev, day: date) -> Party | None:
    return holder_on(zev, PartyRole.REPRESENTATIVE, day)


def _create(zev, party, role, valid_from, valid_to) -> ZevPartyRole:
    row = ZevPartyRole(zev=zev, party=party, role=role, valid_from=valid_from, valid_to=valid_to)
    row.full_clean()
    row.save()
    return row


@transaction.atomic
def assign_role(zev, party, role: str, valid_from: date, *, valid_to: date | None = None) -> ZevPartyRole:
    """Give ``party`` ``role`` from ``valid_from``.

    For the issuer and the representative, the holder on ``valid_from`` is
    ended the day before (a window that would become empty is deleted); a
    holder starting after ``valid_from`` must be ended first. A landowner is
    simply added, once per party.
    """
    if party.zev_id != zev.pk:
        raise ValidationError({"party": "The party belongs to another ZEV."})
    if valid_to is not None and valid_to < valid_from:
        raise ValidationError({"valid_to": "The role cannot end before it starts."})
    rows = list(ZevPartyRole.objects.select_for_update().filter(zev=zev, role=role).order_by("valid_from"))

    if role not in SINGLE_HOLDER_ROLES:
        if any(row.party_id == party.pk and row.valid_to is None for row in rows):
            raise ValidationError({"party": "The party already holds this role."})
        return _create(zev, party, role, valid_from, valid_to)

    if any(row.valid_from > valid_from for row in rows):
        raise ValidationError({"valid_from": "A later holder exists; end it first."})
    for row in rows:
        if row.valid_to is not None and row.valid_to < valid_from:
            continue
        if row.party_id == party.pk and row.valid_to is None and valid_to is None:
            return row
        end_role(row, valid_from - timedelta(days=1))
    return _create(zev, party, role, valid_from, valid_to)


def end_role(row: ZevPartyRole, last_day: date) -> ZevPartyRole | None:
    """End ``row`` on ``last_day``; a row that would end before it starts is deleted."""
    if last_day < row.valid_from:
        row.delete()
        return None
    row.valid_to = last_day
    row.save(update_fields=["valid_to", "updated_at"])
    return row


def ensure_initial_roles(zev, party, valid_from: date) -> None:
    """Make ``party`` the issuer and a landowner from ``valid_from``, unless the
    ZEV already has an issuer — what creating a ZEV with its owner sets up."""
    if ZevPartyRole.objects.filter(zev=zev, role=PartyRole.ISSUER).exists():
        return
    _create(zev, party, PartyRole.ISSUER, valid_from, None)
    _create(zev, party, PartyRole.LANDOWNER, valid_from, None)
