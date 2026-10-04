"""Give every ZEV its buildings and attach its metering points (#890, ADR 0029).

The rule follows the ZEV type (SPEC-2026-10-buildings-and-sites §4.5):

- a ZEV is one property: one building, every metering point in it;
- a vZEV joins several properties: one building per distinct participant
  address, each metering point in the building of the participant(s) of its
  latest assignment, the rest in the default building (the issuer's, else one
  carrying only the ZEV's postal code).

The address is a guess to be checked: a participant's billing address is not
necessarily where its meter is. The same rule lives in
``zev.buildings.assign_buildings_from_participants`` for the transfer
importer; this file re-implements it on the historical models.
"""

from django.db import migrations


def _norm(value):
    return (value or "").strip().casefold()


def _key(address_line1, postal_code, city):
    if not (address_line1 or "").strip():
        return None
    return (_norm(address_line1), _norm(postal_code), _norm(city))


def _name(address_line1, postal_code, city, fallback):
    if (address_line1 or "").strip():
        return address_line1.strip()
    return f"{postal_code or ''} {city or ''}".strip() or fallback


def _issuer_party(ZevPartyRole, zev):
    rows = ZevPartyRole.objects.filter(zev=zev, role="issuer").select_related("party")
    row = rows.filter(valid_to__isnull=True).order_by("-valid_from").first() or rows.order_by("-valid_from").first()
    return row.party if row else None


def _initial_fields(zev, issuer):
    if (
        issuer is not None
        and (issuer.address_line1 or "").strip()
        and (not zev.postal_code or zev.postal_code == issuer.postal_code)
    ):
        return {
            "name": _name(issuer.address_line1, issuer.postal_code, issuer.city, zev.name),
            "address_line1": issuer.address_line1,
            "address_line2": issuer.address_line2,
            "postal_code": issuer.postal_code,
            "city": issuer.city,
        }
    return {"name": zev.name, "address_line1": "", "address_line2": "", "postal_code": zev.postal_code, "city": ""}


def to_buildings(apps, schema_editor):
    Zev = apps.get_model("zev", "Zev")
    Building = apps.get_model("zev", "Building")
    Participant = apps.get_model("zev", "Participant")
    MeteringPoint = apps.get_model("zev", "MeteringPoint")
    Assignment = apps.get_model("zev", "MeteringPointAssignment")
    ZevPartyRole = apps.get_model("zev", "ZevPartyRole")

    for zev in Zev.objects.all().iterator():
        issuer = _issuer_party(ZevPartyRole, zev)
        points = MeteringPoint.objects.filter(zev=zev)

        if zev.zev_type != "vzev":
            building = Building.objects.create(zev=zev, **_initial_fields(zev, issuer))
            points.update(building=building)
            continue

        buildings = {}
        by_participant = {}
        participants = (
            Participant.objects.filter(zev=zev)
            .select_related("party")
            .order_by("party__sort_name", "party__first_name", "id")
        )
        for participant in participants:
            party = participant.party
            key = _key(party.address_line1, party.postal_code, party.city)
            if key is None:
                continue
            if key not in buildings:
                buildings[key] = Building.objects.create(
                    zev=zev,
                    name=_name(party.address_line1, party.postal_code, party.city, zev.name),
                    address_line1=party.address_line1,
                    address_line2=party.address_line2,
                    postal_code=party.postal_code,
                    city=party.city,
                )
            by_participant[participant.pk] = buildings[key]

        issuer_key = _key(issuer.address_line1, issuer.postal_code, issuer.city) if issuer is not None else None
        fallback = buildings.get(issuer_key) if issuer_key is not None else None

        assignments = {}
        for row in Assignment.objects.filter(metering_point__zev=zev):
            assignments.setdefault(row.metering_point_id, []).append(row)

        for point in points:
            rows = assignments.get(point.pk, [])
            target = None
            if rows:
                latest = max(row.valid_from for row in rows)
                found = {by_participant.get(row.participant_id) for row in rows if row.valid_from == latest}
                if len(found) == 1 and None not in found:
                    target = next(iter(found))
            if target is None:
                if fallback is None:
                    fallback = Building.objects.create(zev=zev, **_initial_fields(zev, issuer))
                target = fallback
            MeteringPoint.objects.filter(pk=point.pk).update(building=target)

        if not Building.objects.filter(zev=zev).exists():
            Building.objects.create(zev=zev, **_initial_fields(zev, issuer))


class Migration(migrations.Migration):

    dependencies = [
        ("zev", "0040_building"),
    ]

    operations = [migrations.RunPython(to_buildings, migrations.RunPython.noop)]
