"""Providers: how a source's data reaches OpenZEV (SPEC §6.1).

A pull provider verifies a credential and, from PR 3 on, fetches intervals. The
push provider has no entry here: it delivers through the ingest endpoint.

A provider module registers itself on import (``solar_manager``); ``MeteringConfig.ready()`` imports it. Creating a
source for a provider that is not registered is refused, so a half-built
integration cannot be connected.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Iterator, NamedTuple, Protocol


class ProviderError(Exception):
    """A problem talking to the vendor. The message is safe to show the participant."""


class ProviderAuthError(ProviderError):
    """The vendor rejected the credential: the participant has to enter a key again."""


class ProviderRateLimited(ProviderError):
    """The vendor asked us to slow down. ``retry_after`` is its advice in seconds (0 when it gave none)."""

    def __init__(self, message: str, retry_after: int = 0):
        super().__init__(message)
        self.retry_after = retry_after


class Point(NamedTuple):
    """One interval as a provider reports it: an aware UTC interval *start* and four flows in kWh."""

    timestamp: datetime
    consumption_kwh: Decimal
    production_kwh: Decimal
    import_kwh: Decimal
    export_kwh: Decimal


class Provider(Protocol):
    def verify(self, external_id: str, credential: str) -> str:
        """Check a credential against the vendor and return the one to store.

        Vendors that rotate refresh tokens return the new token; the caller
        stores what this returns, never the value it passed in. Raises
        ``ProviderAuthError`` when the vendor rejects the key and
        ``ProviderError`` for anything else, with a participant-safe message.
        """

    def check(self, source) -> None:
        """Exchange the stored credential and read one hour, persisting a rotated token.

        Raises the same errors as ``fetch``. Used by the "test connection" action.
        """

    def fetch(self, source, start: datetime, end: datetime) -> Iterator[list[Point]]:
        """Yield the points of ``[start, end)`` in chunks, oldest first.

        A caller stores each chunk before asking for the next, so an interrupted run
        resumes. Errors are the same as for ``verify``; ``ProviderRateLimited`` carries the
        vendor's ``Retry-After``.
        """


PROVIDERS: dict[str, Provider] = {}
