"""Rounding of the amounts a participant pays (per-ZEV ``invoice_rounding``).

Switzerland has no coin below 5 Rappen, so a ZEV can round what it asks for to
the nearest 0.05 CHF. Only the payable figures are rounded: line items, the
subtotal and the VAT stay as calculated, and the difference is stored apart
(``Invoice.rounding_chf``, ``Invoice.due_rounding_chf``, ``Credit.rounding_chf``)
and printed as its own line. Rounding is therefore outside the VAT base.
"""

from decimal import ROUND_HALF_UP, Decimal

from zev.models import InvoiceRounding

FIVE_RAPPEN = Decimal("0.05")
_CENT = Decimal("0.01")


def rounding_step(zev) -> Decimal | None:
    """The step a ZEV rounds payable amounts to, or ``None`` for exact amounts."""
    if zev.invoice_rounding == InvoiceRounding.FIVE_RAPPEN:
        return FIVE_RAPPEN
    return None


def round_to_step(amount: Decimal, step: Decimal | None) -> Decimal:
    """``amount`` rounded half away from zero to a multiple of ``step``.

    Cent amounts never tie on 0.05 (0.025 is not a cent), so half-up is only
    there to make the mode explicit and symmetric for payouts."""
    if step is None:
        return amount.quantize(_CENT, rounding=ROUND_HALF_UP)
    return ((amount / step).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * step).quantize(_CENT)


def rounding_difference(amount: Decimal, step: Decimal | None) -> Decimal:
    """What has to be added to ``amount`` to reach the rounded figure."""
    if step is None:
        return Decimal("0.00")
    return round_to_step(amount, step) - amount
