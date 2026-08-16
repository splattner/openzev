"""Add default_digest to PdfTemplate for stale-override detection."""

import hashlib

from django.conf import settings
from django.db import migrations, models


def backfill_default_digests(apps, schema_editor):
    """Digest of the on-disk default at migrate time for pre-existing overrides.

    This is a baseline, not a provenance detection: legacy rows carry no
    history, so every existing override is stamped with the digest of the
    default shipping in this release and treated as fresh. An override saved
    against an older release is unknowably stale — the data needed to detect
    that was never stored — so it can only be flagged stale once a *future*
    release changes the default. Rows whose template file cannot be resolved
    keep a blank digest (treated as unknown, never stale, by ``_is_stale``).
    """
    PdfTemplate = apps.get_model("invoices", "PdfTemplate")
    for record in PdfTemplate.objects.all():
        path = settings.BASE_DIR / "templates" / record.template_name
        if not path.is_file():
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        PdfTemplate.objects.filter(pk=record.pk).update(default_digest=digest)


class Migration(migrations.Migration):

    dependencies = [
        ("invoices", "0008_alter_invoice_invoice_number_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="pdftemplate",
            name="default_digest",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.RunPython(backfill_default_digests, migrations.RunPython.noop),
    ]
