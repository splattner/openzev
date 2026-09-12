"""Fetch bounded windows and record refresh/recovery outcomes."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from django.db.models import F, Max, Min, RowRange, Window

from ..importers.remote import TariffFetchError, fetch_tariff_document
from .adapters import MAX_WINDOW_DAYS, FetchWindow, request_url
from .models import DynamicPricePoint, DynamicTariffSource, FetchStatus
from .protocol import parse_tariff_response
from .vse_v1 import DynamicTariffResponseError, PricePoint
from .storage import (  # re-exported for existing callers
    PriceSeriesConflict as PriceSeriesConflict,
    BilledPriceChanged as BilledPriceChanged,
    PriceIntervalConflict as PriceIntervalConflict,
    store_points as store_points,
)

logger = logging.getLogger(__name__)

#: How far back a backfill reaches. Asking beyond an endpoint's retention is
#: harmless when it clamps or returns an empty result.
BACKFILL_DAYS = 400

#: Maximum lookback when resuming a scheduled recovery cursor.
RECOVERY_DAYS = 14


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

    Not an optimisation. One measured request for its whole retained history
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

    An empty list is a legitimate answer, not a failure: an endpoint may respond
    ``200 {"publication_timestamp": "", "prices": []}`` for a range it holds
    nothing for — a future day, or one older than its retention. Only a
    transport or schema problem raises.
    """
    url = request_url(
        source.url,
        request_mode=source.request_mode,
        query_tariff_type=source.query_tariff_type or source.tariff_type,
        tariff_name=source.tariff_name,
        window=window,
    )
    try:
        payload, _digest = fetch_tariff_document(url)
    except TariffFetchError as exc:
        if source.empty_on_not_found and exc.status_code == 404:
            return [], []
        raise
    series = parse_tariff_response(
        payload, api_version=source.api_version, tariff_type=source.tariff_type,
        tariff_name=source.tariff_name,
    )
    return series.points, series.warnings


