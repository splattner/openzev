"""Invoice lifecycle workflow and regeneration guard tests."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from decimal import Decimal
from threading import Event
from time import monotonic, sleep
from unittest import mock

import pytest
from django.db import connection, connections, transaction
from django.test import TestCase
from django.utils import timezone as django_timezone
from rest_framework.test import APIClient

from accounts.models import UserRole
from invoices.engine import DynamicPriceGapError
from invoices.models import Invoice, InvoiceStatus
from invoices.test_helpers import make_invoice, make_participant, make_user, make_zev
from invoices.workflow import (
    InvoiceWorkflowError,
    approve_invoice,
    cancel_invoice,
    mark_invoice_paid,
    mark_invoice_sent,
    record_email_delivery,
)
from testing import factories
from testing.helpers import authenticate as auth
from tariffs.dynamic.models import DynamicTariffSource
from tariffs.models import BillingMode, EnergyType, Tariff, TariffCategory


class InvoiceWorkflowTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = make_user("wf_owner", UserRole.ZEV_OWNER)
        self.zev = make_zev(self.owner, "WF ZEV")
        self.participant = make_participant(self.zev)
        auth(self.client, self.owner)

    def _action(self, invoice, action_url):
        return self.client.post(f"/api/v1/invoices/invoices/{invoice.pk}/{action_url}/")

    def test_approve_draft(self):
        inv = make_invoice(self.zev, self.participant, InvoiceStatus.DRAFT)
        resp = self._action(inv, "approve")
        self.assertEqual(resp.status_code, 200)
        inv.refresh_from_db()
        self.assertEqual(inv.status, InvoiceStatus.APPROVED)

    def test_approve_already_approved_fails(self):
        inv = make_invoice(self.zev, self.participant, InvoiceStatus.APPROVED)
        resp = self._action(inv, "approve")
        self.assertEqual(resp.status_code, 400)

    def test_mark_sent_from_approved(self):
        inv = make_invoice(self.zev, self.participant, InvoiceStatus.APPROVED)
        resp = self._action(inv, "mark-sent")
        self.assertEqual(resp.status_code, 200)
        inv.refresh_from_db()
        self.assertEqual(inv.status, InvoiceStatus.SENT)
        self.assertIsNotNone(inv.sent_at)

    def test_mark_sent_from_draft_fails(self):
        inv = make_invoice(self.zev, self.participant, InvoiceStatus.DRAFT)
        resp = self._action(inv, "mark-sent")
        self.assertEqual(resp.status_code, 400)

    def test_mark_paid_from_sent(self):
        inv = make_invoice(self.zev, self.participant, InvoiceStatus.SENT)
        resp = self._action(inv, "mark-paid")
        self.assertEqual(resp.status_code, 200)
        inv.refresh_from_db()
        self.assertEqual(inv.status, InvoiceStatus.PAID)

    def test_mark_paid_from_draft_fails(self):
        inv = make_invoice(self.zev, self.participant, InvoiceStatus.DRAFT)
        resp = self._action(inv, "mark-paid")
        self.assertEqual(resp.status_code, 400)

    def test_cancel_draft(self):
        inv = make_invoice(self.zev, self.participant, InvoiceStatus.DRAFT)
        resp = self._action(inv, "cancel")
        self.assertEqual(resp.status_code, 200)
        inv.refresh_from_db()
        self.assertEqual(inv.status, InvoiceStatus.CANCELLED)

    def test_cancel_approved(self):
        inv = make_invoice(self.zev, self.participant, InvoiceStatus.APPROVED)
        resp = self._action(inv, "cancel")
        self.assertEqual(resp.status_code, 200)
        inv.refresh_from_db()
        self.assertEqual(inv.status, InvoiceStatus.CANCELLED)

    def test_cancel_sent(self):
        inv = make_invoice(self.zev, self.participant, InvoiceStatus.SENT)
        resp = self._action(inv, "cancel")
        self.assertEqual(resp.status_code, 200)
        inv.refresh_from_db()
        self.assertEqual(inv.status, InvoiceStatus.CANCELLED)

    def test_cancel_paid_fails(self):
        inv = make_invoice(self.zev, self.participant, InvoiceStatus.PAID)
        resp = self._action(inv, "cancel")
        self.assertEqual(resp.status_code, 400)

    def test_cancel_already_cancelled_fails(self):
        inv = make_invoice(self.zev, self.participant, InvoiceStatus.CANCELLED)
        resp = self._action(inv, "cancel")
        self.assertEqual(resp.status_code, 400)


class StaleInstanceConcurrencyTests(TestCase):
    """#572: a workflow guard must decide against the row's committed
    status, not whatever an already-loaded ``Invoice`` instance happened to
    hold — otherwise a second, stale-in-memory call can undo a terminal
    status another request already committed. Each test here loads the
    *same* row twice (``a`` and ``b``, standing in for two overlapping
    requests or a request racing a delayed email job), transitions it via
    one, and then calls the workflow function on the other — which still
    thinks the row is at whatever status it was loaded with.
    """

    def setUp(self):
        self.owner = make_user("stale_owner", UserRole.ZEV_OWNER)
        self.zev = make_zev(self.owner, "Stale ZEV")
        self.participant = make_participant(self.zev)

    def test_a_paid_invoice_survives_a_stale_cancel(self):
        """Issue #572 repro A: mark_invoice_paid(A) commits `paid`; a
        cancel_invoice(B) whose in-memory copy still says `sent` must not
        undo that."""
        row = make_invoice(self.zev, self.participant, InvoiceStatus.SENT)
        a = Invoice.objects.get(pk=row.pk)
        b = Invoice.objects.get(pk=row.pk)

        mark_invoice_paid(a)  # DB: sent -> paid

        with self.assertRaises(InvoiceWorkflowError):
            cancel_invoice(b)  # b's in-memory status is still "sent"

        row.refresh_from_db()
        self.assertEqual(row.status, InvoiceStatus.PAID)
        # The refused caller's own view is corrected to reality, not left stale.
        self.assertEqual(b.status, InvoiceStatus.PAID)

    def test_a_cancelled_invoice_survives_a_stale_email_delivery(self):
        """Issue #572 repro B: cancel_invoice(A) commits `cancelled`; an
        email job whose in-memory copy still says `approved` must not flip
        it back to `sent`."""
        row = make_invoice(self.zev, self.participant, InvoiceStatus.APPROVED)
        a = Invoice.objects.get(pk=row.pk)
        b = Invoice.objects.get(pk=row.pk)

        cancel_invoice(a)  # DB: approved -> cancelled

        sent_at = django_timezone.now()
        previous_status = record_email_delivery(b, sent_at)  # b's in-memory status is still "approved"

        row.refresh_from_db()
        self.assertEqual(row.status, InvoiceStatus.CANCELLED)
        # Reports the real prior status, not the stale "approved" b was loaded with.
        self.assertEqual(previous_status, InvoiceStatus.CANCELLED)
        # The email genuinely was delivered — that's still worth recording.
        self.assertEqual(row.sent_at, sent_at)
        self.assertEqual(b.status, InvoiceStatus.CANCELLED)

    def test_stale_approve_after_a_concurrent_cancel_is_refused(self):
        row = make_invoice(self.zev, self.participant, InvoiceStatus.DRAFT)
        a = Invoice.objects.get(pk=row.pk)
        b = Invoice.objects.get(pk=row.pk)

        cancel_invoice(a)  # DB: draft -> cancelled

        with self.assertRaises(InvoiceWorkflowError):
            approve_invoice(b)  # b's in-memory status is still "draft"

        row.refresh_from_db()
        self.assertEqual(row.status, InvoiceStatus.CANCELLED)

    def test_stale_mark_sent_after_a_concurrent_cancel_is_refused(self):
        row = make_invoice(self.zev, self.participant, InvoiceStatus.APPROVED)
        a = Invoice.objects.get(pk=row.pk)
        b = Invoice.objects.get(pk=row.pk)

        cancel_invoice(a)  # DB: approved -> cancelled

        with self.assertRaises(InvoiceWorkflowError):
            mark_invoice_sent(b)  # b's in-memory status is still "approved"

        row.refresh_from_db()
        self.assertEqual(row.status, InvoiceStatus.CANCELLED)
        self.assertIsNone(row.sent_at)

    def test_a_second_stale_cancel_reports_already_cancelled_not_the_original_status(self):
        row = make_invoice(self.zev, self.participant, InvoiceStatus.SENT)
        a = Invoice.objects.get(pk=row.pk)
        b = Invoice.objects.get(pk=row.pk)

        cancel_invoice(a)  # DB: sent -> cancelled

        with self.assertRaises(InvoiceWorkflowError) as ctx:
            cancel_invoice(b)  # b's in-memory status is still "sent"
        self.assertEqual(ctx.exception.user_message, "Invoice is already cancelled.")

    def test_email_delivery_after_a_concurrent_mark_sent_does_not_error(self):
        """Two email attempts for the same invoice (e.g. a retried task)
        overlapping mark-sent: the second delivery must not raise, and must
        report the row's real prior status rather than the stale one it was
        loaded with."""
        row = make_invoice(self.zev, self.participant, InvoiceStatus.APPROVED)
        a = Invoice.objects.get(pk=row.pk)
        b = Invoice.objects.get(pk=row.pk)

        mark_invoice_sent(a)  # DB: approved -> sent

        later_sent_at = django_timezone.now()
        previous_status = record_email_delivery(b, later_sent_at)  # b's in-memory status is still "approved"

        self.assertEqual(previous_status, InvoiceStatus.SENT)
        row.refresh_from_db()
        self.assertEqual(row.status, InvoiceStatus.SENT)
        self.assertEqual(row.sent_at, later_sent_at)


class InvoiceEngineGuardTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = make_user("guard_owner", UserRole.ZEV_OWNER)
        self.zev = make_zev(self.owner, "GuardZEV")
        self.participant = make_participant(self.zev)
        auth(self.client, self.owner)

    def _generate(self, participant_id):
        return self.client.post("/api/v1/invoices/invoices/generate/", {
            "participant_id": str(participant_id),
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
        })

    def test_regenerate_approved_invoice_returns_409(self):
        make_invoice(self.zev, self.participant, InvoiceStatus.APPROVED)
        resp = self._generate(self.participant.pk)
        self.assertEqual(resp.status_code, 409)

    def test_regenerate_paid_invoice_returns_409(self):
        make_invoice(self.zev, self.participant, InvoiceStatus.PAID)
        resp = self._generate(self.participant.pk)
        self.assertEqual(resp.status_code, 409)

    def test_regenerate_draft_invoice_succeeds(self):
        make_invoice(self.zev, self.participant, InvoiceStatus.DRAFT)
        resp = self._generate(self.participant.pk)
        # Engine replaces draft; no 409 expected (may be 201 or other non-conflict)
        self.assertNotEqual(resp.status_code, 409)

    def test_regenerate_cancelled_invoice_succeeds(self):
        make_invoice(self.zev, self.participant, InvoiceStatus.CANCELLED)
        resp = self._generate(self.participant.pk)
        self.assertNotEqual(resp.status_code, 409)

    def test_dynamic_price_gap_returns_actionable_structured_error(self):
        source = DynamicTariffSource.objects.create(
            label="Grid dynamic",
            url="https://api.example.ch/grid",
            api_version="v1_0_5",
            tariff_type="grid",
            tariff_name="vario",
        )
        tariff = Tariff.objects.create(
            zev=self.zev,
            name="Grid dynamic",
            category=TariffCategory.GRID_FEES,
            billing_mode=BillingMode.ENERGY,
            energy_type=EnergyType.GRID,
            valid_from="2026-01-01",
            dynamic_source=source,
        )
        missing_at = datetime(2026, 1, 5, 10, tzinfo=timezone.utc)

        with mock.patch(
            "invoices.views.generate_invoice",
            side_effect=DynamicPriceGapError(tariff=tariff, missing_at=missing_at),
        ):
            response = self._generate(self.participant.pk)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "dynamic_price_gap")
        self.assertEqual(response.data["source_id"], str(source.pk))
        self.assertEqual(response.data["missing_at"], missing_at.isoformat())


@pytest.mark.django_db(transaction=True)
def test_concurrent_cancel_and_mark_paid_serialize_on_the_row_lock():
    """#572: real database concurrency coverage, not just the sequential
    same-thread reproductions above. Two genuinely overlapping transactions
    — one holding the invoice's row lock (standing in for an in-flight
    ``cancel_invoice``), the other running the real ``mark_invoice_paid`` —
    must serialize rather than race: the second has to wait for the first to
    commit, then see its result and correctly refuse. Modelled on
    ``test_invoice_price_read_blocks_concurrent_maintenance_until_evidence_commits``
    in ``invoices/test_dynamic_evidence.py``, the one other real-concurrency
    test in this codebase.
    """
    if connection.vendor != "postgresql":
        pytest.skip("Requires PostgreSQL row locks and pg_blocking_pids")

    zev = factories.ZevFactory()
    participant = factories.ParticipantFactory(zev=zev)
    invoice = Invoice.objects.create(
        invoice_number="T-CONC-00001",
        zev=zev,
        participant=participant,
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        status=InvoiceStatus.SENT,
        total_chf=Decimal("42.00"),
    )

    holder_ready, release, blocked_connected = Event(), Event(), Event()
    blocked_pid = []
    result = {}

    def hold_the_lock():
        # Stands in for an in-flight cancel_invoice: takes the row lock and
        # holds it open past the point where a competing writer would try
        # to acquire it too, then commits the cancellation.
        try:
            with transaction.atomic():
                Invoice.objects.select_for_update().get(pk=invoice.pk)
                holder_ready.set()
                assert release.wait(10), "Test did not release the row lock"
                Invoice.objects.filter(pk=invoice.pk).update(status=InvoiceStatus.CANCELLED)
        finally:
            connections.close_all()

    def attempt_mark_paid():
        try:
            # Grabbed on this thread's own (as yet unused) connection before
            # the blocking call, so the pid is valid for the query that is
            # about to block — same trick as the evidence-locking test.
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                blocked_pid.append(cursor.fetchone()[0])
            blocked_connected.set()
            try:
                mark_invoice_paid(Invoice.objects.get(pk=invoice.pk))
                result["error"] = None
            except InvoiceWorkflowError as exc:
                result["error"] = exc.user_message
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        holder = pool.submit(hold_the_lock)
        assert holder_ready.wait(10)
        try:
            blocked = pool.submit(attempt_mark_paid)
            assert blocked_connected.wait(10)
            deadline = monotonic() + 5
            is_blocked = False
            while monotonic() < deadline:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT cardinality(pg_blocking_pids(%s))", [blocked_pid[0]])
                    is_blocked = cursor.fetchone()[0] > 0
                if is_blocked:
                    break
                sleep(0.01)
            assert is_blocked, "mark_invoice_paid did not wait for the cancelling transaction's row lock"
        finally:
            release.set()
        holder.result(timeout=10)
        blocked.result(timeout=10)

    # The lock serialized the two writers: mark_invoice_paid only ran its
    # guard after the cancellation committed, so it saw `cancelled` — not
    # the `sent` status the invoice had when this test set it up — and
    # correctly refused rather than racing it into `paid`.
    assert result["error"] == "Only sent invoices can be marked as paid."
    invoice.refresh_from_db()
    assert invoice.status == InvoiceStatus.CANCELLED
