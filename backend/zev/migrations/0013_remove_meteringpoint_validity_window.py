from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("zev", "0012_zev_additional_contract_notes"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="meteringpoint",
            name="valid_from",
        ),
        migrations.RemoveField(
            model_name="meteringpoint",
            name="valid_to",
        ),
    ]
