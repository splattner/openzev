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

A dynamic tariff (``Tariff.dynamic_source``) has no periods to fall back to at
all — its price lives in a fetched time series, not on the tariff. It prints
the average of whatever has been fetched instead, which is exactly as much of
an approximation as the multi-band fallback below is, and is flagged to the
reader the same way (``footnote_dynamic_average``, mirroring
``footnote_multiband_base``).
"""
from decimal import Decimal

from django.db.models import Avg

from tariffs.dynamic.models import DynamicPricePoint
from tariffs.models import PeriodType


def dynamic_average_chf_per_kwh(tariff) -> Decimal | None:
    """The mean fetched price for a dynamic tariff's series.

    None when nothing has been fetched yet — a source just configured, or one
    still waiting on its first scheduled run — so the caller can decide how to
    print "no price yet" rather than silently printing zero.
    """
    result = DynamicPricePoint.objects.filter(
        source_id=tariff.dynamic_source_id
    ).aggregate(avg=Avg("price_chf_per_kwh"))["avg"]
    return Decimal(str(result)) if result is not None else None


def display_grid_base_chf_per_kwh(grid_tariffs) -> Decimal:
    """Sum of the display price of each ``grid_tariffs`` entry.

    Per static tariff: its flat price if it has one, else its HT price, else
    its first period — the same fallback a reader would reach for if handed
    the tariff sheet and asked "what's the headline rate?". Multi-band grid
    tariffs are approximated this way on purpose; pair with
    :func:`grid_base_is_multiband` to decide whether that approximation needs
    flagging to the reader.

    Per dynamic tariff: the average of its fetched series
    (:func:`dynamic_average_chf_per_kwh`), or nothing if it has none yet — a
    document is printed at some moment, and an untouched sum understates the
    base rather than guessing at a number nobody fetched.
    """
    total = Decimal("0")
    for tariff in grid_tariffs:
        if tariff.dynamic_source_id:
            average = dynamic_average_chf_per_kwh(tariff)
            if average is not None:
                total += average
            continue
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
    """True when any *static* tariff contributing to the base has more than
    one band. A dynamic tariff is never counted here — it needs its own
    footnote (:func:`grid_base_is_dynamic`), because "the price depends on
    the time band" and "the price is a fluctuating fetched series" are
    different things to tell the reader, worded differently in
    ``footnote_multiband_base`` vs ``footnote_dynamic_average``.

    ``len(list(...))`` rather than ``.count()``: callers already hold
    ``periods`` prefetched, and ``.count()`` would issue a fresh query instead
    of using that cache.
    """
    return any(
        not tariff.dynamic_source_id and len(list(tariff.periods.all())) > 1
        for tariff in grid_tariffs
    )


def grid_base_is_dynamic(grid_tariffs) -> bool:
    """True when any tariff contributing to the base is dynamic.

    A fluctuating fetched price printed as one static number is an
    approximation by construction, same as the multi-band case, but the
    reader needs a different explanation for why — see
    :func:`grid_base_is_multiband`.
    """
    return any(tariff.dynamic_source_id for tariff in grid_tariffs)
