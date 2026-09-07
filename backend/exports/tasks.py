"""Celery tasks for the export job lifecycle.

``run_export_job`` executes one claimed job; ``sweep_export_jobs`` deletes
expired artifacts and recovers jobs a killed worker left ``running``. Sweeping
runs on the beat schedule and opportunistically at the start of every job run,
so deployments without a beat process still clean up while jobs execute.
"""

import logging
from datetime import timedelta

from billiard.exceptions import SoftTimeLimitExceeded
from celery import shared_task
from django.conf import settings
from django.core.files.base import ContentFile
from django.db import models
from django.utils import timezone as djtimezone

from audit.models import AuditEventSource, AuditEventStatus
from audit.services import record_audit_event
from .exporters import EXPORT_DEFINITIONS, ExportNotPossibleError, render_export
from .models import ExportJob, ExportJobStatus

logger = logging.getLogger(__name__)

# Safe, user-visible summary of a job that died without producing a file.
_STALE_RUNNING_MESSAGE = (
    "The export did not finish. Prepare a new export to try again."
)

# ── Time budgets ────────────────────────────────────────────────────────────
# These decorate the Celery task, so they must be import-time constants: a
# soft limit at EXPORT_RUNNER_TIMEOUT_S and a hard limit a grace above it.
# The sweep cutoffs sit above both so it never fails a job still within its
# own limits (a lost ``queued`` job gets far longer than any backlog).
_RUNNER_SOFT_LIMIT_S = int(getattr(settings, "EXPORT_RUNNER_TIMEOUT_S", 1800))
_RUNNER_HARD_GRACE_S = 900
_RUNNER_HARD_LIMIT_S = _RUNNER_SOFT_LIMIT_S + _RUNNER_HARD_GRACE_S
_SWEEP_RUNNING_GRACE_S = 900
_SWEEP_QUEUED_CUTOFF_S = 4 * 60 * 60


def _audit_best_effort(job, *, action_type, category, summary, status, metadata=None):
    """Record a job audit event without ever replacing the original outcome.

    The audit log is a side channel: a write failure must not turn a completed
    export into an error, nor mask the exception a failed job is about to
    re-raise.
    """
    definition = EXPORT_DEFINITIONS[job.export_type]
    try:
        record_audit_event(
            action_category=category,
            action_type=action_type,
            target_type="exports.ExportJob",
            target=job,
            target_id=str(job.pk),
            target_display=definition.display_for(job.zev, job.params),
            summary=summary,
            status=status,
            user=job.requester,
            zev=job.zev,
            source=AuditEventSource.CELERY,
            metadata=metadata or {},
        )
    except Exception:  # noqa: BLE001
        logger.exception("Export audit event could not be recorded for job %s", job.pk)


def _delete_orphaned_file(job, stored_name) -> None:
    """Best-effort removal of a file just written; failures are logged only."""
    try:
        if stored_name:
            job.result_file.storage.delete(stored_name)
    except Exception:  # noqa: BLE001
        logger.exception("Orphaned export file could not be removed: %s", stored_name)


def _mark_failed(job, message: str, *, guard=None) -> bool:
    """Mark the job failed with a single-row UPDATE.

    The update keys only on the primary key (plus an optional ``guard``
    filter), never on the in-memory instance, so it cannot write a state the
    caller did not itself observe. Returns whether a row was updated.
    """
    queryset = ExportJob.objects.filter(pk=job.pk)
    if guard is not None:
        queryset = queryset.filter(guard)
    return queryset.update(
        status=ExportJobStatus.FAILED,
        error_message=message[:500],
    ) == 1


