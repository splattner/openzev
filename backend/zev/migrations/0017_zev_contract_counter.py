"""Add contract_counter to Zev for the per-ZEV contract document-number sequence."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("zev", "0016_zev_payment_term_days_alter_zev_email_body_template_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="zev",
            name="contract_counter",
            field=models.PositiveIntegerField(
                default=1,
                help_text="Auto-incremented participation-contract document number",
            ),
        ),
    ]
