"""Restore a whole instance from a backup archive (SPEC-2026-09-backup-and-restore §6.5).

The one thing this module exists to guarantee is that a failed restore leaves the
instance exactly as it was: every database write happens in a single
transaction, the invoice PDFs are written inside that transaction's window and
removed again if it rolls back, and everything that can be checked *before* the
first write (integrity, scope, schema, key material, emptiness) is.

Rows are loaded with their original primary keys (ADR 0023). ``bulk_create`` is
used for speed, with each model's ``auto_now``/``auto_now_add`` switched off for
the duration: those fields stamp ``timezone.now()`` in ``pre_save``, which would
overwrite every ``created_at`` in the archive with the moment of the restore.
Integer-keyed tables then have their sequences moved past the restored maximum,
or the next insert would collide with a row that came from the backup.

Instance restore is deliberately the only mode here. Restoring one community into
a running instance is a different operation with different safety rules (ADR
0023) and lives elsewhere.
"""

from __future__ import annotations

import hashlib
import io
import logging
import shutil
import tempfile
import zipfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import IO, BinaryIO

from django.apps import apps
from django.conf import settings
from django.core import serializers
from django.core.files.base import File
from django.core.files.storage import default_storage
from django.core.management.color import no_style
from django.core.serializers.base import DeserializationError
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.recorder import MigrationRecorder

from audit.models import AuditActionCategory, AuditEventSource
from audit.services import record_audit_event

from . import archive, crypto
from .archive import SCOPE_INSTANCE
from .registry import (
    INSTANCE_SECTIONS,
    MEDIA_FIELDS,
    UNSCOPED_SECTIONS,
    ZEV_SECTIONS,
    backed_up_labels,
)

logger = logging.getLogger(__name__)

ACTION_RESTORED = "backup.instance_restored"

_BATCH = 1000
_COPY_BLOCK = 1024 * 1024
_AUTO_PK_TYPES = {"AutoField", "BigAutoField", "SmallAutoField"}


class RestoreError(Exception):
    """The restore was refused or failed and rolled back; ``str(exc)`` is user-safe."""


@dataclass
class RestoreReport:
    dry_run: bool
    manifest: dict
    counts: dict[str, int] = field(default_factory=dict)  # model label → rows loaded
    replaced: dict[str, int] = field(default_factory=dict)  # model label → existing rows removed
    media_files: int = 0
    media_bytes: int = 0
    media_missing: int = 0
    media_skipped: int = 0
    sequences: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def records(self) -> int:
        return sum(self.counts.values())


# ── preflight ────────────────────────────────────────────────────────────────

def _relevant_apps() -> set[str]:
    """The apps whose tables a backup writes: only their schema has to match."""
    return {label.split(".")[0] for label in backed_up_labels()}


def check_migrations(manifest: dict) -> None:
    """Refuse unless the database schema is the one the archive was written from.

    Rows are loaded through the *current* models, so a column the archive has but
    the schema lacks (or the reverse) would be silently dropped or defaulted.
    Backups are logical dumps of one schema state; only that state restores
    them. Only the apps that own backed-up tables are compared, so an unrelated
    library upgrading its own migrations does not block a restore.
    """
    archived = {app: set(names) for app, names in manifest["migrations"].items() if app in _relevant_apps()}
    current: dict[str, set[str]] = {}
    for app, name in MigrationRecorder(connection).applied_migrations():
        if app in _relevant_apps():
            current.setdefault(app, set()).add(name)

    known = set(MigrationLoader(connection, ignore_no_migrations=True).graph.nodes)
    unknown = sorted(f"{app}.{name}" for app, names in archived.items() for name in names if (app, name) not in known)
    if unknown:
        raise RestoreError(
            "This backup was taken by a newer version of OpenZEV than this one: it contains "
            f"migrations this code does not have ({_sample(unknown)}). Upgrade OpenZEV first."
        )

    behind = sorted(f"{app}.{n}" for app, names in archived.items() for n in names - current.get(app, set()))
    if behind:
        raise RestoreError(
            f"The database has not applied migrations that the backup was taken with ({_sample(behind)}). "
            "Run `python manage.py migrate` first."
        )

    ahead = {app: sorted(names - archived.get(app, set())) for app, names in current.items()}
    ahead = {app: names for app, names in ahead.items() if names}
    if ahead:
        steps = "; ".join(
            f"python manage.py migrate {app} {sorted(archived[app])[-1]}" for app in sorted(ahead) if archived.get(app)
        )
        listed = _sample([f"{app}.{name}" for app, names in sorted(ahead.items()) for name in names])
        raise RestoreError(
            f"The database schema is newer than the backup ({listed}). A backup restores only into the schema it "
            "was taken from, because rows are loaded through the current models. Migrate this database back "
            f"first{f' ({steps})' if steps else ''}, restore, then run `python manage.py migrate` to move forward."
        )