def execute_export_job(job_id: str) -> dict | None:
    """Claim and execute one queued export job.

    Returns the outcome counts, or ``None`` when the claim was lost: the job
    was no longer ``queued`` (duplicate task delivery — the first claim wins)
    or the sweep failed it while the render was running. Raises on failure
    after the job row and audit trail have recorded it, so Celery logs the
    original exception.
    """
    now = djtimezone.now()
    claimed = ExportJob.objects.filter(
        pk=job_id, status=ExportJobStatus.QUEUED,
    ).update(status=ExportJobStatus.RUNNING, started_at=now)
    if not claimed:
        return None

    # Claim first, then sweep: the sweep must not fail this job (already
    # claimed and fresh) while it is about to run.
    try:
        sweep_export_jobs_impl()
    except Exception:  # noqa: BLE001 - cleanup must never abort the job
        logger.exception("Opportunistic export sweep failed before job %s", job_id)

    job = ExportJob.objects.select_related("zev", "requester").get(pk=job_id)
    definition = EXPORT_DEFINITIONS[job.export_type]
    action_prefix = definition.audit_prefix
    category = definition.audit_category
    try:
        result = render_export(job)
    except SoftTimeLimitExceeded:
        # Soft limit reached: record the failure, then re-raise so the pool
        # replaces the process.
        logger.exception("Export job %s hit its soft time limit", job_id)
        _mark_failed(job, _STALE_RUNNING_MESSAGE)
        _audit_best_effort(
            job, action_type=f"{action_prefix}.failed", category=category,
            summary=f"Export for ZEV {job.zev.name} was interrupted by its time limit.",
            status=AuditEventStatus.FAILED, metadata={"error": "soft time limit"},
        )
        raise
    except ExportNotPossibleError as exc:
        logger.error("Export job %s failed: %s", job_id, exc)
        _mark_failed(job, str(exc))
        _audit_best_effort(
            job, action_type=f"{action_prefix}.failed", category=category,
            summary=f"Export failed for ZEV {job.zev.name}: {exc}.",
            status=AuditEventStatus.FAILED, metadata={"error": str(exc)},
        )
        raise
    except Exception:
        # Unknown failure: log the traceback; only a generic message is
        # user-safe.
        logger.exception("Export job %s failed unexpectedly", job_id)
        _mark_failed(job, "Could not generate the export.")
        _audit_best_effort(
            job, action_type=f"{action_prefix}.failed", category=category,
            summary=f"Export failed for ZEV {job.zev.name}.",
            status=AuditEventStatus.FAILED,
        )
        raise

    storage_name = f"{job.export_type}-{job.pk}.zip"
    stored_name = None
    try:
        job.result_file.save(storage_name, ContentFile(result.payload), save=False)
        stored_name = job.result_file.name
    except Exception:
        _delete_orphaned_file(job, stored_name)
        logger.exception("Export job %s could not store its result", job_id)
        _mark_failed(job, "Could not generate the export.")
        _audit_best_effort(
            job, action_type=f"{action_prefix}.failed", category=category,
            summary=f"Export failed for ZEV {job.zev.name}.",
            status=AuditEventStatus.FAILED,
        )
        raise

    # Publish only after the file is stored; the UPDATE is guarded on
    # still-``running``, so a sweep that already failed the job cannot be
    # overwritten by the late completion.
    completed_at = djtimezone.now()
    try:
        published = ExportJob.objects.filter(
            pk=job.pk, status=ExportJobStatus.RUNNING,
        ).update(
            status=ExportJobStatus.COMPLETED,
            completed_at=completed_at,
            file_expires_at=completed_at + timedelta(
                hours=int(getattr(settings, "EXPORT_RETENTION_HOURS", 24))
            ),
            result_file=stored_name,
            generated_count=result.generated_count,
            omitted_count=len(result.omitted_ids),
            omitted_participant_ids=result.omitted_ids,
            error_message="",
        )
    except Exception:
        _delete_orphaned_file(job, stored_name)
        logger.exception("Export job %s could not publish its result", job_id)
        _mark_failed(job, "Could not generate the export.")
        _audit_best_effort(
            job, action_type=f"{action_prefix}.failed", category=category,
            summary=f"Export failed for ZEV {job.zev.name}.",
            status=AuditEventStatus.FAILED,
        )
        raise
    if not published:
        # A sweep already failed the job while the render ran on — discard the
        # artifact and do not resurrect the job.
        logger.warning(
            "Export job %s was no longer running when its render finished; "
            "discarding the result", job_id,
        )
        _delete_orphaned_file(job, stored_name)
        return None

    partial = bool(result.omitted_ids)
    logger.info(
        "Export job %s completed for ZEV %s: %d generated, %d omitted",
        job_id, job.zev.name, result.generated_count, len(result.omitted_ids),
    )
    _audit_best_effort(
        job,
        action_type=f"{action_prefix}.completed",
        category=category,
        summary=definition.completed_summary_for(job.zev, job.params, result),
        status=AuditEventStatus.SUCCESS,
        metadata={
            "generated_count": result.generated_count,
            "omitted_count": len(result.omitted_ids),
            "partial": partial,
            "omitted_participant_ids": result.omitted_ids,
        },
    )
    return {
        "generated_count": result.generated_count,
        "omitted_count": len(result.omitted_ids),
    }


