"""Encryption for third-party integration credentials at rest.

Mirrors ``accounts/mfa_crypto.py``: a Fernet key *list* consumed through
``MultiFernet`` (the first key encrypts, every key decrypts), so a key can be
rotated without making stored credentials unreadable. The key is
``settings.INTEGRATION_ENCRYPTION_KEYS``, deliberately independent of
``SECRET_KEY``, ``MFA_ENCRYPTION_KEYS`` and ``BACKUP_ENCRYPTION_KEYS`` and never
derived from them. See ADR 0031.

A connector credential cannot be hashed (the server must send it to the vendor),
so it needs reversible encryption. There is no fallback to another key and no
plaintext path.
"""

from __future__ import annotations

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings


class IntegrationNotConfigured(Exception):
    """``INTEGRATION_ENCRYPTION_KEYS`` is empty.

    Raised at the point something would need the key, not at import time: an
    instance that never connects a pull source configures nothing and never
    hits this.
    """


class IntegrationKeyError(Exception):
    """None of the configured keys could decrypt this credential.

    Distinct from ``IntegrationNotConfigured``: keys *are* configured, but this
    token was encrypted under one that is no longer in the list (a rotation that
    dropped the old key too early, a restore onto another instance), or the row
    is corrupted.
    """


@lru_cache(maxsize=4)
def _cached_fernet(keys: tuple[str, ...]) -> MultiFernet:
    # Cached per key tuple, so a settings override in a test gets its own
    # instance instead of one built from stale keys.
    return MultiFernet([Fernet(key.encode("utf-8") if isinstance(key, str) else key) for key in keys])


def configured_keys() -> tuple[str, ...]:
    return tuple(key for key in settings.INTEGRATION_ENCRYPTION_KEYS if key)


def encryption_configured() -> bool:
    return bool(configured_keys())


def _fernet() -> MultiFernet:
    keys = configured_keys()
    if not keys:
        raise IntegrationNotConfigured(
            "INTEGRATION_ENCRYPTION_KEYS is not configured. Generate one with "
            '`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` '
            "and set it before connecting a pull source."
        )
    return _cached_fernet(keys)


def encrypt_secret(value: str) -> bytes:
    """Encrypt ``value`` with the first configured key.

    Raises ``IntegrationNotConfigured`` when no key is configured.
    """
    return _fernet().encrypt(value.encode("utf-8"))


def decrypt_secret(token: bytes) -> str:
    """Decrypt ``token`` with any configured key.

    Raises ``IntegrationNotConfigured`` when no key is configured, or
    ``IntegrationKeyError`` when keys are configured but none opens this token.
    """
    try:
        return _fernet().decrypt(bytes(token)).decode("utf-8")
    except InvalidToken as exc:
        raise IntegrationKeyError(
            "No configured INTEGRATION_ENCRYPTION_KEYS key could decrypt this credential. "
            "If a key was recently rotated out, restore it and run `manage.py rotate_integration_key` first."
        ) from exc
