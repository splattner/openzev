"""The backup job lifecycle: claim, build, encrypt, store, publish.

Mirrors ``exports.tasks`` (ADR 0017): the job row is persisted before it is
enqueued, the claim is a single guarded ``UPDATE`` so duplicate delivery runs
it once, publication is guarded on the job still being ``running`` so a late
completion cannot overwrite a job someone else already failed, and every
message stored on the row is safe to show an administrator.

``execute_backup_job`` does the work and is called both by the Celery task and
directly by ``manage.py openzev_backup``, which must work on an instance with no
broker running.
"""

from __future__ import annotations

import hashlib
import logging
import tempfile
from pathlib import Path

from billiard.exceptions import SoftTimeLimitExceeded
from celery import shared_task
from django.conf import settings
from django.utils import timezone
from django.utils.text import slugify

from audit.models import AuditActionCategory, AuditEventSource, AuditEventStatus
from audit.services import record_audit_event

from . import archive, crypto
from .models import BackupJob, BackupJobScope, BackupJobStatus, BackupJobTrigger, RestoreJob
from .restore import RestoreError
from .restore_zev import RestoreRefused, restore_zev
from .storage import DestinationError, fetch_from_destination, store_archive

logger = logging.getLogger(__name__)

# Decorate the Celery task, so they must be import-time constants: a soft limit
# at BACKUP_RUNNER_TIMEOUT_S and a hard limit a grace above it, as for exports.
_SOFT_LIMIT_S = int(getattr(settings, "BACKUP_RUNNER_TIMEOUT_S", 10800))
_HARD_GRACE_S = 900
_HARD_LIMIT_S = _SOFT_LIMIT_S + _HARD_GRACE_S

_GENERIC_FAILURE = "The backup could not be completed. The server log has the details."
_INTERRUPTED = "The backup was interrupted by its time limit."
_DIGEST_BLOCK = 1024 * 1024

ACTION_STARTED = "backup.started"
ACTION_COMPLETED = "backup.completed"
ACTION_FAILED = "backup.failed"

ACTION_RESTORE_STARTED = "restore.started"
ACTION_RESTORE_PREVIEWED = "restore.previewed"
ACTION_RESTORED = "zev.restored"
ACTION_RESTORE_FAILED = "restore.failed"


def _audit_best_effort(job, *, action_type, summary, status, source, metadata=None):
    """Record a job audit event without ever replacing the outcome it describes.

    The audit log is a side channel: a failed write must not turn a completed
    backup into an error, nor mask the exception a failed job is about to raise.
    """
    try:
        record_audit_event(
            action_category=AuditActionCategory.SYSTEM,
            action_type=action_type,
            target_type="backups.BackupJob",
            target=job,
            target_id=str(job.pk),
            target_display=job.archive_name or f"{job.scope} backup",
            summary=summary,
            status=status,
            user=job.requester,
            zev=job.zev,
            source=source,
            metadata=metadata or {},
        )
    except Exception:  # noqa: BLE001
        logger.exception("Backup audit event could not be recorded for job %s", job.pk)


def _mark_failed(job, message: str) -> None:
    """Fail the job with a single-row UPDATE that only ever moves it out of ``running``."""
    BackupJob.objects.filter(pk=job.pk, status=BackupJobStatus.RUNNING).update(
        status=BackupJobStatus.FAILED,
        completed_at=timezone.now(),
        error_message=message[:500],
    )


def _digest(path: Path) -> tuple[str, int]:
    sha = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while block := handle.read(_DIGEST_BLOCK):
            sha.update(block)
            size += len(block)
    return sha.hexdigest(), size


def archive_name_for(job, *, encrypted: bool) -> str:
    """``openzev-backup-<label>-<timestamp>-<job>.zip[.enc]``.

    The job id fragment makes the name unique and ties a file on disk back to
    its row; the label is slugified so it is safe as an object key.
    """
    if job.scope == "zev" and job.zev is not None:
        label = f"zev-{slugify(job.zev.name)[:40] or str(job.zev.pk)[:8]}"
    else:
        label = slugify(settings.INSTANCE_NAME)[:40] or "instance"
    stamp = timezone.localtime().strftime("%Y%m%d-%H%M%S")
    return f"openzev-backup-{label}-{stamp}-{str(job.pk)[:8]}.zip" + (".enc" if encrypted else "")


