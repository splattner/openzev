"""Encryption for backup artifacts and stored destination secrets.

Everything here hangs off ``settings.BACKUP_ENCRYPTION_KEYS``, a dedicated,
optional, rotatable key list that is deliberately independent of
``MFA_ENCRYPTION_KEYS`` and ``SECRET_KEY`` — see ADR 0024. The first key
encrypts; every key can decrypt, so a rotation is: add the new key first, take
fresh backups, retire the old key once no retained archive still needs it.

Two different things are encrypted, with keys derived from the same
configured string under different HKDF ``info`` labels so a value encrypted
for one purpose can never be presented as the other:

* **Destination secrets** (an S3 secret access key stored on a
  ``BackupDestination`` row) — short, so Fernet is fine.
* **Archives** — arbitrarily large, so they are encrypted as a stream in
  authenticated chunks (AES-256-GCM). Fernet needs the whole message in
  memory to encrypt or decrypt and cannot be used here.

Envelope layout of an encrypted archive::

    b"OZBK1"                          5-byte magic
    <uint32 header length><header>    JSON: algorithm, key fingerprint,
                                      chunk size, nonce prefix
    (<uint32 length><ciphertext+tag>)*   one per chunk

Each chunk's associated data binds its position (a counter) and whether it is
the last one, plus a digest of the header. Reordering, dropping or truncating
chunks, or editing the header, therefore fails authentication instead of
quietly yielding a shorter archive.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import struct
from typing import BinaryIO

from cryptography.exceptions import InvalidTag
from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.conf import settings

MAGIC = b"OZBK1"
ALGORITHM = "AES-256-GCM"
DEFAULT_CHUNK_SIZE = 1024 * 1024
# A key shorter than this is a passphrase, not a key. HKDF stretches entropy, it
# cannot create it, so a short human-chosen string would make the whole scheme
# guessable.
MIN_KEY_LENGTH = 32

_ARCHIVE_INFO = b"openzev-backup-archive-v1"
_SECRET_INFO = b"openzev-backup-destination-secret-v1"

_GCM_TAG_LENGTH = 16
_MAX_HEADER_BYTES = 64 * 1024
_MAX_CHUNK_SIZE = 64 * 1024 * 1024
_NONCE_PREFIX_BYTES = 4


class BackupCryptoError(Exception):
    """Base class; ``str(exc)`` is safe to show an administrator."""


class BackupKeysNotConfigured(BackupCryptoError):
    """``BACKUP_ENCRYPTION_KEYS`` is empty and something needs a key."""


class BackupKeyRejected(BackupCryptoError):
    """A configured key is unusable (for example too short to be a key)."""


class BackupKeyMissing(BackupCryptoError):
    """The archive or secret was encrypted under a key this instance lacks."""

    def __init__(self, message: str, *, fingerprint: str = ""):
        super().__init__(message)
        self.fingerprint = fingerprint


class BackupEnvelopeError(BackupCryptoError):
    """The encrypted archive is corrupt, truncated or has been tampered with."""


# ── keys ─────────────────────────────────────────────────────────────────────

def configured_keys() -> tuple[str, ...]:
    """The configured keys, validated. Empty when encryption is not set up."""
    keys = tuple(key for key in settings.BACKUP_ENCRYPTION_KEYS if key)
    for key in keys:
        if len(key) < MIN_KEY_LENGTH:
            raise BackupKeyRejected(
                f"A BACKUP_ENCRYPTION_KEYS entry is shorter than {MIN_KEY_LENGTH} characters. "
                "Generate one with "
                '`python -c "import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"`.'
            )
    return keys


def encryption_configured() -> bool:
    return bool(configured_keys())


def key_fingerprint(key: str) -> str:
    """Identify ``key`` without revealing it: the first 16 hex of its SHA-256.

    Recorded in manifests so a restore can name the key it needs. A fingerprint
    identifies a key; it does not help anyone recover one.
    """
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def active_fingerprint() -> str:
    """Fingerprint of the key that encrypts new archives, or ``""`` if none."""
    keys = configured_keys()
    return key_fingerprint(keys[0]) if keys else ""


def _derive(key: str, info: bytes) -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(), length=32, salt=None, info=info,
    ).derive(key.encode("utf-8"))


# ── destination secrets ──────────────────────────────────────────────────────

def _secret_fernet() -> MultiFernet:
    keys = configured_keys()
    if not keys:
        raise BackupKeysNotConfigured(
            "BACKUP_ENCRYPTION_KEYS is not configured, so a secret cannot be stored. "
            "Set the key, or supply the credentials through BACKUP_S3_ACCESS_KEY_ID / "
            "BACKUP_S3_SECRET_ACCESS_KEY instead."
        )
    return MultiFernet([
        Fernet(base64.urlsafe_b64encode(_derive(key, _SECRET_INFO))) for key in keys
    ])


def encrypt_secret(value: str) -> bytes:
    """Encrypt ``value`` under the first configured key."""
    return _secret_fernet().encrypt(value.encode("utf-8"))


def decrypt_secret(token: bytes) -> str:
    """Decrypt ``token`` under any configured key."""
    try:
        return _secret_fernet().decrypt(bytes(token)).decode("utf-8")
    except InvalidToken as exc:
        raise BackupKeyMissing(
            "No configured BACKUP_ENCRYPTION_KEYS key can decrypt the stored secret. "
            "If a key was rotated out, restore it, or enter the secret again."
        ) from exc


# ── archive envelope ─────────────────────────────────────────────────────────

def _aad(header_digest: bytes, counter: int, final: bool) -> bytes:
    return header_digest + struct.pack(">QB", counter, 1 if final else 0)


def _nonce(prefix: bytes, counter: int) -> bytes:
    return prefix + counter.to_bytes(8, "big")


def _read_exactly(src: BinaryIO, size: int) -> bytes:
    data = src.read(size)
    if len(data) != size:
        raise BackupEnvelopeError("The encrypted archive is truncated.")
    return data


def is_encrypted(src: BinaryIO) -> bool:
    """Whether ``src`` starts with the envelope magic. Leaves the position unchanged."""
    position = src.tell()
    try:
        return src.read(len(MAGIC)) == MAGIC
    finally:
        src.seek(position)


def encrypt_stream(src: BinaryIO, dst: BinaryIO, *, chunk_size: int = DEFAULT_CHUNK_SIZE) -> str:
    """Encrypt ``src`` into ``dst`` under the first configured key.

    Reads one chunk ahead so the last non-empty chunk can be marked final; an
    empty source still yields one (empty) final chunk. Memory use is bounded by
    ``chunk_size`` regardless of archive size. Returns the key fingerprint.
    """
    keys = configured_keys()
    if not keys:
        raise BackupKeysNotConfigured("BACKUP_ENCRYPTION_KEYS is not configured.")
    if not 0 < chunk_size <= _MAX_CHUNK_SIZE:
        raise ValueError("chunk_size out of range")

    key = keys[0]
    fingerprint = key_fingerprint(key)
    aead = AESGCM(_derive(key, _ARCHIVE_INFO))
    prefix = os.urandom(_NONCE_PREFIX_BYTES)
    header = json.dumps(
        {
            "algorithm": ALGORITHM,
            "key_fingerprint": fingerprint,
            "chunk_size": chunk_size,
            "nonce_prefix": prefix.hex(),
        },
        sort_keys=True,
    ).encode("utf-8")
    header_digest = hashlib.sha256(header).digest()

    dst.write(MAGIC + struct.pack(">I", len(header)) + header)

    counter = 0
    pending = src.read(chunk_size)
    while True:
        following = src.read(chunk_size) if len(pending) == chunk_size else b""
        final = not following
        sealed = aead.encrypt(_nonce(prefix, counter), pending, _aad(header_digest, counter, final))
        dst.write(struct.pack(">I", len(sealed)) + sealed)
        if final:
            return fingerprint
        pending = following
        counter += 1


def decrypt_stream(src: BinaryIO, dst: BinaryIO) -> str:
    """Decrypt ``src`` into ``dst``; returns the fingerprint of the key that opened it.

    Raises ``BackupKeyMissing`` (naming the required fingerprint) when this
    instance holds no matching key, and ``BackupEnvelopeError`` for anything
    that fails authentication — including a truncated or reordered archive.
    """
    if src.read(len(MAGIC)) != MAGIC:
        raise BackupEnvelopeError("This file is not an encrypted OpenZEV backup.")
    (header_length,) = struct.unpack(">I", _read_exactly(src, 4))
    if not 0 < header_length <= _MAX_HEADER_BYTES:
        raise BackupEnvelopeError("The encrypted archive header is corrupt.")
    header = _read_exactly(src, header_length)
    try:
        meta = json.loads(header)
        if meta["algorithm"] != ALGORITHM:
            raise BackupEnvelopeError(f"Unsupported encryption algorithm {meta['algorithm']!r}.")
        fingerprint = str(meta["key_fingerprint"])
        chunk_size = int(meta["chunk_size"])
        prefix = bytes.fromhex(meta["nonce_prefix"])
    except (ValueError, KeyError, TypeError) as exc:
        raise BackupEnvelopeError("The encrypted archive header is corrupt.") from exc
    if not 0 < chunk_size <= _MAX_CHUNK_SIZE or len(prefix) != _NONCE_PREFIX_BYTES:
        raise BackupEnvelopeError("The encrypted archive header is corrupt.")

    key = next((k for k in configured_keys() if key_fingerprint(k) == fingerprint), None)
    if key is None:
        raise BackupKeyMissing(
            f"This backup is encrypted under a key this instance does not have "
            f"(fingerprint {fingerprint}). Add it to BACKUP_ENCRYPTION_KEYS.",
            fingerprint=fingerprint,
        )
    aead = AESGCM(_derive(key, _ARCHIVE_INFO))
    header_digest = hashlib.sha256(header).digest()
    max_sealed = chunk_size + _GCM_TAG_LENGTH

    def read_sealed() -> bytes | None:
        raw = src.read(4)
        if not raw:
            return None
        if len(raw) != 4:
            raise BackupEnvelopeError("The encrypted archive is truncated.")
        (length,) = struct.unpack(">I", raw)
        if not _GCM_TAG_LENGTH <= length <= max_sealed:
            raise BackupEnvelopeError("The encrypted archive is corrupt.")
        return _read_exactly(src, length)

    counter = 0
    current = read_sealed()
    if current is None:
        raise BackupEnvelopeError("The encrypted archive contains no data.")
    while current is not None:
        following = read_sealed()
        final = following is None
        try:
            dst.write(aead.decrypt(_nonce(prefix, counter), current, _aad(header_digest, counter, final)))
        except InvalidTag as exc:
            raise BackupEnvelopeError(
                "The encrypted archive failed authentication: it is corrupted, truncated "
                "or has been tampered with."
            ) from exc
        current = following
        counter += 1
    return fingerprint
