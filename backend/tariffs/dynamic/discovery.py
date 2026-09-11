"""Discover a dynamic endpoint's protocol version, choices, and capabilities."""

from __future__ import annotations

from dataclasses import dataclass

from ..importers.remote import TariffFetchError, fetch_tariff_document
from .adapters import DynamicApiVersion, DynamicRequestMode, FetchWindow, request_url
from .protocol import (
    DiscoveredComponent,
    detect_api_version,
    discover_components,
    parse_tariff_response,
    possible_components,
)
from .vse_v1 import DynamicTariffResponseError


@dataclass(frozen=True)
class EndpointDiscovery:
    api_version: str
    components: list[DiscoveredComponent]
    version_detected: bool = True
    components_discovered: bool = True


@dataclass(frozen=True)
class SourceCapabilities:
    api_version: str
    request_mode: str
    query_tariff_type: str
    supports_range: bool
    points: list
    warnings: list[str]


def _read_version(payload: object, requested_version: str | None) -> tuple[str, bool]:
    detected = None
    try:
        detected = detect_api_version(payload)
    except DynamicTariffResponseError:
        if not requested_version:
            raise
    if requested_version and detected and requested_version != detected:
        raise DynamicTariffResponseError(
            f"The endpoint responds with {DynamicApiVersion(detected).label}, not "
            f"{DynamicApiVersion(requested_version).label}."
        )
    return requested_version or detected, detected is not None


def discover_endpoint(url: str, *, api_version: str | None = None) -> EndpointDiscovery:
    """Fetch the unfiltered endpoint and list billable component/product pairs."""

    payload, _digest = fetch_tariff_document(url)
    version, version_detected = _read_version(payload, api_version)
    components = discover_components(payload, version)
    if not components:
        if api_version and isinstance(payload, dict) and payload.get("prices") == []:
            components = possible_components(version)
            return EndpointDiscovery(
                api_version=version,
                components=components,
                version_detected=False,
                components_discovered=False,
            )
        raise DynamicTariffResponseError("The endpoint returned no billable CHF/kWh energy component.")
    return EndpointDiscovery(
        api_version=version,
        components=components,
        version_detected=version_detected,
        components_discovered=True,
    )


def probe_source_configuration(
    url: str,
    *,
    api_version: str,
    tariff_type: str,
    tariff_name: str = "",
) -> SourceCapabilities:
    """Validate one choice and infer request behavior without VNB-specific code."""

    discovery = discover_endpoint(url, api_version=api_version)
    matching = [item for item in discovery.components if item.tariff_type == tariff_type]
    if api_version == DynamicApiVersion.V2_0_0 and tariff_name:
        matching = [item for item in matching if item.tariff_name == tariff_name]
    if not matching:
        raise DynamicTariffResponseError(
            "The selected price component is not available from this endpoint."
        )

    spellings = [tariff_type]
    hyphenated = tariff_type.replace("_", "-")
    if hyphenated != tariff_type:
        spellings.append(hyphenated)

    selected_payload = None
    query_tariff_type = ""
    for spelling in spellings:
        try:
            candidate_url = request_url(
                url,
                request_mode=DynamicRequestMode.STANDARD,
                query_tariff_type=spelling,
                tariff_name=tariff_name,
            )
            payload, _digest = fetch_tariff_document(candidate_url)
            _read_version(payload, api_version)
            series = parse_tariff_response(payload, api_version=api_version, tariff_type=tariff_type)
        except (TariffFetchError, DynamicTariffResponseError):
            continue
        selected_payload = payload
        query_tariff_type = spelling
        break

    if selected_payload is None:
        if tariff_name:
            raise DynamicTariffResponseError(
                "The endpoint does not accept the selected product name."
            )
        payload, _digest = fetch_tariff_document(url)
        series = parse_tariff_response(payload, api_version=api_version, tariff_type=tariff_type)
        if not series.points:
            raise DynamicTariffResponseError(
                "The exact endpoint URL returned no prices for the selected component."
            )
        return SourceCapabilities(
            api_version=api_version,
            request_mode=DynamicRequestMode.EXACT_URL,
            query_tariff_type="",
            supports_range=False,
            points=series.points,
            warnings=series.warnings,
        )

    supports_range = False
    if series.points:
        sample = series.points[0]
        try:
            ranged_url = request_url(
                url,
                request_mode=DynamicRequestMode.STANDARD,
                query_tariff_type=query_tariff_type,
                tariff_name=tariff_name,
                window=FetchWindow(sample.valid_from, sample.valid_to),
            )
            ranged_payload, _digest = fetch_tariff_document(ranged_url)
            _read_version(ranged_payload, api_version)
            ranged_series = parse_tariff_response(
                ranged_payload, api_version=api_version, tariff_type=tariff_type
            )
            # A server that silently ignores range parameters is not range
            # capable. Both VSE versions permit at most the immediately
            # adjacent interval around the requested boundary.
            supports_range = bool(ranged_series.points) and len(ranged_series.points) <= 3 and all(
                point.valid_to >= sample.valid_from and point.valid_from <= sample.valid_to
                for point in ranged_series.points
            )
        except (TariffFetchError, DynamicTariffResponseError):
            pass

    return SourceCapabilities(
        api_version=api_version,
        request_mode=DynamicRequestMode.STANDARD,
        query_tariff_type=query_tariff_type,
        supports_range=supports_range,
        points=series.points,
        warnings=series.warnings,
    )
