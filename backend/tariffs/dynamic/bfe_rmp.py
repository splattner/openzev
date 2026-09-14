"""Parser for the BFE reference market price CSV (Referenz-Marktpreise gemäss
Art. 15 EnFV).

Unlike the VSE-protocol sources, this is not a live endpoint answering a
parameterised request: it is a small federal open-data publication, quarterly
or monthly, carrying one figure per technology for the whole period — see
https://www.i14y.admin.ch/de/catalog/datasets/BFE-DS-0020 and
docs/adr/0018-dynamic-tariff-price-series.md. Two files exist, differing only
by period column and (naturally) by URL:

    Year,Period,Days,Volume_pv_MWh,Price_pv_CHF_MWh,Volume_wasserkraft_MWh,Price_wasserkraft_CHF_MWh,...
    2026,Q2,91,2054782,38.96,3751071,93.18,30934,88.73,418953,87.79

    Year,Month,Days,Volume_pv_MWh,Price_pv_CHF_MWh,...
    2026,4,30,...

This module is pure: no database, no network, no Django — only the standard
library, mirroring ``vse_v1``/``vse_v2``. Since 1 January 2026 this is also
the statutory default feed-in compensation absent another agreement (Art. 15
EnG/EnV).
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, DivisionByZero, InvalidOperation
from zoneinfo import ZoneInfo

from .vse_v1 import DynamicTariffResponseError, PricePoint

TARIFF_TYPES = ("feed_in",)

#: The technology columns BFE publishes. Used as the dynamic source's
#: ``tariff_name`` — the same slot v2 uses for a product identity.
TECHNOLOGIES = ("pv", "wasserkraft", "windenergie", "biomasse")

# BFE publishes 2 decimals of CHF/MWh, which divides exactly into 5 decimals
# of CHF/kWh — the precision ``DynamicPricePoint.price_chf_per_kwh`` stores.
PRICE_QUANTUM = Decimal("0.00001")

_ZURICH = ZoneInfo("Europe/Zurich")

_QUARTER_START_MONTH = {"Q1": 1, "Q2": 4, "Q3": 7, "Q4": 10}


@dataclass
class ParsedSeries:
    points: list[PricePoint] = field(default_factory=list)
    publication_timestamp: datetime | None = None
    warnings: list[str] = field(default_factory=list)


def _local_month_start(year: int, month: int) -> datetime:
    """Midnight Europe/Zurich on the first of ``month``, as UTC.

    Never ambiguous: Swiss DST transitions land at 02:00/03:00 local, never
    at midnight on the first of a month.
    """
    return datetime(year, month, 1, tzinfo=_ZURICH).astimezone(timezone.utc)


def _add_months(year: int, month: int, months: int) -> tuple[int, int]:
    total = (year * 12 + (month - 1)) + months
    return total // 12, total % 12 + 1


def _period_interval(row: dict, index: int) -> tuple[datetime, datetime]:
    """The [start, end) UTC interval one CSV row's period covers."""
    raw_year = row.get("Year")
    try:
        year = int(str(raw_year).strip())
    except (TypeError, ValueError):
        raise DynamicTariffResponseError(f"Row {index} has an invalid Year: {raw_year!r}.")

    if "Period" in row:
        # Quarterly file: "Period" holds "Q1".."Q4".
        raw_period = str(row.get("Period") or "").strip().upper()
        start_month = _QUARTER_START_MONTH.get(raw_period)
        if start_month is None:
            raise DynamicTariffResponseError(f"Row {index} has an invalid Period: {row.get('Period')!r}.")
        end_year, end_month = _add_months(year, start_month, 3)
    elif "Month" in row:
        raw_month = row.get("Month")
        try:
            start_month = int(str(raw_month).strip())
        except (TypeError, ValueError):
            start_month = -1
        if not 1 <= start_month <= 12:
            raise DynamicTariffResponseError(f"Row {index} has an invalid Month: {raw_month!r}.")
        end_year, end_month = _add_months(year, start_month, 1)
    else:
        raise DynamicTariffResponseError("The CSV has neither a 'Period' nor a 'Month' column.")

    return _local_month_start(year, start_month), _local_month_start(end_year, end_month)


def _price(raw: object, *, label: str) -> Decimal | None:
    """The published CHF/MWh figure, converted to CHF/kWh — or ``None`` for a
    not-yet-published period, which BFE leaves blank rather than omitting the
    row entirely."""
    if raw is None or str(raw).strip() == "":
        return None
    try:
        chf_per_mwh = Decimal(str(raw).strip())
    except InvalidOperation as exc:
        raise DynamicTariffResponseError(f"{label} is not a number: {raw!r}.") from exc
    try:
        return (chf_per_mwh / Decimal(1000)).quantize(PRICE_QUANTUM)
    except (InvalidOperation, DivisionByZero) as exc:
        raise DynamicTariffResponseError(f"{label} is not a number: {raw!r}.") from exc


def _reject_overlaps(points: list[PricePoint]) -> None:
    for earlier, later in zip(points, points[1:]):
        if later.valid_from < earlier.valid_to:
            raise DynamicTariffResponseError(
                "Two price periods overlap "
                f"({earlier.valid_from.isoformat()} → {earlier.valid_to.isoformat()} and "
                f"{later.valid_from.isoformat()} → {later.valid_to.isoformat()})."
            )


def parse_tariff_response(text: str, *, tariff_name: str) -> ParsedSeries:
    """Read the decoded CSV text into price points for one technology.

    ``tariff_name`` selects the technology column (one of ``TECHNOLOGIES``) —
    the CSV carries all four, but a source prices exactly one, the way a v2
    source prices exactly one product.
    """
    if tariff_name not in TECHNOLOGIES:
        raise DynamicTariffResponseError(
            f"Unknown technology {tariff_name!r}; expected one of {', '.join(TECHNOLOGIES)}."
        )
    if not isinstance(text, str):
        raise DynamicTariffResponseError("The response is not text.")

    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise DynamicTariffResponseError("The CSV has no header row.")
    column = f"Price_{tariff_name}_CHF_MWh"
    if column not in reader.fieldnames:
        raise DynamicTariffResponseError(f"The CSV has no {column!r} column.")

    series = ParsedSeries()
    for index, row in enumerate(reader):
        valid_from, valid_to = _period_interval(row, index)
        if valid_to <= valid_from:
            raise DynamicTariffResponseError(
                f"Row {index} ends at or before it starts ({valid_from.isoformat()} → {valid_to.isoformat()})."
            )
        price = _price(row.get(column), label=f"Row {index} {column}")
        if price is None:
            continue
        series.points.append(PricePoint(valid_from=valid_from, valid_to=valid_to, price_chf_per_kwh=price))

    series.points.sort(key=lambda point: point.valid_from)
    _reject_overlaps(series.points)
    return series
