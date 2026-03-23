"""Add local_tariff_notes field to Zev."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("zev", "0010_zev_invoice_language"),
    ]

    operations = [
        migrations.AddField(
            model_name="zev",
            name="local_tariff_notes",
            field=models.TextField(
                blank=True,
                help_text=(
                    "Free-text conditions for the local ZEV tariff in following years. "
                    "Shown on the participation contract PDF."
                ),
            ),
        ),
    ]
