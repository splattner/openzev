"""Encryption for the TOTP secret at rest.

Kept separate from ``models.py`` for the same reason ``api_keys.py`` is: the
crypto choice belongs in one readable file rather than scattered across model
methods.

This is the one field in the whole MFA feature that needs *reversible*
encryption — TOTP verification recomputes the code from the shared secret, so
the server must be able to read it back. Recovery codes and API keys are
hashed one-way instead; that is correct for them and would be wrong here.

The key is ``settings.MFA_ENCRYPTION_KEYS``, deliberately independent of
``SECRET_KEY`` — see ADR 0021. Do not derive one from the other.
"""

from __future__ import annotations

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings


class MfaNotConfigured(Exception):
    """``MFA_ENCRYPTION_KEYS`` is empty.

    Raised at the point something would need the key, not at import time —
    an instance with no MFA users configures nothing and never hits this.
    """


class MfaKeyError(Exception):
    """None of the configured keys could decrypt this secret.

    Distinct from ``MfaNotConfigured``: keys *are* configured, but this
    particular token was encrypted under one that is no longer in the list —
    a rotation that dropped the old key before re-encrypting every device, or
    a corrupted row.
    """


@lru_cache(maxsize=4)
def _cached_fernet(keys: tuple[str, ...]) -> MultiFernet:
    # Cached per key tuple (not just "the current keys"), so a settings
    # override in a test — or a key rotation mid-process, which does not
    # happen in practice but costs nothing to handle — gets its own instance
    # rather than reusing one built from stale keys.
    return MultiFernet([Fernet(key.encode("utf-8") if isinstance(key, str) else key) for key in keys])


def _fernet() -> MultiFernet:
    keys = tuple(settings.MFA_ENCRYPTION_KEYS)
    if not keys:
        raise MfaNotConfigured(
            "MFA_ENCRYPTION_KEYS is not configured. Generate one with "
            '`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` '
            "and set it before enabling two-factor authentication."
        )
    return _cached_fernet(keys)


def encrypt_secret(value: str) -> bytes:
    """Encrypt ``value`` with the first configured key.

    Raises ``MfaNotConfigured`` when no key is configured.
    """
    return _fernet().encrypt(value.encode("utf-8"))


def decrypt_secret(token: bytes) -> str:
    """Decrypt ``token`` with any configured key.

    Raises ``MfaNotConfigured`` when no key is configured, or ``MfaKeyError``
    when keys are configured but none of them can open this particular token.
    """
    try:
        return _fernet().decrypt(bytes(token)).decode("utf-8")
    except InvalidToken as exc:
        raise MfaKeyError(
            "No configured MFA_ENCRYPTION_KEYS key could decrypt this secret. "
            "If a key was recently rotated out, restore it and run `manage.py rotate_mfa_key` first."
        ) from exc
