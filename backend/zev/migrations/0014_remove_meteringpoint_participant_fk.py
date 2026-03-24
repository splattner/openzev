from django.db import migrations


def backfill_assignments_from_participant_fk(apps, schema_editor):
    MeteringPoint = apps.get_model("zev", "MeteringPoint")
    MeteringPointAssignment = apps.get_model("zev", "MeteringPointAssignment")

    for metering_point in MeteringPoint.objects.exclude(participant_id__isnull=True).iterator():
        if MeteringPointAssignment.objects.filter(metering_point_id=metering_point.id).exists():
            continue

        participant = metering_point.participant
        if participant is None:
            continue

        valid_from = participant.valid_from
        valid_to = participant.valid_to
        if valid_to and valid_to < valid_from:
            valid_to = valid_from

        MeteringPointAssignment.objects.create(
            metering_point_id=metering_point.id,
            participant_id=participant.id,
            valid_from=valid_from,
            valid_to=valid_to,
        )


class Migration(migrations.Migration):

    dependencies = [
        ("zev", "0013_remove_meteringpoint_validity_window"),
    ]

    operations = [
        migrations.RunPython(backfill_assignments_from_participant_fk, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="meteringpoint",
            name="participant",
        ),
    ]
