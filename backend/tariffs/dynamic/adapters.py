"""Per-operator request adapters for the VSE dynamic tariff API.

Every operator answers with the same envelope — :mod:`vse_v1` parses that once.
What differs is the *request*: which query parameters are understood, how the
tariff type is spelled in them, and how "I have nothing for that window" comes
back. Those differences are small but real, and each one below was measured
against the live endpoint on 2026-09-11 rather than read off a document.

Adding an operator means adding one subclass here; it should not require
touching the parser, the fetcher or the model.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django.db import models


class DynamicAdapter(models.TextChoices):
    """Which operator's dialect a source speaks."""

    VSE_V1 = "vse_v1", "VSE standard (v1)"
    GROUPE_E = "groupe_e", "Groupe E"
    BKW = "bkw", "BKW"


@dataclass(frozen=True)
class FetchWindow:
    """A half-open window of wall-clock time to ask an operator for."""

    start: datetime
    end: datetime


class BaseAdapter:
    """The VSE v1 request contract, which most operators should follow.

    ``GET {url}?tariff_type=&tariff_name=&start_timestamp=&end_timestamp=``,
    where omitting the timestamps means "the current day".
    """

    key = DynamicAdapter.VSE_V1
    #: Whether the endpoint understands ``start_timestamp``/``end_timestamp``.
    #: When it does not, only the current day can ever be fetched, and history
    #: that was not captured on the day is gone for good.
    supports_range = True
    #: Longest window to ask for in one request. Groupe E's full retained
    #: history in a single call came back 5 016 921 bytes — 95.7 % of
    #: ``importers.remote.MAX_DOCUMENT_BYTES`` — so a backfill has to be walked
    #: in chunks rather than asked for at once.
    max_window_days = 31

    def tariff_type_param(self, tariff_type: str) -> str:
        """How this operator spells the tariff type in a query string."""
        return tariff_type

    def request_url(self, url: str, *, tariff_type: str, tariff_name: str = "", window: FetchWindow | None = None) -> str:
        """The URL to fetch, preserving any query the operator already put in it.

        The URL can arrive from ``prices.dynamic.url`` in a published tariff
        document, where an operator may already have pinned the product or the
        component. Parameters we set win over ones already there, because the
        source row is the configuration of record; everything else is kept.
        """
        parts = urlsplit(url)
        params = dict(parse_qsl(parts.query, keep_blank_values=True))
        params["tariff_type"] = self.tariff_type_param(tariff_type)
        if tariff_name:
            params["tariff_name"] = tariff_name
        if window is not None:
            if not self.supports_range:
                raise ValueError(f"{self.key.label} does not accept a time range.")
            params["start_timestamp"] = window.start.isoformat()
            params["end_timestamp"] = window.end.isoformat()
        return urlunsplit(parts._replace(query=urlencode(params)))


class VseV1Adapter(BaseAdapter):
    """An operator that follows the published template without deviation."""


class GroupeEAdapter(BaseAdapter):
    """Groupe E — ``https://api.tariffs.groupe-e.ch/v2/tariffs``.

    Serves ``grid`` and ``integrated`` for the products ``vario`` (the default),
    ``double``, ``project_1`` and ``project_3``, at quarter-hourly resolution,
    with roughly nine months of history and day-ahead publication in the
    afternoon.

    Two things to know. The product materially changes the money — the same
    interval quoted 0.1398 under ``vario`` and 0.1267 under ``double`` — so
    ``tariff_name`` is never left to the endpoint's default. And a range it
    holds nothing for comes back ``200 {"publication_timestamp": "", "prices": []}``,
    so an empty answer proves nothing about coverage.
    """

    key = DynamicAdapter.GROUPE_E

    def tariff_type_param(self, tariff_type: str) -> str:
        # Groupe E's query enum is hyphenated where the standard, and Groupe E's
        # own response keys, use an underscore. Measured: `tariff_type=feed_in`
        # is a 400 naming `feed-in, grid, integrated` as the allowed values.
        return "feed-in" if tariff_type == "feed_in" else tariff_type


class BkwAdapter(BaseAdapter):
    """BKW — ``https://api.bkw.ch/api/dyntariffs/v1/Tariffs/energyreturn``.

    Serves ``feed_in`` only, for the current local day, out of a cache that is
    republished during the day. Documented at
    ``https://api.bkw.ch/api/dyntariffs/swagger/v1/swagger.json``.

    It accepts **no query parameters at all** — any parameter is a 400 — so
    there is no history to backfill and nothing to filter server-side. Whatever
    is not fetched on the day is unrecoverable, which is the sharpest argument
    for storing what we fetch as billing evidence rather than as a cache.
    """

    key = DynamicAdapter.BKW
    supports_range = False

    def request_url(self, url: str, *, tariff_type: str, tariff_name: str = "", window: FetchWindow | None = None) -> str:
        if window is not None:
            raise ValueError("BKW does not accept a time range.")
        return url


_ADAPTERS: dict[str, BaseAdapter] = {
    adapter.key.value: adapter for adapter in (VseV1Adapter(), GroupeEAdapter(), BkwAdapter())
}


def adapter_for(key: str) -> BaseAdapter:
    try:
        return _ADAPTERS[key]
    except KeyError:
        raise ValueError(f"Unknown dynamic tariff adapter {key!r}.") from None