def _summary(manifest: dict) -> dict:
    return {
        "scope": manifest["scope"],
        "zevs": len(manifest["zevs"]),
        "records": sum(manifest["counts"].values()),
        "members": len(manifest["members"]),
        "media_files": sum(z["media"]["files"] for z in manifest["zevs"]),
        "media_missing": sum(len(z["media"]["missing"]) for z in manifest["zevs"]),
    }


def execute_backup_job(job_id, *, source: str = AuditEventSource.CELERY, destination=None) -> dict | None:
    """Claim and execute one queued backup job.

    Returns ``{"location", "bytes", "encrypted"}``, or ``None`` when the claim
    was lost (duplicate delivery: the first claim wins). ``destination``
    overrides the job's own — used by the CLI's ad-hoc ``--path``. Raises after
    the job row and audit trail have recorded a failure, so a caller and the
    Celery log both see the original exception.
    """
    claimed = BackupJob.objects.filter(pk=job_id, status=BackupJobStatus.QUEUED).update(
        status=BackupJobStatus.RUNNING, started_at=timezone.now(),
    )
    if not claimed:
        return None

    job = BackupJob.objects.select_related("zev", "destination", "requester").get(pk=job_id)
    target = destination or job.destination
    _audit_best_effort(
        job, action_type=ACTION_STARTED, status=AuditEventStatus.STARTED, source=source,
        summary=f"Backup started ({job.scope}).",
    )

    try:
        if target is None:
            raise DestinationError("This backup has no destination to write to.")
        fingerprint = crypto.active_fingerprint()

        with tempfile.TemporaryDirectory(dir=settings.BACKUP_WORK_DIR or None) as work:
            plain = Path(work) / "archive.zip"
            with plain.open("wb") as handle:
                manifest = archive.build_archive(
                    handle, scope=job.scope, zev=job.zev, encryption_fingerprint=fingerprint,
                )

            stored = plain
            if fingerprint:
                stored = Path(work) / "archive.zip.enc"
                with plain.open("rb") as clear, stored.open("wb") as sealed:
                    crypto.encrypt_stream(clear, sealed)
                # Free the plaintext copy before the upload: an archive can be
                # large, and this is the peak-disk moment.
                plain.unlink()

            sha256, size = _digest(stored)
            name = archive_name_for(job, encrypted=bool(fingerprint))
            location = store_archive(target, stored, name)
    except SoftTimeLimitExceeded:
        logger.exception("Backup job %s hit its soft time limit", job_id)
        _mark_failed(job, _INTERRUPTED)
        _audit_best_effort(
            job, action_type=ACTION_FAILED, status=AuditEventStatus.FAILED, source=source,
            summary="Backup was interrupted by its time limit.", metadata={"error": "soft time limit"},
        )
        raise
    except (DestinationError, crypto.BackupCryptoError) as exc:
        # These carry messages written to be shown; nothing else does.
        logger.error("Backup job %s failed: %s", job_id, exc)
        _mark_failed(job, str(exc))
        _audit_best_effort(
            job, action_type=ACTION_FAILED, status=AuditEventStatus.FAILED, source=source,
            summary=f"Backup failed: {exc}", metadata={"error": str(exc)},
        )
        raise
    except Exception:
        logger.exception("Backup job %s failed unexpectedly", job_id)
        _mark_failed(job, _GENERIC_FAILURE)
        _audit_best_effort(
            job, action_type=ACTION_FAILED, status=AuditEventStatus.FAILED, source=source,
            summary="Backup failed unexpectedly.",
        )
        raise

    published = BackupJob.objects.filter(pk=job.pk, status=BackupJobStatus.RUNNING).update(
        status=BackupJobStatus.COMPLETED,
        completed_at=timezone.now(),
        archive_name=name,
        archive_location=location,
        archive_bytes=size,
        archive_sha256=sha256,
        encrypted=bool(fingerprint),
        encryption_key_fingerprint=fingerprint,
        manifest_json=manifest,
        error_message="",
    )
    if not published:
        # Someone failed the job while the archive was being built. The artifact
        # is already at its destination; say so rather than silently orphaning it.
        logger.warning(
            "Backup job %s was no longer running when its archive was stored at %s", job_id, location,
        )
        return None

    job.refresh_from_db()
    logger.info("Backup job %s completed: %s (%d bytes)", job_id, location, size)
    _audit_best_effort(
        job, action_type=ACTION_COMPLETED, status=AuditEventStatus.SUCCESS, source=source,
        summary=f"Backup completed ({job.scope}, {'encrypted' if fingerprint else 'NOT encrypted'}).",
        metadata={
            **_summary(manifest),
            "bytes": size,
            "encrypted": bool(fingerprint),
            "destination": target.name,
            "location": location,
        },
    )
    return {"location": location, "bytes": size, "encrypted": bool(fingerprint)}


