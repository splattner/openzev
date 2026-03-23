from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tariffs', '0003_alter_tariff_billing_mode'),
    ]

    operations = [
        migrations.AddField(
            model_name='tariff',
            name='percentage',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text='Percentage of all energy tariffs (same energy type) used as the effective price. Only applicable for billing_mode=percentage_of_energy.',
                max_digits=5,
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name='tariff',
            name='billing_mode',
            field=models.CharField(
                choices=[
                    ('energy', 'By energy'),
                    ('percentage_of_energy', 'Percentage of energy tariffs'),
                    ('monthly_fee', 'Monthly fee'),
                    ('yearly_fee', 'Yearly fee'),
                    ('per_metering_point_monthly_fee', 'Per metering point monthly fee'),
                    ('per_metering_point_yearly_fee', 'Per metering point yearly fee'),
                ],
                default='energy',
                max_length=40,
            ),
        ),
    ]
