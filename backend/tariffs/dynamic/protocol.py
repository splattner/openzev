"""Version detection, component discovery, and parser dispatch."""

from __future__ import annotations

from dataclasses import dataclass

from .adapters import DynamicApiVersion
from .vse_v1 import BILLABLE_UNIT as V1_BILLABLE_UNIT
from .vse_v1 import TARIFF_TYPES as V1_TARIFF_TYPES
from .vse_v1 import DynamicTariffResponseError, parse_tariff_response as parse_v1
from .vse_v2 import BILLABLE_UNIT as V2_BILLABLE_UNIT
from .vse_v2 import TARIFF_TYPES as V2_TARIFF_TYPES
from .vse_v2 import parse_tariff_response as parse_v2


@dataclass(frozen=True, order=True)
class DiscoveredComponent:
    tariff_type: str
    tariff_name: str = ""


def possible_components(api_version: str) -> list[DiscoveredComponent]:
    """Choices to offer only when an explicitly-versioned response is empty."""

    if api_version == DynamicApiVersion.V1_0_5:
        tariff_types = V1_TARIFF_TYPES
    elif api_version == DynamicApiVersion.V2_0_0:
        tariff_types = V2_TARIFF_TYPES
    else:
        raise DynamicTariffResponseError(f"Unsupported API version {api_version!r}.")
    return [DiscoveredComponent(tariff_type) for tariff_type in tariff_types if tariff_type != "refund"]


def detect_api_version(payload: object) -> str:
    """Detect v1 arrays versus v2 tariff-component objects."""

    if not isinstance(payload, dict) or not isinstance(payload.get("prices"), list):
        raise DynamicTariffResponseError("The response has no 'prices' list.")
    for price in payload["prices"]:
        if not isinstance(price, dict):
            continue
        for tariff_type in dict.fromkeys((*V1_TARIFF_TYPES, *V2_TARIFF_TYPES)):
            component = price.get(tariff_type)
            if isinstance(component, list):
                return DynamicApiVersion.V1_0_5
            if isinstance(component, dict):
                return DynamicApiVersion.V2_0_0
    raise DynamicTariffResponseError(
        "The API version cannot be detected because the response contains no tariff components. Choose a version and try again."
    )


def discover_components(payload: object, api_version: str) -> list[DiscoveredComponent]:
    if not isinstance(payload, dict) or not isinstance(payload.get("prices"), list):
        raise DynamicTariffResponseError("The response has no 'prices' list.")
    found: set[DiscoveredComponent] = set()
    if api_version == DynamicApiVersion.V1_0_5:
        for price in payload["prices"]:
            if not isinstance(price, dict):
                continue
            for tariff_type in V1_TARIFF_TYPES:
                component = price.get(tariff_type)
                if isinstance(component, list) and any(
                    isinstance(item, dict) and item.get("unit") == V1_BILLABLE_UNIT for item in component
                ):
                    found.add(DiscoveredComponent(tariff_type))
    elif api_version == DynamicApiVersion.V2_0_0:
        for price in payload["prices"]:
            if not isinstance(price, dict):
                continue
            for tariff_type in V2_TARIFF_TYPES:
                # Storage-support refunds cannot price general exported kWh.
                if tariff_type == "refund":
                    continue
                component = price.get(tariff_type)
                if not isinstance(component, dict):
                    continue
                energy = component.get("energy")
                if isinstance(energy, dict) and energy.get("unit") == V2_BILLABLE_UNIT:
                    found.add(DiscoveredComponent(tariff_type, str(component.get("tariff_name") or "")))
    else:
        raise DynamicTariffResponseError(f"Unsupported API version {api_version!r}.")
    return sorted(found)


def parse_tariff_response(payload: object, *, api_version: str, tariff_type: str, tariff_name: str = ""):
    if api_version == DynamicApiVersion.V1_0_5:
        return parse_v1(payload, tariff_type=tariff_type)
    if api_version == DynamicApiVersion.V2_0_0:
        if tariff_name and isinstance(payload, dict):
            for row in payload.get("prices", []) if isinstance(payload.get("prices"), list) else []:
                component = row.get(tariff_type) if isinstance(row, dict) else None
                if isinstance(component, dict) and component.get("tariff_name") != tariff_name:
                    raise DynamicTariffResponseError("The endpoint returned a different product than the configured tariff name.")
        return parse_v2(payload, tariff_type=tariff_type)
    raise DynamicTariffResponseError(f"Unsupported API version {api_version!r}.")
