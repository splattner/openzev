"""Generalise SupplementarySource: capabilities, ZEV-held sources, grid connection point.

Existing rows become participant-held, history-only sources on a metering point, with their
``zev`` taken from the metering point (SPEC-2026-live-energy-data §4.1).
"""

import django.db.models.deletion
from django.db import migrations, models


def backfill_zev(apps, schema_editor):
    Source = apps.get_model("metering", "SupplementarySource")
    for source in Source.objects.select_related("metering_point").iterator():
        source.zev_id = source.metering_point.zev_id
        source.save(update_fields=["zev"])


class Migration(migrations.Migration):

    dependencies = [
        ("metering", "0011_alter_meterreading_condition_help_text"),
        ("zev", "0047_meteringpoint_metering_point_secondary_differs_from_primary"),
    ]

    operations = [
        migrations.AddField(
            model_name="supplementarysource",
            name="zev",
            field=models.ForeignKey(
                null=True, on_delete=django.db.models.deletion.CASCADE,
                related_name="energy_data_sources", to="zev.zev",
            ),
        ),
        migrations.AddField(
            model_name="supplementarysource",
            name="target",
            field=models.CharField(
                choices=[("metering_point", "Metering point"), ("connection_point", "Grid connection point")],
                default="metering_point", max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="supplementarysource",
            name="held_by",
            field=models.CharField(
                choices=[("participant", "Participant"), ("zev", "ZEV")], default="participant", max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="supplementarysource",
            name="provides_history",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="supplementarysource",
            name="provides_live",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="supplementarysource",
            name="provides_forecast",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="supplementarysource",
            name="live_last_seen_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="supplementarysource",
            name="metering_point",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.CASCADE,
                related_name="supplementary_sources", to="zev.meteringpoint",
            ),
        ),
        migrations.AlterField(
            model_name="supplementarysource",
            name="participant",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.CASCADE,
                related_name="supplementary_sources", to="zev.participant",
            ),
        ),
        migrations.RunPython(backfill_zev, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="supplementarysource",
            name="zev",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="energy_data_sources", to="zev.zev",
            ),
        ),
        migrations.AddConstraint(
            model_name="supplementarysource",
            constraint=models.UniqueConstraint(
                condition=models.Q(("provides_history", True)), fields=("metering_point",),
                name="uniq_source_history_per_mp",
            ),
        ),
        migrations.AddConstraint(
            model_name="supplementarysource",
            constraint=models.UniqueConstraint(
                condition=models.Q(("provides_live", True)), fields=("metering_point",),
                name="uniq_source_live_per_mp",
            ),
        ),
        migrations.AddConstraint(
            model_name="supplementarysource",
            constraint=models.UniqueConstraint(
                condition=models.Q(("provides_forecast", True)), fields=("metering_point",),
                name="uniq_source_forecast_per_mp",
            ),
        ),
        migrations.AddConstraint(
            model_name="supplementarysource",
            constraint=models.UniqueConstraint(
                condition=models.Q(("target", "connection_point")), fields=("zev",),
                name="uniq_connection_point_per_zev",
            ),
        ),
        migrations.AddConstraint(
            model_name="supplementarysource",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("metering_point__isnull", False), ("target", "metering_point")),
                    models.Q(
                        ("held_by", "zev"), ("metering_point__isnull", True), ("provides_forecast", False),
                        ("provides_history", False), ("provides_live", True), ("target", "connection_point"),
                    ),
                    _connector="OR",
                ),
                name="source_target_consistent",
            ),
        ),
        migrations.AddConstraint(
            model_name="supplementarysource",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("held_by", "participant"), ("participant__isnull", False)),
                    models.Q(("held_by", "zev"), ("participant__isnull", True)),
                    _connector="OR",
                ),
                name="source_holder_consistent",
            ),
        ),
        migrations.AddConstraint(
            model_name="supplementarysource",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("provides_history", True), ("provides_live", True), ("provides_forecast", True),
                    _connector="OR",
                ),
                name="source_has_capability",
            ),
        ),
    ]
