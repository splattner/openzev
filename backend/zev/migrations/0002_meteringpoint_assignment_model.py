# Manually crafted migration:
# 1. Add `zev` FK to MeteringPoint as nullable, and make `participant` nullable.
# 2. Backfill `zev` from `participant.zev` for all existing rows.
# 3. Enforce NOT NULL on `zev`.
# 4. Create the MeteringPointAssignment model.

import django.db.models.deletion
import uuid

from django.db import migrations, models


def backfill_metering_point_zev(apps, schema_editor):
    MeteringPoint = apps.get_model("zev", "MeteringPoint")
    for mp in MeteringPoint.objects.select_related("participant").filter(zev__isnull=True):
        if mp.participant_id is not None:
            mp.zev_id = mp.participant.zev_id
            mp.save(update_fields=["zev_id"])


class Migration(migrations.Migration):

    dependencies = [
        ("zev", "0001_initial"),
    ]

    operations = [
        # ── Step 1: Add `zev` as nullable FK, make `participant` optional ────────
        migrations.AddField(
            model_name="meteringpoint",
            name="zev",
            field=models.ForeignKey(
                null=True,
                blank=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="metering_points",
                to="zev.zev",
            ),
        ),
        migrations.AlterField(
            model_name="meteringpoint",
            name="participant",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="metering_points",
                to="zev.participant",
                help_text="Deprecated direct link. Use assignments for temporal participant ownership.",
            ),
        ),
        # ── Step 2: Backfill `zev` from `participant.zev` for existing rows ──────
        migrations.RunPython(backfill_metering_point_zev, migrations.RunPython.noop),
        # ── Step 3: Enforce NOT NULL on `zev` ────────────────────────────────────
        migrations.AlterField(
            model_name="meteringpoint",
            name="zev",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="metering_points",
                to="zev.zev",
            ),
        ),
        # ── Step 4: Update help_text + remove old CASCADE on participant ──────────
        # (AlterField already done above, nothing more needed for participant)
        # ── Step 5: Create MeteringPointAssignment model ─────────────────────────
        migrations.CreateModel(
            name="MeteringPointAssignment",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("valid_from", models.DateField()),
                ("valid_to", models.DateField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "metering_point",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="assignments",
                        to="zev.meteringpoint",
                    ),
                ),
                (
                    "participant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="metering_point_assignments",
                        to="zev.participant",
                    ),
                ),
            ],
            options={
                "ordering": ["-valid_from", "-created_at"],
            },
        ),
        migrations.AddConstraint(
            model_name="meteringpointassignment",
            constraint=models.UniqueConstraint(
                fields=["metering_point", "participant", "valid_from"],
                name="uniq_metering_point_assignment_start",
            ),
        ),
    ]
