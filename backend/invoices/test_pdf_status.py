"""Coverage for ``Invoice.pdf_status``.

An invoice's document is rendered off the request, so ``pdf_file`` being empty
answers "is there a document" but not "is one coming". This field is the second
answer, and the tests that matter are the ones asserting it never claims more
than the row actually holds: READY only alongside a stored file, FAILED
wherever a render died, and never left PENDING for work that was never queued.
"""

from datetime import date
from unittest import mock

import pytest
from rest_framework.test import APIClient

from invoices.models import Invoice, InvoicePdfStatus, InvoiceStatus
from testing.factories import InvoiceFactory, OwnerFactory, ParticipantFactory, ZevFactory
from testing.helpers import authenticate

pytestmark = pytest.mark.django_db


def _client(owner):
    client = APIClient()
    authenticate(client, owner)
    return client


def _setup():
    owner = OwnerFactory()
    zev = ZevFactory(owner=owner)
    participant = ParticipantFactory(zev=zev)
    return owner, zev, participant


def _invoice(participant, **kwargs):
    return InvoiceFactory(
        zev=participant.zev,
        participant=participant,
        status=kwargs.pop("status", InvoiceStatus.DRAFT),
        period_start=kwargs.pop("period_start", date(2026, 1, 1)),
        period_end=kwargs.pop("period_end", date(2026, 1, 31)),
        **kwargs,
    )


class TestDefaultAndBackfill:
    def test_a_new_invoice_has_no_document_and_says_so(self):
        _owner, _zev, participant = _setup()

        assert _invoice(participant).pdf_status == InvoicePdfStatus.NONE

    def test_none_is_not_failed(self):
        """Nobody asked for a document, so nothing failed to produce one."""
        _owner, _zev, participant = _setup()

        assert _invoice(participant).pdf_status != InvoicePdfStatus.FAILED


class TestRenderOutcomes:
    def test_a_saved_pdf_is_ready(self):
        from invoices.pdf import save_invoice_pdf

        _owner, _zev, participant = _setup()
        invoice = _invoice(participant)

        with mock.patch("invoices.pdf.generate_pdf", return_value=b"%PDF-1.7\n"):
            save_invoice_pdf(invoice)

        invoice.refresh_from_db()
        assert invoice.pdf_status == InvoicePdfStatus.READY
        assert invoice.pdf_file

    def test_ready_is_written_with_the_file_not_before_it(self):
        """A status claiming a document the row does not have is worse than none."""
        from invoices.pdf import save_invoice_pdf

        _owner, _zev, participant = _setup()
        invoice = _invoice(participant)

        with mock.patch("invoices.pdf.generate_pdf", side_effect=RuntimeError("boom")):
            with pytest.raises(RuntimeError):
                save_invoice_pdf(invoice)

        invoice.refresh_from_db()
        assert invoice.pdf_status == InvoicePdfStatus.NONE
        assert not invoice.pdf_file

    def test_a_failed_render_is_recorded_as_failed(self):
        from invoices.tasks import _render_pdfs

        _owner, _zev, participant = _setup()
        invoice = _invoice(participant)

        with mock.patch("invoices.pdf.save_invoice_pdf", side_effect=RuntimeError("boom")):
            assert _render_pdfs([invoice]) == 1

        invoice.refresh_from_db()
        assert invoice.pdf_status == InvoicePdfStatus.FAILED

    def test_a_shared_context_failure_fails_every_invoice_in_the_period(self):
        """These never reach save_invoice_pdf, so they need marking separately."""
        from invoices.tasks import _render_pdfs

        _owner, _zev, participant = _setup()
        first = _invoice(participant)
        second = _invoice(participant)

        with mock.patch(
            "invoices.pdf.build_invoice_pdf_period_context", side_effect=RuntimeError("boom"),
        ):
            assert _render_pdfs([first, second]) == 2

        for invoice in (first, second):
            invoice.refresh_from_db()
            assert invoice.pdf_status == InvoicePdfStatus.FAILED

    def test_one_failure_does_not_mark_its_neighbours_failed(self):
        from invoices.tasks import _render_pdfs

        _owner, _zev, participant = _setup()
        doomed = _invoice(participant)
        fine = _invoice(participant)

        def render(invoice, **_kwargs):
            if invoice.pk == doomed.pk:
                raise RuntimeError("boom")
            Invoice.objects.filter(pk=invoice.pk).update(pdf_status=InvoicePdfStatus.READY)

        with mock.patch("invoices.pdf.save_invoice_pdf", side_effect=render):
            _render_pdfs([doomed, fine])

        doomed.refresh_from_db()
        fine.refresh_from_db()
        assert doomed.pdf_status == InvoicePdfStatus.FAILED
        assert fine.pdf_status == InvoicePdfStatus.READY


