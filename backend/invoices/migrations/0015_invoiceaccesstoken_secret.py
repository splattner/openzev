"""Store the access-token secret instead of its hash.

Not a rename: the column changes meaning. ``hashed_secret`` held a SHA-256
digest, which cannot be turned back into the secret a printed QR needs, and
reprinting an unchanged link is the property the feature depends on. The
reasoning for storing it in clear is on ``InvoiceAccessToken.secret``.

Any existing row is dropped rather than migrated, because a digest is not a
secret and pretending otherwise would leave tokens that authenticate nothing.
The model shipped in no release, so there are none outside development.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("invoices", "0014_invoiceaccesstoken"),
    ]

    operations = [
        migrations.RunSQL(
            "DELETE FROM invoices_invoiceaccesstoken;",
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RemoveField(
            model_name="invoiceaccesstoken",
            name="hashed_secret",
        ),
        migrations.AddField(
            model_name="invoiceaccesstoken",
            name="secret",
            field=models.CharField(default="", max_length=64),
            preserve_default=False,
        ),
    ]
