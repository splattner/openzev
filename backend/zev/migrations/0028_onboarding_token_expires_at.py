# Gives outstanding onboarding links a 30-day lifetime from creation.
from datetime import timedelta

from django.db import migrations, models
from django.db.models import F


def backfill_expires_at(apps, schema_editor):
    Token = apps.get_model("zev", "ParticipantOnboardingToken")
    Token.objects.filter(expires_at__isnull=True).update(
        expires_at=F("created_at") + timedelta(days=30)
    )


class Migration(migrations.Migration):

    dependencies = [
        ('zev', '0027_zev_disabled_state'),
    ]

    operations = [
        migrations.AddField(
            model_name='participantonboardingtoken',
            name='expires_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(backfill_expires_at, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='participantonboardingtoken',
            name='expires_at',
            field=models.DateTimeField(),
        ),
    ]
