from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("metering", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="importlog",
            name="zev",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.CASCADE,
                related_name="import_logs",
                to="zev.zev",
            ),
        ),
    ]
