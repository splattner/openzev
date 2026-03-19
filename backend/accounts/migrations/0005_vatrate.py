from django.db import migrations, models
import django.core.validators


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0004_appsettings_date_time_format"),
    ]

    operations = [
        migrations.CreateModel(
            name="VatRate",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "rate",
                    models.DecimalField(
                        decimal_places=4,
                        help_text="VAT rate as decimal fraction (e.g. 0.0810 for 8.10%).",
                        max_digits=5,
                        validators=[django.core.validators.MinValueValidator(0), django.core.validators.MaxValueValidator(1)],
                    ),
                ),
                ("valid_from", models.DateField()),
                ("valid_to", models.DateField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["-valid_from", "-created_at"],
            },
        ),
    ]
