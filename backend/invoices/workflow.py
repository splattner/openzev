"""
Invoice lifecycle state machine.

Centralizes the allowed status transitions for invoices so the rules are
defined and tested in one place. Both the HTTP views and the Celery email
task delegate to these functions instead of mutating ``Invoice.status``
inline.

State machine::

    draft ──approve──▶ approved ──mark_sent──▶ sent ──mark_paid──▶ paid
      │                   │                      │
      └───────cancel──────┴──────────cancel──────┘        (paid is final)

    cancelled is terminal (but draft/cancelled invoices may be regenerated
    by the engine).

Concurrency (#572): every transition below checks and writes the row's
*current* database state inside one locked transaction (``SELECT ... FOR
UPDATE``), never the possibly-stale status of whatever ``Invoice`` instance
the caller happened to load. Two overlapping calls therefore serialize on
the row lock instead of racing — the second sees the first one's committed
result rather than the value it was loaded with. On PostgreSQL that lock is
real (see ``test_concurrent_cancel_and_mark_paid_serialize_on_the_row_lock``
in ``test_workflow.py``); on SQLite, where ``SELECT ... FOR UPDATE`` is a
no-op, correctness still holds for the sequential case because each call
re-reads the row rather than trusting the caller's instance — SQLite has no
real concurrent writers to race against in the first place (single-writer
file locking). ``record_email_delivery`` uses the same locked read, and the
lock is acquired *after* the slow part (SMTP delivery) has already
completed in the caller, not held across it.
"""

from django.db import transaction
from django.utils import timezone

from .models import Invoice, InvoiceStatus


class InvoiceWorkflowError(Exception):
    """Raised when an invoice status transition is not allowed.

    ``user_message`` carries a safe, predefined string describing the guard
    violation. Views should use this attribute in HTTP responses rather than
    ``str(self)`` to avoid broad exception-message exposure flagged by static
    analysis tools.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.user_message: str = message


def _lock_and_transition(invoice, *, allowed_from, to_status, invalid_message, extra_fields=None):
    """Validate and apply a status transition against the row's committed
    state, then mirror the result onto the caller's ``invoice`` instance.

    ``allowed_from`` is a single status or a set of them; the transition is
    refused unless the row's *current* status (re-read under a row lock, not
    whatever ``invoice.status`` held when it was loaded) is one of them.
    ``invalid_message`` is called with that current status to build the
    ``InvoiceWorkflowError`` message when the guard fails.

    On success, the written fields are copied back onto ``invoice`` so the
    caller keeps its own instance — with its prefetched relations — for
    serialization/audit use, while it now reports the persisted state. On
    failure, ``invoice.status`` is corrected to that same reality before
    raising, so a caller can't go on to describe a transition that never
    happened using a stale value.
    """
    with transaction.atomic():
        locked = Invoice.objects.select_for_update().get(pk=invoice.pk)
        allowed = {allowed_from} if isinstance(allowed_from, str) else set(allowed_from)
        if locked.status not in allowed:
            invoice.status = locked.status
            raise InvoiceWorkflowError(invalid_message(locked.status))

        before_status = locked.status
        locked.status = to_status
        locked.updated_at = timezone.now()
        update_fields = ["status", "updated_at"]
        if extra_fields:
            for field, value in extra_fields.items():
                setattr(locked, field, value)
                update_fields.append(field)
        locked.save(update_fields=update_fields)

    invoice.status = locked.status
    invoice.updated_at = locked.updated_at
    if extra_fields:
        for field in extra_fields:
            setattr(invoice, field, getattr(locked, field))
    return {"status": before_status}


def approve_invoice(invoice: Invoice) -> dict:
    """Transition draft → approved. Returns the ``before`` diff dict."""
    return _lock_and_transition(
        invoice,
        allowed_from=InvoiceStatus.DRAFT,
        to_status=InvoiceStatus.APPROVED,
        invalid_message=lambda _current: "Only draft invoices can be approved.",
    )


def mark_invoice_sent(invoice: Invoice) -> dict:
    """Transition approved → sent and stamp ``sent_at``. Returns the ``before`` diff dict."""
    return _lock_and_transition(
        invoice,
        allowed_from=InvoiceStatus.APPROVED,
        to_status=InvoiceStatus.SENT,
        invalid_message=lambda _current: "Only approved invoices can be marked as sent.",
        extra_fields={"sent_at": timezone.now()},
    )


def mark_invoice_paid(invoice: Invoice) -> dict:
    """Transition sent → paid. Returns the ``before`` diff dict."""
    return _lock_and_transition(
        invoice,
        allowed_from=InvoiceStatus.SENT,
        to_status=InvoiceStatus.PAID,
        invalid_message=lambda _current: "Only sent invoices can be marked as paid.",
    )


def cancel_invoice(invoice: Invoice) -> dict:
    """Cancel a not-yet-paid invoice. Returns the ``before`` diff dict."""
    return _lock_and_transition(
        invoice,
        allowed_from={InvoiceStatus.DRAFT, InvoiceStatus.APPROVED, InvoiceStatus.SENT},
        to_status=InvoiceStatus.CANCELLED,
        invalid_message=lambda current: (
            "Invoice is already cancelled." if current == InvoiceStatus.CANCELLED
            else "Paid invoices cannot be cancelled."
        ),
    )


def record_email_delivery(invoice: Invoice, sent_at) -> str:
    """Record a successful email delivery on the invoice.

    Stamps ``sent_at`` and auto-transitions approved → sent (other statuses
    are left unchanged). Returns the status the invoice *actually* had in
    the database at that moment — not the possibly-stale status on the
    passed-in ``invoice``, which the caller (the email Celery task) loaded
    well before a slow SMTP send completed.

    Unlike the guarded transitions above, this never raises: an email that
    was delivered after the invoice was independently cancelled or paid is
    still worth recording — the message really was sent — it just must not
    resurrect a status that decision already moved past (#572).
    """
    with transaction.atomic():
        locked = Invoice.objects.select_for_update().get(pk=invoice.pk)
        previous_status = locked.status
        locked.sent_at = sent_at
        locked.updated_at = timezone.now()
        update_fields = ["sent_at", "updated_at"]
        if locked.status == InvoiceStatus.APPROVED:
            locked.status = InvoiceStatus.SENT
            update_fields.append("status")
        locked.save(update_fields=update_fields)

    invoice.status = locked.status
    invoice.sent_at = locked.sent_at
    invoice.updated_at = locked.updated_at
    return previous_status


def can_delete_invoice(invoice: Invoice) -> bool:
    """Non-admins may only delete draft or cancelled invoices."""
    return invoice.status in (InvoiceStatus.DRAFT, InvoiceStatus.CANCELLED)
