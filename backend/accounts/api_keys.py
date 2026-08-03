"""Generation, hashing and parsing of API keys.

Kept separate from ``models.py`` so the crypto choices sit in one readable file
rather than scattered across model methods.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

# Marker so a leaked key is recognisable: secret scanners can be taught the
# pattern, and a key pasted into a log or an issue is greppable.
KEY_NAMESPACE = "ozv"

# 12 hex characters. Only an identifier, not a secret — it is stored in clear
# and shown in the UI so a key can be recognised after creation. Hex rather than
# url-safe base64 because the alphabet must not contain the separator.
PREFIX_BYTES = 6

# 256 bits of entropy. See ``hash_secret`` for why this size matters.
SECRET_BYTES = 32

SEPARATOR = "_"


def generate_key() -> tuple[str, str, str]:
    """Return ``(full_key, prefix, hashed_secret)``.

    ``full_key`` is the only time the secret exists in plain text; the caller
    shows it once and must not persist it.
    """
    prefix = secrets.token_hex(PREFIX_BYTES)
    secret = secrets.token_urlsafe(SECRET_BYTES)
    full_key = f"{KEY_NAMESPACE}{SEPARATOR}{prefix}{SEPARATOR}{secret}"
    return full_key, prefix, hash_secret(secret)


def hash_secret(secret: str) -> str:
    """Hash an API key secret with a single SHA-256 pass.

    This is deliberately *not* Django's password hasher, and that is not a
    shortcut. PBKDF2 runs ~600k iterations because passwords are low-entropy
    and human-chosen, so an attacker who steals the hashes can guess them --
    the slowness buys time. An API key is 256 bits from ``secrets.token_urlsafe``:
    there is nothing to guess, and no iteration count changes that.

    What the iteration count *would* change is the cost of every single API
    request, since the key is verified on each one. PBKDF2 would put ~100 ms of
    CPU in front of every call.

    Do not "upgrade" this to a password hasher.
    """
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def verify_secret(secret: str, hashed: str) -> bool:
    """Constant-time comparison of a presented secret against a stored hash."""
    return hmac.compare_digest(hash_secret(secret), hashed)


def split_key(raw_key: str) -> tuple[str, str] | None:
    """Split ``ozv_<prefix>_<secret>`` into ``(prefix, secret)``.

    Returns ``None`` for anything that is not shaped like one of our keys, so
    callers can reject without a database round-trip.

    Split with ``maxsplit`` so the secret keeps any separators of its own:
    ``token_urlsafe`` draws from an alphabet that includes ``_``, so a naive
    three-way split rejects roughly a third of the keys we issue.
    """
    parts = raw_key.split(SEPARATOR, 2)
    if len(parts) != 3:
        return None
    namespace, prefix, secret = parts
    if namespace != KEY_NAMESPACE or not prefix or not secret:
        return None
    return prefix, secret


def default_api_key_expiry():
    """Expiry applied to a key created without an explicit one.

    Optional-with-a-default only helps if the default is visible: the list shows
    ``expires_at`` on every key precisely so this does not turn into silent
    breakage a year from now.
    """
    from datetime import timedelta

    from django.conf import settings
    from django.utils import timezone

    days = settings.API_KEY_DEFAULT_EXPIRY_DAYS
    if not days:
        return None
    return timezone.now() + timedelta(days=days)
