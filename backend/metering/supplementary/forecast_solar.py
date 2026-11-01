"""forecast.solar as a forecast provider (SPEC-2026-live-energy-data §6.3).

``GET {base}[/{api_key}]/estimate/watts/{lat}/{lon}/{tilt}/{azimuth}/{kwp}`` answers one plane per call, so a
plant with n planes costs n calls. The public tier (no key) allows 12 calls per rolling hour per calling IP,
one plane per call, today and tomorrow, at one-hour resolution. Only rounded coordinates leave the instance.

The client is as defensive as the Solar Manager one: one fixed host, no redirects, a short timeout, a response
size cap, and no vendor text in any error shown to a user.
"""

from __future__ import annotations

import json
import logging
import socket
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone as dt_timezone
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings

from ..live import store
from ..live.forecast_hours import ForecastHour, sum_hours, to_hours
from .providers import ForecastDeferred, ProviderError, ProviderRateLimited

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT_S = 20
MAX_RESPONSE_BYTES = 1024 * 1024
UNREACHABLE = "forecast.solar could not be reached. Try again later."
UNREADABLE = "forecast.solar sent a response that could not be read."
NO_SETUP = "Add the roof planes of the plant and the building's coordinates to get a forecast."
TOO_MANY_PLANES = (
    "This plant has more roof planes than the forecast.solar call budget of this instance allows per hour. "
    "A forecast.solar key (FORECAST_SOLAR_API_KEY) and a higher FORECAST_SOLAR_MAX_CALLS_PER_HOUR fix this."
)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _round_coordinate(value) -> str:
    """Two decimals (about a kilometre): the precise location stays on this instance."""
    return f"{Decimal(value):.2f}"


class ForecastSolarClient:
    """Stateless HTTP; knows nothing about sources."""

    @property
    def base_url(self) -> str:
        return settings.FORECAST_SOLAR_BASE_URL.rstrip("/")

    def estimate_watts(self, *, latitude, longitude, tilt: int, azimuth: int, kwp) -> dict:
        key = settings.FORECAST_SOLAR_API_KEY
        path = "/".join(
            part for part in (
                urllib.parse.quote(key, safe="") if key else "", "estimate", "watts",
                _round_coordinate(latitude), _round_coordinate(longitude), str(int(tilt)), str(int(azimuth)),
                f"{Decimal(kwp):.2f}",
            ) if part
        )
        request = urllib.request.Request(
            f"{self.base_url}/{path}",
            headers={"Accept": "application/json", "User-Agent": "OpenZEV/1.0 (+https://github.com/splattner/openzev)"},
        )
        opener = urllib.request.build_opener(_NoRedirect)
        try:
            with opener.open(request, timeout=REQUEST_TIMEOUT_S) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            raise self._http_error(exc) from None
        except (urllib.error.URLError, socket.timeout, TimeoutError, OSError, ValueError) as exc:
            logger.warning("forecast.solar request failed: %s", type(exc).__name__)
            raise ProviderError(UNREACHABLE) from None
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ProviderError("forecast.solar sent an unexpectedly large response.")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise ProviderError(UNREADABLE) from None
        if not isinstance(payload, dict):
            raise ProviderError(UNREADABLE)
        return payload

    @staticmethod
    def _http_error(exc: urllib.error.HTTPError) -> ProviderError:
        if exc.code == 429:
            wait = 0
            for header in ("Retry-After", "X-Ratelimit-Reset"):
                try:
                    wait = int(exc.headers.get(header, "") or 0)
                except (TypeError, ValueError):
                    wait = 0
                if wait:
                    break
            return ProviderRateLimited(
                "forecast.solar is limiting requests. It will be tried again later.", retry_after=max(0, min(wait, 3600))
            )
        if exc.code == 503:
            return ProviderError("forecast.solar is in maintenance. It will be tried again later.")
        if 500 <= exc.code < 600:
            return ProviderError(UNREACHABLE)
        if 300 <= exc.code < 400:
            return ProviderError("forecast.solar answered with a redirect, which is not followed.")
        return ProviderError(f"forecast.solar refused the request (HTTP {exc.code}).")


def map_watts(payload, *, now: datetime | None = None) -> list[ForecastHour]:
    """One plane's ``estimate/watts`` answer as UTC hours.

    ``result.watts`` maps local timestamps (``message.info.timezone``) to the mean power since the previous
    key, so a key marks the *end* of the interval it covers.
    """
    if not isinstance(payload, dict) or not isinstance(payload.get("result"), dict):
        raise ProviderError(UNREADABLE)
    info = (payload.get("message") or {}).get("info") if isinstance(payload.get("message"), dict) else None
    zone_name = info.get("timezone") if isinstance(info, dict) else None
    try:
        zone = ZoneInfo(zone_name) if isinstance(zone_name, str) and zone_name else None
    except (ZoneInfoNotFoundError, ValueError):
        zone = None
    if zone is None:
        raise ProviderError(UNREADABLE)
    watts = payload["result"].get("watts", payload["result"])
    if not isinstance(watts, dict):
        raise ProviderError(UNREADABLE)
    samples = []
    for stamp, value in watts.items():
        try:
            instant = datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S").replace(tzinfo=zone).astimezone(dt_timezone.utc)
        except (TypeError, ValueError):
            continue
        if value is None or isinstance(value, bool) or not isinstance(value, (int, float, str)):
            continue
        try:
            power = Decimal(str(value))
        except InvalidOperation:
            continue
        if not power.is_finite() or abs(power) > settings.LIVE_MAX_ABS_POWER_W:
            continue
        samples.append((instant, power, None, None))
    return to_hours(samples, marks="end")


class ForecastSolarProvider:
    def __init__(self, client: ForecastSolarClient | None = None):
        self.client = client or ForecastSolarClient()

    def fetch_forecast(self, source) -> list[ForecastHour]:
        """The summed forecast of every plane of the source's plant.

        Raises ``ForecastDeferred`` (nothing called) when the planes do not fit the hourly call budget.
        """
        point = source.metering_point
        building = point.building
        planes = list(point.pv_planes.all())
        if not planes or building.latitude is None or building.longitude is None:
            raise ProviderError(NO_SETUP)
        if len(planes) > settings.FORECAST_SOLAR_MAX_CALLS_PER_HOUR:
            raise ProviderError(TOO_MANY_PLANES)
        if not store.take_forecast_solar_calls(len(planes)):
            raise ForecastDeferred()
        series = []
        for plane in planes:
            try:
                payload = self.client.estimate_watts(
                    latitude=building.latitude, longitude=building.longitude, tilt=plane.tilt_deg,
                    azimuth=plane.azimuth_deg, kwp=plane.peak_power_kwp,
                )
            except ProviderRateLimited as exc:
                store.set_forecast_solar_backoff(exc.retry_after or 3600)
                raise
            series.append(map_watts(payload))
        return sum_hours(series)

