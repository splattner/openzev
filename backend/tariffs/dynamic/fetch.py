"""Fetching a dynamic price series and writing it down.

The HTTP work is delegated to ``importers.remote.fetch_tariff_document``, which
already solves this exact problem: a URL that ultimately comes from an operator's
published document, fetched server-side, so the SSRF guard, the redirect
re-validation, the size cap and the user-safe/log-only error split all apply
unchanged.

What this module adds is the walking and the writing: asking for a long window
in chunks small enough to stay under that size cap, upserting points
idempotently, and reporting which parts of the asked-for window came back empty.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from django.db import transaction
from django.db.models import Max, Min

from ..importers.remote import TariffFetchError, fetch_tariff_document
from .adapters import FetchWindow, adapter_for
from .models import DynamicPricePoint, DynamicTariffSource, FetchStatus
from .vse_v1 import DynamicTariffResponseError, PricePoint, parse_tariff_response

logger = logging.getLogger(__name__)

#: How far back a backfill reaches. Groupe E retains roughly nine months; asking
#: for more is harmless (the operator clamps) and costs one wasted request.
BACKFILL_DAYS = 400


@dataclass
class FetchResult:
    """What one fetch achieved, in the shape the Celery task returns."""

    source_id: str
    requests: int = 0
    points_written: int = 0
    warnings: list[str] | None = None

    def as_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "requests": self.requests,
            "points_written": self.points_written,
            "warnings": self.warnings or [],
        }


def chunk_windows(start: datetime, end: datetime, *, max_days: int) -> list[FetchWindow]:
    """Split a window into pieces an operator will answer in one response.

    Not an optimisation. One Groupe E request for its whole retained history
    came back 5 016 921 bytes — 95.7 % of ``remote.MAX_DOCUMENT_BYTES`` — and
    took long enough to strain the 20-second timeout. A month is ~590 KB.
    """
    if end <= start:
        return []
    windows, cursor, step = [], start, timedelta(days=max_days)
    while cursor < end:
        stop = min(cursor + step, end)
        windows.append(FetchWindow(start=cursor, end=stop))
        cursor = stop
    return windows


def fetch_window(source: DynamicTariffSource, window: FetchWindow | None) -> tuple[list[PricePoint], list[str]]:
    """Fetch and parse one request's worth of prices.

    An empty list is a legitimate answer, not a failure: Groupe E responds
    ``200 {"publication_timestamp": "", "prices": []}`` for a range it holds
    nothing for — a future day, or one older than its retention. Only a
    transport or schema problem raises.
    """
    adapter = adapter_for(source.adapter)
    url = adapter.request_url(
        source.url, tariff_type=source.tariff_type, tariff_name=source.tariff_name, window=window,
    )
    payload, _digest = fetch_tariff_document(url)
    try:
        series = parse_tariff_response(payload, tariff_type=source.tariff_type)
    except DynamicTariffResponseError as exc:
        # The parser's messages name the operator's own field, so they are safe
        # to show; the URL may carry a product name, so it stays in the log.
        raise TariffFetchError(str(exc), log_detail=f"{exc} while reading {url}") from exc
    return series.points, series.warnings


@transaction.atomic
def store_points(source: DynamicTariffSource, points: list[PricePoint]) -> int:
    """Upsert points, then refresh the source's denormalised extent.

    Re-fetching a window that is already stored has to be free of side effects:
    both operators republish during the day, and a corrected price must land on
    the existing row rather than beside it.
    """
    if points:
        DynamicPricePoint.objects.bulk_create(
            [
                DynamicPricePoint(
                    source=source,
                    valid_from=point.valid_from.astimezone(timezone.utc),
                    valid_to=point.valid_to.astimezone(timezone.utc),
                    price_chf_per_kwh=point.price_chf_per_kwh,
                )
                for point in points
            ],
            update_conflicts=True,
            unique_fields=["source", "valid_from"],
            update_fields=["valid_to", "price_chf_per_kwh"],
        )
    extent = DynamicPricePoint.objects.filter(source=source).aggregate(
        first=Min("valid_from"), last=Max("valid_to"),
    )
    DynamicTariffSource.objects.filter(pk=source.pk).update(
        covers_from=extent["first"], covers_to=extent["last"],
    )
    return len(points)


def refresh_source(source: DynamicTariffSource, *, backfill: bool = False, now: datetime | None = None) -> FetchResult:
    """Bring one source up to date, recording the outcome on the source row.

    Without ``backfill`` this asks for yesterday through the day after
    tomorrow. Each edge earns its place: yesterday because the window is in UTC
    while operators publish in local time, so a window starting at UTC midnight
    would clip the first one or two hours of the Swiss day; today because both
    operators republish it while it is running; tomorrow because Groupe E posts
    the day-ahead prices in the afternoon and there is no reason to wait a day
    to store them. Re-asking for an interval already stored is an idempotent
    upsert, so the overlap costs nothing.

    An endpoint that takes no range (BKW) is simply asked once for whatever it
    is serving.
    """
    now = now or datetime.now(timezone.utc)
    adapter = adapter_for(source.adapter)
    result = FetchResult(source_id=str(source.pk), warnings=[])

    if not adapter.supports_range:
        windows: list[FetchWindow | None] = [None]
    else:
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        start = today - timedelta(days=BACKFILL_DAYS if backfill else 1)
        windows = list(chunk_windows(start, today + timedelta(days=2), max_days=adapter.max_window_days))

    try:
        for window in windows:
            points, warnings = fetch_window(source, window)
            result.requests += 1
            result.points_written += store_points(source, points)
            for warning in warnings:
                if warning not in result.warnings:
                    result.warnings.append(warning)
    except TariffFetchError as exc:
        logger.warning("Dynamic tariff fetch failed for %s: %s", source.pk, exc.log_detail, exc_info=True)
        DynamicTariffSource.objects.filter(pk=source.pk).update(
            last_fetch_status=FetchStatus.FAILED,
            last_fetch_at=now,
            last_fetch_error=str(exc)[:500],
        )
        raise

    DynamicTariffSource.objects.filter(pk=source.pk).update(
        last_fetch_status=FetchStatus.OK,
        last_fetch_at=now,
        last_success_at=now,
        last_fetch_error="",
    )
    return result


def coverage_gaps(source: DynamicTariffSource, start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    """Stretches of ``[start, end)`` the stored series does not price.

    Reported as the holes themselves rather than as a count, because the count
    a complete day should have is not a constant: a quarter-hourly series has 96
    intervals on most days, 92 when the clocks go forward and 100 when they go
    back. Walking the stored intervals sidesteps that entirely, and also handles
    an operator whose resolution is hourly.
    """
    rows = (
        DynamicPricePoint.objects.filter(source=source, valid_to__gt=start, valid_from__lt=end)
        .order_by("valid_from")
        .values_list("valid_from", "valid_to")
    )
    gaps, cursor = [], start
    for valid_from, valid_to in rows:
        if valid_from > cursor:
            gaps.append((cursor, valid_from))
        cursor = max(cursor, valid_to)
        if cursor >= end:
            break
    if cursor < end:
        gaps.append((cursor, end))
    return gaps
