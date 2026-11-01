"""Solar Manager as a pull provider (SPEC §6.2, ADR 0031).

Talks to ``/v3`` of the vendor's cloud API:

* ``POST /v3/auth/refresh`` exchanges the participant's API key (a refresh token) for a
  one-hour bearer token. With key rotation on, the response carries a *new* refresh token
  and the old one is dead from that moment, so the new one is persisted, under a row lock,
  before the bearer token is used.
* ``GET /v3/users/{smId}/data/range?from=&to=&interval=900`` returns the 15-minute series.
* ``GET /v3/users/{smId}/data/stream`` returns the current power, for the live view
  (SPEC-2026-live-energy-data §6.1).
* ``GET /v3/users/{smId}/data/forecast`` returns the production forecast for the next days
  (SPEC-2026-live-energy-data §6.3).

History reads only the four measured flows (``cWh``, ``pWh``, ``iWh``, ``eWh``); the vendor's
derived ``cPvWh`` / ``scWh`` and the ``*W`` power fields are ignored there. The live stream reads
``t``, ``iW``, ``eW``, ``pW`` and ``cW`` and nothing else.

The client is deliberately small and defensive: one fixed host, no redirects, a short
timeout, a response-size cap, the ``smId`` validated before it enters a URL, and no vendor
text in any error shown to the participant.
"""

from __future__ import annotations

import json
import logging
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone as dt_timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Iterator

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from allocation.validity import civil_date, period_end_exclusive_dt, period_start_dt

from ..live import store
from ..live.forecast_hours import ForecastHour, to_hours
from ..live.store import LiveSample
from ..models import SOLAR_MANAGER_ID_RE, SupplementarySource
from .crypto import IntegrationKeyError, IntegrationNotConfigured, decrypt_secret, encrypt_secret
from .providers import PROVIDERS, Point, ProviderAuthError, ProviderError, ProviderRateLimited
from .stats import INTERVAL, INTERVAL_S

logger = logging.getLogger(__name__)

#: ``t`` marks the *start* of its interval, like ``MeterReading.timestamp``. Verified against
#: a real meter day on 2026-10-08 (SPEC §6.2); reconciliation keeps checking it. A vendor
#: change would be a one-line fix here.
T_MARKS_INTERVAL = "start"
_T_OFFSET = {"start": timedelta(0), "end": -INTERVAL}[T_MARKS_INTERVAL]

REQUEST_TIMEOUT_S = 20
MAX_RESPONSE_BYTES = 2 * 1024 * 1024  # a day at 15 minutes is ~15 KB; this is two orders of magnitude of headroom
#: The vendor documents neither a rate limit nor a maximum range. One civil day per request,
#: sequentially, with a short pause, is conservative on both counts.
PAUSE_BETWEEN_REQUESTS_S = 0.25
#: An access token lives an hour; renew well before so a long backfill never sends an expired one.
ACCESS_TOKEN_MAX_AGE = timedelta(minutes=45)
#: The bearer token lives an hour; the live cache keeps it a little less, so a cached one is never
#: sent when it is about to expire (SPEC-2026-live-energy-data §4.4).
LIVE_ACCESS_CACHE_S = 50 * 60
#: Below this, a negative Wh value is sensor noise rather than data and is read as zero.
NOISE_WH = Decimal("5")

WH_TO_KWH = Decimal("1000")
QUANTUM = Decimal("0.0001")
FIELD_MAP = {
    "cWh": "consumption_kwh",
    "pWh": "production_kwh",
    "iWh": "import_kwh",
    "eWh": "export_kwh",
}