def _sample(items: list[str], limit: int = 5) -> str:
    shown = ", ".join(items[:limit])
    return f"{shown}, and {len(items) - limit} more" if len(items) > limit else shown


def key_warnings(manifest: dict) -> list[str]:
    """Warnings about secrets the backup carries but this instance cannot use.

    A restore proceeds without the MFA key — recovery codes and an administrator's
    reset are the escapes (ADR 0021) — but the operator must hear it now, not
    from the first person who cannot log in.
    """
    warnings: list[str] = []
    accounts_member = manifest["members"].get("instance/accounts.jsonl", {})
    totp_devices = accounts_member.get("models", {}).get("accounts.TotpDevice", 0)
    theirs = set(manifest.get("secret_fingerprints", {}).get("mfa_encryption_keys", []))
    ours = {crypto.key_fingerprint(key) for key in settings.MFA_ENCRYPTION_KEYS if key}
    if totp_devices and theirs and not (theirs & ours):
        warnings.append(
            f"This backup holds {totp_devices} authenticator (TOTP) secret(s) encrypted under MFA_ENCRYPTION_KEYS "
            f"fingerprint {', '.join(sorted(theirs))}, and none of this instance's MFA keys match. Those users "
            "will not be able to pass the authenticator step. Configure the original MFA_ENCRYPTION_KEYS to "
            "keep them working, or plan to reset their MFA (recovery codes and an administrator reset still work)."
        )
    return warnings


def existing_rows() -> dict[str, int]:
    """Row counts of every table a restore would replace, empty ones left out."""
    counts = {}
    for label in _clear_order():
        n = apps.get_model(label)._base_manager.count()
        if n:
            counts[label] = n
    return counts


def _is_empty() -> bool:
    """A fresh installation: no community and no account other than a bootstrap superuser."""
    user_model = apps.get_model("accounts.User")
    return not apps.get_model("zev.Zev")._base_manager.exists() and not (
        user_model._base_manager.filter(is_superuser=False).exists()
    )


# ── load plan ────────────────────────────────────────────────────────────────

def _load_plan(manifest: dict) -> list[tuple[str, frozenset[str]]]:
    """``(member name, model labels it may contain)`` in load order.

    The allow-list is the security boundary of a restore: a section can only
    create rows of the models the registry assigns to it, so an archive cannot
    smuggle rows into ``sessions.Session`` or anything else outside the backup.
    """
    plan: list[tuple[str, frozenset[str]]] = [
        (f"instance/{name}.jsonl", frozenset(labels)) for name, labels in INSTANCE_SECTIONS
    ]
    for entry in manifest["zevs"]:
        for name, parts in ZEV_SECTIONS:
            plan.append((f"zevs/{entry['id']}/{name}.jsonl", frozenset(part.label for part in parts)))
    # Rows that outlive a deleted community come last: they point at people and
    # participants that must already be there.
    plan += [(f"instance/{name}.jsonl", frozenset({label})) for name, label in UNSCOPED_SECTIONS]
    return plan


