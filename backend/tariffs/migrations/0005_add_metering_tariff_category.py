from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tariffs', '0004_add_percentage_billing_mode'),
    ]

    operations = [
        migrations.AlterField(
            model_name='tariff',
            name='category',
            field=models.CharField(
                choices=[
                    ('energy', 'Energy'),
                    ('grid_fees', 'Grid Fees'),
                    ('levies', 'Levies'),
                    ('metering', 'Metering Tariff'),
                ],
                default='energy',
                max_length=20,
            ),
        ),
    ]
