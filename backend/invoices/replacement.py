"""Replace an unpaid issued invoice without leaving it cancelled on failure."""

from django.db import transaction

from metering.locks import lock_billing_inputs, protect_billing_scope
from zev.models import Participant
from .engine import generate_invoice
from .models import Invoice, InvoiceStatus
from .workflow import InvoiceWorkflowError, cancel_invoice


@transaction.atomic
def replace_invoice(invoice: Invoice) -> tuple[Invoice, dict]:
    # Match generation's lock order before cancellation locks the invoice.
    protect_billing_scope(invoice.zev)
    Participant.objects.select_for_update().values("pk").get(pk=invoice.participant_id)
    lock_billing_inputs(invoice.zev)
    original = Invoice.objects.select_for_update(of=("self",)).get(pk=invoice.pk)
    if original.status not in (InvoiceStatus.APPROVED, InvoiceStatus.SENT):
        raise InvoiceWorkflowError("Only unpaid issued invoices can be replaced. Regenerate a draft or correct a paid invoice instead.")
    # Legacy issued rows also need the marker that keeps them during generation.
    if original.approved_at is None:
        original.approved_at = original.sent_at or original.updated_at
        original.save(update_fields=["approved_at"])
    before = cancel_invoice(original)
    replacement = generate_invoice(invoice.participant, original.period_start, original.period_end)
    return replacement, before