def _clear_order() -> list[str]:
    """Every backed-up model, dependants before what they point at."""
    seen: list[str] = []
    for _, labels in INSTANCE_SECTIONS:
        seen += labels
    for _, parts in ZEV_SECTIONS:
        seen += [part.label for part in parts]
    seen += [label for _, label in UNSCOPED_SECTIONS]
    unique = list(dict.fromkeys(seen))
    return list(reversed(unique))


# ── writing ──────────────────────────────────────────────────────────────────

@contextmanager
def _stored_timestamps(model) -> Iterator[None]:
    """Let ``bulk_create`` keep the timestamps it is given.

    ``auto_now`` / ``auto_now_add`` overwrite the value in ``pre_save``, which
    ``bulk_create`` runs; ``Model.save_base(raw=True)`` (what ``loaddata`` uses)
    skips that but inserts one row per statement. Switching the flags off for the
    duration of the insert keeps both properties. Restore is a single-process
    command, so touching class-level field state is safe, and it is put back in
    ``finally``.
    """
    fields = [f for f in model._meta.concrete_fields if getattr(f, "auto_now", False) or getattr(f, "auto_now_add", False)]
    saved = [(f, f.auto_now, f.auto_now_add) for f in fields]
    try:
        for f in fields:
            f.auto_now = f.auto_now_add = False
        yield
    finally:
        for f, auto_now, auto_now_add in saved:
            f.auto_now, f.auto_now_add = auto_now, auto_now_add


def _clear() -> None:
    """Remove what the restore replaces, dependants first."""
    # Not backed up, but they hold a PROTECT foreign key to a community.
    apps.get_model("exports.ExportJob")._base_manager.all().delete()
    for label in _clear_order():
        apps.get_model(label)._base_manager.all().delete()


def _records(zf: zipfile.ZipFile, member: str, allowed: frozenset[str]) -> Iterator:
    """Deserialized rows of one section, each checked against the section's allow-list."""
    with zf.open(member) as raw:
        for record in serializers.deserialize("jsonl", io.TextIOWrapper(raw, encoding="utf-8")):
            label = record.object._meta.label
            if label not in allowed:
                raise RestoreError(f"{member} holds a {label} record, which does not belong in that section.")
            yield record


def _load_member(
    zf, member, allowed, expected, report, referenced_media, *, write: bool, transform: Callable | None = None
) -> None:
    per_model: dict[str, int] = {}
    batch: list = []
    batch_label = ""

    def flush() -> None:
        if not batch:
            return
        if write:
            model = type(batch[0])
            with _stored_timestamps(model):
                model._base_manager.bulk_create(batch, batch_size=_BATCH)
        batch.clear()

    try:
        for record in _records(zf, member, allowed):
            instance = record.object
            label = instance._meta.label
            per_model[label] = per_model.get(label, 0) + 1
            if transform is not None:
                transform(instance)
            if label != batch_label:
                flush()
                batch_label = label
            batch.append(instance)
            if len(batch) >= _BATCH:
                flush()
            for media_label, field_name, _ in MEDIA_FIELDS:
                if label == media_label and (name := getattr(instance, field_name).name):
                    referenced_media.add(name)
        flush()
    except (DeserializationError, ValueError, TypeError, KeyError, AttributeError) as exc:
        # The message would quote field values (participant names, addresses); the
        # operator gets the section, the log gets the cause.
        logger.exception("Restore could not read %s", member)
        raise RestoreError(
            f"{member} has a record this version cannot read. The backup and the code disagree about the "
            "schema; see the server log for the cause."
        ) from exc

    # The writer lists empty models too; only rows that exist can disagree.
    recorded = {label: n for label, n in expected.items() if n}
    if per_model != recorded:
        raise RestoreError(f"{member} holds {per_model}, but the manifest recorded {recorded}.")
    for label, n in per_model.items():
        report.counts[label] = report.counts.get(label, 0) + n


