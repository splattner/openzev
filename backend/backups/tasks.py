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
from .models import BackupJob, BackupJobStatus
from .storage import DestinationError, store_archive

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
