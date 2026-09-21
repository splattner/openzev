# Generated for overwrite-warnings separation (metering import safe-write).

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('metering', '0003_alter_importlog_options_alter_meterreading_options'),
    ]

    operations = [
        migrations.AddField(
            model_name='importlog',
            name='warnings',
            field=models.JSONField(default=list),
        ),
    ]
