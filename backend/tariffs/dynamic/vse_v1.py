"""Parser for the VSE-compatible dynamic tariff response, schema version 1.

The response shape is standardised — SmartGridready publishes a JSON Schema and
an OpenAPI template for it, version 1.0.5 (2026-05-28), derived from the VSE
document *Dynamische Netznutzungstarife im Verteilnetz (HDN-CH 2025)*:
https://github.com/SmartGridready/SGrSpecifications/tree/master/DynamicTariff

    {
      "publication_timestamp": "2026-01-31T18:00:00+01:00",
      "prices": [
        {"start_timestamp": ..., "end_timestamp": ...,
         "grid": [{"unit": "CHF_kWh", "value": 0.113}, {"unit": "CHF_m", "value": 5}]}
      ]
    }

This module is pure: no database, no network, no Django. It takes a decoded
payload and returns price points, the way ``importers/vse_json`` takes a tariff
document and returns candidates.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation

from config.ui_notices import UiNotice

# The tariff types the standard defines. ``integrated`` is a *combination* of
# ``electricity`` and ``grid``, and the fee types are additive on top — which is
# why choosing one is a billing decision, not a display preference. See the
# double-counting note in docs/specs/2026-09-dynamic-tariffs.md.
TARIFF_TYPES = (
    "electricity",
    "grid",
    "integrated",
    "regional_fees",
    "feed_in",
)

# The only unit OpenZEV can bill from a time series. The standard defines 24:
# energy (CHF_kWh, CHF_kVarh), fixed-per-period (CHF_y … CHF_15min) and demand
# (CHF_kW_y … CHF_kW_15min). A demand charge needs metered demand, which OpenZEV
# does not have (#529); a fixed-per-period charge is already expressible as a
# static monthly or yearly fee tariff and does not need a time series at all.
BILLABLE_UNIT = "CHF_kWh"

# Five decimals is what ``TariffPeriod.price_chf_per_kwh`` stores, so it is the
# ceiling for a dynamic price too. Both probed operators publish four.
PRICE_QUANTUM = Decimal("0.00001")


class DynamicTariffResponseError(ValueError):
    """The remote tariff response or selected configuration is invalid."""

    def __init__(self, message, *, code="invalid_dynamic_response", params=None):
        super().__init__(message)
        self.code = code
        self.params = params or {}


@dataclass(frozen=True)
class PricePoint:
    """One priced interval. Timestamps are timezone-aware."""

    valid_from: datetime
    valid_to: datetime
    price_chf_per_kwh: Decimal


@dataclass
class ParsedSeries:
    """What one response yielded, plus what it could not carry.

    ``warnings`` names priced components that were dropped rather than billed.
    Silence there is how a tariff ends up billed at the wrong number, which is
    the same reason ``importers.vse_json._dropped_component_warnings`` exists.
    """

    points: list[PricePoint] = field(default_factory=list)
    publication_timestamp: datetime | None = None
    warnings: list[str] = field(default_factory=list)


def parse_timestamp(raw: object, *, label: str) -> datetime:
    """Read one ISO-8601 timestamp, which must carry an offset.

    A naive timestamp is refused rather than assumed: guessing a zone for a
    price that will be multiplied by metered energy is how an invoice silently
    shifts by an hour twice a year. Prices are stored as UTC instants (ADR 0026).
    """
    if not isinstance(raw, str) or not raw.strip():
        raise DynamicTariffResponseError(
            f"{label} is missing.",
            code="timestamp_missing", params={"field": label},
        )
    try:
        text = raw.strip()
        if text.endswith(("Z", "z")):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise DynamicTariffResponseError(
            f"{label} is not an ISO-8601 timestamp: {raw!r}.",
            code="timestamp_invalid", params={"field": label, "received": repr(raw)[:200]},
        ) from exc
    if parsed.tzinfo is None:
        raise DynamicTariffResponseError(
            f"{label} has no UTC offset: {raw!r}. The standard requires one, because a "
            "price without a zone cannot be matched to a meter reading.",
            code="timestamp_offset_missing", params={"field": label},
        )
    return parsed


def _publication_timestamp(raw: object) -> datetime | None:
    """The publication stamp, which is allowed to be absent.

    The v1 schema declares ``TimeStamp`` as ``anyOf: [date-time, empty]`` and
    An endpoint may return ``""`` for a range with no data, so an empty string
    is conformant rather than broken. v2 allows ``null`` for the same reason.
    """
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    return parse_timestamp(raw, label="publication_timestamp")


def _price(raw: object, *, label: str) -> Decimal:
    """One price value, which may legitimately be negative.

    Negative grid-usage prices are the point of a dynamic tariff, not an error:
    Production captures include negative grid prices around the solar peak.
    """
    try:
        if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
            raise ValueError
        value = Decimal(str(raw)).quantize(PRICE_QUANTUM)
        if not value.is_finite():
            raise ValueError
        return value
    except (InvalidOperation, ValueError) as exc:
        raise DynamicTariffResponseError(
            f"{label} is not a number: {raw!r}.",
            code="component_value_invalid", params={"field": label, "received": repr(raw)[:200]},
        ) from exc


def _reject_version_2(component: object, tariff_type: str) -> None:
    """Refuse a v2 payload by name instead of misreading it.

    The two versions are told apart by this one shape: in v1 a tariff type holds
    an *array* of ``{unit, value}``; in v2 it holds an *object* whose ``base`` /
    ``energy`` / ``power`` / ``reactive_energy`` keys hold those pairs, beside
    metadata like ``tariff_name`` and ``municipality_number``. v2 went final on
    2026-09-01 targeting 2027, so this will be met in the field.
    """
    if isinstance(component, dict):
        raise DynamicTariffResponseError(
            f"This endpoint answers with schema version 2, where {tariff_type!r} is an "
            "object rather than a list of prices. OpenZEV reads version 1 only."
        )


def _billable_value(component: object, *, tariff_type: str, label: str) -> tuple[Decimal | None, list[str]]:
    """Pick the CHF/kWh price out of one tariff type's component list.

    The component is a list because one tariff type can carry several units at
    once — the standard's own example pairs a ``CHF_kWh`` energy price with a
    ``CHF_m`` monthly base fee in the same interval. Reading element ``[0]``
    would be right by luck on both endpoints probed so far and wrong the first
    time an operator orders them differently, so the unit is matched, never the
    position.
    """
    _reject_version_2(component, tariff_type)
    if component is None:
        return None, []
    if not isinstance(component, list):
        raise DynamicTariffResponseError(f"{label} is not a list of prices.")

    price: Decimal | None = None
    dropped: list[str] = []
    for index, entry in enumerate(component):
        if not isinstance(entry, dict):
            raise DynamicTariffResponseError(f"{label} holds something that is not a price.")
        unit = str(entry.get("unit") or "").strip()
        if unit == BILLABLE_UNIT:
            if price is not None:
                raise DynamicTariffResponseError(
                    f"{label} carries more than one {BILLABLE_UNIT} price; which one applies is undefined."
                )
            price = _price(entry.get("value"), label=f"{label}[{index}].value")
        elif unit:
            dropped.append(unit)
        elif "value" in entry:
            dropped.append("<missing unit>")
    return price, dropped


def _dropped_unit_warnings(
    tariff_type: str, units: set[str], *, demand_prefix: str = "CHF_kW_", reactive: str = "CHF_kVarh",
) -> list[str]:
    """Say which priced units were left behind, once per response (v2 passes its slash spellings)."""
    warnings = []
    demand = sorted(u for u in units if u.startswith(demand_prefix))
    if demand:
        warnings.append(UiNotice.of(
            "series_demand_omitted",
            "The {tariff_type} series also publishes a demand charge ({units}) "
            "which is not billed: OpenZEV does not meter demand.",
            tariff_type=tariff_type, units=", ".join(demand),
        ))
    if reactive in units:
        warnings.append(UiNotice.of(
            "series_reactive_omitted",
            f"The {{tariff_type}} series also publishes a reactive-energy charge ({reactive}) which is not billed.",
            tariff_type=tariff_type,
        ))
    if "<missing unit>" in units:
        warnings.append(UiNotice.of(
            "series_unit_missing",
            "The {tariff_type} series contains a price with no unit; it was not billed.",
            tariff_type=tariff_type,
        ))
    fixed = sorted(
        u for u in units
        if u not in {reactive, "<missing unit>"} and not u.startswith(demand_prefix)
    )
    if fixed:
        warnings.append(UiNotice.of(
            "series_fixed_omitted",
            "The {tariff_type} series also publishes a fixed charge ({units}) which is not "
            "billed here: add it as a monthly or yearly fee tariff, which does not need a time series.",
            tariff_type=tariff_type, units=", ".join(fixed),
        ))
    return warnings


def parse_tariff_response(payload: object, *, tariff_type: str) -> ParsedSeries:
    """Read one response into price points for ``tariff_type``.

    An interval that does not carry the requested tariff type at all is skipped
    rather than refused: the standard says a type may simply be absent, and an
    endpoint may omit an interval entirely when its own source has no value.
    Detecting those holes is the caller's job — see ``fetch.coverage_gaps`` —
    because only the caller knows which window was asked for.
    """
    if tariff_type not in TARIFF_TYPES:
        raise DynamicTariffResponseError(f"Unknown tariff type {tariff_type!r}.")
    if not isinstance(payload, dict):
        raise DynamicTariffResponseError("The response is not a JSON object.")

    raw_prices = payload.get("prices")
    if raw_prices is None:
        raise DynamicTariffResponseError("The response has no 'prices'.")
    if not isinstance(raw_prices, list):
        raise DynamicTariffResponseError("The response's 'prices' is not a list.")

    series = ParsedSeries(publication_timestamp=_publication_timestamp(payload.get("publication_timestamp")))
    dropped_units: set[str] = set()

    for index, raw in enumerate(raw_prices):
        if not isinstance(raw, dict):
            raise DynamicTariffResponseError(f"Price entry {index} is not an object.")
        valid_from = parse_timestamp(raw.get("start_timestamp"), label=f"prices[{index}].start_timestamp")
        valid_to = parse_timestamp(raw.get("end_timestamp"), label=f"prices[{index}].end_timestamp")
        if valid_to <= valid_from:
            _reject_interval(index, valid_from, valid_to)
        price, dropped = _billable_value(
            raw.get(tariff_type), tariff_type=tariff_type, label=f"prices[{index}].{tariff_type}",
        )
        dropped_units.update(dropped)
        if price is None:
            continue
        series.points.append(PricePoint(valid_from=valid_from, valid_to=valid_to, price_chf_per_kwh=price))

    series.points.sort(key=lambda point: point.valid_from)
    _reject_overlaps(series.points)
    series.warnings.extend(_dropped_unit_warnings(tariff_type, dropped_units))
    return series


def _reject_interval(index: int, valid_from: datetime, valid_to: datetime) -> None:
    params = {"start": valid_from.isoformat(), "end": valid_to.isoformat()}
    raise DynamicTariffResponseError(
        "Price entry {index} ends at or before it starts ({start} → {end}).".format(index=index, **params),
        code="price_interval_invalid", params=params,
    )


def _reject_overlaps(points: list[PricePoint]) -> None:
    """Two prices covering the same instant is not a hole we can paper over."""
    for earlier, later in zip(points, points[1:]):
        if later.valid_from < earlier.valid_to:
            params = {
                "start": earlier.valid_from.isoformat(), "end": earlier.valid_to.isoformat(),
                "other_start": later.valid_from.isoformat(), "other_end": later.valid_to.isoformat(),
            }
            raise DynamicTariffResponseError(
                "Two price intervals overlap ({start} → {end} and {other_start} → {other_end}); "
                "which price applies is undefined.".format(**params),
                code="price_intervals_overlap", params=params,
            )