class _HashingFile(File):
    """A stored-file source that digests what storage reads from it."""

    def __init__(self, source) -> None:
        super().__init__(source)
        self.sha256 = hashlib.sha256()
        self.size = 0

    def chunks(self, chunk_size=None):
        while block := self.file.read(chunk_size or _COPY_BLOCK):
            self.sha256.update(block)
            self.size += len(block)
            yield block


class MediaUndo:
    """What a restore did to storage, so a failure can put it back.

    Storage is not transactional. A file the restore creates is removed again; a
    file it overwrites is copied aside first and written back, so a failed
    restore over a live instance does not leave a PDF holding the backup's bytes
    next to a database row that never changed.
    """

    def __init__(self) -> None:
        self.created: list[str] = []
        self.replaced: dict[str, IO[bytes]] = {}

    def keep(self, name: str) -> None:
        """Copy ``name`` aside before it is deleted."""
        stash = tempfile.TemporaryFile(dir=settings.BACKUP_WORK_DIR or None)
        with default_storage.open(name, "rb") as current:
            shutil.copyfileobj(current, stash, _COPY_BLOCK)
        self.replaced[name] = stash

    def rollback(self) -> None:
        for name in self.created:
            if name in self.replaced:
                continue
            try:
                default_storage.delete(name)
            except Exception:  # noqa: BLE001 - best effort; the original error is what matters
                logger.warning("Could not remove %s after a failed restore", name)
        for name, stash in self.replaced.items():
            try:
                stash.seek(0)
                default_storage.delete(name)
                default_storage.save(name, File(stash))
            except Exception:  # noqa: BLE001
                logger.error("Could not put %s back after a failed restore", name)

    def close(self) -> None:
        for stash in self.replaced.values():
            stash.close()


def _restore_media(
    zf, manifest, referenced: set[str], report: RestoreReport, undo: MediaUndo, *, only_zev: str | None = None
) -> None:
    """Copy each invoice PDF back into storage under the exact name the database holds.

    Only names an ``Invoice`` row actually references are written, and each is
    re-checked as a safe relative path: the archive is trusted to be an OpenZEV
    backup, not to name where files go.
    """
    for entry in manifest["zevs"]:
        if only_zev is not None and entry["id"] != only_zev:
            continue
        prefix = f"zevs/{entry['id']}/media/"
        report.media_missing += len(entry.get("media", {}).get("missing", []))
        for member in sorted(name for name in manifest["members"] if name.startswith(prefix)):
            name = archive._safe_media_name(member[len(prefix):])
            if name is None or name not in referenced:
                report.media_skipped += 1
                continue
            if default_storage.exists(name):
                # ``save`` would pick a fresh name for a taken one; the invoice row
                # needs this exact one.
                undo.keep(name)
                default_storage.delete(name)
            with zf.open(member) as source:
                content = _HashingFile(source)
                saved = default_storage.save(name, content)
            undo.created.append(saved)
            expected = manifest["members"][member]
            if saved != name or content.sha256.hexdigest() != expected["sha256"] or content.size != expected["bytes"]:
                raise RestoreError(f"{name} could not be restored intact.")
            report.media_files += 1
            report.media_bytes += content.size


def _reconcile_sequences(report: RestoreReport, labels: list[str] | None = None) -> None:
    """Move every integer key sequence past the restored maximum.

    Rows arrive with their own primary keys, so the counters the database keeps
    for its next auto-generated one never moved; the first ordinary insert would
    reuse an id a restored row already holds.
    """
    models = [
        apps.get_model(label)
        for label in (labels if labels is not None else _clear_order())
        if apps.get_model(label)._meta.pk.get_internal_type() in _AUTO_PK_TYPES
    ]
    with connection.cursor() as cursor:
        for statement in connection.ops.sequence_reset_sql(no_style(), models):
            cursor.execute(statement)
    report.sequences = sorted(model._meta.db_table for model in models)


