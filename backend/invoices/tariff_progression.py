"""Combined per-kWh tariff progression (SPEC-2026-tariff-progression).

For one ZEV and one energy type this adds up every per-kWh tariff that applies,
over time, the way the invoice engine would price a kWh:

* band resolution is ``tariffs.periods.resolve_band``, the one rule shared with
  the engine;
* a percentage-of-energy tariff is a share of the grid tariffs' bands *at the
  same time* (``invoices.engine._price_energy``);
* VAT follows ``Zev.vat_mode`` and the engine's input-VAT classifier.

The summed price depends on when the energy is used, so the year is cut into
cells (month, weekday, part of the day). Cells where the same combination of
bands applies form a *slot*, and each distinct slot is a line in the chart.
Fixed fees are returned separately and never added to the per-kWh total.

A dynamic tariff has no bands, only a stored price per interval. It is included
as a duration-weighted mean over each slot within each interval (a calendar
month at most), which is what the engine's per-reading prices average to; a
percentage tariff on a dynamic grid base takes its share of that mean the same
way. Months with missing prices are reported, never silently averaged away.

Nothing here touches the database beyond the tariffs, VAT rates and fetched
prices of the request, each read once.
"""
from __future__ import annotations

import json
from bisect import bisect_right
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import NamedTuple

from django.utils import timezone

from accounts.models import VatRate
from allocation.validity import period_window, wall_clock
from tariffs.dynamic.models import DynamicPricePoint
from tariffs.models import BillingMode, EnergyType, TariffCategory
from tariffs.periods import resolve_band
from tariffs.series import series_key, sort_versions
from zev.models import VatMode

from .engine import _tariff_bears_input_vat

#: The most slots one interval may produce: 12 months times two bands, the most a
#: single seasonal HT/NT tariff gives. Beyond it the chart would be unreadable.
MAX_SLOTS_PER_INTERVAL = 24

#: A fetched series that covers less of a slot's hours than this is reported as
#: partial. Not 1: a day with a clock change is an hour longer or shorter than the
#: nominal 24, so full coverage can read a little under or over.
DYNAMIC_COVERAGE_COMPLETE = Decimal("0.99")

_PRICE_STEP = Decimal("0.00001")
_FEE_STEP = Decimal("0.01")
_ONE = Decimal("1")
_HUNDRED = Decimal("100")

#: A non-leap year in which every month holds every weekday at least four times,
#: so each (month, weekday) pair has a real date to resolve bands on.
_REFERENCE_YEAR = 2025

_ENERGY_MODES = frozenset({BillingMode.ENERGY, BillingMode.PERCENTAGE_OF_ENERGY})

#: Fixed-fee billing modes: (unit, scope). ``community`` fees are what the whole
#: community pays, divided between participants by ``split_key``.
_FEE_MODES = {
    BillingMode.MONTHLY_FEE: ("month", "participant"),
    BillingMode.YEARLY_FEE: ("year", "participant"),
    BillingMode.PER_METERING_POINT_MONTHLY_FEE: ("month", "metering_point"),
    BillingMode.PER_METERING_POINT_YEARLY_FEE: ("year", "metering_point"),
    BillingMode.SHARED_MONTHLY_FEE: ("month", "community"),
    BillingMode.SHARED_YEARLY_FEE: ("year", "community"),
}

_CATEGORY_ORDER = [category for category in TariffCategory.values if category != TariffCategory.OTHER]
_ALL_MONTHS = tuple(range(1, 13))
_ALL_WEEKDAYS = tuple(range(7))
_ALL_DAY = ({"from": "00:00", "to": "24:00"},)


class TooManyBands(Exception):
    """An interval resolves to more slots than a chart can show."""


def _d(value) -> Decimal:
    return Decimal("0") if value is None else Decimal(str(value))


def _quantised(value: Decimal, step: Decimal = _PRICE_STEP) -> Decimal:
    return value.quantize(step, rounding=ROUND_HALF_UP)


def _text(value: Decimal | None, step: Decimal = _PRICE_STEP) -> str | None:
    return None if value is None else str(_quantised(value, step))


def _active_on(item, day: date) -> bool:
    return item.valid_from <= day and (item.valid_to is None or item.valid_to >= day)


