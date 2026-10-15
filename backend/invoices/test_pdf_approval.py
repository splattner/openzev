"""Stored PDFs and email attachments must follow the approved document copy."""

import io
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic, sleep
from unittest.mock import patch

import pytest
from django.db import connection, connections, transaction
from django.test.utils import CaptureQueriesContext
from pypdf import PdfReader

from invoices.document_parties import copy_for_render
from invoices.models import Invoice, InvoicePdfStatus, InvoiceStatus
from invoices.pdf import InvoicePdfSupersededError, save_invoice_pdf
from invoices.tasks import _render_pdfs, send_invoice_email_task
from invoices.workflow import approve_invoice, mark_invoice_sent
from testing.factories import InvoiceFactory, ParticipantFactory
from testing.helpers import authenticate
from zev.parties import ensure_initial_roles


def _render_copy(invoice, **_kwargs):
    issuer, recipient = copy_for_render(invoice)
    return json.dumps({"issuer": issuer, "recipient": recipient}).encode()


@pytest.mark.django_db
@pytest.mark.parametrize("batch", [False, True])
def test_email_attaches_the_approved_copy(
    batch, owner_client, participant, mailoutbox, django_capture_on_commit_callbacks,
):
    invoice = InvoiceFactory(zev=participant.zev, participant=participant)
    with patch("invoices.pdf.generate_pdf", side_effect=_render_copy):
        save_invoice_pdf(invoice)
    draft_name = invoice.pdf_file.name
    storage = invoice.pdf_file.storage

    participant.party.address_line1 = "Approved address 7"
    participant.party.save(update_fields=["address_line1"])
    participant.zev.bank_name = "Approved bank"
    participant.zev.save(update_fields=["bank_name"])

    with django_capture_on_commit_callbacks(execute=True):
        if batch:
            response = owner_client.post("/api/v1/invoices/invoices/approve-all/", {
                "zev_id": str(invoice.zev_id),
                "period_start": str(invoice.period_start),
                "period_end": str(invoice.period_end),
            }, format="json")
            assert response.status_code == 200
            assert response.data["approved"] == 1
        else:
            response = owner_client.post(f"/api/v1/invoices/invoices/{invoice.pk}/approve/")
            assert response.status_code == 200

    invoice.refresh_from_db()
    assert invoice.status == InvoiceStatus.APPROVED
    assert not invoice.pdf_file
    assert invoice.pdf_status == InvoicePdfStatus.NONE
    assert not storage.exists(draft_name)

    # Subsequent party edits must not leak into a newly rendered attachment.
    participant.party.address_line1 = "Later address 9"
    participant.party.save(update_fields=["address_line1"])
    with patch("invoices.pdf.generate_pdf", side_effect=_render_copy):
        send_invoice_email_task.run(str(invoice.pk))

    assert len(mailoutbox) == 1
    attachment = json.loads(mailoutbox[0].attachments[0][1])
    assert attachment["recipient"]["address_line1"] == "Approved address 7"
    assert attachment["issuer"]["bank_name"] == "Approved bank"
    invoice.refresh_from_db()
    assert invoice.status == InvoiceStatus.SENT
    assert invoice.pdf_status == InvoicePdfStatus.READY


@pytest.mark.django_db
@pytest.mark.parametrize("change_copy", [False, True])
def test_late_draft_render_is_discarded_and_email_uses_the_approved_copy(
    change_copy, participant, mailoutbox, django_capture_on_commit_callbacks,
):
    invoice = InvoiceFactory(zev=participant.zev, participant=participant)
    rendered = []

    def render(inv, **kwargs):
        content = _render_copy(inv, **kwargs)
        rendered.append(content)
        if len(rendered) == 1:
            if change_copy:
                participant.party.address_line1 = "Approved address 7"
                participant.party.save(update_fields=["address_line1"])
            approve_invoice(Invoice.objects.get(pk=invoice.pk))
        return content

    with (
        django_capture_on_commit_callbacks(execute=True),
        patch("invoices.pdf.generate_pdf", side_effect=render) as generate,
        patch.object(invoice.pdf_file.storage, "delete", wraps=invoice.pdf_file.storage.delete) as delete,
    ):
        save_invoice_pdf(invoice)
        send_invoice_email_task.run(str(invoice.pk))

    assert generate.call_count == 2
    assert len(mailoutbox) == 1
    assert mailoutbox[0].attachments[0][1] == rendered[1]
    assert json.loads(rendered[1])["recipient"]["address_line1"] == (
        "Approved address 7" if change_copy else ""
    )
    delete.assert_called_once()
    invoice.refresh_from_db()
    assert invoice.pdf_file.read() == rendered[1]
    assert invoice.status == InvoiceStatus.SENT
    assert invoice.pdf_status == InvoicePdfStatus.READY


