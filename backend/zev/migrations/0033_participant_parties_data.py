from django.db import migrations

FIELDS = (
    "title", "first_name", "last_name", "email", "phone",
    "address_line1", "address_line2", "postal_code", "city",
)


def to_parties(apps, schema_editor):
    """One person party per participant, with its names, contact data and address."""
    Participant = apps.get_model("zev", "Participant")
    Party = apps.get_model("zev", "Party")
    for participant in Participant.objects.filter(party__isnull=True).iterator(chunk_size=500):
        values = {name: getattr(participant, name) or "" for name in FIELDS}
        party = Party.objects.create(
            zev_id=participant.zev_id, kind="person", sort_name=values["last_name"].strip(), **values,
        )
        Participant.objects.filter(pk=participant.pk).update(party=party)


def to_participants(apps, schema_editor):
    """Reverse: copy each party's fields back onto its participants."""
    Participant = apps.get_model("zev", "Participant")
    for participant in Participant.objects.exclude(party=None).select_related("party").iterator(chunk_size=500):
        party = participant.party
        last_name = party.last_name or party.organisation_name
        values = {name: getattr(party, name) or "" for name in FIELDS}
        values["last_name"] = last_name
        Participant.objects.filter(pk=participant.pk).update(**values)


class Migration(migrations.Migration):
    """#761 phase 2 (ADR 0028), step 2 of 3: every participant gets its party."""

    dependencies = [
        ("zev", "0032_party"),
    ]

    operations = [
        migrations.RunPython(to_parties, to_participants),
    ]