UNREACHABLE = "Solar Manager could not be reached. Try again later."
REJECTED_KEY = "Solar Manager did not accept this API key."
DENIED = "Solar Manager denied access to this installation. Check the Solar Manager id and the API key."


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class SolarManagerClient:
    """Stateless HTTP calls; knows nothing about sources or storage."""

    def __init__(self, base_url: str | None = None):
        self._base_url = base_url

    @property
    def base_url(self) -> str:
        return (self._base_url or settings.SOLAR_MANAGER_BASE_URL).rstrip("/")

    def _request(self, method: str, path: str, *, query: dict | None = None, body: dict | None = None,
                 bearer: str | None = None, auth_codes: tuple[int, ...] = (401, 403, 404)) -> dict:
        url = self.base_url + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        headers = {"Accept": "application/json", "User-Agent": "OpenZEV/1.0 (+https://github.com/splattner/openzev)"}
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if bearer:
            headers["Authorization"] = f"Bearer {bearer}"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        opener = urllib.request.build_opener(_NoRedirect)
        try:
            with opener.open(request, timeout=REQUEST_TIMEOUT_S) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            raise self._http_error(exc, auth_codes) from None
        except (urllib.error.URLError, socket.timeout, TimeoutError, OSError, ValueError) as exc:
            # Never the exception text: it can carry hosts, paths and library detail.
            logger.warning("Solar Manager request failed: %s", type(exc).__name__)
            raise ProviderError(UNREACHABLE) from None
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ProviderError("Solar Manager sent an unexpectedly large response.")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise ProviderError("Solar Manager sent a response that could not be read.") from None
        if not isinstance(payload, dict):
            raise ProviderError("Solar Manager sent a response that could not be read.")
        return payload

    @staticmethod
    def _http_error(exc: urllib.error.HTTPError, auth_codes: tuple[int, ...]) -> ProviderError:
        code = exc.code
        if code == 429:
            try:
                wait = int(exc.headers.get("Retry-After", "") or 0)
            except (TypeError, ValueError):
                wait = 0
            return ProviderRateLimited("Solar Manager is limiting requests. It will be tried again later.",
                                       retry_after=max(0, min(wait, 3600)))
        if 300 <= code < 400:
            return ProviderError("Solar Manager answered with a redirect, which is not followed.")
        if code in auth_codes:
            return ProviderAuthError(DENIED)
        if 500 <= code < 600:
            return ProviderError(UNREACHABLE)
        return ProviderError(f"Solar Manager refused the request (HTTP {code}).")

    # ---- calls ----

    def refresh(self, refresh_token: str) -> tuple[str, str]:
        """Exchange ``refresh_token``. Returns ``(access_token, refresh_token_to_keep)``.

        The second value is the new refresh token when the vendor rotates, otherwise the old one.
        """
        try:
            # 400 is the vendor's answer to a malformed or unknown token.
            payload = self._request(
                "POST", "/v3/auth/refresh", body={"grant_type": "refresh_token", "refresh_token": refresh_token},
                auth_codes=(400, 401, 403),
            )
        except ProviderAuthError:
            raise ProviderAuthError(REJECTED_KEY) from None
        access = payload.get("access_token")
        if not isinstance(access, str) or not access:
            raise ProviderError("Solar Manager sent a response that could not be read.")
        rotated = payload.get("refresh_token")
        return access, rotated if isinstance(rotated, str) and rotated else refresh_token

    def range(self, access_token: str, sm_id: str, start: datetime, end: datetime) -> list[Point]:
        """The 15-minute points whose interval starts in ``[start, end)``."""
        _check_sm_id(sm_id)
        payload = self._request(
            "GET",
            f"/v3/users/{urllib.parse.quote(sm_id, safe='')}/data/range",
            query={"from": _iso(start), "to": _iso(end), "interval": INTERVAL_S},
            bearer=access_token,
        )
        return map_points(payload.get("data"), start, end)

    def stream(self, access_token: str, sm_id: str) -> dict:
        """The vendor's current-power payload, unmapped (see ``map_stream``)."""
        _check_sm_id(sm_id)
        return self._request(
            "GET", f"/v3/users/{urllib.parse.quote(sm_id, safe='')}/data/stream", bearer=access_token
        )

    def forecast(self, access_token: str, sm_id: str) -> dict:
        """The vendor's production forecast for the next days, unmapped (see ``map_forecast``)."""
        _check_sm_id(sm_id)
        return self._request(
            "GET", f"/v3/users/{urllib.parse.quote(sm_id, safe='')}/data/forecast", bearer=access_token
        )