@pytest.mark.django_db
def test_approval_uses_current_data_even_with_cached_relations(participant):
    invoice = InvoiceFactory(zev=participant.zev, participant=participant)
    invoice = Invoice.objects.select_related("zev", "participant__party").get(pk=invoice.pk)
    participant.party.address_line1 = "Approved address 7"
    participant.party.save(update_fields=["address_line1"])

    approve_invoice(invoice)

    assert invoice.recipient["address_line1"] == "Approved address 7"


@pytest.mark.django_db
def test_rolled_back_approval_keeps_the_draft_pdf(participant, django_capture_on_commit_callbacks):
    invoice = InvoiceFactory(zev=participant.zev, participant=participant)
    with patch("invoices.pdf.generate_pdf", side_effect=_render_copy):
        save_invoice_pdf(invoice)
    draft_name = invoice.pdf_file.name

    with django_capture_on_commit_callbacks(execute=True):
        with pytest.raises(RuntimeError, match="roll back"):
            with transaction.atomic():
                approve_invoice(invoice)
                raise RuntimeError("roll back")

    invoice.refresh_from_db()
    assert invoice.status == InvoiceStatus.DRAFT
    assert invoice.pdf_file.name == draft_name
    assert invoice.pdf_file.storage.exists(draft_name)
    assert invoice.pdf_status == InvoicePdfStatus.READY


@pytest.mark.django_db
def test_repeated_snapshot_changes_abort_without_publishing(participant):
    invoice = InvoiceFactory(zev=participant.zev, participant=participant)

    def render(inv, **kwargs):
        content = _render_copy(inv, **kwargs)
        Invoice.objects.filter(pk=invoice.pk).update(recipient={"changed": True})
        return content

    with (
        patch("invoices.pdf.generate_pdf", side_effect=render) as generate,
        patch.object(invoice.pdf_file.storage, "delete", wraps=invoice.pdf_file.storage.delete) as delete,
    ):
        with pytest.raises(InvoicePdfSupersededError, match="both PDF render attempts"):
            save_invoice_pdf(invoice)

    assert generate.call_count == 2
    assert delete.call_count == 2
    assert all(not invoice.pdf_file.storage.exists(call.args[0]) for call in delete.call_args_list)
    invoice.refresh_from_db()
    assert not invoice.pdf_file
    assert invoice.pdf_status == InvoicePdfStatus.NONE


@pytest.mark.django_db
def test_repeated_snapshot_changes_clear_pending_pdf_status(participant):
    invoice = InvoiceFactory(
        zev=participant.zev, participant=participant, pdf_status=InvoicePdfStatus.PENDING,
    )

    def render(inv, **kwargs):
        content = _render_copy(inv, **kwargs)
        Invoice.objects.filter(pk=invoice.pk).update(recipient={"changed": True})
        return content

    with patch("invoices.pdf.generate_pdf", side_effect=render) as generate:
        assert _render_pdfs([invoice]) == 0

    assert generate.call_count == 2
    invoice.refresh_from_db()
    assert not invoice.pdf_file
    assert invoice.pdf_status == InvoicePdfStatus.NONE


@pytest.mark.django_db
@pytest.mark.parametrize("caller", ["http", "task"])
@pytest.mark.parametrize("superseded", [False, True])
def test_losing_render_preserves_the_winning_pdf(caller, superseded, owner_client, participant):
    invoice = InvoiceFactory(
        zev=participant.zev, participant=participant, pdf_status=InvoicePdfStatus.PENDING,
    )
    attempts = []
    winning_files = []

    def render(inv, **_kwargs):
        content = _render_copy(inv)
        attempts.append(content)
        if superseded and len(attempts) == 1:
            approve_invoice(Invoice.objects.get(pk=invoice.pk))
            return content

        winner = Invoice.objects.get(pk=invoice.pk)
        with patch("invoices.pdf.generate_pdf", side_effect=_render_copy):
            save_invoice_pdf(winner)
        winning_files.append(winner.pdf_file.name)
        if superseded:
            mark_invoice_sent(winner)
            return content
        raise RuntimeError("Renderer failed after another render finished")

    with patch("invoices.pdf.generate_pdf", side_effect=render):
        if caller == "http":
            response = owner_client.post(f"/api/v1/invoices/invoices/{invoice.pk}/generate-pdf/")
            assert response.status_code == (409 if superseded else 500)
        else:
            assert _render_pdfs([invoice]) == (0 if superseded else 1)

    invoice.refresh_from_db()
    assert len(attempts) == (2 if superseded else 1)
    assert invoice.pdf_file.name == winning_files[0]
    assert invoice.pdf_status == InvoicePdfStatus.READY
    assert json.loads(invoice.pdf_file.read())["recipient"] == invoice.recipient


