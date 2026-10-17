"""Invoice numbering is per-ZEV, not global (issue #401).

``Zev.next_invoice_number()`` reads ``invoice_prefix``/``invoice_counter`` off
the ZEV row, so two communities each counting from 1 is the intended model. The
model used to carry a global ``unique=True`` on ``invoice_number``, which
contradicted that: every ZEV ships with the same ``INV`` default, so the second
one's billing run died on a database constraint.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Event
from time import monotonic, sleep

import pytest
from django.db import IntegrityError, connection, connections, transaction

from audit.models import AuditEvent
from invoices.engine import generate_invoices_for_zev
from invoices.models import Invoice
from testing.factories import OwnerFactory, ParticipantFactory, ZevFactory
from zev.models import Zev

pytestmark = pytest.mark.django_db

START, END = date(2026, 1, 1), date(2026, 1, 31)


def _zev_with_participants(owner, count, **kwargs):
    zev = ZevFactory(owner=owner, **kwargs)
    for _ in range(count):
        ParticipantFactory(zev=zev)
    return zev


class TestInvoiceNumberAllocation:
    def test_stale_instances_allocate_distinct_numbers(self):
        first = ZevFactory()
        stale = Zev.objects.get(pk=first.pk)

        assert first.next_invoice_number() == "INV-00001"
        assert stale.next_invoice_number() == "INV-00002"
        assert stale.invoice_counter == 3
        first.refresh_from_db()
        assert first.invoice_counter == 3

    def test_allocation_uses_the_persisted_prefix_and_counter(self):
        zev = ZevFactory()
        Zev.objects.filter(pk=zev.pk).update(invoice_prefix="NEW", invoice_counter=42)

        assert zev.next_invoice_number() == "NEW-00042"
        assert zev.invoice_prefix == "NEW"
        assert zev.invoice_counter == 43

    def test_rollback_returns_the_number_even_with_a_stale_instance(self):
        zev = ZevFactory()

        with transaction.atomic():
            assert zev.next_invoice_number() == "INV-00001"
            transaction.set_rollback(True)

        assert Zev.objects.get(pk=zev.pk).invoice_counter == 1
        assert zev.next_invoice_number() == "INV-00001"
        assert zev.invoice_counter == 2


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("rollback", [False, True], ids=["commit", "rollback"])
def test_concurrent_invoice_allocations_serialize(rollback):
    if connection.vendor != "postgresql":
        pytest.skip("Requires PostgreSQL row locks and pg_blocking_pids")

    zev = ZevFactory()
    ready, allocate = Event(), Event()
    contender_pid = []

    def competing_allocation():
        try:
            stale = Zev.objects.get(pk=zev.pk)
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '10s'")
                cursor.execute("SELECT pg_backend_pid()")
                contender_pid.append(cursor.fetchone()[0])
            ready.set()
            assert allocate.wait(10), "Competing allocation was not started"
            return stale.next_invoice_number()
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=1) as pool:
        contender = pool.submit(competing_allocation)
        assert ready.wait(10), "Competing connection was not ready"
        try:
            with transaction.atomic():
                assert zev.next_invoice_number() == "INV-00001"
                allocate.set()
                deadline = monotonic() + 5
                blocked = False
                while monotonic() < deadline:
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT cardinality(pg_blocking_pids(%s))", [contender_pid[0]])
                        blocked = cursor.fetchone()[0] > 0
                    if blocked:
                        break
                    sleep(0.01)
                assert blocked, "Competing allocation did not wait for the ZEV row lock"
                transaction.set_rollback(rollback)
        finally:
            allocate.set()
        assert contender.result(timeout=10) == ("INV-00001" if rollback else "INV-00002")

    zev.refresh_from_db()
    assert zev.invoice_counter == (2 if rollback else 3)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("allocator", ["next_invoice_number", "next_contract_number"])
def test_number_allocation_allows_foreign_key_inserts(allocator):
    if connection.vendor != "postgresql":
        pytest.skip("Requires PostgreSQL row locks")

    zev = ZevFactory()

    def insert_audit_event():
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '5s'")
            return AuditEvent.objects.create(
                zev_id=zev.pk, action_category="system", action_type="test.number_allocation",
                target_type="zev", summary="Number allocation lock regression",
            ).pk
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=1) as pool:
        with transaction.atomic():
            getattr(zev, allocator)()
            event_id = pool.submit(insert_audit_event).result(timeout=10)
            assert AuditEvent.objects.filter(pk=event_id, zev=zev).exists()


class TestNumberingIsScopedToTheZev:
    def test_two_zevs_on_the_default_prefix_both_bill(self):
        """The regression from #401: ZEV B used to fail on every participant."""
        owner = OwnerFactory()
        a = _zev_with_participants(owner, 2)
        b = _zev_with_participants(owner, 2)
        assert a.invoice_prefix == b.invoice_prefix == "INV"

        result_a = generate_invoices_for_zev(a, START, END)
        result_b = generate_invoices_for_zev(b, START, END)

        assert result_a.failures == []
        assert result_b.failures == []
        assert len(result_a.invoices) == 2
        assert len(result_b.invoices) == 2

    def test_both_zevs_count_from_one(self):
        """Each community's numbering is its own sequence, starting at 1."""
        owner = OwnerFactory()
        a = _zev_with_participants(owner, 2)
        b = _zev_with_participants(owner, 2)

        generate_invoices_for_zev(a, START, END)
        generate_invoices_for_zev(b, START, END)

        numbers_a = sorted(Invoice.objects.filter(zev=a).values_list("invoice_number", flat=True))
        numbers_b = sorted(Invoice.objects.filter(zev=b).values_list("invoice_number", flat=True))

        assert numbers_a == ["INV-00001", "INV-00002"]
        assert numbers_b == ["INV-00001", "INV-00002"]

    def test_distinct_prefixes_still_work(self):
        """Setting a prefix remains a valid way to tell communities apart."""
        owner = OwnerFactory()
        a = _zev_with_participants(owner, 1, invoice_prefix="AAA")
        b = _zev_with_participants(owner, 1, invoice_prefix="BBB")

        generate_invoices_for_zev(a, START, END)
        generate_invoices_for_zev(b, START, END)

        assert Invoice.objects.filter(zev=a).get().invoice_number == "AAA-00001"
        assert Invoice.objects.filter(zev=b).get().invoice_number == "BBB-00001"


