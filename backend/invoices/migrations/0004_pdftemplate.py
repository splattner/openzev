from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("invoices", "0003_add_metering_tariff_category"),
    ]

    operations = [
        migrations.CreateModel(
            name="PdfTemplate",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("template_name", models.CharField(max_length=200, unique=True)),
                ("content", models.TextField()),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
    ]