@shared_task(bind=True, soft_time_limit=_SOFT_LIMIT_S, time_limit=_HARD_LIMIT_S)
def run_backup_job(self, job_id: str):
    """Execute one backup job (see :func:`execute_backup_job`)."""
    return execute_backup_job(job_id)


# ── restoring one community ──────────────────────────────────────────────────

_RESTORE_GENERIC_FAILURE = "The restore could not be completed. Nothing was changed. The server log has the details."
_RESTORE_INTERRUPTED = "The restore was interrupted by its time limit. If it had started writing, it was rolled back."


def _audit_restore_best_effort(job, *, action_type, summary, status, source, metadata=None):
    """Record a restore audit event without ever replacing the outcome it describes."""
    from zev.models import Zev

    try:
        record_audit_event(
            action_category=AuditActionCategory.SYSTEM,
            action_type=action_type,
            target_type="backups.RestoreJob",
            target=job,
            target_id=str(job.pk),
            target_display=f"restore of {job.target_zev_name or job.target_zev_id}",
            summary=summary,
            status=status,
            user=job.requester,
            # Looked up now: the community may have been recreated by this very restore.
            zev=Zev.objects.filter(pk=job.target_zev_id).first(),
            source=source,
            metadata={"dry_run": job.dry_run, "force": job.force, **(metadata or {})},
        )
    except Exception:  # noqa: BLE001
        logger.exception("Restore audit event could not be recorded for job %s", job.pk)


def _mark_restore_failed(job, message: str, plan: dict | None = None) -> None:
    fields = {"status": BackupJobStatus.FAILED, "completed_at": timezone.now(), "error_message": message[:500]}
    if plan is not None:
        fields["plan_json"] = plan
    RestoreJob.objects.filter(pk=job.pk, status=BackupJobStatus.RUNNING).update(**fields)


def _take_safety_backup(job, *, source, destination):
    """A backup of the community as it is now, run to completion before the restore writes anything."""
    from zev.models import Zev

    target = destination or job.safety_destination or (job.source_backup.destination if job.source_backup else None)
    if target is None:
        raise RestoreError(
            "There is nowhere to write the safety backup. Choose a destination; the restore was not started."
        )
    backup = BackupJob.objects.create(
        scope=BackupJobScope.ZEV,
        zev=Zev.objects.get(pk=job.target_zev_id),
        trigger=BackupJobTrigger.PRE_RESTORE,
        destination=None if destination is not None else target,
        requester=job.requester,
    )
    RestoreJob.objects.filter(pk=job.pk).update(safety_backup=backup)
    try:
        execute_backup_job(backup.pk, source=source, destination=destination)
    except Exception:
        backup.refresh_from_db()
        raise RestoreError(
            "The safety backup failed, so nothing was restored"
            + (f": {backup.error_message}" if backup.error_message else ".")
        ) from None
    return str(backup.pk)


