"""Generic request construction for VSE-compatible dynamic tariff APIs.

The public configuration is deliberately protocol-based: OpenZEV stores the
API version and capabilities discovered from an endpoint, never the VNB that
happens to operate it. A conforming endpoint accepts the standard query
parameters. Some endpoints only serve the URL verbatim; discovery records that
capability without teaching the application a provider name.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django.db import models


class DynamicApiVersion(models.TextChoices):
    V1_0_5 = "v1_0_5", "v1.0.5"
    V2_0_0 = "v2_0_0", "v2.0.0"


class DynamicRequestMode(models.TextChoices):
    STANDARD = "standard", "Standard query parameters"
    EXACT_URL = "exact_url", "Exact URL"


@dataclass(frozen=True)
class FetchWindow:
    """A half-open window of wall-clock time to ask an operator for."""

    start: datetime
    end: datetime


MAX_WINDOW_DAYS = 31


def request_url(
    url: str,
    *,
    request_mode: str,
    query_tariff_type: str,
    tariff_name: str = "",
    window: FetchWindow | None = None,
) -> str:
    """Build a request using capabilities measured during discovery."""

    if request_mode == DynamicRequestMode.EXACT_URL:
        if window is not None:
            raise ValueError("This endpoint does not accept a time range.")
        return url
    if request_mode != DynamicRequestMode.STANDARD:
        raise ValueError(f"Unknown dynamic tariff request mode {request_mode!r}.")

    parts = urlsplit(url)
    params = dict(parse_qsl(parts.query, keep_blank_values=True))
    params["tariff_type"] = query_tariff_type
    if tariff_name:
        params["tariff_name"] = tariff_name
    if window is not None:
        params["start_timestamp"] = window.start.isoformat()
        params["end_timestamp"] = window.end.isoformat()
    return urlunsplit(parts._replace(query=urlencode(params)))
