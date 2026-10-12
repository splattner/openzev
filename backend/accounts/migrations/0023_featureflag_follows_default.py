from django.db import migrations, models

SUPPLEMENTARY_FLAG = "supplementary_energy_data_enabled"


def untouched_supplementary_follows_default(apps, schema_editor):
    """A stored "off" on the energy data flag is the seeded default, not a decision.

    The flag now defaults to on once ``INTEGRATION_ENCRYPTION_KEYS`` is configured (ADR 0033).
    An existing "off" row cannot be told apart from an admin's own choice, and the flag shipped
    off, so it is treated as unchosen. A stored "on" stays a choice.
    """
    FeatureFlag = apps.get_model("accounts", "FeatureFlag")
    FeatureFlag.objects.filter(name=SUPPLEMENTARY_FLAG, enabled=False).update(follows_default=True)


class Migration(migrations.Migration):
    dependencies = [("accounts", "0022_oauth_trust_missing_email_verified")]

    operations = [
        migrations.AddField(
            model_name="featureflag",
            name="follows_default",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "No admin has chosen a value yet: the flag takes the code default, which for a flag "
                    "with a computed default (``DYNAMIC_DEFAULTS``) follows the instance's configuration. "
                    "Saving a choice clears it, so an explicit \"off\" always wins."
                ),
            ),
        ),
        migrations.RunPython(untouched_supplementary_follows_default, migrations.RunPython.noop),
    ]
