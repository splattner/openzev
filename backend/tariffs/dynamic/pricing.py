"""Bounded duration-weighted display summaries, separate from exact invoice pricing."""

from dataclasses import dataclass
from bisect import bisect_left, bisect_right
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from allocation.validity import period_end_exclusive_dt, period_window
from django.db.models import Q

from .adapters import DynamicApiVersion
from .models import DynamicPricePoint, DynamicTariffSource


DYNAMIC_DISPLAY_DAYS = 30
DISPLAY_PRICE_QUANTUM = Decimal("0.00001")

#: Protocols that publish one price for a whole period (a quarter, a month)
#: rather than continuously. Their newest figure is always weeks old — BFE
#: publishes a quarter on the 10th working day *after* it ends — so a display
#: window anchored on today would sit in the unpublished stretch and report
#: nothing at all, permanently. These anchor on the end of coverage instead.
PERIOD_PUBLISHED_API_VERSIONS = frozenset({DynamicApiVersion.BFE_RMP})


@dataclass(frozen=True)
class DynamicPriceSummary:
    status: str
    average_chf_per_kwh: Decimal | None
    reference_from: date | None
    reference_to: date | None

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "average_chf_per_kwh": (
                str(self.average_chf_per_kwh)
                if self.average_chf_per_kwh is not None
                else None
            ),
            "reference_from": (
                self.reference_from.isoformat() if self.reference_from else None
            ),
            "reference_to": self.reference_to.isoformat() if self.reference_to else None,
        }


def _summarize_rows(rows, *, start, end, reference_from, reference_to, floor=None) -> DynamicPriceSummary:
    """Duration weighting over sorted, non-overlapping stored intervals.

    ``floor`` is applied per interval, before weighting — flooring the
    finished average instead would understate a tariff whose series dips
    below the floor for only part of the window, and would disagree with
    what the invoice actually bills (see ``TariffResolver.price_at``).
    """
    cursor = start
    weighted_total = Decimal("0")
    covered_seconds = Decimal("0")
    complete = True
    for valid_from, valid_to, price in rows:
        clipped_from = max(valid_from, start)
        clipped_to = min(valid_to, end)
        if clipped_to <= clipped_from:
            continue
        if clipped_from > cursor:
            complete = False
        seconds = Decimal(str((clipped_to - clipped_from).total_seconds()))
        price = Decimal(str(price))
        if floor is not None:
            price = max(price, floor)
        weighted_total += price * seconds
        covered_seconds += seconds
        cursor = clipped_to

    if not covered_seconds:
        return DynamicPriceSummary(
            "unavailable", None, reference_from, reference_to
        )
    if cursor < end:
        complete = False
    average = (weighted_total / covered_seconds).quantize(
        DISPLAY_PRICE_QUANTUM, rounding=ROUND_HALF_UP
    )
    return DynamicPriceSummary(
        "complete" if complete else "partial",
        average,
        reference_from,
        reference_to,
    )


def _last_fully_covered_day(covers_to) -> date:
    """The newest civil day the stored series prices from end to end.

    A period-published series ends on a local month boundary, which is 22:00
    or 23:00 UTC — so the UTC day holding that instant is only priced for part
    of itself, and anchoring on it would report an otherwise complete window
    as partial. Stepping back one day lands on the last whole one.
    """
    day = (covers_to - timedelta(microseconds=1)).date()
    return day if period_end_exclusive_dt(day) <= covers_to else day - timedelta(days=1)


def _display_anchor(tariff, as_of: date, coverage_ends: dict) -> date:
    """The day a period-published source's display window should end on.

    Every other source is anchored on ``as_of``: a window with nothing in it
    is the honest answer there, and it is how a stalled endpoint surfaces.
    """
    covers_to = coverage_ends.get(tariff.dynamic_source_id)
    if covers_to is None:
        return as_of
    return min(as_of, _last_fully_covered_day(covers_to))


def _summary_window(tariff, *, as_of: date, days: int):
    """The clipped display window for ``tariff``, or None when pre-validity."""
    reference_to = min(as_of, tariff.valid_to) if tariff.valid_to else as_of
    if reference_to < tariff.valid_from:
        return None
    reference_from = max(tariff.valid_from, reference_to - timedelta(days=days - 1))
    start, end = period_window(reference_from, reference_to)
    return reference_from, reference_to, start, end


def summarize_dynamic_tariff(
    tariff, *, as_of: date, days: int = DYNAMIC_DISPLAY_DAYS
) -> DynamicPriceSummary:
    """Return a duration-weighted price for a bounded tariff-valid window.

    ``status`` is ``complete`` only if stored intervals cover every instant in
    the window, ``partial`` when at least one interval exists but gaps remain,
    and ``unavailable`` when no usable interval exists.
    """
    return summarize_requests({tariff.pk: (tariff, as_of)}, days=days)[tariff.pk]


def summarize_requests(requests: dict, *, days: int = DYNAMIC_DISPLAY_DAYS) -> dict:
    """Batch key → (tariff, reference date) requests over disjoint source windows.

    Both start and end bisections require non-overlapping stored intervals.
    Migration 0014 checks legacy rows; store_points maintains this invariant.
    """
    if days < 1:
        raise ValueError("days must be at least 1.")
    source_ids = {
        tariff.dynamic_source_id for tariff, _as_of in requests.values() if tariff.dynamic_source_id
    }
    # One query for every period-published source in the batch, so anchoring
    # the window costs nothing per tariff.
    coverage_ends = dict(
        DynamicTariffSource.objects
        .filter(pk__in=source_ids, api_version__in=PERIOD_PUBLISHED_API_VERSIONS)
        .exclude(covers_to=None)
        .values_list("pk", "covers_to")
    )
    windows = {}
    for key, (tariff, as_of) in requests.items():
        if not tariff.dynamic_source_id:
            raise ValueError("A dynamic price summary requires dynamic_source.")
        window = _summary_window(
            tariff, as_of=_display_anchor(tariff, as_of, coverage_ends), days=days
        )
        windows[key] = (
            (tariff.dynamic_source_id, tariff.minimum_price_chf_per_kwh, *window) if window else None
        )
    spans: dict = {}
    for value in windows.values():
        if value is None:
            continue
        source_id, _floor, _rf, _rt, start, end = value
        spans.setdefault(source_id, []).append((start, end))
    rows_by_source = {}
    for source_id, ranges in spans.items():
        merged = []
        for start, end in sorted(ranges):
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
            else:
                merged.append((start, end))
        predicate = Q()
        for start, end in merged:
            predicate |= Q(valid_from__lt=end, valid_to__gt=start)
        rows = list(DynamicPricePoint.objects.filter(predicate, source_id=source_id)
                    .order_by("valid_from").values_list("valid_from", "valid_to", "price_chf_per_kwh"))
        rows_by_source[source_id] = (rows, [row[0] for row in rows], [row[1] for row in rows])
    summaries = {}
    for key, window in windows.items():
        if window is None:
            summaries[key] = DynamicPriceSummary("unavailable", None, None, None)
            continue
        source_id, floor, reference_from, reference_to, start, end = window
        source_rows, starts, ends = rows_by_source[source_id]
        rows = source_rows[bisect_right(ends, start):bisect_left(starts, end)]
        summaries[key] = _summarize_rows(
            rows, start=start, end=end,
            reference_from=reference_from, reference_to=reference_to, floor=floor,
        )
    return summaries
