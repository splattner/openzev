"""Export job API: create, list/latest, status and download.

Lifecycle rules — persist before enqueueing, suppress duplicate renders,
scope every endpoint to the requester's current ZEV read access — are
explained where each is enforced (async design: ADR 0017).
"""

import logging

from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import FileResponse
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.models import AuditEventStatus
from audit.services import record_audit_event
from zev.models import Zev

from .exporters import (
    EXPORT_DEFINITIONS,
    ExportValidationError,
    validate_export,
)
from .models import ExportJob, ExportJobStatus
from .serializers import ExportJobSerializer
from .tasks import run_export_job

logger = logging.getLogger(__name__)

_CREATE_BODY_ERRORS = {
    "export_type": "export_type is required.",
    "zev_id": "zev_id is required.",
    "params": "params is required.",
}

_ENQUEUE_FAILED_MESSAGE = (
    "The export could not be queued. Please try again."
)


def _zev_or_error(request, zev_id) -> tuple[Zev | None, Response | None]:
    """Fetch ``zev_id`` and confirm the caller may start exports for it."""
    try:
        zev = Zev.objects.get(pk=zev_id)
    except (Zev.DoesNotExist, ValidationError):
        # ValidationError is what the UUID primary key raises for a malformed
        # id; to the caller it is indistinguishable from a missing one.
        return None, Response({"error": "ZEV not found."}, status=status.HTTP_404_NOT_FOUND)
    if not request.user.is_admin and zev.owner != request.user:
        return None, Response({"error": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)
    return zev, None


def _get_owned_job_or_error(request, job_id) -> tuple[ExportJob | None, Response | None]:
    """Fetch a job the caller created and may still read the ZEV of."""
    try:
        job = ExportJob.objects.select_related("zev", "requester").get(pk=job_id)
    except (ExportJob.DoesNotExist, ValidationError):
        return None, Response({"error": "Export job not found."}, status=status.HTTP_404_NOT_FOUND)
    if job.requester_id != request.user.id:
        return None, Response({"error": "Export job not found."}, status=status.HTTP_404_NOT_FOUND)
    if not request.user.is_admin and job.zev.owner != request.user:
        return None, Response({"error": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)
    return job, None


class ExportJobView(APIView):
    """Create and list export jobs.

    ``POST {export_type, zev_id, params}`` creates a job and queues it, with
    ``params`` validated by the export type's validator (annual statements:
    ``{"year": 2026}``); the response is ``202`` with the job. ``GET`` lists
    the caller's own jobs (newest first), optionally narrowed by
    ``?export_type=``/``?zev_id=``.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        queryset = ExportJob.objects.filter(requester=request.user).select_related("zev")
        if not request.user.is_admin:
            # Same rule as status/download: losing ZEV read access hides the
            # job's metadata too.
            queryset = queryset.filter(zev__owner=request.user)
        export_type = request.query_params.get("export_type")
        zev_id = request.query_params.get("zev_id")
        if export_type:
            queryset = queryset.filter(export_type=export_type)
        if zev_id:
            queryset = queryset.filter(zev_id=zev_id)
        try:
            limit = max(1, min(int(request.query_params.get("limit", 20)), 100))
        except (TypeError, ValueError):
            limit = 20

        jobs = list(queryset[:limit])
        return Response(ExportJobSerializer(jobs, many=True).data)

    def post(self, request, *args, **kwargs):
        export_type = request.data.get("export_type")
        zev_id = request.data.get("zev_id")
        params = request.data.get("params")

        if not export_type:
            return Response({"error": _CREATE_BODY_ERRORS["export_type"]},
                            status=status.HTTP_400_BAD_REQUEST)
        if not zev_id:
            return Response({"error": _CREATE_BODY_ERRORS["zev_id"]},
                            status=status.HTTP_400_BAD_REQUEST)
        if not isinstance(params, dict):
            return Response({"error": _CREATE_BODY_ERRORS["params"]},
                            status=status.HTTP_400_BAD_REQUEST)

        zev, error = _zev_or_error(request, zev_id)
        if error:
            return error

        try:
            cleaned_params = validate_export(export_type, zev, params)
        except ExportValidationError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        # A repeat request for an identical inflight job (same requester, ZEV
        # and params) returns that job instead of rendering the same data
        # twice. Params are JSON, so the match runs in Python across all
        # active jobs — the newest alone would miss an older matching one.
        # (Best-effort: two truly concurrent requests can still race past it.)
        active_jobs = list(
            ExportJob.objects.filter(
                export_type=export_type,
                zev=zev,
                requester=request.user,
                status__in=[ExportJobStatus.QUEUED, ExportJobStatus.RUNNING],
            ).order_by("-created_at")
        )
        existing = next(
            (
                candidate
                for candidate in active_jobs
                if candidate.params == cleaned_params
            ),
            None,
        )
        if existing is not None:
            return Response(
                {
                    "detail": "Export already queued.",
                    "job": ExportJobSerializer(existing).data,
                },
                status=status.HTTP_202_ACCEPTED,
            )

        job = ExportJob.objects.create(
            export_type=export_type,
            zev=zev,
            requester=request.user,
            params=cleaned_params,
        )
        definition = EXPORT_DEFINITIONS[job.export_type]
        action_prefix = definition.audit_prefix
        category = definition.audit_category
        try:
            record_audit_event(
                request=request,
                action_category=category,
                action_type=f"{action_prefix}.created",
                target_type="exports.ExportJob",
                target=job,
                target_id=str(job.pk),
                target_display=definition.display_for(zev, cleaned_params),
                summary=definition.created_summary_for(zev, cleaned_params),
                status=AuditEventStatus.QUEUED,
                metadata=definition.audit_metadata_for(cleaned_params),
            )
        except Exception:  # noqa: BLE001 - a lost audit line must not drop the job
            logger.exception("Export creation audit event could not be recorded")

        # The row is committed (autocommit) before enqueueing. If the broker
        # is down the task cannot be delivered: mark the job failed so the
        # user sees a real error and the sweep does not later "recover" a job
        # that was never actually queued.
        try:
            transaction.on_commit(lambda: run_export_job.delay(str(job.pk)))
        except Exception:  # noqa: BLE001
            logger.exception("Export job %s could not be enqueued", job.pk)
            ExportJob.objects.filter(pk=job.pk).update(
                status=ExportJobStatus.FAILED,
                error_message=_ENQUEUE_FAILED_MESSAGE[:500],
            )
            try:
                record_audit_event(
                    request=request,
                    action_category=category,
                    action_type=f"{action_prefix}.failed",
                    target_type="exports.ExportJob",
                    target=job,
                    target_id=str(job.pk),
                    target_display=definition.display_for(zev, cleaned_params),
                    summary=definition.enqueue_failed_summary_for(zev, cleaned_params),
                    status=AuditEventStatus.FAILED,
                    metadata={"error": "enqueue failed"},
                )
            except Exception:  # noqa: BLE001
                logger.exception("Enqueue-failure audit event could not be recorded")
            return Response(
                {"error": _ENQUEUE_FAILED_MESSAGE},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return Response(
            {
                "detail": "Export queued.",
                "job": ExportJobSerializer(job).data,
            },
            status=status.HTTP_202_ACCEPTED,
        )


class ExportJobStatusView(APIView):
    """Progress state and download availability of one of the caller's jobs."""

    permission_classes = [IsAuthenticated]

    def get(self, request, pk, *args, **kwargs):
        job, error = _get_owned_job_or_error(request, pk)
        if error:
            return error
        return Response(ExportJobSerializer(job).data)


class ExportJobDownloadView(APIView):
    """Serve the completed artifact, re-checking access and expiry."""

    permission_classes = [IsAuthenticated]

    def get(self, request, pk, *args, **kwargs):
        job, error = _get_owned_job_or_error(request, pk)
        if error:
            return error
        if job.status != ExportJobStatus.COMPLETED:
            return Response(
                {"error": "Export is not ready."}, status=status.HTTP_404_NOT_FOUND,
            )
        if not job.result_file or job.expired:
            return Response(
                {
                    "error": (
                        "The export download has expired. "
                        "Prepare a new export to get current data."
                    )
                },
                status=status.HTTP_410_GONE,
            )

        filename = EXPORT_DEFINITIONS[job.export_type].filename(job.params)
        return FileResponse(
            job.result_file.open("rb"),
            content_type="application/zip",
            as_attachment=True,
            filename=filename,
        )
