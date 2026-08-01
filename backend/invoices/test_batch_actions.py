"""Coverage for invoice batch and email-retry API actions.

The legacy ``invoices/tests.py`` covers single-invoice lifecycle transitions well.
This module focuses on the period-wide actions that can otherwise regress in
production workflows: approve-all, send-all, download-pdfs, and retry-email.
"""

from datetime import date
from unittest import mock

import pytest
from django.core.files.base import ContentFile
from rest_framework.test import APIClient

from invoices.models import EmailLog, InvoiceStatus
from testing.factories import InvoiceFactory, OwnerFactory, ParticipantFactory, ZevFactory
from testing.helpers import authenticate

pytestmark = pytest.mark.django_db

PERIOD_PAYLOAD = {
    "period_start": "2026-01-01",
    "period_end": "2026-01-31",
}


def _owner_client(owner):
    client = APIClient()
    authenticate(client, owner)
    return client


def _period_payload(zev):
    return {"zev_id": str(zev.id), **PERIOD_PAYLOAD}


def _invoice(participant, *, status=InvoiceStatus.DRAFT, period_start=date(2026, 1, 1), period_end=date(2026, 1, 31)):
    return InvoiceFactory(
        zev=participant.zev,
        participant=participant,
        status=status,
        period_start=period_start,
        period_end=period_end,
    )


class TestInvoiceBatchActions:
    def test_approve_all_approves_only_drafts_in_requested_period(self):
        owner = OwnerFactory()
        zev = ZevFactory(owner=owner)
        participant = ParticipantFactory(zev=zev)
        draft = _invoice(participant, status=InvoiceStatus.DRAFT)
        approved = _invoice(participant, status=InvoiceStatus.APPROVED)
        other_period = _invoice(
            participant,
            status=InvoiceStatus.DRAFT,
            period_start=date(2026, 2, 1),
            period_end=date(2026, 2, 28),
        )
        client = _owner_client(owner)

        response = client.post("/api/v1/invoices/invoices/approve-all/", _period_payload(zev), format="json")

        assert response.status_code == 200
        assert response.data == {"approved": 1}
        draft.refresh_from_db()
        approved.refresh_from_db()
        other_period.refresh_from_db()
        assert draft.status == InvoiceStatus.APPROVED
        assert approved.status == InvoiceStatus.APPROVED
        assert other_period.status == InvoiceStatus.DRAFT

    def test_send_all_queues_only_approved_invoices_with_recipient(self):
        owner = OwnerFactory()
        zev = ZevFactory(owner=owner)
        with_email = ParticipantFactory(zev=zev, email="with-email@example.com")
        without_email = ParticipantFactory(zev=zev, email="")
        draft_participant = ParticipantFactory(zev=zev, email="draft@example.com")
        approved_with_email = _invoice(with_email, status=InvoiceStatus.APPROVED)
        _invoice(without_email, status=InvoiceStatus.APPROVED)
        _invoice(draft_participant, status=InvoiceStatus.DRAFT)
        client = _owner_client(owner)

        with mock.patch("invoices.views.send_invoice_email_task.delay") as delay:
            response = client.post("/api/v1/invoices/invoices/send-all/", _period_payload(zev), format="json")

        assert response.status_code == 200
        assert response.data == {"queued": 1, "skipped": 1}
        delay.assert_called_once_with(str(approved_with_email.pk), "with-email@example.com")

    def test_batch_actions_reject_other_owners_zev(self):
        owner = OwnerFactory()
        other_owner = OwnerFactory()
        zev = ZevFactory(owner=owner)
        client = _owner_client(other_owner)

        response = client.post("/api/v1/invoices/invoices/approve-all/", _period_payload(zev), format="json")

        assert response.status_code == 403

    def test_download_pdfs_returns_404_when_period_has_no_pdfs(self):
        owner = OwnerFactory()
        zev = ZevFactory(owner=owner)
        participant = ParticipantFactory(zev=zev)
        _invoice(participant, status=InvoiceStatus.APPROVED)
        client = _owner_client(owner)

        response = client.post("/api/v1/invoices/invoices/download-pdfs/", _period_payload(zev), format="json")

        assert response.status_code == 404
        assert "No PDFs" in response.data["error"]

    def test_download_pdfs_returns_zip_for_available_pdfs(self):
        owner = OwnerFactory()
        zev = ZevFactory(owner=owner)
        participant = ParticipantFactory(zev=zev)
        invoice = _invoice(participant, status=InvoiceStatus.APPROVED)
        invoice.pdf_file.save("batch-invoice.pdf", ContentFile(b"PDF bytes"), save=True)
        client = _owner_client(owner)

        response = client.post("/api/v1/invoices/invoices/download-pdfs/", _period_payload(zev), format="json")

        assert response.status_code == 200
        assert response["Content-Type"] == "application/zip"
        assert "invoices-2026-01-01.zip" in response["Content-Disposition"]
        assert response.content

    def test_generate_all_queues_background_task(self):
        owner = OwnerFactory()
        zev = ZevFactory(owner=owner)
        ParticipantFactory(zev=zev)
        ParticipantFactory(zev=zev)
        client = _owner_client(owner)

        with mock.patch("invoices.views.generate_zev_invoices_task.delay") as delay:
            response = client.post("/api/v1/invoices/invoices/generate-all/", _period_payload(zev), format="json")

        assert response.status_code == 202
        assert response.data == {
            "detail": "Invoice generation queued.",
            "queued": True,
            "participant_count": 2,
        }
        delay.assert_called_once_with(str(zev.id), "2026-01-01", "2026-01-31")

    def test_generate_all_rejects_other_owners_zev(self):
        owner = OwnerFactory()
        other_owner = OwnerFactory()
        zev = ZevFactory(owner=owner)
        client = _owner_client(other_owner)

        with mock.patch("invoices.views.generate_zev_invoices_task.delay") as delay:
            response = client.post("/api/v1/invoices/invoices/generate-all/", _period_payload(zev), format="json")

        assert response.status_code == 403
        delay.assert_not_called()

    def test_generate_pdfs_all_queues_background_task(self):
        owner = OwnerFactory()
        zev = ZevFactory(owner=owner)
        participant = ParticipantFactory(zev=zev)
        _invoice(participant, status=InvoiceStatus.APPROVED)
        client = _owner_client(owner)

        with mock.patch("invoices.views.generate_zev_pdfs_task.delay") as delay:
            response = client.post("/api/v1/invoices/invoices/generate-pdfs-all/", _period_payload(zev), format="json")

        assert response.status_code == 202
        assert response.data == {
            "detail": "PDF generation queued.",
            "queued": True,
            "invoice_count": 1,
        }
        delay.assert_called_once_with(str(zev.id), "2026-01-01", "2026-01-31")


