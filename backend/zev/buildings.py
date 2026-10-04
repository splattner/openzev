"""Buildings of a ZEV — where its metering points are (#890, ADR 0029).

A ZEV always has at least one building. ``default_building`` is the one a
metering point falls back to; ``initial_building_fields`` is what a ZEV's first
building contains; ``assign_buildings_from_participants`` is the vZEV rule that
``zev.0041_buildings_from_existing_data`` re-implements on historical models
and the transfer importer applies to archives without buildings.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from .models import Building, Participant, PartyRole, ZevPartyRole, ZevType
from .parties import issuer_on

ADDRESS_FIELDS = ("address_line1", "address_line2", "postal_code", "city")


def building_name_for(address_line1: str, postal_code: str, city: str, fallback: str) -> str:
    """A building's label from an address: the street line, else the place, else ``fallback``."""
    if (address_line1 or "").strip():
        return address_line1.strip()
    place = f"{postal_code or ''} {city or ''}".strip()
    return place or fallback


def address_key(party) -> tuple[str, str, str] | None:
    """What makes two addresses the same building; ``None`` without a street line."""
    if not (party.address_line1 or "").strip():
        return None
    return tuple((value or "").strip().casefold() for value in (party.address_line1, party.postal_code, party.city))


def _issuer_party(zev):
    party = issuer_on(zev, timezone.localdate())
    if party is not None:
        return party
    row = (
        ZevPartyRole.objects.filter(zev=zev, role=PartyRole.ISSUER)
        .select_related("party")
        .order_by("-valid_from")
        .first()
    )
    return row.party if row else None


def initial_building_fields(zev, *, issuer=None) -> dict:
    """The fields of a ZEV's first building.

    The issuer's address when it has a street line and lives at the grid
    connection's postal code (or the ZEV has none); otherwise just the ZEV's
    postal code, named after the ZEV.
    """
    if issuer is None:
        issuer = _issuer_party(zev)
    if (
        issuer is not None
        and (issuer.address_line1 or "").strip()
        and (not zev.postal_code or zev.postal_code == issuer.postal_code)
    ):
        return {
            "name": building_name_for(issuer.address_line1, issuer.postal_code, issuer.city, zev.name),
            "address_line1": issuer.address_line1,
            "address_line2": issuer.address_line2,
            "postal_code": issuer.postal_code,
            "city": issuer.city,
        }
    return {
        "name": zev.name,
        "address_line1": "",
        "address_line2": "",
        "postal_code": zev.postal_code,
        "city": "",
    }


@transaction.atomic
def default_building(zev) -> Building:
    """The ZEV's oldest building; creates the first one when it has none."""
    building = Building.objects.filter(zev=zev).order_by("created_at", "id").first()
    if building is None:
        building = Building.objects.create(zev=zev, **initial_building_fields(zev))
    return building


def ensure_initial_building(zev) -> Building:
    """Called by every creation flow once the issuer role exists."""
    return default_building(zev)


@transaction.atomic
def assign_buildings_from_participants(zev, points) -> None:
    """Attach ``points`` (metering points of ``zev``) to buildings (SPEC §4.5).

    A ZEV is one property: everything goes to its single building. A vZEV gets
    a building per distinct participant address; a point goes to the building
    of the participants of its latest assignment, else to the default building
    (the issuer's, when it has one).
    """
    points = list(points)
    if zev.zev_type != ZevType.VZEV:
        building = default_building(zev)
        for point in points:
            point.building = building
            point.save(update_fields=["building", "updated_at"])
        return

    buildings: dict[tuple, Building] = {}
    for building in Building.objects.filter(zev=zev).order_by("created_at", "id"):
        key = tuple((value or "").strip().casefold() for value in (building.address_line1, building.postal_code, building.city))
        buildings.setdefault(key, building)
    participants = list(
        Participant.objects.filter(zev=zev).select_related("party").order_by("party__sort_name", "party__first_name", "id")
    )
    by_participant: dict = {}
    for participant in participants:
        key = address_key(participant.party)
        if key is None:
            continue
        if key not in buildings:
            party = participant.party
            buildings[key] = Building.objects.create(
                zev=zev,
                name=building_name_for(party.address_line1, party.postal_code, party.city, zev.name),
                address_line1=party.address_line1,
                address_line2=party.address_line2,
                postal_code=party.postal_code,
                city=party.city,
            )
        by_participant[participant.pk] = buildings[key]

    issuer = _issuer_party(zev)
    issuer_key = address_key(issuer) if issuer is not None else None
    fallback = buildings.get(issuer_key) if issuer_key is not None else None

    from .models import MeteringPointAssignment

    for point in points:
        assignments = list(MeteringPointAssignment.objects.filter(metering_point=point))
        target = None
        if assignments:
            latest = max(a.valid_from for a in assignments)
            found = {by_participant.get(a.participant_id) for a in assignments if a.valid_from == latest}
            if len(found) == 1 and None not in found:
                target = next(iter(found))
        if target is None:
            if fallback is None:
                fields = initial_building_fields(zev, issuer=issuer)
                fallback = Building.objects.filter(zev=zev, **fields).order_by("created_at", "id").first()
                if fallback is None:
                    fallback = Building.objects.create(zev=zev, **fields)
            target = fallback
        point.building = target
        point.save(update_fields=["building", "updated_at"])
    default_building(zev)