def refresh_source(source: DynamicTariffSource, *, backfill: bool = False, now: datetime | None = None) -> FetchResult:
    """Refresh one source in bounded requests, recording failures and recovery progress.

    Each window is independent. Deterministic schema/storage refusals fail the
    run without Celery retry; see the dynamic tariff spec, fetching section."""
    now = now or datetime.now(timezone.utc)
    result = FetchResult(source_id=str(source.pk), warnings=[])
    # Only set on the ranged path; the exact-URL path needs no retry cursor.
    range_start = None

    if not source.supports_range:
        windows: list[FetchWindow | None] = [None]
    else:
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        horizon = today - timedelta(days=RECOVERY_DAYS)
        if backfill:
            start = today - timedelta(days=BACKFILL_DAYS)
        elif source.recovery_from is not None:
            # Clamp: an ancient cursor (e.g. a failed 400-day backfill
            # chunk) must not turn every scheduled tick into a
            # full-history fan-out. The older hole stays recorded until a
            # backfill clears it.
            start = min(today - timedelta(days=1), max(source.recovery_from, horizon))
        elif source.covers_to is not None:
            start = min(today - timedelta(days=1), source.covers_to)
        elif source.last_success_at is not None:
            successful_day = source.last_success_at.astimezone(timezone.utc).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            start = min(today - timedelta(days=1), successful_day)
        else:
            start = today - timedelta(days=1)
        range_start = start
        windows = list(chunk_windows(start, today + timedelta(days=2), max_days=MAX_WINDOW_DAYS))

    failed: list[str] = []
    failed_windows: list[FetchWindow] = []
    refused: list[str] = []
    refused_windows: list[FetchWindow] = []
    recovery_from = None
    try:
        for window in windows:
            try:
                points, warnings = fetch_window(source, window)
            except TariffFetchError as exc:
                failed.append(str(exc))
                if window is not None:
                    failed_windows.append(window)
                continue
            except DynamicTariffResponseError as exc:
                refused.append(str(exc))
                if window is not None:
                    refused_windows.append(window)
                continue
            result.requests += 1
            try:
                result.points_written += store_points(source, points)
            except PriceSeriesConflict as exc:
                refused.append(str(exc))
                if window is not None:
                    refused_windows.append(window)
                continue
            for warning in warnings:
                if warning not in result.warnings:
                    result.warnings.append(warning)
        unresolved = [window.start for window in failed_windows + refused_windows]
        if (
            range_start is not None
            and source.recovery_from is not None
            and source.recovery_from < range_start
        ):
            # Clamp requests, not evidence of failures. Neither a later failure
            # nor a successful limited refresh resolves an unattempted window.
            unresolved.append(source.recovery_from)
        recovery_from = min(unresolved, default=None)
        DynamicTariffSource.objects.filter(pk=source.pk).update(
            recovery_from=recovery_from,
        )
        if refused:
            # Surface deterministic conflicts before transport failures.
            raise PriceSeriesConflict("; ".join(refused[:3]))
        if failed and result.requests == 0:
            raise TariffFetchError("; ".join(failed[:3]), log_detail="; ".join(failed[:3]))
        if failed:
            # Partial success remains OK; retain failed windows for recovery.
            summary = "; ".join(failed[:3])
            logger.warning(
                "Dynamic tariff fetch for %s answered %s window(s) and failed %s: %s",
                source.pk, result.requests, len(failed), summary,
            )
            result.warnings.append(
                f"{len(failed)} price window(s) could not be fetched: {summary}"
            )
    except TariffFetchError as exc:
        logger.warning("Dynamic tariff fetch failed for %s: %s", source.pk, exc.log_detail, exc_info=True)
        DynamicTariffSource.objects.filter(pk=source.pk).update(
            last_fetch_status=FetchStatus.FAILED,
            last_fetch_at=now,
            last_fetch_error=str(exc)[:500],
        )
        raise
    except (PriceSeriesConflict, DynamicTariffResponseError) as exc:
        logger.warning("Dynamic tariff prices refused for %s: %s", source.pk, exc)
        DynamicTariffSource.objects.filter(pk=source.pk).update(
            last_fetch_status=FetchStatus.FAILED,
            last_fetch_at=now,
            last_fetch_error=str(exc)[:500],
        )
        raise
    except Exception as exc:
        logger.warning("Dynamic tariff fetch failed for %s: %s", source.pk, exc, exc_info=True)
        DynamicTariffSource.objects.filter(pk=source.pk).update(
            last_fetch_status=FetchStatus.FAILED,
            last_fetch_at=now,
            # Keep operator-facing errors generic; full details are logged above.
            last_fetch_error=f"Unexpected {type(exc).__name__} while fetching; see the server log."[:500],
        )
        raise

    DynamicTariffSource.objects.filter(pk=source.pk).update(
        last_fetch_status=FetchStatus.OK,
        last_fetch_at=now,
        last_success_at=now,
        last_fetch_error="",
        recovery_from=recovery_from,
    )
    return result


def coverage_gaps(source: DynamicTariffSource, start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    """Stretches of ``[start, end)`` the stored series does not price.

    Reported as the holes themselves rather than as a count, because the count
    an operator-local publication day should have is not a constant: a
    quarter-hourly series has 92/96/100 intervals across DST changes. OpenZEV's
    billing windows use UTC civil days. A database window finds boundaries after all
    preceding rows have ended, so Python receives the gaps rather than every
    quarter-hour in the requested span. ``Max`` rather than ``Lag`` keeps this
    correct if legacy overlapping rows are present.
    """
    if end <= start:
        return []
    rows = (
        DynamicPricePoint.objects.filter(source=source, valid_to__gt=start, valid_from__lt=end)
        .order_by("valid_from")
    )
    bounds = rows.aggregate(first=Min("valid_from"), last=Max("valid_to"))
    if bounds["first"] is None:
        return [(start, end)]

    gaps = []
    if bounds["first"] > start:
        gaps.append((start, min(bounds["first"], end)))

    interior = (
        rows.annotate(
            previous_end=Window(
                expression=Max("valid_to"),
                order_by=(F("valid_from").asc(), F("pk").asc()),
                frame=RowRange(start=None, end=-1),
            )
        )
        .filter(valid_from__gt=F("previous_end"))
        .values_list("previous_end", "valid_from")
    )
    gaps.extend(
        (max(previous_end, start), min(valid_from, end))
        for previous_end, valid_from in interior
        if previous_end < end and valid_from > start
    )
    if bounds["last"] < end:
        gaps.append((max(bounds["last"], start), end))
    return gaps
