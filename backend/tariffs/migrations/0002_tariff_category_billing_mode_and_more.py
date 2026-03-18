from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tariffs', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='tariff',
            name='billing_mode',
            field=models.CharField(
                choices=[
                    ('energy', 'By energy'),
                    ('monthly_fee', 'Monthly fee'),
                    ('yearly_fee', 'Yearly fee'),
                ],
                default='energy',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='tariff',
            name='category',
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
            model_name='tariff',
            name='fixed_price_chf',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True),
        ),
        migrations.AlterField(
            model_name='tariff',
            name='energy_type',
            field=models.CharField(
                blank=True,
                choices=[
                    ('local', 'Local (Solar/ZEV)'),
                    ('grid', 'Grid (Netzstrom)'),
                    ('feed_in', 'Feed-in (Einspeisung)'),
                ],
                max_length=20,
                null=True,
            ),
        ),
        migrations.AlterModelOptions(
            name='tariff',
            options={'ordering': ['zev', 'category', 'name', '-valid_from']},
        ),
    ]
