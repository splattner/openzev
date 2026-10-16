"""
Invoice lifecycle state machine.

Centralizes the allowed status transitions for invoices so the rules are
defined and tested in one place. Both the HTTP views and the Celery email
task delegate to these functions instead of mutating ``Invoice.status``
inline.

State machine::

    draft ──approve──▶ approved ──mark_sent──▶ sent ──mark_paid──▶ paid
      │                   │                      │  ◀─delete_payment─┘
      └───────cancel──────┴──────────cancel──────┘

    cancelled is terminal. A draft or cancelled invoice that was never
    approved may be replaced by the engine; one that was approved is kept for
    good (``approved_at``, ADR 0037).

Payments (#388): ``record_payment`` books money received against a sent
invoice and moves it to ``paid`` once the amount due is covered;
``mark_invoice_paid`` books the outstanding amount in one go. An invoice with
payments is never cancelled or deleted directly.

Corrections (#388): ``correct_invoice`` is the one way out of ``paid`` and the
only cancellation of an invoice that received money. It issues a ``Credit``
(credit note): a full reversal credits what was received and cancels the
invoice; a partial credit leaves the invoice as it is.

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

from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from zev.models import VatMode

from .models import Credit, CreditKind, Invoice, InvoicePdfStatus, InvoiceStatus, Payment


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


def _lock_and_transition(invoice, *, allowed_from, to_status, invalid_message, extra_fields=None, guard=None):
    """Validate and apply a status transition against the row's committed
    state, then mirror the result onto the caller's ``invoice`` instance.

    ``allowed_from`` is a single status or a set of them; the transition is
    refused unless the row's *current* status (re-read under a row lock, not
    whatever ``invoice.status`` held when it was loaded) is one of them.
    ``invalid_message`` is called with that current status to build the
    ``InvoiceWorkflowError`` message when the guard fails. ``guard``, if given,
    is called with the locked row and returns a refusal message or ``None``.
    A callable ``extra_fields`` builds its values from the locked row.

    On success, the written fields are copied back onto ``invoice`` so the
    caller keeps its own instance — with its prefetched relations — for
    serialization/audit use, while it now reports the persisted state. On
    failure, ``invoice.status`` is corrected to that same reality before
    raising, so a caller can't go on to describe a transition that never
    happened using a stale value.
    """
    with transaction.atomic():
        rows = Invoice.objects.select_for_update(of=("self",))
        if to_status == InvoiceStatus.APPROVED:
            rows = rows.select_related("zev", "participant__party")
        locked = rows.get(pk=invoice.pk)
        allowed = {allowed_from} if isinstance(allowed_from, str) else set(allowed_from)
        if locked.status not in allowed:
            invoice.status = locked.status
            raise InvoiceWorkflowError(invalid_message(locked.status))
        refusal = guard(locked) if guard else None
        if refusal:
            raise InvoiceWorkflowError(refusal)

        if callable(extra_fields):
            extra_fields = extra_fields(locked)
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
    """Transition draft → approved. Returns the ``before`` diff dict.

    Freeze a fresh party copy and clear the PDF reference in one transaction.
    """
    from .document_parties import build_copy
    from .pdf import delete_stored_pdf

    def approval_fields(locked):
        fields = build_copy(locked)
        if locked.pdf_file:
            storage = locked.pdf_file.storage
            stored_name = locked.pdf_file.name
            transaction.on_commit(lambda: delete_stored_pdf(storage, stored_name))
        return {
            **fields, "pdf_file": "", "pdf_status": InvoicePdfStatus.NONE,
            # Never cleared: from here on the invoice is issued (ADR 0037).
            "approved_at": timezone.now(),
        }

    return _lock_and_transition(
        invoice,
        allowed_from=InvoiceStatus.DRAFT,
        to_status=InvoiceStatus.APPROVED,
        invalid_message=lambda _current: "Only draft invoices can be approved.",
        extra_fields=approval_fields,
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


def paid_chf(invoice_pk) -> Decimal:
    """Sum of the payments recorded for an invoice."""
    return Payment.objects.filter(invoice_id=invoice_pk).aggregate(
        total=Sum("amount_chf")
    )["total"] or Decimal("0")


def amount_due(invoice: Invoice) -> Decimal:
    """What the invoice asks the participant to pay. Negative for a producer
    payout."""
    return invoice.total_chf


def _mirror_status(invoice: Invoice, locked: Invoice) -> None:
    invoice.status = locked.status
    invoice.updated_at = locked.updated_at


def record_payment(invoice: Invoice, *, amount_chf: Decimal, paid_on, note: str = "", user=None) -> dict:
    """Book a payment against a sent invoice. Returns the ``before`` diff dict
    with the new ``payment`` under its own key.

    A positive amount due takes partial payments up to the outstanding amount;
    a payout (amount due ≤ 0) is only settled in full, through
    :func:`mark_invoice_paid`. The invoice turns ``paid`` once the payments
    cover the amount due.
    """
    with transaction.atomic():
        locked = Invoice.objects.select_for_update().get(pk=invoice.pk)
        if locked.status != InvoiceStatus.SENT:
            _mirror_status(invoice, locked)
            raise InvoiceWorkflowError(
                "Invoice is already fully paid." if locked.status == InvoiceStatus.PAID
                else "Only sent invoices can receive payments."
            )
        due = amount_due(locked)
        if due <= 0:
            raise InvoiceWorkflowError("This invoice has nothing to collect. Mark it as paid instead.")
        if amount_chf <= 0:
            raise InvoiceWorkflowError("The payment amount must be positive.")
        if paid_on > timezone.localdate():
            raise InvoiceWorkflowError("The payment date cannot be in the future.")
        outstanding = due - paid_chf(locked.pk)
        if amount_chf > outstanding:
            raise InvoiceWorkflowError(f"The payment exceeds the outstanding amount of CHF {outstanding:.2f}.")

        payment = Payment.objects.create(
            invoice=locked, amount_chf=amount_chf, paid_on=paid_on, note=note,
            source=Payment.Source.MANUAL, created_by=user,
        )
        before_status = locked.status
        if amount_chf == outstanding:
            locked.status = InvoiceStatus.PAID
        locked.updated_at = timezone.now()
        locked.save(update_fields=["status", "updated_at"])

    _mirror_status(invoice, locked)
    return {"status": before_status, "payment": payment}


def mark_invoice_paid(invoice: Invoice, *, paid_on=None, user=None) -> dict:
    """Transition sent → paid, booking the outstanding amount as one payment.

    Returns the ``before`` diff dict with the payment (``None`` when nothing
    was outstanding, e.g. a zero total) under ``payment``.
    """
    paid_on = paid_on or timezone.localdate()
    with transaction.atomic():
        locked = Invoice.objects.select_for_update().get(pk=invoice.pk)
        if locked.status != InvoiceStatus.SENT:
            _mirror_status(invoice, locked)
            raise InvoiceWorkflowError("Only sent invoices can be marked as paid.")
        if paid_on > timezone.localdate():
            raise InvoiceWorkflowError("The payment date cannot be in the future.")
        outstanding = amount_due(locked) - paid_chf(locked.pk)
        payment = None
        if outstanding != 0:
            payment = Payment.objects.create(
                invoice=locked, amount_chf=outstanding, paid_on=paid_on,
                source=Payment.Source.MARK_PAID, created_by=user,
            )
        before_status = locked.status
        locked.status = InvoiceStatus.PAID
        locked.updated_at = timezone.now()
        locked.save(update_fields=["status", "updated_at"])

    _mirror_status(invoice, locked)
    return {"status": before_status, "payment": payment}


def delete_payment(payment: Payment) -> dict:
    """Remove a payment entered by mistake. Returns the ``before`` diff dict.

    A paid invoice whose payments no longer cover the amount due goes back to
    ``sent`` — the only way out of ``paid`` besides a correction.
    """
    with transaction.atomic():
        locked = Invoice.objects.select_for_update().get(pk=payment.invoice_id)
        if locked.status not in (InvoiceStatus.SENT, InvoiceStatus.PAID):
            raise InvoiceWorkflowError("Payments of a cancelled invoice cannot be removed.")
        if Credit.objects.filter(source_invoice_id=locked.pk).exists():
            raise InvoiceWorkflowError("Payments of an invoice with credit notes cannot be removed.")
        before_status = locked.status
        Payment.objects.filter(pk=payment.pk).delete()
        if locked.status == InvoiceStatus.PAID and paid_chf(locked.pk) != amount_due(locked):
            locked.status = InvoiceStatus.SENT
        locked.updated_at = timezone.now()
        locked.save(update_fields=["status", "updated_at"])

    payment.invoice.status = locked.status
    payment.invoice.updated_at = locked.updated_at
    return {"status": before_status}


def cancel_invoice(invoice: Invoice) -> dict:
    """Cancel a not-yet-paid invoice without payments. Returns the ``before``
    diff dict."""
    return _lock_and_transition(
        invoice,
        allowed_from={InvoiceStatus.DRAFT, InvoiceStatus.APPROVED, InvoiceStatus.SENT},
        to_status=InvoiceStatus.CANCELLED,
        invalid_message=lambda current: (
            "Invoice is already cancelled." if current == InvoiceStatus.CANCELLED
            else "Paid invoices cannot be cancelled. Correct the invoice instead."
        ),
        guard=lambda locked: (
            "Invoices with recorded payments cannot be cancelled. Correct the invoice instead."
            if Payment.objects.filter(invoice_id=locked.pk).exists() else None
        ),
    )


_CENT = Decimal("0.01")


def invoice_vat_mode(invoice: Invoice) -> str:
    """The VAT mode an invoice was issued under, worked out from its fields:
    ``Invoice`` does not store it and ``Zev.vat_mode`` may have changed since."""
    if invoice.embedded_vat_chf is not None:
        return VatMode.INCLUSIVE
    if invoice.vat_base_chf is not None or invoice.vat_chf != 0:
        return VatMode.REGISTERED
    return VatMode.NOT_REGISTERED


def credit_vat_split(source: Invoice, amount: Decimal) -> dict:
    """The VAT figures of a credit of ``amount`` (gross) against ``source``.

    A credit over the invoice's full total copies its VAT exactly. Any other
    amount is scaled: a registered invoice takes ``amount × rate / (1 + rate)``;
    an inclusive one takes the same share of its embedded VAT as ``amount`` is
    of the total (the inclusive invoice stores no rate); a non-registered one
    carries none.
    """
    mode = invoice_vat_mode(source)
    if amount == source.total_chf:
        return {
            "vat_mode": mode, "vat_rate": source.vat_rate, "vat_chf": source.vat_chf,
            "embedded_vat_chf": source.embedded_vat_chf,
        }
    vat_chf, embedded = Decimal("0"), None
    if mode == VatMode.REGISTERED:
        vat_chf = (amount * source.vat_rate / (1 + source.vat_rate)).quantize(_CENT, rounding=ROUND_HALF_UP)
    elif mode == VatMode.INCLUSIVE:
        embedded = (source.embedded_vat_chf * amount / source.total_chf).quantize(_CENT, rounding=ROUND_HALF_UP)
    return {"vat_mode": mode, "vat_rate": source.vat_rate, "vat_chf": vat_chf, "embedded_vat_chf": embedded}


def credited_chf(invoice_pk) -> Decimal:
    """Sum of the credit notes issued for an invoice."""
    return Credit.objects.filter(source_invoice_id=invoice_pk).aggregate(
        total=Sum("amount_chf")
    )["total"] or Decimal("0")


def correct_invoice(
    invoice: Invoice, *, kind: str, reason: str, amount_chf: Decimal | None = None, user=None,
) -> dict:
    """Correct an invoice that received money by issuing a credit note.

    Returns the ``before`` diff dict with the new ``credit`` under its own key.

    * ``reversal``: credits what was received, less any earlier partial credit,
      and cancels the invoice. The period can then be regenerated.
    * ``adjustment``: credits ``amount_chf`` (up to what was received and not
      yet credited) and leaves the invoice as it is.

    Only a ``paid`` invoice, or a ``sent`` one with payments, qualifies: a sent
    invoice nobody paid is simply cancelled. A producer payout (total ≤ 0) is
    out of scope.
    """
    reason = (reason or "").strip()
    with transaction.atomic():
        locked = Invoice.objects.select_for_update().select_related("zev", "participant__party").get(pk=invoice.pk)
        received = paid_chf(locked.pk)
        if locked.status not in (InvoiceStatus.SENT, InvoiceStatus.PAID):
            _mirror_status(invoice, locked)
            raise InvoiceWorkflowError(
                "Invoice is already cancelled." if locked.status == InvoiceStatus.CANCELLED
                else "Only paid invoices, or sent invoices with payments, can be corrected. "
                     "Cancel an invoice that has no payments instead."
            )
        if locked.status == InvoiceStatus.SENT and received <= 0:
            raise InvoiceWorkflowError(
                "Only paid invoices, or sent invoices with payments, can be corrected. "
                "Cancel a sent invoice that has no payments instead."
            )
        if locked.total_chf <= 0:
            raise InvoiceWorkflowError("Invoices with nothing to collect (payouts) cannot be corrected.")
        if kind not in CreditKind.values:
            raise InvoiceWorkflowError("Unknown correction kind.")
        if not reason:
            raise InvoiceWorkflowError("A reason is required.")

        creditable = received - credited_chf(locked.pk)
        if kind == CreditKind.REVERSAL:
            amount = creditable
            if amount <= 0:
                raise InvoiceWorkflowError("Everything received for this invoice has already been credited.")
        else:
            if amount_chf is None or amount_chf <= 0:
                raise InvoiceWorkflowError("The credit amount must be positive.")
            if amount_chf > creditable:
                raise InvoiceWorkflowError(f"The credit exceeds the creditable amount of CHF {creditable:.2f}.")
            amount = amount_chf

        credit = Credit.objects.create(
            credit_number=locked.zev.next_credit_note_number(),
            zev=locked.zev, participant=locked.participant, kind=kind, source_invoice=locked,
            reason=reason, amount_chf=amount, issuer=locked.issuer, recipient=locked.recipient,
            pdf_status=InvoicePdfStatus.PENDING, created_by=user,
            **credit_vat_split(locked, amount),
        )
        before_status = locked.status
        if kind == CreditKind.REVERSAL:
            locked.status = InvoiceStatus.CANCELLED
            locked.updated_at = timezone.now()
            locked.save(update_fields=["status", "updated_at"])
        # The render reads the committed credit, so it is queued once it is there.
        from .tasks import generate_credit_pdf_task
        transaction.on_commit(lambda: generate_credit_pdf_task.delay(str(credit.pk)), robust=True)

    _mirror_status(invoice, locked)
    return {"status": before_status, "credit": credit}


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
    """Non-admins may only delete draft or cancelled invoices that were never
    approved: an issued invoice keeps its number for good (ADR 0037)."""
    return (
        invoice.status in (InvoiceStatus.DRAFT, InvoiceStatus.CANCELLED)
        and invoice.approved_at is None
    )
