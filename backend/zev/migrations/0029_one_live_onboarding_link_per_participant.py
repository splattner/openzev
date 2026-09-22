# Revokes older duplicates, then enforces one unrevoked link per participant.
#
# The EXCLUSIVE table lock (Postgres only) stops an old pod from inserting a
# duplicate between the cleanup and AddConstraint below.
from django.db import migrations, models
from django.utils import timezone


def revoke_duplicate_unrevoked_links(apps, schema_editor):
    Token = apps.get_model("zev", "ParticipantOnboardingToken")
    if schema_editor.connection.vendor == "postgresql":
        table = schema_editor.connection.ops.quote_name(Token._meta.db_table)
        schema_editor.execute(f"LOCK TABLE {table} IN EXCLUSIVE MODE")
    duplicated = (
        Token.objects.filter(revoked_at__isnull=True)
        .values("participant_id")
        .annotate(dupes=models.Count("id"))
        .filter(dupes__gt=1)
        .values_list("participant_id", flat=True)
    )
    for participant_id in duplicated:
        ids = list(
            Token.objects.filter(participant_id=participant_id, revoked_at__isnull=True)
            .order_by("-created_at", "id")
            .values_list("id", flat=True)
        )
        Token.objects.filter(id__in=ids[1:]).update(revoked_at=timezone.now())


class Migration(migrations.Migration):

    dependencies = [
        ('zev', '0028_onboarding_token_expires_at'),
    ]

    operations = [
        migrations.RunPython(revoke_duplicate_unrevoked_links, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='participantonboardingtoken',
            constraint=models.UniqueConstraint(condition=models.Q(('revoked_at__isnull', True)), fields=('participant',), name='one_unrevoked_onboarding_token_per_participant'),
        ),
    ]
