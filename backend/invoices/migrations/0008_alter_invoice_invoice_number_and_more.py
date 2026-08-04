"""Scope invoice-number uniqueness to the ZEV (see issue #401).

Existing rows satisfied a *global* unique constraint, so they trivially satisfy
the narrower per-ZEV one — the constraint can be added without a data migration.
The drop has to come first so the two constraints never coexist.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('invoices', '0007_emaillog_status_choices'),
        ('zev', '0016_zev_payment_term_days_alter_zev_email_body_template_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='invoice',
            name='invoice_number',
            field=models.CharField(max_length=50),
        ),
        migrations.AddConstraint(
            model_name='invoice',
            constraint=models.UniqueConstraint(fields=('zev', 'invoice_number'), name='unique_invoice_number_per_zev'),
        ),
    ]
