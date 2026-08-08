"""Shared helpers for invoice tests.

These preserve the object shapes used by the legacy ``tests.py`` module while
newer tests gradually move to factories in ``testing.factories``.
"""

from datetime import date
from decimal import Decimal

from invoices.models import Invoice, InvoiceStatus
from testing.helpers import make_user as make_user
from zev.models import Participant, Zev


_counter = 0


def make_zev(owner, name="Test ZEV"):
    return Zev.objects.create(name=name, owner=owner, zev_type="vzev", invoice_prefix="T")


def make_participant(zev, user=None, first="Jane", last="Doe"):
    return Participant.objects.create(
        zev=zev,
        user=user,
        first_name=first,
        last_name=last,
        email=f"{first.lower()}@example.com",
        valid_from=date(2026, 1, 1),
    )


def make_invoice(zev, participant, inv_status=InvoiceStatus.DRAFT):
    global _counter
    _counter += 1
    return Invoice.objects.create(
        invoice_number=f"T-{_counter:05d}",
        zev=zev,
        participant=participant,
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        status=inv_status,
        total_chf=Decimal("42.00"),
    )
