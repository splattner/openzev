"""Shared tariff-pricing helpers used by more than one printed document.

Extracted from ``contract_pdf`` so a second document — the tariff overview —
does not have to invent a second answer to "what does a percentage-of-energy
tariff effectively cost right now?"

This is deliberately *not* what the billing engine uses. ``engine._price_energy``
resolves a grid price per reading timestamp, because it has real consumption to
price and a multi-band grid tariff genuinely charges different rates at
different times. A printed document with no consumption to resolve a timestamp
against needs a single static figure instead, and the two must not silently
drift into disagreeing about it — see
``docs/specs/2026-09-tariff-overview-pdf.md`` §6.1.
"""
from decimal import Decimal

from tariffs.models import PeriodType


def display_grid_base_chf_per_kwh(grid_tariffs) -> Decimal:
    """Sum of the display price of each ``grid_tariffs`` entry.

    Per tariff: its flat price if it has one, else its HT price, else its
    first period — the same fallback a reader would reach for if handed the
    tariff sheet and asked "what's the headline rate?". Multi-band grid
    tariffs are approximated this way on purpose; pair with
    :func:`grid_base_is_multiband` to decide whether that approximation needs
    flagging to the reader.
    """
    total = Decimal("0")
    for tariff in grid_tariffs:
        periods = list(tariff.periods.all())
        flat = next((p for p in periods if p.period_type == PeriodType.FLAT), None)
        if flat:
            total += Decimal(str(flat.price_chf_per_kwh))
            continue
        high = next((p for p in periods if p.period_type == PeriodType.HIGH), None)
        if high:
            total += Decimal(str(high.price_chf_per_kwh))
        elif periods:
            total += Decimal(str(periods[0].price_chf_per_kwh))
    return total


def grid_base_is_multiband(grid_tariffs) -> bool:
    """True when any tariff contributing to the base has more than one band.

    ``len(list(...))`` rather than ``.count()``: callers already hold
    ``periods`` prefetched, and ``.count()`` would issue a fresh query instead
    of using that cache.
    """
    return any(len(list(tariff.periods.all())) > 1 for tariff in grid_tariffs)
