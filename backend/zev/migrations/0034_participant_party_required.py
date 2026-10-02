import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """#761 phase 2 (ADR 0028), step 3 of 3: the party is required and holds the
    names; the participant columns go."""

    dependencies = [
        ("zev", "0033_participant_parties_data"),
    ]

    operations = [
        migrations.AlterField(
            model_name="participant",
            name="party",
            field=models.ForeignKey(on_delete=django.db.models.deletion.RESTRICT, related_name="participations", to="zev.party"),
        ),
        migrations.AlterModelOptions(
            name="participant",
            options={"base_manager_name": "objects", "ordering": ["party__sort_name", "party__first_name", "id"]},
        ),
        # Blank first so that migrating back can re-add the columns to filled
        # tables (with "" until 0033's reverse copies the names back).
        migrations.AlterField(model_name="participant", name="first_name", field=models.CharField(blank=True, max_length=100)),
        migrations.AlterField(model_name="participant", name="last_name", field=models.CharField(blank=True, max_length=100)),
        migrations.RemoveField(model_name="participant", name="title"),
        migrations.RemoveField(model_name="participant", name="first_name"),
        migrations.RemoveField(model_name="participant", name="last_name"),
        migrations.RemoveField(model_name="participant", name="email"),
        migrations.RemoveField(model_name="participant", name="phone"),
        migrations.RemoveField(model_name="participant", name="address_line1"),
        migrations.RemoveField(model_name="participant", name="address_line2"),
        migrations.RemoveField(model_name="participant", name="postal_code"),
        migrations.RemoveField(model_name="participant", name="city"),
    ]
