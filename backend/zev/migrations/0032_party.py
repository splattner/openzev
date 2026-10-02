import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """#761 phase 2 (ADR 0028), step 1 of 3: parties exist, participants may point at one."""

    dependencies = [
        ("zev", "0031_zev_access_grant"),
    ]

    operations = [
        migrations.CreateModel(
            name="Party",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("kind", models.CharField(choices=[("person", "Person"), ("organisation", "Organisation")], default="person", max_length=20)),
                ("title", models.CharField(blank=True, choices=[("mr", "Mr."), ("mrs", "Mrs."), ("ms", "Ms."), ("dr", "Dr."), ("prof", "Prof.")], max_length=10)),
                ("first_name", models.CharField(blank=True, max_length=100)),
                ("last_name", models.CharField(blank=True, max_length=100)),
                ("organisation_name", models.CharField(blank=True, max_length=200)),
                ("name_addition", models.CharField(blank=True, max_length=200)),
                ("email", models.EmailField(blank=True, max_length=254)),
                ("phone", models.CharField(blank=True, max_length=30)),
                ("address_line1", models.CharField(blank=True, max_length=200)),
                ("address_line2", models.CharField(blank=True, max_length=200)),
                ("postal_code", models.CharField(blank=True, max_length=10)),
                ("city", models.CharField(blank=True, max_length=100)),
                ("notes", models.TextField(blank=True)),
                ("sort_name", models.CharField(blank=True, db_index=True, editable=False, max_length=200)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("zev", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="parties", to="zev.zev")),
            ],
            options={
                "verbose_name_plural": "parties",
                "ordering": ["sort_name", "first_name", "id"],
            },
        ),
        migrations.AddField(
            model_name="participant",
            name="party",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.RESTRICT, related_name="participations", to="zev.party"),
        ),
    ]
