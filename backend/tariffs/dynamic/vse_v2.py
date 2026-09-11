"""Parser for the VSE-compatible dynamic tariff response, schema v2.0.0."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation

from .vse_v1 import PRICE_QUANTUM, DynamicTariffResponseError, PricePoint, parse_timestamp

TARIFF_TYPES = (
    "electricity", "grid", "metering", "national_fees", "regional_fees",
    "dso", "dso_complete", "integrated", "integrated_complete", "feed_in", "refund",
)
BILLABLE_UNIT = "CHF/kWh"


@dataclass
class ParsedSeries:
    points: list[PricePoint] = field(default_factory=list)
    publication_timestamp: datetime | None = None
    warnings: list[str] = field(default_factory=list)


def _publication_timestamp(raw: object) -> datetime | None:
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    return parse_timestamp(raw, label="publication_timestamp")


def _value(raw: object, *, label: str) -> Decimal:
    if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
        raise DynamicTariffResponseError(f"{label} is not a number: {raw!r}.")
    try:
        return Decimal(str(raw)).quantize(PRICE_QUANTUM)
    except (InvalidOperation, ValueError) as exc:
        raise DynamicTariffResponseError(f"{label} is not a number: {raw!r}.") from exc


def _energy_price(component: object, *, label: str) -> tuple[Decimal | None, list[str]]:
    if component is None:
        return None, []
    if not isinstance(component, dict):
        raise DynamicTariffResponseError(f"{label} is not a version 2 tariff component.")
    energy = component.get("energy")
    if energy is None:
        return None, []
    if not isinstance(energy, dict):
        raise DynamicTariffResponseError(f"{label}.energy is not a price.")
    unit = str(energy.get("unit") or "").strip()
    if unit != BILLABLE_UNIT:
        return None, [unit] if unit else []
    return _value(energy.get("value"), label=f"{label}.energy value"), []


def parse_tariff_response(payload: object, *, tariff_type: str) -> ParsedSeries:
    if tariff_type not in TARIFF_TYPES:
        raise DynamicTariffResponseError(f"Unknown tariff type {tariff_type!r}.")
    if not isinstance(payload, dict):
        raise DynamicTariffResponseError("The response is not a JSON object.")
    raw_prices = payload.get("prices")
    if not isinstance(raw_prices, list):
        raise DynamicTariffResponseError("The response's 'prices' is not a list.")

    series = ParsedSeries(publication_timestamp=_publication_timestamp(payload.get("publication_timestamp")))
    unsupported_units: set[str] = set()
    for index, raw in enumerate(raw_prices):
        if not isinstance(raw, dict):
            raise DynamicTariffResponseError(f"Price entry {index} is not an object.")
        valid_from = parse_timestamp(raw.get("start_timestamp"), label=f"Price entry {index} start_timestamp")
        valid_to = parse_timestamp(raw.get("end_timestamp"), label=f"Price entry {index} end_timestamp")
        if valid_to <= valid_from:
            raise DynamicTariffResponseError(f"Price entry {index} ends at or before it starts.")
        price, units = _energy_price(raw.get(tariff_type), label=f"Price entry {index} {tariff_type}")
        unsupported_units.update(units)
        if price is not None:
            series.points.append(PricePoint(valid_from=valid_from, valid_to=valid_to, price_chf_per_kwh=price))

    series.points.sort(key=lambda point: point.valid_from)
    for earlier, later in zip(series.points, series.points[1:]):
        if later.valid_from < earlier.valid_to:
            raise DynamicTariffResponseError("Two price intervals overlap; which price applies is undefined.")
    if unsupported_units:
        series.warnings.append(
            f"The selected energy component uses unsupported unit(s): {', '.join(sorted(unsupported_units))}."
        )
    return series
