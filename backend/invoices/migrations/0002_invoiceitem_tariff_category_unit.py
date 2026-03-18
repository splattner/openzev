from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('invoices', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='invoiceitem',
            name='tariff_category',
            field=models.CharField(
                choices=[
                    ('energy', 'Energy'),
                    ('grid_fees', 'Grid Fees'),
                    ('levies', 'Levies'),
                ],
                default='energy',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='invoiceitem',
            name='unit',
            field=models.CharField(default='kWh', max_length=20),
        ),
        migrations.AlterModelOptions(
            name='invoiceitem',
            options={'ordering': ['sort_order', 'item_type', 'description']},
        ),
    ]