def _clock(value: time) -> str:
    return f"{value.hour:02d}:{value.minute:02d}"


def _reference_dates() -> dict[tuple[int, int], date]:
    dates: dict[tuple[int, int], date] = {}
    day = date(_REFERENCE_YEAR, 1, 1)
    while day.year == _REFERENCE_YEAR:
        dates.setdefault((day.month, day.weekday()), day)
        day += timedelta(days=1)
    return dates


_REFERENCE_DATES = _reference_dates()


class _Cells:
    """The year as (month, weekday, part-of-day) cells, and the bands in them.

    Parts of the day are cut at every window edge of every band in the request,
    so within one part no band can change. A tariff's band in a cell is resolved
    once for the whole request.
    """

    def __init__(self, tariffs, periods_of):
        edges = {time(0, 0)}
        for tariff in tariffs:
            for period in periods_of(tariff):
                for edge in (period.time_from, period.time_to):
                    if edge is not None:
                        edges.add(edge.replace(second=0, microsecond=0))
        self.starts = sorted(edges)
        self.cells = [
            (month, weekday, part)
            for month in _ALL_MONTHS
            for weekday in _ALL_WEEKDAYS
            for part in range(len(self.starts))
        ]
        self._periods_of = periods_of
        self._memo: dict[tuple, object] = {}

    def index(self, month: int, weekday: int, part: int) -> int:
        """Position of a cell in ``cells`` (months outermost, parts innermost)."""
        return ((month - 1) * 7 + weekday) * len(self.starts) + part

    def part_of(self, clock: time) -> int:
        return bisect_right(self.starts, clock) - 1

    def part_seconds(self) -> list[int]:
        """How long each part of the day lasts, in nominal seconds."""
        edges = [start.hour * 3600 + start.minute * 60 for start in self.starts] + [24 * 3600]
        return [edges[i + 1] - edges[i] for i in range(len(self.starts))]

    def band(self, tariff, index: int):
        key = (tariff.pk, index)
        try:
            return self._memo[key]
        except KeyError:
            month, weekday, part = self.cells[index]
            # A naive datetime is read as the Swiss wall clock by ``resolve_band``.
            moment = datetime.combine(_REFERENCE_DATES[month, weekday], self.starts[part])
            band = self._memo[key] = resolve_band(self._periods_of(tariff), moment)
            return band

    def _windows(self, parts: list[int]) -> tuple:
        runs: list[list[int]] = []
        for part in parts:
            if runs and runs[-1][1] == part:
                runs[-1][1] = part + 1
            else:
                runs.append([part, part + 1])
        last = len(self.starts)
        windows = [
            (_clock(self.starts[first]), _clock(self.starts[end]) if end < last else "24:00")
            for first, end in runs
        ]
        # A band that runs past midnight is two cells of the same weekday set:
        # report it the way the model stores it, as one window with from > to.
        if len(windows) > 1 and windows[0][0] == "00:00" and windows[-1][1] == "24:00":
            windows = [(windows[-1][0], windows[0][1]), *windows[1:-1]]
        return tuple(windows)

    def rules(self, indices: list[int]) -> list[dict]:
        """Fold a slot's cells into months / weekdays / windows rules."""
        parts: dict[tuple[int, int], list[int]] = defaultdict(list)
        for index in indices:
            month, weekday, part = self.cells[index]
            parts[month, weekday].append(part)

        by_month: dict[int, dict[tuple, list[int]]] = defaultdict(lambda: defaultdict(list))
        for (month, weekday), found in parts.items():
            by_month[month][self._windows(sorted(found))].append(weekday)

        months_by_shape: dict[tuple, list[int]] = defaultdict(list)
        for month, groups in by_month.items():
            shape = tuple(sorted((tuple(sorted(days)), windows) for windows, days in groups.items()))
            months_by_shape[shape].append(month)

        rules = [
            {
                "months": sorted(months),
                "weekdays": list(days),
                "windows": [{"from": start, "to": end} for start, end in windows],
            }
            for shape, months in months_by_shape.items()
            for days, windows in shape
        ]
        rules.sort(key=lambda rule: (rule["windows"][0]["from"], rule["months"][0], rule["weekdays"][0]))
        return rules