# ── entry point ──────────────────────────────────────────────────────────────

def restore_instance(
    source: BinaryIO,
    *,
    dry_run: bool = False,
    force: bool = False,
    progress: Callable[[str], None] = lambda message: None,
) -> RestoreReport:
    """Restore the whole instance from the backup in ``source``.

    Raises ``RestoreError`` (or ``ArchiveError`` / ``crypto.BackupCryptoError``
    for an unreadable archive) with nothing changed. ``dry_run`` runs every check
    and reads every record, but writes nothing.
    """
    with archive.open_archive(source) as zf:
        progress("Verifying the archive…")
        manifest = archive.verify_open_archive(zf)["manifest"]

        if manifest["scope"] != SCOPE_INSTANCE:
            raise RestoreError(
                "This is a backup of a single community. A whole-instance restore needs an instance backup."
            )
        check_migrations(manifest)
        report = RestoreReport(dry_run=dry_run, manifest=manifest, warnings=key_warnings(manifest))

        if not _is_empty() and not force:
            raise RestoreError(
                "This instance already has data (communities or accounts). A whole-instance restore is meant "
                "for a fresh installation; it replaces everything. Pass --force to replace this instance's "
                "data with the backup."
            )
        report.replaced = existing_rows()

        plan = _load_plan(manifest)
        referenced_media: set[str] = set()

        if dry_run:
            for member, allowed in plan:
                progress(f"Reading {member}…")
                _load_member(zf, member, allowed, manifest["members"][member]["models"], report, referenced_media, write=False)
            return report

        undo = MediaUndo()
        try:
            with transaction.atomic():
                _clear()
                for member, allowed in plan:
                    progress(f"Restoring {member}…")
                    _load_member(
                        zf, member, allowed, manifest["members"][member]["models"], report, referenced_media, write=True
                    )
                _verify_database_counts(report)
                connection.check_constraints()
                progress("Restoring invoice PDFs…")
                _restore_media(zf, manifest, referenced_media, report, undo)
                _reconcile_sequences(report)
        except (IntegrityError, DatabaseError) as exc:
            logger.exception("Restore was rejected by the database")
            undo.rollback()
            raise RestoreError(
                "The database rejected the backup's data; nothing was restored. "
                "The server log has the details."
            ) from exc
        except BaseException:
            undo.rollback()
            raise
        finally:
            undo.close()

    _audit(report, force=force)
    return report


def _verify_database_counts(report: RestoreReport) -> None:
    """Every restored table must hold exactly what was loaded into it."""
    for label in _clear_order():
        expected = report.counts.get(label, 0)
        actual = apps.get_model(label)._base_manager.count()
        if actual != expected:
            raise RestoreError(f"{label}: loaded {expected} rows but the table holds {actual}.")


def _audit(report: RestoreReport, *, force: bool) -> None:
    """Record the restore in the (just restored) trail; never fails a finished restore."""
    manifest = report.manifest
    try:
        record_audit_event(
            action_category=AuditActionCategory.SYSTEM,
            action_type=ACTION_RESTORED,
            target_type="instance",
            target_display=manifest.get("instance_name") or "instance",
            summary=f"Instance restored from a backup taken {manifest.get('created_at', 'at an unknown time')}.",
            source=AuditEventSource.MANAGEMENT_COMMAND,
            metadata={
                "backup_created_at": manifest.get("created_at"),
                "backup_instance_name": manifest.get("instance_name"),
                "openzev_version": manifest.get("openzev_version"),
                "records": report.records,
                "communities": len(manifest["zevs"]),
                "invoice_pdfs": report.media_files,
                "forced": force,
                "replaced_existing_rows": sum(report.replaced.values()),
            },
        )
    except Exception:  # noqa: BLE001
        logger.exception("The restore audit event could not be recorded")