def execute_restore_job(job_id, *, source: str = AuditEventSource.CELERY, archive_file=None, safety_destination=None):
    """Claim and execute one queued per-ZEV restore job.

    ``archive_file`` (a local path) replaces the job's ``source_backup`` — used by
    ``manage.py openzev_restore --mode zev``, whose archive is a file or a URL
    rather than a ``BackupJob``. ``safety_destination`` likewise stands in for a
    saved destination. Returns the finished plan, or ``None`` when the claim was
    lost. Raises after the row and audit trail record a failure.
    """
    claimed = RestoreJob.objects.filter(pk=job_id, status=BackupJobStatus.QUEUED).update(
        status=BackupJobStatus.RUNNING, started_at=timezone.now(),
    )
    if not claimed:
        return None

    job = RestoreJob.objects.select_related(
        "source_backup__destination", "safety_destination", "requester",
    ).get(pk=job_id)
    if not job.dry_run:
        _audit_restore_best_effort(
            job, action_type=ACTION_RESTORE_STARTED, status=AuditEventStatus.STARTED, source=source,
            summary=f"Restore of {job.target_zev_name or job.target_zev_id} started.",
        )

    try:
        with tempfile.TemporaryDirectory(dir=settings.BACKUP_WORK_DIR or None) as work:
            path = Path(archive_file) if archive_file is not None else Path(work) / "backup"
            if archive_file is None:
                if job.source_backup is None:
                    raise RestoreError("The backup this restore was created from no longer exists.")
                fetch_from_destination(job.source_backup.destination, job.source_backup.archive_location, path)
            with path.open("rb") as handle:
                result = restore_zev(
                    handle,
                    str(job.target_zev_id),
                    dry_run=job.dry_run,
                    force=job.force,
                    safety_backup=lambda: _take_safety_backup(job, source=source, destination=safety_destination),
                    exclude_job=job.pk,
                )
    except SoftTimeLimitExceeded:
        logger.exception("Restore job %s hit its soft time limit", job_id)
        _mark_restore_failed(job, _RESTORE_INTERRUPTED)
        _audit_restore_best_effort(
            job, action_type=ACTION_RESTORE_FAILED, status=AuditEventStatus.FAILED, source=source,
            summary="Restore was interrupted by its time limit.", metadata={"error": "soft time limit"},
        )
        raise
    except RestoreRefused as exc:
        logger.info("Restore job %s was refused: %s", job_id, exc)
        _mark_restore_failed(job, str(exc), exc.plan)
        _audit_restore_best_effort(
            job, action_type=ACTION_RESTORE_FAILED, status=AuditEventStatus.FAILED, source=source,
            summary=f"Restore refused: {exc}",
            metadata={"error": str(exc), "conflicts": [c["kind"] for c in exc.plan["conflicts"]]},
        )
        raise
    except (RestoreError, archive.ArchiveError, crypto.BackupCryptoError, DestinationError) as exc:
        # These carry messages written to be shown; nothing else does.
        logger.error("Restore job %s failed: %s", job_id, exc)
        details = {"verification_failures": exc.failures} if isinstance(exc, archive.ArchiveError) and exc.failures else None
        _mark_restore_failed(job, str(exc), details)
        _audit_restore_best_effort(
            job, action_type=ACTION_RESTORE_FAILED, status=AuditEventStatus.FAILED, source=source,
            summary=f"Restore failed: {exc}", metadata={"error": str(exc)},
        )
        raise
    except Exception:
        logger.exception("Restore job %s failed unexpectedly", job_id)
        _mark_restore_failed(job, _RESTORE_GENERIC_FAILURE)
        _audit_restore_best_effort(
            job, action_type=ACTION_RESTORE_FAILED, status=AuditEventStatus.FAILED, source=source,
            summary="Restore failed unexpectedly.",
        )
        raise

    plan = result.plan
    published = RestoreJob.objects.filter(pk=job.pk, status=BackupJobStatus.RUNNING).update(
        status=BackupJobStatus.COMPLETED,
        completed_at=timezone.now(),
        plan_json=plan,
        target_zev_name=plan["zev"]["name"] or job.target_zev_name,
        error_message="",
    )
    if not published:
        logger.warning("Restore job %s was no longer running when it finished", job_id)
        return None

    job.refresh_from_db()
    backup = job.source_backup
    if job.dry_run:
        _audit_restore_best_effort(
            job, action_type=ACTION_RESTORE_PREVIEWED, status=AuditEventStatus.SUCCESS, source=source,
            summary=f"Restore of {job.target_zev_name} previewed"
            + (" (it would be refused)." if plan["blocked"] else "."),
            metadata={"conflicts": [c["kind"] for c in plan["conflicts"]]},
        )
    else:
        _audit_restore_best_effort(
            job, action_type=ACTION_RESTORED, status=AuditEventStatus.SUCCESS, source=source,
            summary=f"{job.target_zev_name} restored from the backup of {plan['backup']['created_at']}.",
            metadata={
                "source_backup": str(backup.pk) if backup else job.source_description,
                "backup_created_at": plan["backup"]["created_at"],
                "sections": plan["restored"],
                "accounts_relinked": plan["accounts"]["relink"],
                "accounts_missing": len(plan["accounts"]["missing"]),
                "overridden": [c["kind"] for c in plan["conflicts"]],
                "safety_backup": plan["safety_backup_id"],
            },
        )
    logger.info("Restore job %s completed (dry_run=%s)", job_id, job.dry_run)
    return plan


@shared_task(bind=True, soft_time_limit=_SOFT_LIMIT_S, time_limit=_HARD_LIMIT_S)
def run_restore_job(self, job_id: str):
    """Execute one restore job (see :func:`execute_restore_job`)."""
    return execute_restore_job(job_id)
