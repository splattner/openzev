"""Backup archive: the writer, the manifest, and the verifier.

The container is a ZIP of JSON Lines sections plus the invoice PDF bytes
(SPEC-2026-09-backup-and-restore §6.1), with ``kind: "backup"`` in the manifest
so it can never be mistaken for a transfer archive (ADR 0023)::

    manifest.json
    instance/<section>.jsonl                 accounts, settings, templates, ...
    instance/unscoped_*.jsonl                rows whose ZEV was deleted
    zevs/<zev id>/<section>.jsonl            one community's rows
    zevs/<zev id>/account_refs.json          who the referenced users are
    zevs/<zev id>/media/<storage name>       that community's invoice PDFs

Every JSON line is Django's own serialization of a row — ``{"model", "pk",
"fields"}`` — so primary keys and every column travel exactly as stored. That
is the property that separates a backup from a transfer archive, which mints
new identifiers by design.

The manifest is written last so its counts and per-member SHA-256 digests are
the ones actually produced. Nothing here holds a whole section in memory:
sections stream through ``QuerySet.iterator()`` into a compressing zip member.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import tempfile
import zipfile
from collections.abc import Iterable, Iterator
from pathlib import PurePosixPath
from typing import IO, BinaryIO

from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import serializers
from django.core.files.storage import default_storage
from django.db import connection, transaction
from django.db.migrations.recorder import MigrationRecorder
from django.utils import timezone

from metering.importers.limits import MAX_REPORTED_ERRORS

from . import crypto
from .registry import (
    INSTANCE_SECTIONS,
    MEDIA_FIELDS,
    UNSCOPED_SECTIONS,
    ZEV_SECTIONS,
)

KIND = "backup"
FORMAT_VERSION = 1
SUPPORTED_FORMAT_VERSIONS = frozenset({1})
MANIFEST_NAME = "manifest.json"

SCOPE_INSTANCE = "instance"
SCOPE_ZEV = "zev"
SCOPES = (SCOPE_INSTANCE, SCOPE_ZEV)

_ITERATOR_CHUNK = 2000
_COPY_BLOCK = 1024 * 1024


class ArchiveError(ValueError):
    """The archive is malformed, corrupt or not a backup; ``str(exc)`` is user-safe.

    ``failures`` lists individual problems (capped at ``MAX_REPORTED_ERRORS``);
    ``total_failures`` is the true count.
    """

    def __init__(self, message: str, *, failures: list[str] | None = None, total_failures: int | None = None):
        super().__init__(message)
        self.failures = failures or []
        self.total_failures = total_failures if total_failures is not None else len(self.failures)


# ── writing ──────────────────────────────────────────────────────────────────

class _HashingWriter(io.RawIOBase):
    """A write-only file that forwards to ``target`` and digests what passes."""

    def __init__(self, target: IO[bytes]):
        self._target = target
        self._sha = hashlib.sha256()
        self.size = 0

    def writable(self) -> bool:
        return True

    def write(self, data) -> int:
        view = bytes(data)
        self._sha.update(view)
        self.size += len(view)
        self._target.write(view)
        return len(view)

    def hexdigest(self) -> str:
        return self._sha.hexdigest()


class _Counted:
    """Iterate ``source`` while counting what passes through."""

    def __init__(self, source: Iterable):
        self._source = source
        self.count = 0

    def __iter__(self) -> Iterator:
        for item in self._source:
            self.count += 1
            yield item


def _serialized_fields(model) -> list[str]:
    """Every concrete column except the primary key (which serializes as ``pk``).

    Explicit, because leaving ``fields`` unset would also serialize many-to-many
    relations — see ``registry`` for why those are excluded.
    """
    return [field.name for field in model._meta.concrete_fields if field.serialize]


def _safe_media_name(name: str) -> str | None:
    """A storage name safe to use as an archive path, or ``None``.

    Rejects absolute paths and ``..`` segments: the value is read from the
    database, and an archive member must not be able to name a place outside
    its own directory when it is restored.
    """
    path = PurePosixPath(name)
    if not path.parts or path.is_absolute() or ".." in path.parts:
        return None
    return path.as_posix()


class _Writer:
    def __init__(self, archive: zipfile.ZipFile):
        self._zip = archive
        self.members: dict[str, dict] = {}

    def json_member(self, name: str, payload) -> None:
        data = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
        self._zip.writestr(name, data)
        self.members[name] = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}

    def jsonl_member(self, name: str, parts: list[tuple[str, Iterable]]) -> int:
        """Stream ``parts`` — ``(model label, iterable of instances)`` — into one member."""
        per_model: dict[str, int] = {}
        with self._zip.open(name, "w", force_zip64=True) as raw:
            hasher = _HashingWriter(raw)
            text = io.TextIOWrapper(hasher, encoding="utf-8", newline="\n")
            for label, instances in parts:
                model = apps.get_model(label)
                counted = _Counted(instances)
                serializers.serialize("jsonl", counted, stream=text, fields=_serialized_fields(model))
                per_model[label] = counted.count
            text.flush()
            text.detach()
        records = sum(per_model.values())
        self.members[name] = {
            "sha256": hasher.hexdigest(),
            "bytes": hasher.size,
            "records": records,
            "models": per_model,
        }
        return records

    def media_member(self, name: str, storage_name: str) -> int | None:
        """Copy one stored file into the archive; the byte count, or ``None`` if unreadable.

        Two rows can name the same file; it is stored once (a second entry of the
        same name would leave the archive with an ambiguous duplicate member).
        """
        if name in self.members:
            return self.members[name]["bytes"]
        try:
            source = default_storage.open(storage_name, "rb")
        except (FileNotFoundError, OSError):
            return None
        with source, self._zip.open(name, "w", force_zip64=True) as raw:
            hasher = _HashingWriter(raw)
            while block := source.read(_COPY_BLOCK):
                hasher.write(block)
        self.members[name] = {"sha256": hasher.hexdigest(), "bytes": hasher.size}
        return hasher.size


def _rows(queryset) -> Iterator:
    return queryset.iterator(chunk_size=_ITERATOR_CHUNK)


def _referenced_user_ids(model, queryset) -> set[int]:
    """Ids of accounts that ``queryset``'s rows point at, through any foreign key."""
    user_model = get_user_model()
    ids: set[int] = set()
    for field in model._meta.concrete_fields:
        if field.is_relation and field.related_model is user_model:
            ids.update(
                value
                for value in queryset.order_by().values_list(field.attname, flat=True).distinct()
                if value is not None
            )
    return ids


