"""Create ContractIssue: frozen, versioned participation-contract snapshots.

``rendered_on`` records the calendar date the document was rendered with, so
change detection can reproduce the issued document instead of re-rendering
at "today" (which would mint a new version every calendar day). Both foreign
keys are nullable ``SET_NULL``: issued contracts are an immutable archive and
survive participant/ZEV deletion.
"""

import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models

import invoices.models


class Migration(migrations.Migration):

    dependencies = [
        ("invoices", "0009_pdf_template_default_digest"),
        ("zev", "0017_zev_contract_counter"),
    ]

    operations = [
        migrations.CreateModel(
            name="ContractIssue",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("version", models.PositiveIntegerField()),
                ("document_number", models.CharField(max_length=32)),
                ("language", models.CharField(max_length=2)),
                (
                    "rendered_on",
                    models.DateField(
                        default=invoices.models.contract_issue_rendered_on_default,
                        help_text="Calendar date the document was rendered with (its issue date)",
                    ),
                ),
                ("context_hash", models.CharField(help_text="sha256 of the rendered HTML", max_length=64)),
                ("pdf", models.BinaryField(editable=False)),
                ("issued_at", models.DateTimeField(auto_now_add=True)),
                (
                    "issued_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "participant",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="contract_issues",
                        to="zev.participant",
                    ),
                ),
                (
                    "zev",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="contract_issues",
                        to="zev.zev",
                    ),
                ),
            ],
            options={
                "ordering": ["-version"],
            },
        ),
        migrations.AddConstraint(
            model_name="contractissue",
            constraint=models.UniqueConstraint(
                fields=("participant", "version"),
                name="uniq_contract_issue_participant_version",
            ),
        ),
    ]