class TestDuplicatesWithinOneZevAreStillRejected:
    """Narrowing the constraint must not weaken it inside a single ZEV —
    that is the property a ZEV owner's bookkeeping actually depends on."""

    def test_a_duplicate_number_in_the_same_zev_is_refused(self):
        owner = OwnerFactory()
        zev = _zev_with_participants(owner, 2)
        first, second = list(zev.participants.all())
        Invoice.objects.create(
            invoice_number="INV-00001", zev=zev, participant=first,
            period_start=START, period_end=END,
        )

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                Invoice.objects.create(
                    invoice_number="INV-00001", zev=zev, participant=second,
                    period_start=START, period_end=END,
                )

    def test_the_same_number_in_a_different_zev_is_allowed(self):
        owner = OwnerFactory()
        a = _zev_with_participants(owner, 1)
        b = _zev_with_participants(owner, 1)

        Invoice.objects.create(
            invoice_number="INV-00001", zev=a, participant=a.participants.get(),
            period_start=START, period_end=END,
        )
        Invoice.objects.create(
            invoice_number="INV-00001", zev=b, participant=b.participants.get(),
            period_start=START, period_end=END,
        )

        assert Invoice.objects.filter(invoice_number="INV-00001").count() == 2

    def test_the_constraint_is_enforced_by_the_database(self):
        """`bulk_create` bypasses `save()`, so this pins the DB constraint
        itself rather than any application-level guard."""
        owner = OwnerFactory()
        zev = _zev_with_participants(owner, 2)
        first, second = list(zev.participants.all())

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                Invoice.objects.bulk_create([
                    Invoice(invoice_number="INV-00009", zev=zev, participant=first,
                            period_start=START, period_end=END),
                    Invoice(invoice_number="INV-00009", zev=zev, participant=second,
                            period_start=START, period_end=END),
                ])