def _check_sm_id(sm_id: str) -> None:
    if not SOLAR_MANAGER_ID_RE.match(sm_id or ""):
        raise ProviderAuthError("A Solar Manager id has 3 to 24 letters or digits.")


def _iso(value: datetime) -> str:
    return value.astimezone(dt_timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _kwh(raw) -> Decimal | None:
    """A Wh figure as kWh to the stored four decimals, ``None`` when missing or unreadable."""
    if raw is None or isinstance(raw, bool):
        return None
    try:
        wh = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None
    if not wh.is_finite():
        return None
    if wh < 0 and wh > -NOISE_WH:
        wh = Decimal(0)
    return (wh / WH_TO_KWH).quantize(QUANTUM, rounding=ROUND_HALF_UP)


def map_points(data, start: datetime, end: datetime) -> list[Point]:
    """Vendor rows to ``Point``s. A row with a missing flow is skipped: a gap, never a zero."""
    if not isinstance(data, list):
        return []
    points: dict[datetime, Point] = {}
    for row in data:
        if not isinstance(row, dict) or not isinstance(row.get("t"), str):
            continue
        try:
            stamp = parse_datetime(row["t"])
        except ValueError:
            stamp = None
        if stamp is None or stamp.tzinfo is None:
            continue
        stamp = stamp.astimezone(dt_timezone.utc) + _T_OFFSET
        if not (start <= stamp < end):
            continue
        values = {name: _kwh(row.get(field)) for field, name in FIELD_MAP.items()}
        if any(value is None for value in values.values()):
            continue
        points[stamp] = Point(timestamp=stamp, **values)
    return [points[stamp] for stamp in sorted(points)]


TENTH = Decimal("0.1")
NO_STREAM_SAMPLE = "Solar Manager sent no usable power reading."


def _watts(raw, *, required: bool) -> Decimal | None:
    """A power in W to one decimal. ``None`` when an optional figure is missing or not a number.

    A required figure that is missing or not a number, or any figure that is not finite or beyond
    ``LIVE_MAX_ABS_POWER_W``, makes the whole payload unusable: a power is never invented.
    """
    value = None
    if raw is not None and not isinstance(raw, bool) and isinstance(raw, (int, float, str)):
        try:
            value = Decimal(str(raw).strip())
        except InvalidOperation:
            value = None
    if value is None:
        if required:
            raise ProviderError(NO_STREAM_SAMPLE)
        return None
    if not value.is_finite() or abs(value) > settings.LIVE_MAX_ABS_POWER_W:
        raise ProviderError(NO_STREAM_SAMPLE)
    return value


def map_stream(payload, source_id: str, now: datetime | None = None) -> LiveSample:
    """The vendor's stream payload to a ``LiveSample`` (SPEC-2026-live-energy-data §6.1).

    ``meter_power_w = iW - eW`` (positive drawn in, negative fed out), ``production_w = pW`` and
    ``consumption_w = cW``; battery and device fields are ignored. A missing or unreadable ``iW`` or
    ``eW`` raises ``ProviderError``: there is no sample rather than a zero. A gross figure that is
    missing or negative is left out. ``t`` that is missing, naive or unreadable falls back to ``now``,
    and one in the future is held at ``now``.
    """
    if not isinstance(payload, dict):
        raise ProviderError(NO_STREAM_SAMPLE)
    now = now or timezone.now()
    imported = _watts(payload.get("iW"), required=True)
    exported = _watts(payload.get("eW"), required=True)
    production = _watts(payload.get("pW"), required=False)
    consumption = _watts(payload.get("cW"), required=False)
    stamp = None
    if isinstance(payload.get("t"), str):
        try:
            stamp = parse_datetime(payload["t"])
        except ValueError:
            stamp = None
    if stamp is None or stamp.tzinfo is None:
        stamp = now
    stamp = min(stamp.astimezone(dt_timezone.utc), now)
    return LiveSample(
        source_id=str(source_id),
        timestamp=stamp,
        received_at=now,
        meter_power_w=(imported - exported).quantize(TENTH, rounding=ROUND_HALF_UP),
        production_w=production.quantize(TENTH, rounding=ROUND_HALF_UP) if production is not None and production >= 0 else None,
        consumption_w=consumption.quantize(TENTH, rounding=ROUND_HALF_UP) if consumption is not None and consumption >= 0 else None,
    )


#: What ``t`` of a forecast row stands for. Taken from the vendor's swagger (API 1.88.11); not yet checked
#: against a real response, as the history timestamps were (SPEC-2026-live-energy-data §6.3). A one-line fix.
FORECAST_T_MARKS = "start"
NO_FORECAST = "Solar Manager sent no usable production forecast."


def map_forecast(payload) -> list[ForecastHour]:
    """The vendor's forecast payload (``data[]`` of ``{t, pW, pWmin, pWmax}``) as UTC hours.

    A row without a readable ``t`` or ``pW`` is skipped; the band (``pWmin``/``pWmax``) is optional. A value
    beyond ``LIVE_MAX_ABS_POWER_W`` rejects the whole payload. No usable row at all is an error, never an
    empty forecast.
    """
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        raise ProviderError(NO_FORECAST)
    samples = []
    for row in data:
        if not isinstance(row, dict) or not isinstance(row.get("t"), str):
            continue
        try:
            stamp = parse_datetime(row["t"])
        except ValueError:
            stamp = None
        if stamp is None or stamp.tzinfo is None:
            continue
        power = _watts(row.get("pW"), required=False)
        if power is None:
            continue
        samples.append((stamp.astimezone(dt_timezone.utc), power, _watts(row.get("pWmin"), required=False),
                        _watts(row.get("pWmax"), required=False)))
    hours = to_hours(samples, marks=FORECAST_T_MARKS)
    if not hours:
        raise ProviderError(NO_FORECAST)
    return hours


def civil_days(start: datetime, end: datetime) -> Iterator[tuple[datetime, datetime]]:
    """``[start, end)`` cut at Swiss midnights. A DST day is 92 or 100 intervals long, not 96."""
    day: date = civil_date(start)
    while True:
        lo = max(start, period_start_dt(day))
        hi = min(end, period_end_exclusive_dt(day))
        if lo >= hi:
            return
        yield lo, hi
        day += timedelta(days=1)


class SolarManagerProvider:
    def __init__(self, client: SolarManagerClient | None = None, pause: float | None = None):
        self.client = client or SolarManagerClient()
        self._pause = pause

    @property
    def pause(self) -> float:
        return PAUSE_BETWEEN_REQUESTS_S if self._pause is None else self._pause

    # ---- credential ----

    def verify(self, external_id: str, credential: str) -> str:
        """Exchange the key and read one hour, before anything is stored (SPEC §5).

        Returns the refresh token to keep, which is a new one when the vendor rotates.
        """
        access, keep = self.client.refresh(credential)
        end = _floor_quarter(datetime.now(dt_timezone.utc))
        self.client.range(access, external_id, end - timedelta(hours=1), end)
        return keep

    def verify_live(self, external_id: str, credential: str) -> str:
        """Like ``verify``, for a source that only provides live data: one stream reading, not a history hour."""
        access, keep = self.client.refresh(credential)
        map_stream(self.client.stream(access, external_id), "verify")
        return keep

    def _access_token(self, source: SupplementarySource) -> str:
        """Exchange the stored key for a bearer token, persisting a rotated key first (ADR 0031).

        Runs under a row lock so two workers can never both spend the same refresh token. The
        new token is saved before the bearer token is returned, and a failure to save is a
        failed refresh, because the old token is already dead.
        """
        with transaction.atomic():
            locked = SupplementarySource.objects.select_for_update().get(pk=source.pk)
            try:
                token = locked.credential
            except (IntegrationKeyError, IntegrationNotConfigured):
                raise ProviderAuthError(
                    "The stored Solar Manager key can no longer be read. Enter the API key again."
                ) from None
            if not token:
                raise ProviderAuthError("No Solar Manager API key is stored. Enter it again.")
            access, keep = self.client.refresh(token)
            if keep != token:
                locked.set_credential(keep)
                locked.save(update_fields=["credential_encrypted", "updated_at"])
        source.credential_encrypted = locked.credential_encrypted
        return access

    def check(self, source: SupplementarySource) -> None:
        access = self._access_token(source)
        end = _floor_quarter(datetime.now(dt_timezone.utc))
        self.client.range(access, source.external_id, end - timedelta(hours=1), end)

    def check_live(self, source: SupplementarySource) -> None:
        """Read one stream sample with the stored key, through the bearer cache like a poll."""
        self.fetch_live(source)

    # ---- live ----

    @staticmethod
    def _cached_access(source_id) -> str | None:
        raw = store.get_sm_access(source_id)
        if not raw:
            return None
        try:
            return decrypt_secret(raw.encode("ascii"))
        except (IntegrationKeyError, IntegrationNotConfigured, UnicodeEncodeError):
            store.drop_sm_access(source_id)
            return None

    @staticmethod
    def _cache_access(source_id, access: str) -> None:
        try:
            store.set_sm_access(source_id, encrypt_secret(access).decode("ascii"), LIVE_ACCESS_CACHE_S)
        except IntegrationNotConfigured:  # cannot encrypt, so do not cache: the next poll exchanges again
            pass

    def _fresh_access(self, source: SupplementarySource) -> str:
        access = self._access_token(source)
        self._cache_access(source.pk, access)
        return access

    def _with_access(self, source: SupplementarySource, call):
        """``call(access_token)`` with the cached bearer token.

        The cache means a 30-second poll does not spend (and rotate) the refresh token every time. When the
        vendor refuses a cached token it is dropped and one fresh exchange is tried before the failure counts
        as an auth failure.
        """
        _check_sm_id(source.external_id)
        access = self._cached_access(source.pk)
        cached = access is not None
        if access is None:
            access = self._fresh_access(source)
        try:
            return call(access)
        except ProviderAuthError:
            if not cached:
                raise
            store.drop_sm_access(source.pk)
            return call(self._fresh_access(source))

    def fetch_live(self, source: SupplementarySource) -> LiveSample:
        """One current-power sample (SPEC-2026-live-energy-data §6.1)."""
        payload = self._with_access(source, lambda access: self.client.stream(access, source.external_id))
        return map_stream(payload, str(source.pk))

    def fetch_forecast(self, source: SupplementarySource) -> list[ForecastHour]:
        """The hourly production forecast of the installation (SPEC-2026-live-energy-data §6.3)."""
        payload = self._with_access(source, lambda access: self.client.forecast(access, source.external_id))
        return map_forecast(payload)

    def check_forecast(self, source: SupplementarySource) -> None:
        self.fetch_forecast(source)

    # ---- data ----

    def fetch(self, source: SupplementarySource, start: datetime, end: datetime) -> Iterator[list[Point]]:
        """Yield the points of ``[start, end)`` one civil day at a time, oldest first.

        A caller stores each chunk before asking for the next, so an interrupted run resumes.
        """
        access = self._access_token(source)
        obtained = time.monotonic()
        first = True
        for lo, hi in civil_days(start, end):
            if not first and self.pause:
                time.sleep(self.pause)
            first = False
            if time.monotonic() - obtained > ACCESS_TOKEN_MAX_AGE.total_seconds():
                access = self._access_token(source)
                obtained = time.monotonic()
            yield self.client.range(access, source.external_id, lo, hi)


def _floor_quarter(value: datetime) -> datetime:
    return value.replace(minute=value.minute - value.minute % 15, second=0, microsecond=0)


PROVIDERS["solar_manager"] = SolarManagerProvider()