def _write_instance(writer: _Writer) -> dict[str, int]:
    counts: dict[str, int] = {}
    for name, labels in INSTANCE_SECTIONS:
        parts = [(label, _rows(apps.get_model(label).objects.order_by("pk"))) for label in labels]
        counts[f"instance/{name}"] = writer.jsonl_member(f"instance/{name}.jsonl", parts)
    for name, label in UNSCOPED_SECTIONS:
        queryset = apps.get_model(label).objects.filter(zev__isnull=True).order_by("pk")
        counts[f"instance/{name}"] = writer.jsonl_member(f"instance/{name}.jsonl", [(label, _rows(queryset))])
    return counts


def _write_zev(writer: _Writer, zev) -> dict:
    base = f"zevs/{zev.pk}"
    counts: dict[str, int] = {}
    user_ids: set[int] = set()

    for name, parts in ZEV_SECTIONS:
        streams = []
        for part in parts:
            model = apps.get_model(part.label)
            queryset = model.objects.filter(**{part.lookup: zev.pk}).order_by(*part.order)
            user_ids |= _referenced_user_ids(model, queryset)
            streams.append((part.label, _rows(queryset)))
        counts[name] = writer.jsonl_member(f"{base}/{name}.jsonl", streams)

    # Per-ZEV restore relinks accounts by natural key (ADR 0023), which needs to
    # know who each referenced user id was. An instance archive carries every
    # account, but a ZEV-scoped one does not — and that is exactly the archive
    # a safety backup is, and the one that must be able to undo a restore.
    user_model = get_user_model()
    writer.json_member(
        f"{base}/account_refs.json",
        {
            "users": [
                {"id": row["pk"], "username": row["username"], "email": row["email"]}
                for row in user_model.objects.filter(pk__in=user_ids).order_by("pk").values("pk", "username", "email")
            ]
        },
    )

    files = total_bytes = 0
    missing: list[str] = []
    unsafe: list[str] = []
    for label, field_name, lookup in MEDIA_FIELDS:
        model = apps.get_model(label)
        names = (
            model.objects.filter(**{lookup: zev.pk})
            .exclude(**{field_name: ""})
            .exclude(**{f"{field_name}__isnull": True})
            .order_by("pk")
            .values_list(field_name, flat=True)
        )
        for storage_name in names:
            safe = _safe_media_name(storage_name)
            if safe is None:
                unsafe.append(storage_name)
                continue
            size = writer.media_member(f"{base}/media/{safe}", safe)
            if size is None:
                missing.append(safe)
            else:
                files += 1
                total_bytes += size

    return {
        "id": str(zev.pk),
        "name": zev.name,
        "counts": counts,
        # A file the database references but storage no longer has is recorded,
        # not fatal: refusing to back up because an old PDF is already gone would
        # make the instance's other data less safe, not more.
        "media": {"files": files, "bytes": total_bytes, "missing": missing, "unsafe": unsafe},
    }


