from django.db import migrations


def delete_invitation_template(apps, schema_editor):
    """Drop any saved override of the removed password-invitation mail.

    ``participant_invitation`` is replaced by ``participant_onboarding``
    (zev.services.send_participant_onboarding_link): the old template's
    ``{username}``/``{temporary_password}`` placeholders describe a flow that
    no longer mints either, so a customised copy of it would render a mail
    promising credentials nobody is issued. Deleting the row reverts any
    instance-specific wording; the new key ships with its own default and is
    editable the same way once the operator wants to customise it again.
    """
    EmailTemplate = apps.get_model("invoices", "EmailTemplate")
    EmailTemplate.objects.filter(template_key="participant_invitation").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("invoices", "0016_invoice_pdf_status"),
    ]

    operations = [
        migrations.RunPython(delete_invitation_template, migrations.RunPython.noop),
    ]
