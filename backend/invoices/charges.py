"""One-off charges (#924): who bears a charge, what each share is, what is locked.

Kept apart from ``engine`` so the charge API can answer "who pays what" with
exactly the code the invoice engine bills with; the engine imports this module,
never the other way round (the lock check imports the engine lazily).
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from tariffs.models import SplitKey
from zev.models import Participant

from .models import Charge, ChargeAllocation, ChargeVatTreatment, Invoice, InvoiceStatus

# After every tariff line: CATEGORY_SORT_ORDER + energy rank + mode rank tops out
# below 500.
CHARGE_SORT_ORDER = 950

CENT = Decimal("0.01")


@dataclass(frozen=True)
class ChargeLine:
    """One participant's share of one charge, ready to become an invoice line."""

    charge: Charge
    total_chf: Decimal
    shared: bool  # more than one participant bears the charge


def bearers_among(participants, day: date, allocation: str, selected_ids=()) -> list[Participant]:
    """The members among ``participants`` who bear a charge dated ``day``.

    Membership is read on the charge date alone, never on an invoice period, so
    a single invoice and a batch run see the same bearers and the same shares.
    """
    chosen = set(selected_ids)
    return sorted(
        (
            p for p in participants
            if p.valid_from <= day
            and (p.valid_to is None or p.valid_to >= day)
            and (allocation == ChargeAllocation.ALL_PARTICIPANTS or p.pk in chosen)
        ),
        key=lambda p: p.pk,
    )


def bearers_for(zev, day: date, allocation: str, selected=()) -> list[Participant]:
    return bearers_among(zev.participants.all(), day, allocation, [p.pk for p in selected])


def charge_bearers(charge: Charge) -> list[Participant]:
    return bearers_for(charge.zev, charge.charge_date, charge.allocation, charge.participants.all())


def split_charge(amount: Decimal, split_key: str, bearers: list[Participant]) -> dict[UUID, Decimal]:
    """Each bearer's share, rounded half-up to the centime on its own.

    Like the shared fees, a share does not make up for the others' rounding, so
    CHF 10.00 over three people recovers CHF 9.99. A share that rounds to zero
    (a zero-weight member, a tiny amount) gets no entry, and nobody is charged
    when there is nobody to divide by.
    """
    if not bearers:
        return {}
    if len(bearers) == 1 or split_key != SplitKey.WEIGHT:
        raw = {p.pk: amount / len(bearers) for p in bearers}
    else:
        weight_sum = sum((p.allocation_weight for p in bearers), Decimal("0"))
        if not weight_sum:
            return {}
        raw = {p.pk: amount * p.allocation_weight / weight_sum for p in bearers}
    shares = {pk: value.quantize(CENT, rounding=ROUND_HALF_UP) for pk, value in raw.items()}
    return {pk: share for pk, share in shares.items() if share}


def charge_lines_by_participant(zev, period_start: date, period_end: date) -> dict[UUID, list[ChargeLine]]:
    """Every charge dated in the period, as the lines each participant is billed.

    Built once per generation run: the batch path reuses it for every invoice.
    """
    charges = list(
        Charge.objects.filter(zev=zev, charge_date__gte=period_start, charge_date__lte=period_end)
        .prefetch_related("participants")
        .order_by("charge_date", "created_at", "id")
    )
    if not charges:
        return {}
    participants = list(zev.participants.all())
    lines: dict[UUID, list[ChargeLine]] = {}
    for charge in charges:
        bearers = bearers_among(
            participants, charge.charge_date, charge.allocation, [p.pk for p in charge.participants.all()],
        )
        shares = split_charge(charge.amount_chf, charge.split_key, bearers)
        for participant_id, share in shares.items():
            lines.setdefault(participant_id, []).append(
                ChargeLine(charge=charge, total_chf=share, shared=len(bearers) > 1)
            )
    return lines


def pass_through_total(lines: list[ChargeLine]) -> Decimal:
    """The part of the lines that stays out of a registered ZEV's VAT base."""
    return sum(
        (line.total_chf for line in lines if line.charge.vat_treatment == ChargeVatTreatment.PASS_THROUGH),
        Decimal("0"),
    )


def locked_invoice_for(day: date, bearers: list[Participant]):
    """An issued invoice that already covers ``day`` for one of the bearers.

    Same rule as invoice regeneration (``engine.locked_overlapping_invoices``):
    past draft and not cancelled. A charge such an invoice cannot pick up must
    not be added or changed, and one it carries must not change under it.
    """
    from .engine import locked_overlapping_invoices

    for participant in bearers:
        invoice = locked_overlapping_invoices(participant, day, day).first()
        if invoice is not None:
            return invoice
    return None


def charge_lock(charge: Charge):
    return locked_invoice_for(charge.charge_date, charge_bearers(charge))


def locked_charge_ids(charges) -> set[UUID]:
    """Which of ``charges`` are locked, in two queries for the whole list.

    The rule is ``charge_lock``'s: a bearer has an invoice past draft that
    covers the charge date. Cancelled invoices do not count, as in
    ``engine.locked_overlapping_invoices``.
    """
    charges = list(charges)
    if not charges:
        return set()
    zev_ids = {charge.zev_id for charge in charges}
    participants_by_zev: dict[UUID, list[Participant]] = {}
    for participant in Participant.objects.filter(zev_id__in=zev_ids):
        participants_by_zev.setdefault(participant.zev_id, []).append(participant)
    issued = list(
        Invoice.objects.filter(
            zev_id__in=zev_ids,
            period_start__lte=max(charge.charge_date for charge in charges),
            period_end__gte=min(charge.charge_date for charge in charges),
        )
        .exclude(status__in=[InvoiceStatus.DRAFT, InvoiceStatus.CANCELLED])
        .values_list("participant_id", "period_start", "period_end")
    )
    locked = set()
    for charge in charges:
        bearers = bearers_among(
            participants_by_zev.get(charge.zev_id, []), charge.charge_date, charge.allocation,
            [p.pk for p in charge.participants.all()],
        )
        bearer_ids = {p.pk for p in bearers}
        if any(
            participant_id in bearer_ids and start <= charge.charge_date <= end
            for participant_id, start, end in issued
        ):
            locked.add(charge.pk)
    return locked