@pytest.mark.django_db
@pytest.mark.parametrize("caller", ["http", "task"])
def test_old_render_failure_preserves_approval(caller, owner_client, participant):
    invoice = InvoiceFactory(zev=participant.zev, participant=participant)

    def render(inv, **_kwargs):
        copy_for_render(inv)
        approve_invoice(Invoice.objects.get(pk=inv.pk))
        raise RuntimeError("Draft render failed after approval")

    with patch("invoices.pdf.generate_pdf", side_effect=render):
        if caller == "http":
            assert owner_client.post(f"/api/v1/invoices/invoices/{invoice.pk}/generate-pdf/").status_code == 500
        else:
            assert _render_pdfs([invoice]) == 1

    invoice.refresh_from_db()
    assert invoice.status == InvoiceStatus.APPROVED
    assert invoice.pdf_status == InvoicePdfStatus.NONE
    assert not invoice.pdf_file


@pytest.mark.django_db
def test_batch_approval_has_a_bounded_query_budget(owner_client, participant):
    invoices = InvoiceFactory.create_batch(10, zev=participant.zev, participant=participant)

    with CaptureQueriesContext(connection) as queries:
        response = owner_client.post("/api/v1/invoices/invoices/approve-all/", {
            "zev_id": str(participant.zev_id), "period_start": str(invoices[0].period_start),
            "period_end": str(invoices[0].period_end),
        }, format="json")

    assert response.status_code == 200
    assert response.data["approved"] == len(invoices)
    assert len(queries) <= 5 * len(invoices) + 15
    assert not any('FROM "invoices_invoiceitem"' in query["sql"] for query in queries)
    assert not any('FROM "invoices_emaillog"' in query["sql"] for query in queries)


@pytest.mark.django_db
def test_changed_draft_copy_publishes_with_one_render(participant):
    invoice = InvoiceFactory(zev=participant.zev, participant=participant)
    copy_for_render(invoice)
    invoice = Invoice.objects.get(pk=invoice.pk)
    participant.party.address_line1 = "Updated address 7"
    participant.party.save(update_fields=["address_line1"])

    with patch("invoices.pdf.render_pdf", return_value=b"%PDF test") as renderer:
        save_invoice_pdf(invoice)

    renderer.assert_called_once()
    assert invoice.recipient["address_line1"] == "Updated address 7"
    assert Invoice.objects.get(pk=invoice.pk).recipient == invoice.recipient


@pytest.mark.django_db
@pytest.mark.slow
def test_rendered_pdf_and_qr_use_the_approved_copy(participant):
    zev = participant.zev
    issuer = ParticipantFactory(
        zev=zev, address_line1="IssuerStreet 1", postal_code="8001", city="Zurich",
    )
    ensure_initial_roles(zev, issuer.party, issuer.valid_from)
    participant.address_line1 = "DraftStreet 1"
    participant.postal_code = "3000"
    participant.city = "Bern"
    participant.save(update_fields=["address_line1", "postal_code", "city"])
    zev.bank_iban = "CH9300762011623852957"
    zev.save(update_fields=["bank_iban"])
    invoice = InvoiceFactory(zev=zev, participant=participant, total_chf="42.00")
    save_invoice_pdf(invoice)

    participant.address_line1 = "ApprovedStreet 7"
    participant.save(update_fields=["address_line1"])
    zev.bank_iban = "CH5604835012345678009"
    zev.save(update_fields=["bank_iban"])
    approve_invoice(Invoice.objects.get(pk=invoice.pk))
    participant.address_line1 = "LaterStreet 9"
    participant.save(update_fields=["address_line1"])
    zev.bank_iban = "CH4431999123000889012"
    zev.save(update_fields=["bank_iban"])

    from qrbill import QRBill

    with patch("qrbill.QRBill", wraps=QRBill) as qr:
        save_invoice_pdf(Invoice.objects.get(pk=invoice.pk))

    invoice.refresh_from_db()
    text = "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(invoice.pdf_file.read())).pages)
    assert "ApprovedStreet 7" in text
    assert "DraftStreet 1" not in text
    assert "LaterStreet 9" not in text
    assert qr.call_args.kwargs["account"] == "CH5604835012345678009"
    assert qr.call_args.kwargs["debtor"]["street"] == "ApprovedStreet 7"


