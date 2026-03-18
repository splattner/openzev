from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tariffs', '0002_tariff_category_billing_mode_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='tariff',
            name='billing_mode',
            field=models.CharField(
                choices=[
                    ('energy', 'By energy'),
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
