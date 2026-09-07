from django.db import migrations, models


def mark_existing_documents_ready(apps, schema_editor):
    """Every invoice that already has a file has a ready document.

    Without this every historical invoice would read "Not generated" next to a
    PDF the operator can open, which is worse than having no column at all. The
    inverse is deliberately *not* backfilled: an invoice with no file may never
    have had one requested, and calling that "failed" would invent a failure.
    """
    Invoice = apps.get_model("invoices", "Invoice")
    Invoice.objects.exclude(pdf_file="").exclude(pdf_file__isnull=True).update(
        pdf_status="ready",
    )


class Migration(migrations.Migration):

    dependencies = [
        ('invoices', '0015_invoiceaccesstoken_secret'),
    ]

    operations = [
        migrations.AddField(
            model_name='invoice',
            name='pdf_status',
            field=models.CharField(choices=[('none', 'Not generated'), ('pending', 'Generating'), ('ready', 'Ready'), ('failed', 'Failed')], default='none', max_length=20),
        ),
        migrations.RunPython(
            mark_existing_documents_ready,
            # Reversing only drops the column, so there is nothing to undo.
            migrations.RunPython.noop,
        ),
    ]
