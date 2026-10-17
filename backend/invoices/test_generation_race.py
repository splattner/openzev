"""PostgreSQL regression tests for concurrent invoice generation."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Event
from time import monotonic, sleep
from unittest.mock import patch

import pytest
from django.db import connection, connections, transaction

from invoices import engine
from invoices.models import Invoice
from invoices.workflow import approve_invoice, cancel_invoice
from testing import factories
from zev.models import Participant, Zev

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(connection.vendor != "postgresql", reason="Requires PostgreSQL row locks"),
]

START, END = date(2026, 1, 1), date(2026, 1, 31)


def _generate(participant_id, start=START, end=END):
    return engine.generate_invoice(Participant.objects.get(pk=participant_id), start, end)


def _blocked_call(pool, call, expected_query):
    ready = Event()
    contender_pid = []
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_backend_pid()")
        holder_pid = cursor.fetchone()[0]

    def run():
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '10s'")
                cursor.execute("SELECT pg_backend_pid()")
                contender_pid.append(cursor.fetchone()[0])
            ready.set()
            return call()
        finally:
            connections.close_all()

    future = pool.submit(run)
    assert ready.wait(10), "Competing connection was not ready"
    deadline = monotonic() + 5
    while monotonic() < deadline:
        if future.done():
            future.result()
            pytest.fail("Competing call completed without waiting")
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_blocking_pids(%s)",
                [contender_pid[0]],
            )
            if holder_pid in cursor.fetchone()[0]:
                # Refresh activity after the wait, avoiding transaction-local stats caching.
                cursor.execute("SELECT pg_stat_clear_snapshot()")
                cursor.execute("SELECT query FROM pg_stat_activity WHERE pid = %s", [contender_pid[0]])
                query = cursor.fetchone()[0]
                assert query.startswith("SELECT") and "FOR " in query and expected_query in query, (
                    f"Expected a lock wait on {expected_query}, got: {query}"
                )
                return future
        sleep(0.01)
    pytest.fail("Competing call did not wait for the holding transaction")


@pytest.mark.parametrize(
    ("second_start", "second_end"),
    [
        pytest.param(START, END, id="identical"),
        pytest.param(date(2026, 1, 15), date(2026, 2, 15), id="partial-overlap"),
    ],
)
def test_overlapping_draft_is_replaced_after_the_participant_lock(second_start, second_end):
    participant = factories.ParticipantFactory()
    with ThreadPoolExecutor(max_workers=1) as pool:
        with transaction.atomic():
            first = _generate(participant.pk)
            pending = _blocked_call(
                pool, lambda: _generate(participant.pk, second_start, second_end),
                'FROM "zev_participant"',
            )
        second = pending.result(timeout=10)

    actual_ids = set(Invoice.objects.filter(participant=participant).values_list("pk", flat=True))
    assert actual_ids == {second.pk}
    assert second.pk != first.pk
    assert (second.period_start, second.period_end) == (second_start, second_end)


@pytest.mark.parametrize("bulk", [False, True], ids=["single", "bulk"])
def test_approved_overlap_is_refused_after_commit(bulk):
    participant = factories.ParticipantFactory()
    call = (
        (lambda: engine.generate_invoices_for_zev(participant.zev, START, END))
        if bulk else (lambda: _generate(participant.pk))
    )
    with ThreadPoolExecutor(max_workers=1) as pool:
        with transaction.atomic():
            first = _generate(participant.pk)
            approve_invoice(first)
            pending = _blocked_call(pool, call, 'FROM "zev_participant"')
        if bulk:
            outcome = pending.result(timeout=10)
            assert outcome.invoices == []
            assert len(outcome.failures) == 1
            assert outcome.failures[0]["participant_id"] == str(participant.pk)
            assert "cannot be regenerated" in outcome.failures[0]["error"]
        else:
            with pytest.raises(ValueError, match="cannot be regenerated"):
                pending.result(timeout=10)

    assert Invoice.objects.filter(participant=participant).get().pk == first.pk


def test_issued_cancellation_is_retained_after_commit():
    participant = factories.ParticipantFactory()
    with ThreadPoolExecutor(max_workers=1) as pool:
        with transaction.atomic():
            first = _generate(participant.pk)
            approve_invoice(first)
            cancel_invoice(first)
            pending = _blocked_call(pool, lambda: _generate(participant.pk), 'FROM "zev_participant"')
        second = pending.result(timeout=10)

    first.refresh_from_db()
    assert first.approved_at is not None
    actual_ids = set(Invoice.objects.filter(participant=participant).values_list("pk", flat=True))
    assert actual_ids == {first.pk, second.pk}


def test_adjacent_periods_are_retained():
    participant = factories.ParticipantFactory()
    with ThreadPoolExecutor(max_workers=1) as pool:
        with transaction.atomic():
            first = _generate(participant.pk)
            approve_invoice(first)
            pending = _blocked_call(
                pool, lambda: _generate(participant.pk, date(2026, 2, 1), date(2026, 2, 28)),
                'FROM "zev_participant"',
            )
        second = pending.result(timeout=10)

    actual_ids = set(Invoice.objects.filter(participant=participant).values_list("pk", flat=True))
    assert actual_ids == {first.pk, second.pk}


def test_rollback_releases_the_lock_and_reuses_the_invoice_number():
    participant = factories.ParticipantFactory()
    initial_counter = participant.zev.invoice_counter
    with ThreadPoolExecutor(max_workers=1) as pool:
        with transaction.atomic():
            first = _generate(participant.pk)
            pending = _blocked_call(pool, lambda: _generate(participant.pk), 'FROM "zev_participant"')
            transaction.set_rollback(True)
        second = pending.result(timeout=10)

    assert second.invoice_number == first.invoice_number
    assert Invoice.objects.filter(participant=participant).get().pk == second.pk
    participant.zev.refresh_from_db()
    assert participant.zev.invoice_counter == initial_counter + 1


def test_different_participants_sharing_a_party_can_generate_concurrently():
    first = factories.ParticipantFactory()
    second = factories.ParticipantFactory(zev=first.zev, party=first.party)
    overlaps_checked, release = Event(), Event()
    discard = engine._discard_replaceable_invoices

    def pause_first(participant, *args):
        discard(participant, *args)
        if participant.pk == first.pk:
            overlaps_checked.set()
            assert release.wait(10), "First generation was not released"

    def generate_first():
        try:
            return _generate(first.pk)
        finally:
            connections.close_all()

    with patch.object(engine, "_discard_replaceable_invoices", side_effect=pause_first):
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(generate_first)
            try:
                assert overlaps_checked.wait(10), "First generation did not check overlaps"
                with transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute("SET LOCAL lock_timeout = '5s'")
                    second_invoice = _generate(second.pk)
            finally:
                release.set()
            first_invoice = pending.result(timeout=10)

    actual_ids = set(Invoice.objects.values_list("pk", flat=True))
    assert actual_ids == {first_invoice.pk, second_invoice.pk}


def test_generation_waits_for_approval_before_checking_or_deleting_overlaps():
    participant = factories.ParticipantFactory()
    first = _generate(participant.pk)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with transaction.atomic():
            approve_invoice(first)
            pending = _blocked_call(pool, lambda: _generate(participant.pk), 'FROM "invoices_invoice"')
        with pytest.raises(ValueError, match="cannot be regenerated"):
            pending.result(timeout=10)

    assert Invoice.objects.filter(participant=participant).get().pk == first.pk
    first.refresh_from_db()
    assert first.approved_at is not None


def test_generation_waits_for_restore_before_locking_the_participant():
    participant = factories.ParticipantFactory()
    original_row = Participant.objects.values().get(pk=participant.pk)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with transaction.atomic():
            Zev.objects.select_for_update().get(pk=participant.zev_id)
            pending = _blocked_call(pool, lambda: _generate(participant.pk), "FOR KEY SHARE")
            # Restore replaces participants while holding the exclusive ZEV lock.
            Participant.objects.filter(pk=participant.pk).delete()
            Participant.objects.create(**original_row)
        invoice = pending.result(timeout=10)

    assert Invoice.objects.filter(participant=participant).get().pk == invoice.pk


def test_generation_finishes_before_a_waiting_restore():
    participant = factories.ParticipantFactory()
    gather = engine._gather_period_readings
    pending = []

    def restore_lock():
        with transaction.atomic():
            return Zev.objects.select_for_update().only("pk").get(pk=participant.zev_id).pk

    with ThreadPoolExecutor(max_workers=1) as pool:
        def gather_while_restore_waits(*args, **kwargs):
            pending.append(_blocked_call(pool, restore_lock, 'FROM "zev_zev"'))
            return gather(*args, **kwargs)

        with patch.object(engine, "_gather_period_readings", side_effect=gather_while_restore_waits):
            invoice = _generate(participant.pk)
        assert pending[0].result(timeout=10) == participant.zev_id

    assert Invoice.objects.get(pk=invoice.pk).participant_id == participant.pk