class _DynamicMeans:
    """Fetched prices of dynamic tariffs, as duration-weighted means over cells.

    Each stored interval is assigned to the cell its start falls in on the Swiss
    wall clock, the way the engine resolves the band of a reading by its start,
    and counts for its whole duration. A tariff's floor (feed-in only) is applied
    per interval, as the engine applies it per price lookup.
    """

    def __init__(self, tariffs, bounds, cells):
        self._cells = cells
        self._bounds = bounds
        self._stats: dict[tuple, dict[int, list]] = defaultdict(dict)
        self._expected: dict[int, dict[int, int]] = {}
        self._load(tariffs)

    def _load(self, tariffs) -> None:
        if not tariffs or not self._bounds:
            return
        by_source: dict = defaultdict(list)
        for tariff in tariffs:
            by_source[tariff.dynamic_source_id].append(tariff)
        starts = [start for start, _end in self._bounds]
        active = {
            (tariff.pk, index): _active_on(tariff, start)
            for tariff in tariffs
            for index, start in enumerate(starts)
        }
        window_start, window_end = period_window(starts[0], self._bounds[-1][1])
        rows = DynamicPricePoint.objects.filter(
            source_id__in=list(by_source), valid_from__gte=window_start, valid_from__lt=window_end,
        ).values_list("source_id", "valid_from", "valid_to", "price_chf_per_kwh").iterator(chunk_size=5000)
        for source_id, valid_from, valid_to, price in rows:
            local = wall_clock(valid_from)
            index = bisect_right(starts, local.date()) - 1
            if index < 0:
                continue
            seconds = int((valid_to - valid_from).total_seconds())
            cell = self._cells.index(local.month, local.weekday(), self._cells.part_of(local.time()))
            for tariff in by_source[source_id]:
                if not active[tariff.pk, index]:
                    continue
                value = Decimal(price)
                if tariff.minimum_price_chf_per_kwh is not None:
                    value = max(value, Decimal(tariff.minimum_price_chf_per_kwh))
                entry = self._stats[tariff.pk, index].setdefault(cell, [Decimal("0"), 0])
                entry[0] += value * seconds
                entry[1] += seconds

    def _expected_seconds(self, index: int) -> dict[int, int]:
        if index not in self._expected:
            start, end = self._bounds[index]
            lengths = self._cells.part_seconds()
            expected: dict[int, int] = defaultdict(int)
            day = start
            while day <= end:
                for part, length in enumerate(lengths):
                    expected[self._cells.index(day.month, day.weekday(), part)] += length
                day += timedelta(days=1)
            self._expected[index] = expected
        return self._expected[index]

    def mean(self, tariff, index: int, cells: list[int]) -> tuple[Decimal | None, Decimal]:
        """(mean CHF/kWh, share of the slot's hours covered) of ``tariff`` over ``cells``.

        The mean is ``None`` when nothing was fetched for them.
        """
        stats = self._stats.get((tariff.pk, index), {})
        weighted, covered = Decimal("0"), 0
        for cell in cells:
            entry = stats.get(cell)
            if entry:
                weighted += entry[0]
                covered += entry[1]
        if not covered:
            return None, Decimal("0")
        expected = self._expected_seconds(index)
        nominal = sum(expected.get(cell, 0) for cell in cells)
        coverage = min(Decimal(covered) / Decimal(nominal), _ONE) if nominal else _ONE
        return weighted / covered, coverage


def _is_all_hours(rules: list[dict]) -> bool:
    return (
        len(rules) == 1
        and tuple(rules[0]["months"]) == _ALL_MONTHS
        and tuple(rules[0]["weekdays"]) == _ALL_WEEKDAYS
        and tuple(rules[0]["windows"]) == _ALL_DAY
    )


def _rate_on(rates: list, day: date) -> Decimal:
    for rate in rates:
        if _active_on(rate, day):
            return Decimal(rate.rate)
    return Decimal("0")


def _vat_boundaries(rates: list) -> set[date]:
    days = set()
    for rate in rates:
        days.add(rate.valid_from)
        if rate.valid_to is not None:
            days.add(rate.valid_to + timedelta(days=1))
    return days


