from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0027_user_email_unique"),
    ]

    operations = [
        migrations.AddField(
            model_name="oauthstate",
            name="session_version",
            field=models.PositiveIntegerField(editable=False, null=True),
        ),
        migrations.AddField(
            model_name="oauthstate",
            name="from_participant_link",
            field=models.BooleanField(default=False, editable=False),
        ),
        migrations.AddField(
            model_name="socialaccount",
            name="from_participant_link",
            field=models.BooleanField(default=False, editable=False),
        ),
        migrations.AddField(
            model_name="mfarecoverycode",
            name="from_participant_link",
            field=models.BooleanField(default=False, editable=False),
        ),
        migrations.AddField(
            model_name="totpdevice",
            name="from_participant_link",
            field=models.BooleanField(default=False, editable=False),
        ),
        migrations.AddField(
            model_name="user",
            name="password_from_participant_link",
            field=models.BooleanField(default=False, editable=False),
        ),
        migrations.AddField(
            model_name="webauthncredential",
            name="from_participant_link",
            field=models.BooleanField(default=False, editable=False),
        ),
    ]