def _applied_migrations() -> dict[str, list[str]]:
    applied: dict[str, list[str]] = {}
    for app_label, name in MigrationRecorder(connection).applied_migrations():
        applied.setdefault(app_label, []).append(name)
    return {app_label: sorted(names) for app_label, names in sorted(applied.items())}


def _secret_fingerprints() -> dict:
    return {
        "mfa_encryption_keys": [crypto.key_fingerprint(key) for key in settings.MFA_ENCRYPTION_KEYS if key],
        "secret_key": crypto.key_fingerprint(settings.SECRET_KEY),
    }


def build_archive(fileobj: BinaryIO, *, scope: str, zev=None, encryption_fingerprint: str = "") -> dict:
    """Write a backup archive of ``scope`` into ``fileobj`` and return its manifest.

    ``scope="instance"`` writes every instance section and every ZEV;
    ``scope="zev"`` writes one community only. ``encryption_fingerprint`` is
    recorded in the manifest when the caller will encrypt the finished file —
    the envelope wraps the whole ZIP, so the manifest inside cannot learn it
    afterwards.

    Runs in one ``REPEATABLE READ`` transaction on PostgreSQL. Sections are read
    over minutes; at ``READ COMMITTED`` a concurrent edit would leave an archive
    of a state that never existed, with counts disagreeing with the rows. The
    ``durable=True`` guard makes this the outermost transaction, so the isolation
    level can be set — called inside another it fails loudly rather than
    silently degrading to a savepoint.
    """
    if scope not in SCOPES:
        raise ValueError(f"Unknown backup scope {scope!r}.")
    if scope == SCOPE_ZEV and zev is None:
        raise ValueError("A ZEV-scoped backup needs a ZEV.")
    if scope == SCOPE_INSTANCE and zev is not None:
        raise ValueError("An instance backup does not take a ZEV.")

    with transaction.atomic(durable=True):
        if connection.vendor == "postgresql":
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        return _build(fileobj, scope=scope, zev=zev, encryption_fingerprint=encryption_fingerprint)


