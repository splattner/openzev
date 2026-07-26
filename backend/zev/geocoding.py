"""Best-effort building-footprint lookup for participant addresses.

Calls the public OpenStreetMap Nominatim search API and caches the result
(never persisted on the model — it's a derived, best-effort artifact of an
external service, not authoritative participant data). Caching is required by
Nominatim's usage policy, which disallows repeating identical queries; keying
the cache by the normalized address also means participants who share a
building address are geocoded only once.

Nominatim is asked for the actual OSM way/relation geometry
(``polygon_geojson=1``), not just its bounding box — a building is a polygon
with angled edges, not an axis-aligned rectangle, and the bounding box alone
would misrepresent it.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = f"OpenZEV/1.0 (+{settings.FRONTEND_URL})"
REQUEST_TIMEOUT_SECONDS = 10

# A geocode result is only accepted as a building if Nominatim tags it as
# such, or its bounding box is small enough to plausibly be a single building
# rather than a street, postal code area, or whole town (the kind of coarse
# fallback match Nominatim returns for an incomplete/ambiguous address) — and
# only if it actually resolved to a mapped polygon (an OSM way/relation), not
# just a bare address point with no drawn footprint.
_BUILDING_ADDRESS_TYPES = {"building", "house"}
_BUILDING_GEOMETRY_TYPES = {"Polygon", "MultiPolygon"}
MAX_BUILDING_DIAGONAL_METERS = 150

CACHE_KEY_PREFIX = "geocode:building:"
POSITIVE_CACHE_TIMEOUT_SECONDS = 180 * 24 * 60 * 60  # ~180 days
NEGATIVE_CACHE_TIMEOUT_SECONDS = 7 * 24 * 60 * 60

# Distinguishes "no match found" (cached) from "not looked up yet" (cache miss,
# which cache.get() also reports as None) so a bad address is retried after the
# shorter negative TTL instead of the long positive one.
_NOT_FOUND = "not_found"


def _cache_key(address_line1: str, postal_code: str, city: str) -> str:
    normalized = "|".join(part.strip().casefold() for part in (address_line1, postal_code, city))
    digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()
    return f"{CACHE_KEY_PREFIX}{digest}"


def _haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    earth_radius_m = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * earth_radius_m * math.asin(math.sqrt(a))


def _is_building_scale(result: dict) -> bool:
    address_type = result.get("addresstype") or result.get("type") or ""
    if address_type in _BUILDING_ADDRESS_TYPES:
        return True

    south, north, west, east = (float(v) for v in result["boundingbox"])
    diagonal = _haversine_meters(south, west, north, east)
    return diagonal <= MAX_BUILDING_DIAGONAL_METERS


def geocode_building_footprint(address_line1: str, postal_code: str, city: str) -> dict | None:
    """Look up a building's real footprint polygon via Nominatim.

    Returns the raw GeoJSON geometry (a ``Polygon`` or ``MultiPolygon``, in
    the coordinate order GeoJSON always uses: ``[longitude, latitude]``), or
    ``None`` if nothing resolved to an actual mapped building. Never raises —
    a failed or imprecise match is treated the same as no match at all.
    """
    if not (address_line1.strip() and city.strip()):
        return None

    params = {
        "street": address_line1,
        "postalcode": postal_code,
        "city": city,
        "country": "Switzerland",
        "format": "jsonv2",
        "polygon_geojson": "1",
        "limit": "1",
    }
    url = f"{NOMINATIM_SEARCH_URL}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            results = json.loads(response.read())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        logger.warning("Nominatim lookup failed for %s, %s %s: %s", address_line1, postal_code, city, exc)
        return None

    if not results:
        return None

    result = results[0]
    try:
        geometry = result.get("geojson")
        if not geometry or geometry.get("type") not in _BUILDING_GEOMETRY_TYPES:
            return None
        if not _is_building_scale(result):
            return None
    except (KeyError, ValueError, TypeError) as exc:
        logger.warning("Unexpected Nominatim response shape for %s, %s %s: %s", address_line1, postal_code, city, exc)
        return None

    return geometry


def warm_geocode_cache(address_line1: str, postal_code: str, city: str) -> None:
    """Populate the cache for this address if it isn't already cached (hit or miss)."""
    key = _cache_key(address_line1, postal_code, city)
    if cache.get(key) is not None:
        return

    footprint = geocode_building_footprint(address_line1, postal_code, city)
    if footprint is None:
        cache.set(key, _NOT_FOUND, timeout=NEGATIVE_CACHE_TIMEOUT_SECONDS)
    else:
        cache.set(key, footprint, timeout=POSITIVE_CACHE_TIMEOUT_SECONDS)


def get_cached_building_footprint(address_line1: str, postal_code: str, city: str) -> dict | None:
    """Read-only lookup used at API serialization time — never calls Nominatim."""
    if not (address_line1 or "").strip():
        return None

    try:
        cached = cache.get(_cache_key(address_line1, postal_code, city))
    except Exception:
        logger.warning("Cache read failed for %s, %s %s", address_line1, postal_code, city, exc_info=True)
        return None
    if cached is None or cached == _NOT_FOUND:
        return None
    return cached