def _gross(vat_mode: str, tariff, net: Decimal, rate: Decimal) -> Decimal | None:
    """What ``net`` becomes once VAT is accounted for, by the ZEV's VAT mode."""
    if vat_mode == VatMode.REGISTERED:
        return net * (_ONE + rate)
    if vat_mode == VatMode.INCLUSIVE:
        return net * (_ONE + rate) if _tariff_bears_input_vat(tariff) else net
    return None


def _default_range(typed, today: date) -> tuple[date, date]:
    if not typed:
        return today, today
    start = min(tariff.valid_from for tariff in typed)
    # An open-ended version is drawn up to today, as the single-tariff chart does.
    end = max(
        tariff.valid_to if tariff.valid_to is not None else max(today, tariff.valid_from)
        for tariff in typed
    )
    return start, max(start, end)


def _month_starts(first: date, last: date):
    """The first day of every calendar month after ``first``, up to ``last``."""
    month = date(first.year + (first.month // 12), first.month % 12 + 1, 1)
    while month <= last:
        yield month
        month = date(month.year + (month.month // 12), month.month % 12 + 1, 1)


class _Component(NamedTuple):
    tariff: object
    #: The band that priced it; ``None`` for a dynamic tariff, which has none.
    band: object | None
    net: Decimal
    gross: Decimal | None
    share: Decimal | None = None
    #: Share of the slot's hours with a fetched price, for a dynamic tariff.
    coverage: Decimal | None = None


def build_progression(
    zev,
    tariffs,
    energy_type: str,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    today: date | None = None,
) -> dict:
    """The combined progression of ``energy_type`` for ``zev``.

    ``tariffs`` are the ZEV's tariffs the caller may see, with ``periods``
    prefetched. Raises :class:`TooManyBands` when an interval has more slots than
    :data:`MAX_SLOTS_PER_INTERVAL`.
    """
    today = today or timezone.localdate()
    tariffs = list(tariffs)
    vat_mode = zev.vat_mode
    with_vat = vat_mode != VatMode.NOT_REGISTERED
    rates = list(VatRate.objects.all()) if with_vat else []

    periods_cache: dict = {}

    def periods_of(tariff):
        if tariff.pk not in periods_cache:
            periods_cache[tariff.pk] = list(tariff.periods.all())
        return periods_cache[tariff.pk]

    typed = [t for t in tariffs if t.billing_mode in _ENERGY_MODES and t.energy_type == energy_type]
    displayed = [t for t in typed if not t.dynamic_source_id]
    dynamic_typed = [t for t in typed if t.dynamic_source_id]
    grid = [t for t in tariffs if t.billing_mode == BillingMode.ENERGY and t.energy_type == EnergyType.GRID]
    grid_static = [t for t in grid if not t.dynamic_source_id]
    grid_dynamic = [t for t in grid if t.dynamic_source_id]

    default_from, default_to = _default_range(typed, today)
    range_from = date_from or default_from
    range_to = date_to or max(default_to, range_from)

    def overlaps_range(tariff) -> bool:
        return tariff.valid_from <= range_to and (tariff.valid_to is None or tariff.valid_to >= range_from)

    expected = {t.category for t in displayed if periods_of(t) and overlaps_range(t)}
    expected |= {t.category for t in dynamic_typed if overlaps_range(t)}
    expected_categories = [c for c in _CATEGORY_ORDER if c in expected]
    # A category is only *missing* inside its own span, like a gap between the
    # versions of one tariff (``tariffs.series.find_gaps``): before its first tariff
    # starts, or after its last one has ended, it simply was not charged.
    spans: dict = {}
    for tariff in displayed + dynamic_typed:
        first, last = spans.get(tariff.category, (tariff.valid_from, tariff.valid_to or date.max))
        spans[tariff.category] = (
            min(first, tariff.valid_from), max(last, tariff.valid_to or date.max),
        )

    has_percentage = any(t.billing_mode == BillingMode.PERCENTAGE_OF_ENERGY for t in displayed)
    shaping_pool = displayed + ([t for t in grid_static if t not in displayed] if has_percentage else [])
    cells = _Cells(shaping_pool, periods_of)
    # Dynamic tariffs that price this view: its own, and the grid base of a percentage tariff.
    dynamic_pool = dynamic_typed + [g for g in (grid_dynamic if has_percentage else []) if g not in dynamic_typed]

    # Breakpoints: wherever a tariff that matters starts or stops, or the VAT rate changes.
    boundaries = {range_from}
    for tariff in typed + (grid if has_percentage else []):
        boundaries.add(tariff.valid_from)
        if tariff.valid_to is not None:
            boundaries.add(tariff.valid_to + timedelta(days=1))
    if with_vat:
        boundaries |= _vat_boundaries(rates)
    # A fetched series is averaged per calendar month while it is in force.
    for tariff in dynamic_pool:
        first = max(range_from, tariff.valid_from)
        last = min(range_to, tariff.valid_to) if tariff.valid_to else range_to
        boundaries.update(_month_starts(first, last))
    # Nothing to chart without a tariff of this type, however long the range.
    starts = sorted(day for day in boundaries if range_from <= day <= range_to) if typed else []
    bounds = [
        (start, starts[position + 1] - timedelta(days=1) if position + 1 < len(starts) else range_to)
        for position, start in enumerate(starts)
    ]
    dynamic = _DynamicMeans(dynamic_pool, bounds, cells)

    intervals = [
        _interval(
            position, start, end, vat_mode=vat_mode, rates=rates, cells=cells, periods_of=periods_of,
            displayed=displayed, dynamic_typed=dynamic_typed, grid_static=grid_static,
            grid_dynamic=grid_dynamic, dynamic=dynamic, spans=spans,
        )
        for position, (start, end) in enumerate(bounds)
    ]

    lines = _assign_lines(intervals)

    return {
        "zev": str(zev.pk),
        "energy_type": energy_type,
        "vat_mode": vat_mode,
        "from": range_from.isoformat(),
        "to": range_to.isoformat(),
        "expected_categories": expected_categories,
        "lines": lines,
        "intervals": intervals,
        "fixed_fees": _fixed_fees(
            tariffs, vat_mode=vat_mode, rates=rates,
            date_from=date_from, date_to=date_to,
        ),
    }


def _interval(position, start, end, *, vat_mode, rates, cells, periods_of, displayed, dynamic_typed,
              grid_static, grid_dynamic, dynamic, spans) -> dict:
    with_vat = vat_mode != VatMode.NOT_REGISTERED
    rate = _rate_on(rates, start) if with_vat else Decimal("0")

    active = [t for t in displayed if _active_on(t, start)]
    active_dynamic = [t for t in dynamic_typed if _active_on(t, start)]
    priceable = [t for t in active if periods_of(t)]
    energy = [t for t in priceable if t.billing_mode == BillingMode.ENERGY]
    percentage = [t for t in priceable if t.billing_mode == BillingMode.PERCENTAGE_OF_ENERGY]
    base = [g for g in grid_static if _active_on(g, start) and periods_of(g)] if percentage else []
    base_dynamic = [g for g in grid_dynamic if _active_on(g, start)] if percentage else []
    present = {t.category for t in active + active_dynamic}
    missing = [
        c for c in _CATEGORY_ORDER
        if c in spans and c not in present and spans[c][0] < start and end < spans[c][1]
    ]

    shaping = list({t.pk: t for t in [*energy, *percentage, *base]}.values())
    flags: dict = {}
    base_blocked: set = set()
    slots = []
    if energy or percentage or active_dynamic:
        groups: dict[tuple, list[int]] = defaultdict(list)
        for index in range(len(cells.cells)):
            groups[tuple(cells.band(t, index).pk for t in shaping)].append(index)
        if len(groups) > MAX_SLOTS_PER_INTERVAL:
            raise TooManyBands(f"{len(groups)} bands between {start} and {end}")
        for indices in groups.values():
            slots.append(_slot(
                indices, cells=cells, shaping=shaping, energy=energy, percentage=percentage,
                base=base, dynamic_energy=active_dynamic, base_dynamic=base_dynamic,
                dynamic=dynamic, position=position, flags=flags, base_blocked=base_blocked,
                vat_mode=vat_mode, rate=rate,
            ))
        if (flags or base_blocked) and not any(slot["categories"] for slot in slots):
            # Nothing could be priced: a line at 0.00000 would read as a real price.
            slots = []

    incomplete = [
        {"tariff_id": str(t.pk), "name": t.name, "reason": flags[t.pk]}
        for t in {t.pk: t for t in [*active_dynamic, *base_dynamic]}.values() if t.pk in flags
    ]
    incomplete += [
        {"tariff_id": str(t.pk), "name": t.name, "reason": "no_bands"}
        for t in active if not periods_of(t)
    ]
    incomplete += [
        {"tariff_id": str(t.pk), "name": t.name, "reason": "dynamic_base"}
        for t in percentage if t.pk in base_blocked
    ]

    return {
        "from": start.isoformat(),
        "to": end.isoformat(),
        "vat_rate": _text(rate, Decimal("0.0001")) if with_vat else None,
        "missing_categories": missing,
        "incomplete": incomplete,
        "slots": slots,
    }


def _slot(indices, *, cells, shaping, energy, percentage, base, dynamic_energy, base_dynamic,
          dynamic, position, flags, base_blocked, vat_mode, rate) -> dict:
    first = indices[0]
    bands = {t.pk: cells.band(t, first) for t in shaping}
    with_vat = vat_mode != VatMode.NOT_REGISTERED

    # A fetched series is averaged over this slot's hours within the interval.
    means: dict = {}
    for tariff in {t.pk: t for t in [*dynamic_energy, *base_dynamic]}.values():
        mean, coverage = dynamic.mean(tariff, position, indices)
        means[tariff.pk] = (mean, coverage)
        if mean is None:
            flags[tariff.pk] = "dynamic_no_data"
        elif coverage < DYNAMIC_COVERAGE_COMPLETE and flags.get(tariff.pk) != "dynamic_no_data":
            flags[tariff.pk] = "dynamic_partial"
    base_known = all(means[g.pk][0] is not None for g in base_dynamic)

    net_base = sum((_d(bands[g.pk].price_chf_per_kwh) for g in base), Decimal("0"))
    gross_base = None
    if vat_mode == VatMode.INCLUSIVE:
        gross_base = sum(
            (_d(bands[g.pk].price_chf_per_kwh) * (_ONE + rate if _tariff_bears_input_vat(g) else _ONE)
             for g in base),
            Decimal("0"),
        )
    if base_known:
        for grid_tariff in base_dynamic:
            mean = means[grid_tariff.pk][0]
            net_base += mean
            if gross_base is not None:
                gross_base += mean * (_ONE + rate if _tariff_bears_input_vat(grid_tariff) else _ONE)

    components = []
    for tariff in energy:
        net = _d(bands[tariff.pk].price_chf_per_kwh)
        components.append(_Component(tariff, bands[tariff.pk], net, _gross(vat_mode, tariff, net, rate)))
    for tariff in dynamic_energy:
        mean, coverage = means[tariff.pk]
        if mean is not None:
            components.append(_Component(tariff, None, mean, _gross(vat_mode, tariff, mean, rate), None, coverage))
    for tariff in percentage:
        band = bands[tariff.pk]
        share = _d(band.percentage)
        if not share:
            # A 0 % band bills nothing and, as in the engine, resolves no base.
            continue
        if not base_known:
            base_blocked.add(tariff.pk)
            continue
        fraction = share / _HUNDRED
        net = net_base * fraction
        if vat_mode == VatMode.INCLUSIVE and not _tariff_bears_input_vat(tariff):
            gross = gross_base * fraction
        else:
            gross = _gross(vat_mode, tariff, net, rate)
        components.append(_Component(tariff, band, net, gross, share))

    categories = []
    total_net = Decimal("0")
    total_gross = Decimal("0")
    for category in _CATEGORY_ORDER:
        rows = sorted(
            (row for row in components if row.tariff.category == category),
            key=lambda row: (row.tariff.name.lower(), str(row.tariff.pk)),
        )
        if not rows:
            continue
        sub_net = sum((row.net for row in rows), Decimal("0"))
        sub_gross = sum((row.gross for row in rows), Decimal("0")) if with_vat else None
        total_net += sub_net
        if with_vat:
            total_gross += sub_gross
        categories.append({
            "category": category,
            "net": _text(sub_net),
            "gross": _text(sub_gross),
            "components": [
                {
                    "tariff_id": str(row.tariff.pk),
                    "name": row.tariff.name,
                    "billing_mode": row.tariff.billing_mode,
                    "band_period_id": str(row.band.pk) if row.band is not None else None,
                    "net": _text(row.net),
                    "gross": _text(row.gross),
                    "percentage": None if row.share is None else format(row.share, "f"),
                    "base_net": None if row.share is None else _text(net_base),
                    "dynamic": row.coverage is not None,
                    "coverage": _text(row.coverage, Decimal("0.0001")),
                }
                for row in rows
            ],
        })

    rules = cells.rules(indices)
    return {
        "line": None,
        "net": _text(total_net),
        "gross": _text(total_gross) if with_vat else None,
        "categories": categories,
        "_rules": rules,
        "_signature": json.dumps(rules, sort_keys=True, separators=(",", ":")),
    }


def _assign_lines(intervals: list[dict]) -> list[dict]:
    """Name the lines: one per distinct "when", all-hours first, then by first appearance."""
    rules_by_signature: dict[str, list[dict]] = {}
    order: list[str] = []
    for interval in intervals:
        interval["slots"].sort(key=lambda slot: (
            slot["_rules"][0]["windows"][0]["from"], slot["_rules"][0]["months"][0],
            slot["_rules"][0]["weekdays"][0],
        ))
        for slot in interval["slots"]:
            if slot["_signature"] not in rules_by_signature:
                rules_by_signature[slot["_signature"]] = slot["_rules"]
                order.append(slot["_signature"])
    order.sort(key=lambda signature: 0 if _is_all_hours(rules_by_signature[signature]) else 1)

    keys = {signature: f"line-{number}" for number, signature in enumerate(order, start=1)}
    for interval in intervals:
        for slot in interval["slots"]:
            slot["line"] = keys[slot.pop("_signature")]
            del slot["_rules"]
        interval["slots"].sort(key=lambda slot: int(slot["line"].split("-")[1]))
    return [{"key": keys[signature], "rules": rules_by_signature[signature]} for signature in order]


def _fixed_fees(tariffs, *, vat_mode, rates, date_from, date_to) -> list[dict]:
    """Every fixed-fee series, never summed: each keeps its own unit and scope."""
    with_vat = vat_mode != VatMode.NOT_REGISTERED
    series: dict[tuple, list] = defaultdict(list)
    for tariff in tariffs:
        if tariff.billing_mode in _FEE_MODES:
            series[series_key(tariff)].append(tariff)

    boundaries = sorted(_vat_boundaries(rates)) if with_vat else []
    result = []
    for versions in series.values():
        ordered = sort_versions(versions)
        newest = ordered[-1]
        unit, scope = _FEE_MODES[newest.billing_mode]
        rows = []
        for tariff in ordered:
            if date_to is not None and tariff.valid_from > date_to:
                continue
            if date_from is not None and tariff.valid_to is not None and tariff.valid_to < date_from:
                continue
            cuts = [tariff.valid_from] + [
                day for day in boundaries
                if day > tariff.valid_from and (tariff.valid_to is None or day <= tariff.valid_to)
            ]
            for position, cut in enumerate(cuts):
                piece_end = cuts[position + 1] - timedelta(days=1) if position + 1 < len(cuts) else tariff.valid_to
                amount = _d(tariff.fixed_price_chf)
                rate = _rate_on(rates, cut) if with_vat else None
                gross = _gross(vat_mode, tariff, amount, rate) if with_vat else None
                rows.append({
                    "tariff_id": str(tariff.pk),
                    "valid_from": cut.isoformat(),
                    "valid_to": piece_end.isoformat() if piece_end else None,
                    "amount_net": _text(amount, _FEE_STEP),
                    "amount_gross": _text(gross, _FEE_STEP),
                    "vat_rate": _text(rate, Decimal("0.0001")) if with_vat else None,
                })
        if not rows:
            continue
        result.append({
            "name": newest.name,
            "category": newest.category,
            "billing_mode": newest.billing_mode,
            "unit": unit,
            "scope": scope,
            "split_key": newest.split_key if scope == "community" else None,
            "versions": rows,
        })
    result.sort(key=lambda fee: (_CATEGORY_ORDER.index(fee["category"]), fee["name"].lower()))
    return result
