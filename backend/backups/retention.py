"""Retention, expiry and stalled-job recovery (SPEC-2026-09-backup-and-restore §6.4).

Deleting a backup is the one irreversible thing this app does on its own
initiative, so the rules are narrow and each one is written to fail towards
keeping a file:

* **Retention is opt-in.** ``BackupDestination.retention_count`` is ``0`` (keep
  everything) until an administrator sets it.
* **The newest is never deleted.** Retention keeps the newest ``N >= 1`` of each
  kind — the whole instance, or one community — per destination, and it runs
  *after* a backup has completed, never before, so a destination set to keep one
  backup cannot be left with none while its replacement is still being written.
* **Only a safety backup expires by date**, and only when
  ``BACKUP_SAFETY_RETENTION_DAYS`` says so.
* **Nothing in use is deleted.** A backup that a queued or running restore is
  reading, or that a verification is reading, is skipped.
* **A failure is contained.** One unreachable destination is logged and counted;
  the others are still swept.

The row outlives its file, so the history stays readable.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from audit.models import AuditActionCategory, AuditEventSource
from audit.services import record_audit_event

from .models import (
    BackupDestination,
    BackupJob,
    BackupJobStatus,
    BackupJobTrigger,
    RestoreJob,
)
from .storage import DestinationError, delete_from_destination

logger = logging.getLogger(__name__)

ACTION_ARTIFACT_DELETED = "backup.artifact_deleted"

REASON_RETENTION = "retention"
REASON_EXPIRED = "expired"
REASON_MANUAL = "manual"

STEPS = ("expired", "retention", "stalled")

# A job is only called stalled well past its own hard limit, so the sweep can
# never fail one that is still legitimately running.
_GRACE_S = 900
_QUEUED_CUTOFF_S = 4 * 60 * 60


def hard_limit_s() -> int:
    return int(settings.BACKUP_RUNNER_TIMEOUT_S) + _GRACE_S


def protected_ids() -> set:
    """Backups something is reading right now, so they must not be deleted."""
    used = set(
        RestoreJob.objects.filter(status__in=(BackupJobStatus.QUEUED, BackupJobStatus.RUNNING))
        .exclude(source_backup__isnull=True)
        .values_list("source_backup_id", flat=True)
    )
    used |= set(BackupJob.objects.filter(verify_started_at__isnull=False).values_list("pk", flat=True))
    return used


def is_in_use(job) -> bool:
    return job.pk in protected_ids()


def delete_artifact(job, *, reason: str, source: str = AuditEventSource.CELERY, user=None) -> bool:
    """Delete ``job``'s file, record it on the row, and audit it.

    Returns whether a file was actually removed (``False``: it was already gone,
    which still counts as deleted). Raises ``DestinationError`` when the
    destination cannot be reached, leaving the row untouched so the next sweep
    tries again.
    """
    existed = delete_from_destination(job.destination, job.archive_location)
    BackupJob.objects.filter(pk=job.pk, artifact_deleted_at__isnull=True).update(
        artifact_deleted_at=timezone.now(), artifact_deleted_reason=reason,
    )
    try:
        record_audit_event(
            action_category=AuditActionCategory.SYSTEM,
            action_type=ACTION_ARTIFACT_DELETED,
            target_type="backups.BackupJob",
            target=job,
            target_id=str(job.pk),
            target_display=job.archive_name or f"{job.scope} backup",
            summary=f"Backup file deleted ({reason}): {job.archive_name}.",
            user=user,
            zev=job.zev,
            source=source,
            metadata={"reason": reason, "location": job.archive_location, "already_gone": not existed},
        )
    except Exception:  # noqa: BLE001 - the file is gone either way
        logger.exception("Audit event for the deletion of backup %s could not be recorded", job.pk)
    return existed


def _expired(now, in_use):
    return [
        # A backup with no destination (written with ``--path``, or its destination
        # was deleted) is not ours to delete: nothing says where its file may live.
        job for job in BackupJob.objects.select_related("destination", "zev").filter(
            status=BackupJobStatus.COMPLETED, artifact_deleted_at__isnull=True, file_expires_at__lte=now,
            destination__isnull=False,
        )
        if job.pk not in in_use
    ]


def _beyond_retention(in_use):
    doomed = []
    for destination in BackupDestination.objects.filter(retention_count__gt=0):
        kept: dict = defaultdict(int)
        newest_first = (
            BackupJob.objects.select_related("destination", "zev")
            .filter(destination=destination, status=BackupJobStatus.COMPLETED, artifact_deleted_at__isnull=True)
            .exclude(trigger=BackupJobTrigger.PRE_RESTORE)
            .order_by("-completed_at", "-created_at")
        )
        for job in newest_first:
            key = (job.scope, job.zev_id)
            kept[key] += 1
            if kept[key] > destination.retention_count and job.pk not in in_use:
                doomed.append(job)
    return doomed


def _fail_stalled(now, report) -> None:
    """Fail jobs a killed worker left ``queued`` or ``running``, and clear dead verification claims."""
    running_cutoff = now - timedelta(seconds=hard_limit_s())
    queued_cutoff = now - timedelta(seconds=_QUEUED_CUTOFF_S)
    for model, noun in ((BackupJob, "backup"), (RestoreJob, "restore")):
        stuck = model.objects.filter(status=BackupJobStatus.RUNNING, started_at__lt=running_cutoff)
        lost = model.objects.filter(status=BackupJobStatus.QUEUED, created_at__lt=queued_cutoff)
        for queryset, message in (
            (stuck, f"The {noun} did not finish: the worker stopped before it could report."),
            (lost, f"The {noun} was never started. Run it again."),
        ):
            for job in list(queryset):
                if report["dry_run"]:
                    report["stalled"].append(str(job.pk))
                    continue
                changed = model.objects.filter(pk=job.pk, status=job.status).update(
                    status=BackupJobStatus.FAILED, completed_at=now, error_message=message,
                )
                if changed:
                    report["stalled"].append(str(job.pk))
                    logger.warning("Failed stalled %s job %s", noun, job.pk)
    dead_claims = BackupJob.objects.filter(verify_started_at__lt=running_cutoff)
    if not report["dry_run"]:
        dead_claims.update(
            verify_started_at=None, verification_ok=False, verified_at=now,
            verification_message="The check did not finish: the worker stopped before it could report.",
        )


def sweep(*, steps=STEPS, dry_run: bool = False, source: str = AuditEventSource.CELERY) -> dict:
    """Run the requested steps and report what was (or, for ``dry_run``, would be) done.

    ``{"expired": [...], "retention": [...], "stalled": [...], "errors": n, "dry_run": bool}``
    where the first two list archive names.
    """
    now = timezone.now()
    report: dict = {"expired": [], "retention": [], "stalled": [], "errors": 0, "dry_run": dry_run}
    in_use = protected_ids()

    for step, reason, jobs in (
        ("expired", REASON_EXPIRED, lambda: _expired(now, in_use)),
        ("retention", REASON_RETENTION, lambda: _beyond_retention(in_use)),
    ):
        if step not in steps:
            continue
        for job in jobs():
            if dry_run:
                report[step].append(job.archive_name)
                continue
            try:
                delete_artifact(job, reason=reason, source=source)
                report[step].append(job.archive_name)
            except DestinationError as exc:
                report["errors"] += 1
                logger.warning("Could not delete backup %s (%s): %s", job.pk, reason, exc)
            except Exception:  # noqa: BLE001 - one bad row must not stop the sweep
                report["errors"] += 1
                logger.exception("Unexpected error deleting backup %s", job.pk)

    if "stalled" in steps:
        _fail_stalled(now, report)
    return report