class TestQueueingMarksPending:
    def test_generating_an_invoice_marks_its_pdf_pending(self):
        owner, zev, participant = _setup()

        with mock.patch("invoices.views.generate_invoice_pdf_task.delay"):
            resp = _client(owner).post(
                "/api/v1/invoices/invoices/generate/",
                {
                    "participant_id": str(participant.id),
                    "period_start": "2026-01-01",
                    "period_end": "2026-01-31",
                },
                format="json",
            )

        assert resp.status_code in (200, 201)
        assert Invoice.objects.get(pk=resp.data["id"]).pdf_status == InvoicePdfStatus.PENDING

    def test_a_broker_outage_marks_failed_rather_than_pending(self):
        """Nothing is coming, so the UI must not show it as on its way."""
        owner, zev, participant = _setup()

        with mock.patch(
            "invoices.views.generate_invoice_pdf_task.delay", side_effect=RuntimeError("no broker"),
        ):
            resp = _client(owner).post(
                "/api/v1/invoices/invoices/generate/",
                {
                    "participant_id": str(participant.id),
                    "period_start": "2026-01-01",
                    "period_end": "2026-01-31",
                },
                format="json",
            )

        assert resp.status_code in (200, 201)
        assert Invoice.objects.get(pk=resp.data["id"]).pdf_status == InvoicePdfStatus.FAILED

    def test_bulk_pdf_generation_marks_the_whole_period_pending(self):
        owner, zev, participant = _setup()
        invoice = _invoice(participant)

        with mock.patch("invoices.views.generate_zev_pdfs_task.delay"):
            resp = _client(owner).post(
                "/api/v1/invoices/invoices/generate-pdfs-all/",
                {"zev_id": str(zev.id), "period_start": "2026-01-01", "period_end": "2026-01-31"},
                format="json",
            )

        assert resp.status_code == 202
        invoice.refresh_from_db()
        assert invoice.pdf_status == InvoicePdfStatus.PENDING

    def test_bulk_invoice_generation_marks_new_invoices_pending(self):
        from invoices.tasks import generate_zev_invoices_task

        _owner, zev, participant = _setup()
        invoices = [_invoice(participant)]
        seen = {}

        def render(invoice, **_kwargs):
            # Read inside the render so the assertion is about what the worker
            # would see, not about the state left after it finished.
            seen[invoice.pk] = Invoice.objects.get(pk=invoice.pk).pdf_status

        with mock.patch("invoices.engine.generate_invoices_for_zev", return_value=(invoices, [])):
            with mock.patch("invoices.pdf.save_invoice_pdf", side_effect=render):
                generate_zev_invoices_task(str(zev.id), "2026-01-01", "2026-01-31")

        assert seen[invoices[0].pk] == InvoicePdfStatus.PENDING


class TestApiExposure:
    def test_the_invoice_payload_reports_the_status(self):
        owner, _zev, participant = _setup()
        invoice = _invoice(participant)

        resp = _client(owner).get(f"/api/v1/invoices/invoices/{invoice.pk}/")

        assert resp.data["pdf_status"] == InvoicePdfStatus.NONE

    def test_a_client_cannot_set_the_status(self):
        """It is written by the render pipeline; a client claiming READY would
        make the column lie about a document that does not exist."""
        owner, _zev, participant = _setup()
        invoice = _invoice(participant)

        _client(owner).patch(
            f"/api/v1/invoices/invoices/{invoice.pk}/",
            {"pdf_status": InvoicePdfStatus.READY},
            format="json",
        )

        invoice.refresh_from_db()
        assert invoice.pdf_status == InvoicePdfStatus.NONE

    def test_the_sync_regenerate_records_a_failure(self):
        owner, _zev, participant = _setup()
        invoice = _invoice(participant)

        with mock.patch("invoices.views.save_invoice_pdf", side_effect=RuntimeError("boom")):
            resp = _client(owner).post(
                f"/api/v1/invoices/invoices/{invoice.pk}/generate-pdf/",
            )

        assert resp.status_code == 500
        invoice.refresh_from_db()
        assert invoice.pdf_status == InvoicePdfStatus.FAILED
