"""Shared tariff validity, unit-price and VAT rules, as the invoice engine bills them.

Band choice at an instant is ``tariffs.periods.resolve_band``.
"""
from __future__ import annotations

import bisect
from datetime import date, datetime
from decimal import Decimal
from typing import Iterable
from uuid import UUID

from accounts.models import VatRate
from tariffs.dynamic.models import DynamicPricePoint
from tariffs.models import EnergyType, Tariff, TariffCategory, TariffPeriod
from tariffs.periods import resolve_band

_ONE = Decimal("1")
_UNRESOLVED = object()  # price_at's band was not passed: None means "resolved, no band"


# ─── Validity ─────────────────────────────────────────────────────────────────


def is_active(item, day: date) -> bool:
    """Whether a ``valid_from``/``valid_to`` row (a tariff, a VAT rate) is in
    force on ``day``. Both ends are inclusive; ``valid_to = None`` is open-ended."""
    return item.valid_from <= day and (item.valid_to is None or item.valid_to >= day)


def is_active_during(item, start: date, end: date) -> bool:
    """Whether the row is in force on at least one day of ``start``..``end``."""
    return item.valid_from <= end and (item.valid_to is None or item.valid_to >= start)


# ─── VAT ──────────────────────────────────────────────────────────────────────


def invoice_vat_rate(period_end: date) -> Decimal:
    """The VAT rate an invoice is billed at, 0 when no rate is in force."""
    # One rate per invoice: the one on period_end, even across a rate change (ADR 0016, billing spec §4.8).
    rate = VatRate.active_for_day(period_end)
    return Decimal(rate.rate) if rate else Decimal("0")


def daily_vat_rate(rates: Iterable[VatRate], day: date) -> Decimal:
    """The VAT rate in force on ``day`` among already-loaded ``rates``, 0 when none is."""
    # A day-by-day view steps on the day the rate changes (tariff progression spec §5.5).
    for rate in rates:
        if is_active(rate, day):
            return Decimal(rate.rate)
    return Decimal("0")


# Categories a non-registered ZEV pays non-recoverable VAT on: the grid
# operator bills Netznutzung, SDL, the Netzzuschlag, the cantonal/communal
# levies and the metering charge with VAT, and grid energy is bought from a
# supplier with VAT. The ZEV's own local (solar) energy and the feed-in
# credit it pays participants carry no input VAT.
_VAT_BEARING_CATEGORIES = frozenset({
    TariffCategory.GRID_FEES,
    TariffCategory.LEVIES,
    TariffCategory.METERING,
})


def bears_input_vat(tariff: Tariff) -> bool:
    """Whether this tariff's cost reaches an unregistered ZEV carrying VAT (ADR 0016)."""
    if tariff.category in _VAT_BEARING_CATEGORIES:
        return True
    if tariff.category == TariffCategory.ENERGY:
        return tariff.energy_type == EnergyType.GRID
    return False


def with_input_vat(tariff: Tariff, net: Decimal, rate: Decimal) -> Decimal:
    """``net`` with ``rate`` folded in when the tariff bears input VAT, else ``net``."""
    return net * (_ONE + rate) if bears_input_vat(tariff) else net


# ─── Percentage-of-energy base ────────────────────────────────────────────────


def percentage_base(tariff: Tariff, net_base: Decimal, gross_base: Decimal) -> Decimal:
    """The grid base a percentage-of-energy tariff takes its share of.

    ``gross_base`` is the grid prices with input VAT folded in (equal to
    ``net_base`` outside ``VatMode.INCLUSIVE``). A percentage tariff that bears
    input VAT itself is grossed afterwards, so it takes the net base (grossing
    both would apply the VAT twice); any other takes the gross base.
    """
    return net_base if bears_input_vat(tariff) else gross_base


# ─── Per-kWh price ────────────────────────────────────────────────────────────


class DynamicSeries:
    """A dynamic tariff source's stored prices, sorted and ready to bisect."""

    def __init__(self, points: list[tuple[datetime, datetime, Decimal]]):
        self.points = points  # (valid_from, valid_to, price), sorted by valid_from
        self._starts = [valid_from for valid_from, _valid_to, _price in points]

    @classmethod
    def load(
        cls,
        source_id: UUID,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> "DynamicSeries":
        """The source's points, or only those overlapping ``start``..``end``."""
        rows = DynamicPricePoint.objects.filter(source_id=source_id)
        if start is not None and end is not None:
            rows = rows.filter(valid_from__lt=end, valid_to__gt=start)
        elif start is not None or end is not None:
            raise ValueError("start and end must be provided together.")
        rows = rows.order_by("valid_from").values_list(
            "valid_from", "valid_to", "price_chf_per_kwh"
        )
        return cls(list(rows))

    def price_at(self, ts: datetime) -> Decimal | None:
        """The stored price whose interval covers ``ts``, or None for a gap."""
        index = bisect.bisect_right(self._starts, ts) - 1
        if index < 0:
            return None
        valid_from, valid_to, price = self.points[index]
        if valid_from <= ts < valid_to:
            return price
        return None


def floored(tariff: Tariff, price: Decimal) -> Decimal:
    """A fetched price raised to the tariff's ``minimum_price_chf_per_kwh``, if any."""
    if tariff.minimum_price_chf_per_kwh is not None:
        return max(price, tariff.minimum_price_chf_per_kwh)
    return price


def price_at(
    tariff: Tariff,
    ts: datetime,
    *,
    series: DynamicSeries | None = None,
    band=_UNRESOLVED,
) -> tuple[Decimal | None, TariffPeriod | None]:
    """The per-kWh price of ``tariff`` at ``ts``, and the band that set it.

    A dynamic tariff is priced from ``series`` with its floor and has no band;
    the price is ``None`` for a gap, which is missing information. A static
    tariff is priced by its band at ``ts`` (``band``, if the caller resolved
    it already) and bills ``Decimal("0")`` without one.
    """
    if tariff.dynamic_source_id:
        if series is None:
            raise ValueError("A dynamic tariff is priced from its series.")
        price = series.price_at(ts)
        return (None if price is None else floored(tariff, price)), None
    if band is _UNRESOLVED:
        band = resolve_band(tariff.periods.all(), ts)
    return (band.price_chf_per_kwh if band is not None else Decimal("0")), band
