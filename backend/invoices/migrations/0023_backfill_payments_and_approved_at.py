"""Backfill ``Invoice.approved_at`` and one ``Payment`` per paid invoice (#388).

Before this, approval left no timestamp and mark-paid recorded no amount. The
audit log is the best evidence of when either happened, so it is used where an
event exists; otherwise the closest field on the invoice stands in.

- ``approved_at``: approved/sent/paid invoices, and cancelled invoices that
  provably went out (an approval event or ``sent_at``). A cancelled invoice
  with neither stays ``NULL`` and can still be replaced by regeneration.
- Payments: one per paid invoice with a non-zero total, for ``total_chf``,
  dated by the newest ``invoice.mark_paid`` event or ``updated_at``.
"""

from zoneinfo import ZoneInfo

from django.db import migrations

ZURICH = ZoneInfo("Europe/Zurich")


def _newest_event_times(AuditEvent, action_type):
    times = {}
    for target_id, created_at in (
        AuditEvent.objects.filter(
            action_type=action_type, target_type="invoices.Invoice", status="success"
        )
        .order_by("created_at")
        .values_list("target_id", "created_at")
        .iterator()
    ):
        times[target_id] = created_at
    return times


def backfill(apps, schema_editor):
    Invoice = apps.get_model("invoices", "Invoice")
    Payment = apps.get_model("invoices", "Payment")
    AuditEvent = apps.get_model("audit", "AuditEvent")

    approved_events = _newest_event_times(AuditEvent, "invoice.approve")
    paid_events = _newest_event_times(AuditEvent, "invoice.mark_paid")

    for invoice in Invoice.objects.filter(approved_at__isnull=True).iterator():
        approved_at = approved_events.get(str(invoice.pk)) or invoice.sent_at
        if approved_at is None and invoice.status in ("approved", "sent", "paid"):
            approved_at = invoice.updated_at
        if approved_at is not None:
            Invoice.objects.filter(pk=invoice.pk).update(approved_at=approved_at)

    payments = []
    for invoice in (
        Invoice.objects.filter(status="paid").exclude(total_chf=0).iterator()
    ):
        if Payment.objects.filter(invoice_id=invoice.pk).exists():
            continue
        paid_at = paid_events.get(str(invoice.pk)) or invoice.updated_at
        payments.append(
            Payment(
                invoice_id=invoice.pk,
                amount_chf=invoice.total_chf,
                paid_on=paid_at.astimezone(ZURICH).date(),
                source="backfill",
            )
        )
    Payment.objects.bulk_create(payments, batch_size=500)


class Migration(migrations.Migration):

    dependencies = [
        ("invoices", "0022_invoice_payments_and_approved_at"),
        ("audit", "0006_alter_auditevent_source"),
    ]

    operations = [
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
