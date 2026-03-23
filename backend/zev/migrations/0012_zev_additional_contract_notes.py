"""Add additional_contract_notes field to Zev."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("zev", "0011_zev_local_tariff_notes"),
    ]

    operations = [
        migrations.AddField(
            model_name="zev",
            name="additional_contract_notes",
            field=models.TextField(
                blank=True,
                help_text="Additional agreements shown in the participation contract PDF.",
            ),
        ),
    ]