@pytest.mark.django_db
@pytest.mark.parametrize("manual_send", [False, True])
def test_owner_can_generate_a_missing_pdf_after_approval(
    manual_send, owner_client, participant, participant_user, api_client,
):
    participant.user = participant_user
    participant.save(update_fields=["user"])
    invoice = InvoiceFactory(zev=participant.zev, participant=participant)
    with patch("invoices.pdf.generate_pdf", side_effect=_render_copy):
        save_invoice_pdf(invoice)

    assert owner_client.post(f"/api/v1/invoices/invoices/{invoice.pk}/approve/").status_code == 200
    assert owner_client.get(f"/api/v1/invoices/invoices/{invoice.pk}/pdf/").status_code == 404
    response = owner_client.post("/api/v1/invoices/invoices/download-pdfs/", {
        "zev_id": str(invoice.zev_id), "period_start": str(invoice.period_start),
        "period_end": str(invoice.period_end),
    }, format="json")
    assert response.status_code == 404
    assert response.data["error"] == "No PDFs available for this period."

    if manual_send:
        assert owner_client.post(f"/api/v1/invoices/invoices/{invoice.pk}/mark-sent/").status_code == 200
        authenticate(api_client, participant_user)
        response = api_client.get(f"/api/v1/invoices/invoices/{invoice.pk}/")
        assert response.status_code == 200
        assert response.data["pdf_url"] is None
        assert response.data["pdf_status"] == InvoicePdfStatus.NONE

    with patch("invoices.pdf.render_pdf", return_value=b"%PDF test"):
        response = owner_client.post(f"/api/v1/invoices/invoices/{invoice.pk}/generate-pdf/")

    assert response.status_code == 200
    invoice.refresh_from_db()
    assert invoice.pdf_status == InvoicePdfStatus.READY


@pytest.mark.django_db
@pytest.mark.parametrize("caller", ["http", "task"])
def test_pdf_generation_handles_a_concurrent_deletion(caller, owner_client, participant):
    invoice = InvoiceFactory(zev=participant.zev, participant=participant)

    def render(inv, **_kwargs):
        content = _render_copy(inv)
        Invoice.objects.get(pk=inv.pk).delete()
        return content

    with patch("invoices.pdf.generate_pdf", side_effect=render):
        if caller == "http":
            assert owner_client.post(f"/api/v1/invoices/invoices/{invoice.pk}/generate-pdf/").status_code == 404
        else:
            assert _render_pdfs([invoice]) == 0

    assert not Invoice.objects.filter(pk=invoice.pk).exists()


@pytest.mark.django_db(transaction=True)
def test_pdf_publication_waits_for_approval_and_rechecks_its_copy(participant):
    if connection.vendor != "postgresql":
        pytest.skip("Requires PostgreSQL row locks and pg_blocking_pids")

    invoice = InvoiceFactory(zev=participant.zev, participant=participant)
    rendered, publish = Event(), Event()
    worker_pid = []
    copies = []

    def render(inv, **kwargs):
        content = _render_copy(inv, **kwargs)
        copies.append(content)
        if len(copies) == 1:
            rendered.set()
            assert publish.wait(10), "Test did not release PDF publication"
        return content

    def save_on_worker():
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '5s'")
                cursor.execute("SET statement_timeout = '10s'")
                cursor.execute("SELECT pg_backend_pid()")
                worker_pid.append(cursor.fetchone()[0])
            save_invoice_pdf(Invoice.objects.get(pk=invoice.pk))
        finally:
            connections.close_all()

    with patch("invoices.pdf.generate_pdf", side_effect=render), ThreadPoolExecutor(max_workers=1) as pool:
        worker = pool.submit(save_on_worker)
        try:
            assert rendered.wait(10), "Worker did not render the draft"
            participant.party.address_line1 = "Approved address 7"
            participant.party.save(update_fields=["address_line1"])
            with transaction.atomic():
                approve_invoice(invoice)
                publish.set()
                deadline = monotonic() + 5
                blocked = False
                while monotonic() < deadline:
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT cardinality(pg_blocking_pids(%s))", [worker_pid[0]])
                        blocked = cursor.fetchone()[0] > 0
                    if blocked:
                        break
                    sleep(0.01)
                assert blocked, "PDF publication did not wait for the approval transaction"
        finally:
            publish.set()
        worker.result(timeout=10)

    invoice.refresh_from_db()
    assert invoice.status == InvoiceStatus.APPROVED
    assert invoice.pdf_status == InvoicePdfStatus.READY
    assert len(copies) == 2
    assert invoice.pdf_file.read() == copies[1]
    assert json.loads(copies[1])["recipient"]["address_line1"] == "Approved address 7"
