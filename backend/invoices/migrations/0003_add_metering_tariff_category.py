from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('invoices', '0002_invoiceitem_tariff_category_unit'),
    ]

    operations = [
        migrations.AlterField(
            model_name='invoiceitem',
            name='tariff_category',
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
