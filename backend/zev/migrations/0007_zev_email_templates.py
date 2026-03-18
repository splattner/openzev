"""Add email_subject_template and email_body_template fields to Zev."""
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("zev", "0006_remove_zev_city"),
    ]

    operations = [
        migrations.AddField(
            model_name="zev",
            name="email_subject_template",
            field=models.CharField(
                default="",
                blank=True,
                max_length=500,
                help_text=(
                    "Subject line template for invoice emails. "
                    "Leave blank to use the system default. "
                    "Available variables: {invoice_number}, {zev_name}, {participant_name}, "
                    "{period_start}, {period_end}, {total_chf}."
                ),
            ),
        ),
        migrations.AddField(
            model_name="zev",
            name="email_body_template",
            field=models.TextField(
                default="",
                blank=True,
                help_text=(
                    "Body template for invoice emails. "
                    "Leave blank to use the system default. "
                    "Available variables: {invoice_number}, {zev_name}, {participant_name}, "
                    "{period_start}, {period_end}, {total_chf}."
                ),
            ),
        ),
    ]
