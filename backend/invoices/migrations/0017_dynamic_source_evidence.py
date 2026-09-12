from datetime import datetime, time, timedelta, timezone

import django.db.models.deletion
from django.db import migrations, models


def backfill_evidence(apps, schema_editor):
    Invoice = apps.get_model("invoices", "Invoice")
    Tariff = apps.get_model("tariffs", "Tariff")
    Evidence = apps.get_model("invoices", "InvoiceDynamicSourceEvidence")
    alias = schema_editor.connection.alias
    for tariff in Tariff.objects.using(alias).exclude(dynamic_source_id=None).iterator():
        invoices = Invoice.objects.using(alias).filter(
            zev_id=tariff.zev_id, period_end__gte=tariff.valid_from,
        )
        if tariff.valid_to:
            invoices = invoices.filter(period_start__lte=tariff.valid_to)
        for invoice in invoices.iterator():
            start = max(invoice.period_start, tariff.valid_from)
            end = min(invoice.period_end, tariff.valid_to or invoice.period_end)
            Evidence.objects.using(alias).create(
                invoice_id=invoice.pk, source_id=tariff.dynamic_source_id,
                tariff_id_snapshot=tariff.pk,
                evidence_from=datetime.combine(start, time.min, tzinfo=timezone.utc),
                evidence_to=datetime.combine(end + timedelta(days=1), time.min, tzinfo=timezone.utc),
            )


class Migration(migrations.Migration):
    dependencies = [
        ("invoices", "0016_invoice_pdf_status"),
        ("tariffs", "0015_source_version_identity"),
    ]

    operations = [
        migrations.CreateModel(
            name="InvoiceDynamicSourceEvidence",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("tariff_id_snapshot", models.UUIDField()),
                ("evidence_from", models.DateTimeField()),
                ("evidence_to", models.DateTimeField()),
                ("invoice", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="dynamic_evidence", to="invoices.invoice")),
                ("source", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="invoice_evidence", to="tariffs.dynamictariffsource")),
            ],
            options={
                "ordering": ["invoice_id", "source_id", "id"],
                "constraints": [
                    models.UniqueConstraint(fields=("invoice", "tariff_id_snapshot"), name="unique_invoice_dynamic_tariff_evidence"),
                    models.CheckConstraint(condition=models.Q(evidence_to__gt=models.F("evidence_from")), name="invoice_dynamic_evidence_valid_range"),
                ],
            },
        ),
        migrations.RunPython(backfill_evidence, migrations.RunPython.noop),
    ]
