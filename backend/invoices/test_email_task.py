"""Failure-path and EmailLog coverage for ``send_invoice_email_task``.

The existing email tests in ``tests.py`` only cover the happy path (an email
lands in the outbox). These tests cover the branches that matter operationally:
the no-recipient skip, the missing-invoice guard, the FAILED branch + retry, the
EmailLog status records, and the APPROVED→SENT transition.
"""

from datetime import date
from decimal import Decimal
from unittest import mock

import pytest
from django.core.files.base import ContentFile

from audit.models import AuditEvent, AuditEventStatus
from invoices.models import EmailLog, InvoiceStatus
from invoices.tasks import send_invoice_email_task
from testing import factories

pytestmark = pytest.mark.django_db


def _approved_invoice_with_pdf(*, email="recipient@example.com"):
    participant = factories.ParticipantFactory(email=email)
    invoice = factories.InvoiceFactory(
        zev=participant.zev,
        participant=participant,
        status=InvoiceStatus.APPROVED,
        total_chf=Decimal("42.00"),
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
    )
    invoice.pdf_file.save("invoice_test.pdf", ContentFile(b"PDF"), save=True)
    return invoice


def test_missing_invoice_returns_without_error():
    # A random UUID that does not correspond to any invoice.
    send_invoice_email_task.run("00000000-0000-0000-0000-000000000000")
    # No EmailLog should be created and no exception raised.
    assert EmailLog.objects.count() == 0


def test_no_recipient_skips_and_logs_failed(mailoutbox):
    participant = factories.ParticipantFactory(email="")
    invoice = factories.InvoiceFactory(
        zev=participant.zev,
        participant=participant,
        status=InvoiceStatus.APPROVED,
    )
    invoice.pdf_file.save("invoice_test.pdf", ContentFile(b"PDF"), save=True)

    send_invoice_email_task.run(str(invoice.pk))

    # No email sent, and no EmailLog record created (skip happens before logging).
    assert len(mailoutbox) == 0
    assert EmailLog.objects.filter(invoice=invoice).count() == 0
    invoice.refresh_from_db()
    assert invoice.status == InvoiceStatus.APPROVED  # unchanged


def test_successful_send_records_sent_log_and_transitions_status(mailoutbox):
    invoice = _approved_invoice_with_pdf()

    send_invoice_email_task.run(str(invoice.pk), "recipient@example.com")

    assert len(mailoutbox) == 1
    log = EmailLog.objects.get(invoice=invoice)
    assert log.status == EmailLog.Status.SENT
    assert log.sent_at is not None
    assert log.recipient == "recipient@example.com"

    invoice.refresh_from_db()
    assert invoice.status == InvoiceStatus.SENT
    assert invoice.sent_at is not None


def test_send_failure_marks_log_failed_and_retries():
    invoice = _approved_invoice_with_pdf()

    # Force the send to fail and the retry to raise so we can assert on it.
    with mock.patch(
        "invoices.tasks.EmailMessage.send", side_effect=RuntimeError("smtp down")
    ), mock.patch.object(
        send_invoice_email_task, "retry", side_effect=RuntimeError("retried")
    ) as retry_mock:
        with pytest.raises(RuntimeError):
            send_invoice_email_task.run(str(invoice.pk), "recipient@example.com")

    retry_mock.assert_called_once()
    log = EmailLog.objects.get(invoice=invoice)
    assert log.status == EmailLog.Status.FAILED
    assert "smtp down" in log.error_message

    invoice.refresh_from_db()
    # Status must NOT advance to SENT on failure.
    assert invoice.status == InvoiceStatus.APPROVED


def test_bookkeeping_failure_after_successful_send_does_not_retry_or_resend(mailoutbox):
    """#576 reproduction: SMTP succeeds, then record_email_delivery raises
    (standing in for any post-delivery database write failing). The message
    already went out — that must not be retried (a retry resends it) or
    reported as an SMTP failure, and the task must still complete rather
    than propagate the bookkeeping error as if the send itself had failed.
    """
    invoice = _approved_invoice_with_pdf()

    with mock.patch(
        "invoices.workflow.record_email_delivery", side_effect=RuntimeError("db down"),
    ), mock.patch.object(
        send_invoice_email_task, "retry", side_effect=AssertionError("must not retry a delivered email"),
    ) as retry_mock:
        # Completes without raising: a bookkeeping failure is caught and
        # logged/audited here, not left to propagate as a task failure.
        send_invoice_email_task.run(str(invoice.pk), "recipient@example.com")

    retry_mock.assert_not_called()
    # Exactly one email actually went out — no duplicate.
    assert len(mailoutbox) == 1

    log = EmailLog.objects.get(invoice=invoice)
    # The send genuinely succeeded — the log must say so, not FAILED, both
    # because it's true and because a FAILED log is what "Retry email" acts
    # on: mislabelling it would let an operator trigger the actual resend
    # this fix exists to prevent.
    assert log.status == EmailLog.Status.SENT
    assert log.sent_at is not None
    assert log.error_message == ""

    # record_email_delivery never committed, so the invoice status is a
    # visible, correctable gap rather than silently wrong data — the same
    # place it would be if this task had never run.
    invoice.refresh_from_db()
    assert invoice.status == InvoiceStatus.APPROVED
    assert invoice.sent_at is None

    event = AuditEvent.objects.filter(action_type="invoice.email_sent").latest("created_at")
    assert event.status == AuditEventStatus.FAILED
    assert "sent" in event.summary.lower()
    assert "db down" in event.summary
    assert event.metadata_json.get("delivered") is True


def test_draft_invoice_stays_draft_after_send(mailoutbox):
    """Only APPROVED invoices transition to SENT; a DRAFT keeps its status."""
    participant = factories.ParticipantFactory(email="draft@example.com")
    invoice = factories.InvoiceFactory(
        zev=participant.zev,
        participant=participant,
        status=InvoiceStatus.DRAFT,
    )
    invoice.pdf_file.save("invoice_test.pdf", ContentFile(b"PDF"), save=True)

    send_invoice_email_task.run(str(invoice.pk), "draft@example.com")

    assert len(mailoutbox) == 1
    invoice.refresh_from_db()
    assert invoice.status == InvoiceStatus.DRAFT
    assert invoice.sent_at is not None
