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


def _component_units(component: object, *, label: str) -> tuple[Decimal | None, set[str]]:
    """Pick the billable price out of one v2 tariff component, and report the rest.

    A v2 ``TariffTypeItem`` can carry ``base``/``energy``/``power``/
    ``reactive_energy`` at once — the same reason a v1 component is a *list*
    of ``{unit, value}`` rather than one price: an operator's example pairs a
    CHF/kWh energy price with a CHF/m base fee in the same interval. Only
    ``energy`` priced in CHF/kWh is billable here; ``base``/``power``/
    ``reactive_energy``, and an ``energy`` in any other unit, are collected
    rather than silently dropped — mirroring v1's ``_billable_value``, which
    exists for exactly this reason.
    """
    if component is None:
        return None, set()
    if not isinstance(component, dict):
        raise DynamicTariffResponseError(f"{label} is not a version 2 tariff component.")
    price: Decimal | None = None
    other_units: set[str] = set()
    for key in ("base", "energy", "power", "reactive_energy"):
        sub = component.get(key)
        if sub is None:
            continue
        if not isinstance(sub, dict):
            raise DynamicTariffResponseError(f"{label}.{key} is not a price.")
        unit = str(sub.get("unit") or "").strip()
        if key == "energy" and unit == BILLABLE_UNIT:
            price = _value(sub.get("value"), label=f"{label}.energy value")
        elif unit:
            other_units.add(unit)
    return price, other_units


def _dropped_unit_warnings(tariff_type: str, units: set[str]) -> list[str]:
    """Say which priced units were left behind, once per response.

    Categorised the same way v1's ``_dropped_unit_warnings`` is, but kept
    separate: v2's ``TariffUnit`` enum spells its units with slashes
    (``CHF/kW/15min``) where v1 uses underscores (``CHF_kW_15min``), so the
    two vocabularies cannot share one function.
    """
    warnings = []
    demand = sorted(u for u in units if u.startswith("CHF/kW/"))
    if demand:
        warnings.append(
            f"The {tariff_type} series also publishes a demand charge ({', '.join(demand)}) "
            "which is not billed: OpenZEV does not meter demand."
        )
    if "CHF/kVarh" in units:
        warnings.append(
            f"The {tariff_type} series also publishes a reactive-energy charge (CHF/kVarh) which is not billed."
        )
    fixed = sorted(u for u in units if u != "CHF/kVarh" and not u.startswith("CHF/kW/"))
    if fixed:
        warnings.append(
            f"The {tariff_type} series also publishes a fixed charge ({', '.join(fixed)}) which is not "
            "billed here: add it as a monthly or yearly fee tariff, which does not need a time series."
        )
    return warnings


def parse_tariff_response(payload: object, *, tariff_type: str) -> ParsedSeries:
    if tariff_type not in TARIFF_TYPES:
        raise DynamicTariffResponseError(f"Unknown tariff type {tariff_type!r}.")
    if not isinstance(payload, dict):
        raise DynamicTariffResponseError("The response is not a JSON object.")
    raw_prices = payload.get("prices")
    if not isinstance(raw_prices, list):
        raise DynamicTariffResponseError("The response's 'prices' is not a list.")

    series = ParsedSeries(publication_timestamp=_publication_timestamp(payload.get("publication_timestamp")))
    dropped_units: set[str] = set()
    for index, raw in enumerate(raw_prices):
        if not isinstance(raw, dict):
            raise DynamicTariffResponseError(f"Price entry {index} is not an object.")
        valid_from = parse_timestamp(raw.get("start_timestamp"), label=f"Price entry {index} start_timestamp")
        valid_to = parse_timestamp(raw.get("end_timestamp"), label=f"Price entry {index} end_timestamp")
        if valid_to <= valid_from:
            raise DynamicTariffResponseError(f"Price entry {index} ends at or before it starts.")
        price, units = _component_units(raw.get(tariff_type), label=f"Price entry {index} {tariff_type}")
        dropped_units.update(units)
        if price is not None:
            series.points.append(PricePoint(valid_from=valid_from, valid_to=valid_to, price_chf_per_kwh=price))

    series.points.sort(key=lambda point: point.valid_from)
    for earlier, later in zip(series.points, series.points[1:]):
        if later.valid_from < earlier.valid_to:
            raise DynamicTariffResponseError("Two price intervals overlap; which price applies is undefined.")
    series.warnings.extend(_dropped_unit_warnings(tariff_type, dropped_units))
    return series