class TestBulkGenerationTasks:
    def test_generate_zev_invoices_task_calls_engine_for_period(self):
        from invoices.tasks import generate_zev_invoices_task

        owner = OwnerFactory()
        zev = ZevFactory(owner=owner)

        with mock.patch("invoices.engine.generate_invoices_for_zev", return_value=[]) as engine:
            generate_zev_invoices_task(str(zev.id), "2026-01-01", "2026-01-31")

        engine.assert_called_once_with(zev, date(2026, 1, 1), date(2026, 1, 31))

    def test_generate_zev_pdfs_task_renders_period_invoices(self):
        from invoices.tasks import generate_zev_pdfs_task

        owner = OwnerFactory()
        zev = ZevFactory(owner=owner)
        participant = ParticipantFactory(zev=zev)
        invoice = _invoice(participant, status=InvoiceStatus.APPROVED)
        _invoice(
            participant,
            status=InvoiceStatus.DRAFT,
            period_start=date(2026, 2, 1),
            period_end=date(2026, 2, 28),
        )

        with mock.patch("invoices.pdf.save_invoice_pdf") as save_pdf:
            generate_zev_pdfs_task(str(zev.id), "2026-01-01", "2026-01-31")

        save_pdf.assert_called_once()
        assert save_pdf.call_args[0][0].pk == invoice.pk


