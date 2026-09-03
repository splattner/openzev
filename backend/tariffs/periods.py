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
