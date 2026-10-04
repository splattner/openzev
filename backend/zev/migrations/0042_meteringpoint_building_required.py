import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("zev", "0041_buildings_from_existing_data"),
    ]

    operations = [
        migrations.AlterField(
            model_name="meteringpoint",
            name="building",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.RESTRICT,
                related_name="metering_points",
                to="zev.building",
            ),
        ),
    ]
