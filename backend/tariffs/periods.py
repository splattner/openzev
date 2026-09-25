"""When a price band applies: which months, which weekdays, which hours.

``TariffPeriod`` stores its months and weekdays as comma-separated strings, so
something has to turn them into sets before they can be matched against a
reading's timestamp. The engine does that once per reading per tariff — tens of
thousands of times for a year of 15-minute data — so the parsed sets are
memoised on the model instance, which the engine holds prefetched for the whole
invoice run.

The month range formatting lives here too, because a seasonal band is written
``Oct–Mar`` on a contract, not ``Jan–Mar, Oct–Dec``: the year wraps, and a
reader who sees the split version has to work out for themselves that it is one
season.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

ALL_MONTHS = frozenset(range(1, 13))
ALL_WEEKDAYS = frozenset(range(7))  # 0 = Monday, matching datetime.weekday()

_MONTHS_CACHE = "_parsed_months"
_WEEKDAYS_CACHE = "_parsed_weekdays"


def parse_number_list(raw: str) -> frozenset[int]:
    """``"1,2,10"`` → ``{1, 2, 10}``. Blank yields the empty set."""
    if not raw:
        return frozenset()
    return frozenset(int(part) for part in raw.split(",") if part.strip())


def format_number_list(numbers) -> str:
    """Stored sorted, so two periods covering the same months compare equal
    as strings and read the same in the admin."""
    return ",".join(str(number) for number in sorted(numbers))


def _cached(period, attribute: str, cache_key: str, everything: frozenset[int]) -> frozenset[int]:
    cached = getattr(period, cache_key, None)
    if cached is None:
        raw = getattr(period, attribute, "") or ""
        # Blank means "no restriction", which is the same thing as every value
        # and spares every caller a None check.
        cached = parse_number_list(raw) or everything
        setattr(period, cache_key, cached)
    return cached


def months_of(period) -> frozenset[int]:
    return _cached(period, "months", _MONTHS_CACHE, ALL_MONTHS)


def weekdays_of(period) -> frozenset[int]:
    return _cached(period, "weekdays", _WEEKDAYS_CACHE, ALL_WEEKDAYS)


def is_seasonal(period) -> bool:
    return months_of(period) != ALL_MONTHS


def month_ranges(months) -> list[tuple[int, int]]:
    """Contiguous runs of months, as ``(first, last)`` pairs.

    December and January are treated as adjacent, so a winter season comes back
    as one ``(10, 3)`` range rather than two. An unrestricted period — or one
    covering all twelve months — returns an empty list: there is no season to
    name.
    """
    months = set(months)
    if not months or months == set(ALL_MONTHS):
        return []

    runs: list[list[int]] = []
    for month in sorted(months):
        if runs and month == runs[-1][-1] + 1:
            runs[-1].append(month)
        else:
            runs.append([month])

    # A season that spans the turn of the year arrives as a run ending in
    # December and one starting in January; they are the same season.
    if len(runs) > 1 and runs[0][0] == 1 and runs[-1][-1] == 12:
        runs[-1].extend(runs.pop(0))

    return [(run[0], run[-1]) for run in runs]


def hhmm(value) -> str:
    """``07:00`` from a ``time`` or from the string a form posted.

    Rows read back from the database hold ``time`` objects, but a freshly
    assigned one holds whatever was given it, and both reach the naming code.
    """
    return str(value)[:5]


# The literal mirrors ``tariffs.models.PeriodType.FLAT``. It cannot be imported
# here: ``TariffPeriod.clean`` reads ``hhmm``/``parse_number_list`` from this
# module, so importing back from ``models`` would be circular.
_FLAT_PERIOD_TYPE = "flat"


def resolve_band(periods, ts: datetime):
    """The band among ``periods`` that prices a tariff at ``ts``, or ``None``.

    The single resolution rule for both energy and percentage bands — see
    ``invoices.engine._resolve_tariff_band``, which delegates here so a static
    tariff's price is resolved in exactly one place regardless of billing
    mode. ``periods`` is any iterable of ``TariffPeriod``-like rows (already
    fetched, not re-queried).
    """
    periods = list(periods)
    if not periods:
        return None

    # The month is checked before anything else, the flat case included: a
    # winter-only flat band that short-circuited on period_type would bill its
    # winter price in July. Bands with no months set match every month.
    in_season = [period for period in periods if ts.month in months_of(period)]

    # A flat band short-circuits without looking at the window, which is only
    # safe because a flat band may not share its months with a timed one.
    t_time = ts.time()
    weekday = ts.weekday()  # 0 = Monday
    for period in in_season:
        if period.period_type == _FLAT_PERIOD_TYPE:
            return period
        if period.time_from and period.time_to:
            if weekday in weekdays_of(period) and period.time_from <= t_time < period.time_to:
                return period

    # Nothing matched the hour: the day's first band in this season, else the
    # tariff's first band overall.
    return (in_season or periods)[0]


# A non-leap reference year: 2025 has no 29 February to double-count or skip,
# so every day-of-year maps to exactly one calendar date across the whole
# resolution loop below.
_AVERAGE_REFERENCE_YEAR = 2025
_AVERAGE_STEP = timedelta(minutes=15)


def average_percentage(tariff) -> Decimal:
    """Time-weighted mean percentage of ``tariff``'s bands over one reference year.

    Used where a single representative percentage is needed (the feasibility
    prefill estimate) rather than the exact per-timestamp resolution the
    engine performs when actually billing. Walks a non-leap reference year
    (2025) in 15-minute steps, resolving each with :func:`resolve_band` — the
    same rule the engine uses — and averages the result. ``Decimal("0")``
    when the tariff has no bands. The result is an estimate by time, not by
    energy.
    """
    periods = list(tariff.periods.all())
    if not periods:
        return Decimal("0")

    total = Decimal("0")
    steps = 0
    current = datetime(_AVERAGE_REFERENCE_YEAR, 1, 1, 0, 0)
    end = datetime(_AVERAGE_REFERENCE_YEAR + 1, 1, 1, 0, 0)
    while current < end:
        band = resolve_band(periods, current)
        total += band.percentage if band is not None and band.percentage is not None else Decimal("0")
        steps += 1
        current += _AVERAGE_STEP

    if steps == 0:
        return Decimal("0")
    return (total / steps).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
