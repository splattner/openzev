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


def _invoice(participant, *, status=InvoiceStatus.DRAFT, period_start=date(2026, 1, 1), period_end=date(2026, 1, 31), invoice_number=None):
    kwargs = {"invoice_number": invoice_number} if invoice_number else {}
    return InvoiceFactory(
        zev=participant.zev,
        participant=participant,
        status=status,
        period_start=period_start,
        period_end=period_end,
        **kwargs,
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

        with mock.patch("invoices.engine.generate_invoices_for_zev", return_value=([], [])) as engine:
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

        with mock.patch("invoices.engine.generate_invoices_for_zev", return_value=(invoices, [])):
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

        with mock.patch("invoices.engine.generate_invoices_for_zev", return_value=(invoices, [])):
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


class TestBulkGenerationIsolatesPerParticipantFailures:
    """One participant's failure must not cost the rest of the ZEV its
    billing run — the invoice batch mirrors the PDF batch isolation
    (``_render_pdfs``)."""

    def test_one_locked_invoice_does_not_abort_the_batch(self):
        from invoices.engine import generate_invoices_for_zev

        owner = OwnerFactory()
        zev = ZevFactory(owner=owner)
        blocked = ParticipantFactory(zev=zev)
        ok = ParticipantFactory(zev=zev)
        _invoice(blocked, status=InvoiceStatus.APPROVED, invoice_number="INV-90001")

        result = generate_invoices_for_zev(zev, date(2026, 1, 1), date(2026, 1, 31))

        assert [invoice.participant_id for invoice in result.invoices] == [ok.id]
        assert len(result.failures) == 1
        assert result.failures[0]["participant_id"] == str(blocked.id)
        assert result.failures[0]["participant_name"] == blocked.full_name
        assert "cannot be regenerated" in result.failures[0]["error"].lower()

    def test_task_reports_partial_success_in_the_audit_event(self):
        from audit.models import AuditEvent, AuditEventStatus
        from invoices.tasks import generate_zev_invoices_task

        owner = OwnerFactory()
        zev = ZevFactory(owner=owner)
        blocked = ParticipantFactory(zev=zev)
        ParticipantFactory(zev=zev)
        _invoice(blocked, status=InvoiceStatus.APPROVED, invoice_number="INV-90001")

        with mock.patch("invoices.pdf.save_invoice_pdf"):
            generate_zev_invoices_task(str(zev.id), "2026-01-01", "2026-01-31")

        event = AuditEvent.objects.filter(action_type="invoice.generate_all").latest("created_at")
        assert event.status == AuditEventStatus.FAILED
        assert event.metadata_json["invoice_count"] == 1
        assert len(event.metadata_json["failures"]) == 1
        assert event.metadata_json["failures"][0]["participant_id"] == str(blocked.id)
        assert "1 participant(s) failed" in event.summary

    def test_failed_participant_gives_its_invoice_number_back(self):
        """A failure *after* ``next_invoice_number()`` must give its number back.

        The locked-invoice guard raises before the counter is touched, so the
        other tests here never exercise the counter path. If the shared ``zev``
        instance is not re-synced after the savepoint rollback, the next
        participant re-uses the stale ``+1`` and either skips a number or
        collides with the previous one (a phantom ``UNIQUE constraint failed``).
        """
        from django.db import IntegrityError
        from invoices.engine import generate_invoices_for_zev
        from invoices.models import Invoice

        owner = OwnerFactory()
        zev = ZevFactory(owner=owner)
        # Participant ordering is (last_name, first_name), so the failing
        # participant sorts first and is processed before the two successes.
        failing = ParticipantFactory(zev=zev, last_name="AAA")
        ParticipantFactory(zev=zev, last_name="BBB")
        ParticipantFactory(zev=zev, last_name="CCC")

        real_create = Invoice.objects.create

        def failing_create(**kwargs):
            if kwargs["participant"].id == failing.id:
                raise IntegrityError("simulated constraint violation")
            return real_create(**kwargs)

        with mock.patch.object(Invoice.objects, "create", side_effect=failing_create):
            result = generate_invoices_for_zev(zev, date(2026, 1, 1), date(2026, 1, 31))

        # The failed participant consumed (and gave back) number 1; the two
        # successes then take 01 and 02 — gapless and collision-free, not the
        # [02, 03] with a phantom second failure the stale counter would cause.
        ok_ids = {p.id for p in zev.participants.exclude(id=failing.id)}
        assert {i.participant_id for i in result.invoices} == ok_ids
        assert {i.invoice_number for i in result.invoices} == {"INV-00001", "INV-00002"}
        assert len(result.failures) == 1
        assert result.failures[0]["participant_id"] == str(failing.id)
        assert "simulated constraint violation" in result.failures[0]["error"]


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