@shared_task(
    bind=True,
    soft_time_limit=_RUNNER_SOFT_LIMIT_S,
    time_limit=_RUNNER_HARD_LIMIT_S,
)
def run_export_job(self, job_id: str):
    """Execute one export job (see :func:`execute_export_job`)."""
    return execute_export_job(job_id)


def sweep_export_jobs_impl() -> dict:
    """Delete expired artifacts and fail jobs that can no longer finish.

    Returns ``{"files_deleted": n, "stale_failed": n}``. ``running`` and
    ``queued`` jobs qualify by the cutoff constants above; each is failed and
    audited like a real failure, unless a worker claimed it after the SELECT
    (the per-job UPDATE re-checks the cutoffs).
    """
    now = djtimezone.now()

    expired_jobs = ExportJob.objects.filter(
        status=ExportJobStatus.COMPLETED,
        file_expires_at__lte=now,
    ).exclude(result_file="").exclude(result_file__isnull=True)
    files_deleted = 0
    for job in expired_jobs:
        file_name = job.result_file.name
        try:
            job.result_file.delete(save=False)
        except Exception:  # noqa: BLE001
            logger.exception("Expired export file could not be deleted: %s", file_name)
            continue
        # Guarded update: only clear a name that still points at this file.
        ExportJob.objects.filter(pk=job.pk, result_file=file_name).update(result_file="")
        files_deleted += 1

    stale_running_cutoff = now - timedelta(
        seconds=_RUNNER_HARD_LIMIT_S + _SWEEP_RUNNING_GRACE_S,
    )
    stale_queued_cutoff = now - timedelta(seconds=_SWEEP_QUEUED_CUTOFF_S)
    stale_jobs = list(
        ExportJob.objects.filter(
            models.Q(status=ExportJobStatus.RUNNING, started_at__lte=stale_running_cutoff)
            | models.Q(status=ExportJobStatus.QUEUED, created_at__lte=stale_queued_cutoff)
        ).select_related("zev", "requester")
    )
    stale_failed = 0
    for job in stale_jobs:
        # Re-check the stale criteria inside the UPDATE: a worker may have
        # claimed the job after the SELECT, and failing it now would kill a
        # healthy run. Only transitions that happen are counted and audited.
        if job.status == ExportJobStatus.RUNNING:
            still_stale = models.Q(
                pk=job.pk,
                status=ExportJobStatus.RUNNING,
                started_at__lte=stale_running_cutoff,
            )
        else:
            still_stale = models.Q(
                pk=job.pk,
                status=ExportJobStatus.QUEUED,
                created_at__lte=stale_queued_cutoff,
            )
        if not _mark_failed(job, _STALE_RUNNING_MESSAGE, guard=still_stale):
            continue
        definition = EXPORT_DEFINITIONS[job.export_type]
        _audit_best_effort(
            job,
            action_type=f"{definition.audit_prefix}.failed",
            category=definition.audit_category,
            summary=f"Export for ZEV {job.zev.name} was marked failed after it stalled.",
            status=AuditEventStatus.FAILED,
            metadata={"stale": True},
        )
        stale_failed += 1

    return {"files_deleted": files_deleted, "stale_failed": stale_failed}


@shared_task
def sweep_export_jobs() -> dict:
    """Periodic cleanup for export artifacts (see :func:`sweep_export_jobs_impl`)."""
    return sweep_export_jobs_impl()