def _build(fileobj: BinaryIO, *, scope: str, zev, encryption_fingerprint: str) -> dict:
    zev_model = apps.get_model("zev.Zev")
    zevs = [zev] if scope == SCOPE_ZEV else list(zev_model.objects.order_by("name", "pk"))

    with zipfile.ZipFile(fileobj, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
        writer = _Writer(archive)
        counts: dict[str, int] = {}
        if scope == SCOPE_INSTANCE:
            counts.update(_write_instance(writer))

        zev_entries = []
        for entry_zev in zevs:
            entry = _write_zev(writer, entry_zev)
            zev_entries.append(entry)
            counts.update({f"zevs/{entry['id']}/{name}": n for name, n in entry["counts"].items()})

        manifest = {
            "kind": KIND,
            "format_version": FORMAT_VERSION,
            "created_at": timezone.localtime().isoformat(timespec="seconds"),
            "instance_name": settings.INSTANCE_NAME,
            "openzev_version": settings.OPENZEV_VERSION,
            "scope": scope,
            "zev_id": str(zev.pk) if zev is not None else None,
            "migrations": _applied_migrations(),
            "counts": counts,
            "members": writer.members,
            "zevs": zev_entries,
            "encryption": (
                {"algorithm": crypto.ALGORITHM, "key_fingerprint": encryption_fingerprint}
                if encryption_fingerprint
                else None
            ),
            "secret_fingerprints": _secret_fingerprints(),
        }
        archive.writestr(MANIFEST_NAME, json.dumps(manifest, indent=2))
    return manifest


# ── reading and verifying ────────────────────────────────────────────────────

def read_manifest(archive: zipfile.ZipFile) -> dict:
    """The manifest of an open archive, structurally checked.

    Raises ``ArchiveError`` rather than letting a malformed one surface as an
    ``AttributeError`` or ``KeyError`` from deeper in.
    """
    try:
        manifest = json.loads(archive.read(MANIFEST_NAME))
    except KeyError as exc:
        raise ArchiveError("This is not an OpenZEV backup: it has no manifest.") from exc
    except (ValueError, zipfile.BadZipFile) as exc:
        raise ArchiveError("The backup manifest is unreadable.") from exc

    if not isinstance(manifest, dict):
        raise ArchiveError("The backup manifest is malformed.")
    if manifest.get("kind") != KIND:
        raise ArchiveError(
            f"This archive is a {manifest.get('kind', 'unknown')!r} archive, not a backup. "
            "Transfer archives are imported from the ZEV settings, not restored."
        )
    if manifest.get("format_version") not in SUPPORTED_FORMAT_VERSIONS:
        raise ArchiveError(
            f"Unsupported backup format version {manifest.get('format_version')!r}; "
            f"this instance reads {sorted(SUPPORTED_FORMAT_VERSIONS)}."
        )
    if manifest.get("scope") not in SCOPES:
        raise ArchiveError("The backup manifest names an unknown scope.")
    for key, expected in (("members", dict), ("counts", dict), ("zevs", list), ("migrations", dict)):
        if not isinstance(manifest.get(key), expected):
            raise ArchiveError(f"The backup manifest is malformed: {key!r} is missing or the wrong type.")
    return manifest


def _work_dir() -> str | None:
    return settings.BACKUP_WORK_DIR or None


@contextlib.contextmanager
def open_archive(source: BinaryIO) -> Iterator[zipfile.ZipFile]:
    """Open a backup as a ``ZipFile``, decrypting first when it is encrypted.

    An encrypted archive is decrypted to a temporary file in ``BACKUP_WORK_DIR``
    that is removed on exit; the ZIP central directory needs random access, so
    it cannot be decrypted lazily.
    """
    with contextlib.ExitStack() as stack:
        readable: BinaryIO = source
        if crypto.is_encrypted(source):
            plain = stack.enter_context(tempfile.TemporaryFile(dir=_work_dir()))
            crypto.decrypt_stream(source, plain)
            plain.seek(0)
            readable = plain
        try:
            archive = stack.enter_context(zipfile.ZipFile(readable))
        except zipfile.BadZipFile as exc:
            raise ArchiveError("The file is not a readable ZIP archive.") from exc
        yield archive


def verify_archive(source: BinaryIO) -> dict:
    """Check a backup end to end without restoring anything.

    Every member listed in the manifest must exist with the recorded SHA-256 and
    size, every JSON Lines section must hold the recorded number of records, the
    manifest's per-section counts must agree with the members, and nothing may
    be in the archive that the manifest does not vouch for. ZIP CRC32 alone is
    not enough for an artifact that crosses a network and sits in a bucket for
    months, hence the SHA-256 (SPEC-2026-09-backup-and-restore §8).

    Returns ``{"manifest", "members", "records"}``; raises ``ArchiveError`` with
    the failures listed otherwise.
    """
    failures: list[str] = []

    def fail(message: str) -> None:
        failures.append(message)

    with open_archive(source) as archive:
        manifest = read_manifest(archive)
        listed = manifest["members"]
        present = set(archive.namelist()) - {MANIFEST_NAME}

        for name in sorted(present - set(listed)):
            fail(f"{name}: present in the archive but not in the manifest")

        records_seen = 0
        for name, expected in sorted(listed.items()):
            if name not in present:
                fail(f"{name}: listed in the manifest but missing from the archive")
                continue
            digest = hashlib.sha256()
            size = lines = 0
            try:
                with archive.open(name) as member:
                    while block := member.read(_COPY_BLOCK):
                        digest.update(block)
                        size += len(block)
                        if "records" in expected:
                            lines += block.count(b"\n")
            except (zipfile.BadZipFile, OSError) as exc:
                fail(f"{name}: unreadable ({exc})")
                continue
            if digest.hexdigest() != expected.get("sha256"):
                fail(f"{name}: checksum mismatch")
            elif size != expected.get("bytes"):
                fail(f"{name}: size mismatch")
            if "records" in expected:
                records_seen += lines
                if lines != expected["records"]:
                    fail(f"{name}: expected {expected['records']} records, found {lines}")

        for section, count in sorted(manifest["counts"].items()):
            member = listed.get(f"{section}.jsonl")
            if member is None:
                fail(f"{section}: counted in the manifest but has no member")
            elif member.get("records") != count:
                fail(f"{section}: manifest counts {count} but the member records {member.get('records')}")

    if failures:
        raise ArchiveError(
            f"The backup failed verification ({len(failures)} problem{'s' if len(failures) != 1 else ''}).",
            failures=failures[:MAX_REPORTED_ERRORS],
            total_failures=len(failures),
        )
    return {"manifest": manifest, "members": len(listed), "records": records_seen}
