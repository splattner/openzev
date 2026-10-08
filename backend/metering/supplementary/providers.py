"""Providers: how a source's data reaches OpenZEV (SPEC §6.1).

A pull provider verifies a credential and, from PR 3 on, fetches intervals. The
push provider has no entry here: it delivers through the ingest endpoint.

The registry is empty until a provider module registers itself. Creating a
source for a provider that is not registered is refused, so a half-built
integration cannot be connected.
"""

from __future__ import annotations

from typing import Protocol


class ProviderError(Exception):
    """A problem talking to the vendor. The message is safe to show the participant."""


class ProviderAuthError(ProviderError):
    """The vendor rejected the credential: the participant has to enter a key again."""


class Provider(Protocol):
    def verify(self, external_id: str, credential: str) -> str:
        """Check a credential against the vendor and return the one to store.

        Vendors that rotate refresh tokens return the new token; the caller
        stores what this returns, never the value it passed in. Raises
        ``ProviderAuthError`` when the vendor rejects the key and
        ``ProviderError`` for anything else, with a participant-safe message.
        """


PROVIDERS: dict[str, Provider] = {}
