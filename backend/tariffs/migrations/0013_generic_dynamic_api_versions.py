from django.db import migrations, models


def migrate_adapter_configuration(apps, schema_editor):
    Source = apps.get_model("tariffs", "DynamicTariffSource")
    for source in Source.objects.all().iterator():
        old_adapter = source.api_version
        source.api_version = "v1_0_5"
        source.request_mode = "exact_url" if old_adapter == "bkw" else "standard"
        source.supports_range = old_adapter != "bkw"
        source.query_tariff_type = (
            "feed-in" if old_adapter == "groupe_e" and source.tariff_type == "feed_in"
            else source.tariff_type
        )
        source.save(update_fields=[
            "api_version", "request_mode", "supports_range", "query_tariff_type",
        ])


def restore_adapter_configuration(apps, schema_editor):
    Source = apps.get_model("tariffs", "DynamicTariffSource")
    for source in Source.objects.all().iterator():
        if source.request_mode == "exact_url":
            source.api_version = "bkw"
        elif source.query_tariff_type == "feed-in":
            source.api_version = "groupe_e"
        else:
            source.api_version = "vse_v1"
        source.save(update_fields=["api_version"])


class Migration(migrations.Migration):
    dependencies = [("tariffs", "0012_dynamic_tariff_source")]

    operations = [
        migrations.RenameField(
            model_name="dynamictariffsource",
            old_name="adapter",
            new_name="api_version",
        ),
        migrations.AddField(
            model_name="dynamictariffsource",
            name="request_mode",
            field=models.CharField(
                choices=[("standard", "Standard query parameters"), ("exact_url", "Exact URL")],
                default="standard",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="dynamictariffsource",
            name="query_tariff_type",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Tariff-type query value discovered for this endpoint.",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="dynamictariffsource",
            name="supports_range",
            field=models.BooleanField(default=True),
        ),
        migrations.RunPython(migrate_adapter_configuration, restore_adapter_configuration),
        migrations.AlterField(
            model_name="dynamictariffsource",
            name="api_version",
            field=models.CharField(
                choices=[("v1_0_5", "v1.0.5"), ("v2_0_0", "v2.0.0")],
                default="v1_0_5",
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="dynamictariffsource",
            name="label",
            field=models.CharField(
                help_text="Shown when picking a source, e.g. 'Dynamic grid price'",
                max_length=200,
            ),
        ),
        migrations.AlterField(
            model_name="dynamictariffsource",
            name="tariff_type",
            field=models.CharField(
                choices=[
                    ("electricity", "Electricity supply"),
                    ("grid", "Grid usage"),
                    ("metering", "Metering"),
                    ("national_fees", "National fees"),
                    ("integrated", "Integrated (electricity + grid)"),
                    ("dso", "DSO total"),
                    ("dso_complete", "Complete DSO total"),
                    ("integrated_complete", "Complete integrated total"),
                    ("regional_fees", "Regional fees"),
                    ("feed_in", "Feed-in remuneration"),
                    ("refund", "Storage refund"),
                ],
                max_length=20,
            ),
        ),
    ]