class TestPdfsAreProducedWithTheInvoice:
    """A PDF is part of producing an invoice, not a later step the operator has
    to remember: without one the invoice cannot be reviewed, downloaded or
    emailed, and the missing-PDF state was a rung on the batch action ladder."""

    def test_bulk_generation_renders_a_pdf_for_every_invoice(self):
        from invoices.tasks import generate_zev_invoices_task

        owner = OwnerFactory()
        zev = ZevFactory(owner=owner)
        participant = ParticipantFactory(zev=zev)
        invoices = [
            _invoice(participant),
            _invoice(participant, period_start=date(2026, 2, 1), period_end=date(2026, 2, 28)),
        ]

        with mock.patch("invoices.engine.generate_invoices_for_zev", return_value=invoices):
            with mock.patch("invoices.pdf.save_invoice_pdf") as save_pdf:
                generate_zev_invoices_task(str(zev.id), "2026-01-01", "2026-01-31")

        assert save_pdf.call_count == 2
        assert {call[0][0].pk for call in save_pdf.call_args_list} == {i.pk for i in invoices}

    def test_one_failing_pdf_does_not_cost_the_others_theirs(self):
        from invoices.tasks import generate_zev_invoices_task

        owner = OwnerFactory()
        zev = ZevFactory(owner=owner)
        participant = ParticipantFactory(zev=zev)
        invoices = [
            _invoice(participant),
            _invoice(participant, period_start=date(2026, 2, 1), period_end=date(2026, 2, 28)),
            _invoice(participant, period_start=date(2026, 3, 1), period_end=date(2026, 3, 31)),
        ]

        with mock.patch("invoices.engine.generate_invoices_for_zev", return_value=invoices):
            with mock.patch(
                "invoices.pdf.save_invoice_pdf",
                side_effect=[ValueError("bad debtor address"), None, None],
            ) as save_pdf:
                generate_zev_invoices_task(str(zev.id), "2026-01-01", "2026-01-31")

        assert save_pdf.call_count == 3

    def test_single_generate_queues_the_pdf_instead_of_blocking_the_response(self):
        """Rendering takes seconds; the caller only needs the invoice back."""
        owner = OwnerFactory()
        zev = ZevFactory(owner=owner)
        participant = ParticipantFactory(zev=zev)
        client = _owner_client(owner)

        with mock.patch("invoices.views.generate_invoice_pdf_task.delay") as queued:
            with mock.patch("invoices.views.generate_invoice", return_value=_invoice(participant)) as engine:
                response = client.post(
                    "/api/v1/invoices/invoices/generate/",
                    {"participant_id": str(participant.id), **PERIOD_PAYLOAD},
                    format="json",
                )

        assert response.status_code == 201
        engine.assert_called_once()
        queued.assert_called_once()

    def test_a_broker_outage_does_not_lose_the_generated_invoice(self):
        """The invoice is the deliverable and it is already committed. Failing
        the request because the queue is down would report an error for work
        that succeeded, leaving the operator unaware the invoice exists — while
        the PDF itself is recoverable (the email task renders one lazily, and
        there is a per-invoice regenerate action)."""
        owner = OwnerFactory()
        zev = ZevFactory(owner=owner)
        participant = ParticipantFactory(zev=zev)
        client = _owner_client(owner)

        with mock.patch(
            "invoices.views.generate_invoice_pdf_task.delay",
            side_effect=ConnectionError("Error 111 connecting to localhost:6379"),
        ):
            with mock.patch("invoices.views.generate_invoice", return_value=_invoice(participant)):
                response = client.post(
                    "/api/v1/invoices/invoices/generate/",
                    {"participant_id": str(participant.id), **PERIOD_PAYLOAD},
                    format="json",
                )

        assert response.status_code == 201

    def test_generate_invoice_pdf_task_renders_the_named_invoice(self):
        from invoices.tasks import generate_invoice_pdf_task

        owner = OwnerFactory()
        zev = ZevFactory(owner=owner)
        participant = ParticipantFactory(zev=zev)
        invoice = _invoice(participant)

        with mock.patch("invoices.pdf.save_invoice_pdf") as save_pdf:
            generate_invoice_pdf_task(str(invoice.pk))

        save_pdf.assert_called_once()
        assert save_pdf.call_args[0][0].pk == invoice.pk

    def test_generate_invoice_pdf_task_tolerates_a_deleted_invoice(self):
        from invoices.tasks import generate_invoice_pdf_task

        import uuid

        with mock.patch("invoices.pdf.save_invoice_pdf") as save_pdf:
            generate_invoice_pdf_task(str(uuid.uuid4()))

        save_pdf.assert_not_called()


class TestInvoiceRetryEmailAction:
    def test_retry_email_rejects_already_sent_log(self):
        owner = OwnerFactory()
        zev = ZevFactory(owner=owner)
        participant = ParticipantFactory(zev=zev)
        invoice = _invoice(participant, status=InvoiceStatus.SENT)
        email_log = EmailLog.objects.create(
            invoice=invoice,
            recipient="sent@example.com",
            subject="Invoice",
            status=EmailLog.Status.SENT,
        )
        client = _owner_client(owner)

        response = client.post(f"/api/v1/invoices/invoices/{invoice.pk}/retry-email/{email_log.pk}/")

        assert response.status_code == 400
        assert response.data["error"] == "Email already sent."

    def test_retry_email_queues_failed_log_recipient(self):
        owner = OwnerFactory()
        zev = ZevFactory(owner=owner)
        participant = ParticipantFactory(zev=zev)
        invoice = _invoice(participant, status=InvoiceStatus.APPROVED)
        email_log = EmailLog.objects.create(
            invoice=invoice,
            recipient="failed@example.com",
            subject="Invoice",
            status=EmailLog.Status.FAILED,
            error_message="smtp down",
        )
        client = _owner_client(owner)

        with mock.patch("invoices.views.send_invoice_email_task.delay") as delay:
            response = client.post(f"/api/v1/invoices/invoices/{invoice.pk}/retry-email/{email_log.pk}/")

        assert response.status_code == 200
        assert response.data["detail"] == "Email retry queued for failed@example.com."
        delay.assert_called_once_with(str(invoice.pk), "failed@example.com")

    def test_retry_email_rejects_log_from_different_invoice(self):
        owner = OwnerFactory()
        zev = ZevFactory(owner=owner)
        participant = ParticipantFactory(zev=zev)
        invoice = _invoice(participant, status=InvoiceStatus.APPROVED)
        other_invoice = _invoice(participant, status=InvoiceStatus.APPROVED)
        other_log = EmailLog.objects.create(
            invoice=other_invoice,
            recipient="other@example.com",
            subject="Invoice",
            status=EmailLog.Status.FAILED,
        )
        client = _owner_client(owner)

        response = client.post(f"/api/v1/invoices/invoices/{invoice.pk}/retry-email/{other_log.pk}/")

        assert response.status_code == 404
