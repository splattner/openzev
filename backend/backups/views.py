"""Backup API (SPEC-2026-09-backup-and-restore §5). Admin-only, throughout.

Nothing here is ZEV-scoped: a backup spans the instance, so these views use
``IsAdmin`` directly rather than ``ZevScopedQuerySetMixin`` — an owner restoring
"their" ZEV would be acting on rows from a snapshot holding every community.
"""

import logging
from pathlib import Path

from django.conf import settings
from django.db import models, transaction
from django.http import FileResponse
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsAdmin
from zev.models import Zev
from audit.models import AuditActionCategory, AuditEventSource, AuditEventStatus
from audit.services import build_diff, build_instance_snapshot, record_audit_event

from . import crypto
from .models import BackupDestination, BackupJob, BackupJobStatus, RestoreJob
from .serializers import (
    BackupDestinationSerializer,
    BackupJobCreateSerializer,
    BackupJobSerializer,
    BackupScheduleSerializer,
    RestoreJobCreateSerializer,
    RestoreJobSerializer,
)
from . import retention, schedule
from .health import backup_health, latest_jobs
from .storage import DestinationError, probe_destination
from .tasks import (
    ACTION_FAILED,
    ACTION_RESTORE_FAILED,
    claim_verification,
    run_backup_job,
    run_restore_job,
    run_verify_job,
)

logger = logging.getLogger(__name__)

# The secret is deliberately not tracked: the audit diff must never carry a
# credential, and "rotated" is recorded as a boolean instead.
DESTINATION_TRACKED_FIELDS = (
    "name", "kind", "enabled", "path", "bucket", "prefix", "region", "endpoint_url",
    "access_key_id", "server_side_encryption", "retention_count",
)

_ENQUEUE_FAILED = "The backup could not be queued. Please try again."
_RESTORE_ENQUEUE_FAILED = "The restore could not be queued. Please try again."


def _record_destination_event(request, *, action_type, destination, summary, changes=None, metadata=None):
    """A destination change is GOVERNANCE, like the other privileged config
    endpoints (OAuth providers): repointing a destination decides where every
    future backup of the instance's data goes."""
    record_audit_event(
        request=request,
        action_category=AuditActionCategory.GOVERNANCE,
        action_type=action_type,
        target_type="backups.BackupDestination",
        target=destination,
        target_id=str(destination.pk),
        target_display=destination.name,
        summary=summary,
        changes=changes,
        metadata=metadata,
    )


class BackupDestinationListCreateView(generics.ListCreateAPIView):
    queryset = BackupDestination.objects.all()
    serializer_class = BackupDestinationSerializer
    permission_classes = [IsAdmin]

    def perform_create(self, serializer):
        destination = serializer.save()
        _record_destination_event(
            self.request,
            action_type="backup_destination.create",
            destination=destination,
            summary=f"Created backup destination {destination.name}.",
            changes=build_diff(
                {}, build_instance_snapshot(destination, DESTINATION_TRACKED_FIELDS), DESTINATION_TRACKED_FIELDS,
            ),
            metadata={"credential_mode": destination.credential_mode},
        )


class BackupDestinationDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = BackupDestination.objects.all()
    serializer_class = BackupDestinationSerializer
    permission_classes = [IsAdmin]

    def perform_update(self, serializer):
        before = build_instance_snapshot(self.get_object(), DESTINATION_TRACKED_FIELDS)
        old_secret = bytes(self.get_object().secret_access_key_encrypted or b"")
        destination = serializer.save()
        _record_destination_event(
            self.request,
            action_type="backup_destination.update",
            destination=destination,
            summary=f"Updated backup destination {destination.name}.",
            changes=build_diff(
                before, build_instance_snapshot(destination, DESTINATION_TRACKED_FIELDS), DESTINATION_TRACKED_FIELDS,
            ),
            metadata={"secret_changed": bytes(destination.secret_access_key_encrypted or b"") != old_secret},
        )

    def destroy(self, request, *args, **kwargs):
        # A destination is how a backup's file is found again — to restore it, verify
        # it, download it, or delete it. Removing one that still holds files would
        # strand them, so it is refused until they are gone (or it is only disabled).
        instance = self.get_object()
        holding = BackupJob.objects.filter(destination=instance).filter(
            models.Q(status__in=(BackupJobStatus.QUEUED, BackupJobStatus.RUNNING))
            | models.Q(status=BackupJobStatus.COMPLETED, artifact_deleted_at__isnull=True)
        ).count()
        if holding:
            return Response(
                {
                    "detail": (
                        f"{holding} backup(s) are stored here or still running. Delete their files first, "
                        "or disable this destination instead."
                    )
                },
                status=status.HTTP_409_CONFLICT,
            )
        return super().destroy(request, *args, **kwargs)

    def perform_destroy(self, instance):
        destination_id, name = str(instance.pk), instance.name
        instance.delete()
        # Only reachable once no file is stored here, so nothing is stranded.
        record_audit_event(
            request=self.request,
            action_category=AuditActionCategory.GOVERNANCE,
            action_type="backup_destination.delete",
            target_type="backups.BackupDestination",
            target_id=destination_id,
            target_display=name,
            summary=f"Deleted backup destination {name}.",
        )


class BackupDestinationTestView(APIView):
    """Write and delete a small probe object, proving the destination is usable."""

    permission_classes = [IsAdmin]

    def post(self, request, pk):
        destination = generics.get_object_or_404(BackupDestination, pk=pk)
        try:
            probe_destination(destination)
        except DestinationError as exc:
            # Deliberate: a DestinationError is never a traceback. Its message is
            # written to be shown (see storage.py) and never carries credentials
            # or a raw provider response; anything else is a 500, not this branch.
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"ok": True})


class BackupJobListCreateView(APIView):
    permission_classes = [IsAdmin]

    def get(self, request):
        queryset = BackupJob.objects.select_related("destination", "zev")
        scope = request.query_params.get("scope")
        job_status = request.query_params.get("status")
        if scope:
            queryset = queryset.filter(scope=scope)
        if job_status:
            queryset = queryset.filter(status=job_status)
        try:
            limit = max(1, min(int(request.query_params.get("limit", 25)), 100))
        except (TypeError, ValueError):
            limit = 25
        return Response(BackupJobSerializer(queryset[:limit], many=True).data)

    def post(self, request):
        serializer = BackupJobCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        job = BackupJob.objects.create(
            scope=data["scope"], zev=data["zev"], destination=data["destination"], requester=request.user,
        )
        record_audit_event(
            request=request,
            action_category=AuditActionCategory.SYSTEM,
            action_type="backup.created",
            target_type="backups.BackupJob",
            target=job,
            target_id=str(job.pk),
            target_display=f"{job.scope} backup",
            summary=f"Backup queued ({job.scope}) to {data['destination'].name}.",
            status=AuditEventStatus.QUEUED,
            zev=job.zev,
            metadata={"destination": data["destination"].name},
        )

        # The row is committed (autocommit) before enqueueing. If the broker is
        # down the task cannot be delivered: fail the job so the user sees a real
        # error instead of a 202 for work that will never run (ADR 0017).
        try:
            transaction.on_commit(lambda: run_backup_job.delay(str(job.pk)))
        except Exception:  # noqa: BLE001
            logger.exception("Backup job %s could not be enqueued", job.pk)
            BackupJob.objects.filter(pk=job.pk).update(status=BackupJobStatus.FAILED, error_message=_ENQUEUE_FAILED)
            record_audit_event(
                request=request,
                action_category=AuditActionCategory.SYSTEM,
                action_type=ACTION_FAILED,
                target_type="backups.BackupJob",
                target=job,
                target_id=str(job.pk),
                summary="Backup could not be queued.",
                status=AuditEventStatus.FAILED,
                zev=job.zev,
                metadata={"error": "enqueue failed"},
            )
            return Response({"detail": _ENQUEUE_FAILED}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        job = BackupJob.objects.select_related("destination", "zev").get(pk=job.pk)
        return Response(BackupJobSerializer(job).data, status=status.HTTP_202_ACCEPTED)


class BackupJobDetailView(generics.RetrieveAPIView):
    queryset = BackupJob.objects.select_related("destination", "zev")
    serializer_class = BackupJobSerializer
    permission_classes = [IsAdmin]


class BackupJobDownloadView(APIView):
    """Stream a finished archive from a local destination.

    S3 artifacts are fetched from the bucket itself: proxying a multi-gigabyte
    object through the application would tie up a worker for the whole transfer
    and duplicate what the storage service does better.
    """

    permission_classes = [IsAdmin]

    def get(self, request, pk):
        job = generics.get_object_or_404(BackupJob.objects.select_related("destination"), pk=pk)
        if job.status != BackupJobStatus.COMPLETED:
            return Response({"detail": "This backup has no artifact to download."}, status=status.HTTP_409_CONFLICT)
        if job.archive_location.startswith("s3://"):
            return Response(
                {"detail": f"This archive is in object storage; download it from {job.archive_location}."},
                status=status.HTTP_409_CONFLICT,
            )

        if job.artifact_deleted_at is not None:
            return Response({"detail": "This backup's file has been deleted."}, status=status.HTTP_410_GONE)

        path = Path(job.archive_location)
        # The location is written by the runner, but it is still a path read from
        # the database: only ever serve a file inside the destination it names.
        destination = job.destination
        if destination is None or destination.kind != "local":
            return Response(
                {"detail": "The destination this archive was written to no longer exists."},
                status=status.HTTP_410_GONE,
            )
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(Path(destination.path).resolve())
        except (FileNotFoundError, ValueError):
            return Response({"detail": "The archive file is no longer available."}, status=status.HTTP_410_GONE)

        return FileResponse(resolved.open("rb"), as_attachment=True, filename=job.archive_name)


class RestoreJobListCreateView(APIView):
    """Per-ZEV restores: preview (``dry_run``, the default) and apply.

    Admin-only, and not scoped: the community is a parameter checked against the
    backup's own manifest. Whole-instance restore is deliberately absent.
    """

    permission_classes = [IsAdmin]

    def get(self, request):
        queryset = RestoreJob.objects.select_related("source_backup")
        target = request.query_params.get("zev_id")
        if target:
            queryset = queryset.filter(target_zev_id=target)
        try:
            limit = max(1, min(int(request.query_params.get("limit", 25)), 100))
        except (TypeError, ValueError):
            limit = 25
        return Response(RestoreJobSerializer(queryset[:limit], many=True).data)

    def post(self, request):
        serializer = RestoreJobCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        if RestoreJob.objects.filter(
            target_zev_id=data["target_zev_id"], status__in=(BackupJobStatus.QUEUED, BackupJobStatus.RUNNING)
        ).exists():
            return Response(
                {"detail": "Another restore of this community is already queued or running."},
                status=status.HTTP_409_CONFLICT,
            )

        job = RestoreJob.objects.create(
            target_zev_id=data["target_zev_id"],
            target_zev_name=data["target_name"],
            source_backup=data["backup"],
            dry_run=data["dry_run"],
            force=data["force"],
            safety_destination=data["safety_destination"],
            requester=request.user,
        )
        record_audit_event(
            request=request,
            action_category=AuditActionCategory.SYSTEM,
            action_type="restore.created",
            target_type="backups.RestoreJob",
            target=job,
            target_id=str(job.pk),
            target_display=f"restore of {job.target_zev_name}",
            summary=f"{'Preview of a' if job.dry_run else 'A'} restore of {job.target_zev_name} queued.",
            status=AuditEventStatus.QUEUED,
            zev=Zev.objects.filter(pk=job.target_zev_id).first(),
            metadata={"source_backup": str(data["backup"].pk), "dry_run": job.dry_run, "force": job.force},
        )

        try:
            transaction.on_commit(lambda: run_restore_job.delay(str(job.pk)))
        except Exception:  # noqa: BLE001
            logger.exception("Restore job %s could not be enqueued", job.pk)
            RestoreJob.objects.filter(pk=job.pk).update(
                status=BackupJobStatus.FAILED, error_message=_RESTORE_ENQUEUE_FAILED
            )
            record_audit_event(
                request=request,
                action_category=AuditActionCategory.SYSTEM,
                action_type=ACTION_RESTORE_FAILED,
                target_type="backups.RestoreJob",
                target=job,
                target_id=str(job.pk),
                summary="Restore could not be queued.",
                status=AuditEventStatus.FAILED,
                metadata={"error": "enqueue failed"},
            )
            return Response({"detail": _RESTORE_ENQUEUE_FAILED}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        job = RestoreJob.objects.select_related("source_backup").get(pk=job.pk)
        return Response(RestoreJobSerializer(job).data, status=status.HTTP_202_ACCEPTED)


class RestoreJobDetailView(generics.RetrieveAPIView):
    queryset = RestoreJob.objects.select_related("source_backup")
    serializer_class = RestoreJobSerializer
    permission_classes = [IsAdmin]


class BackupJobVerifyView(APIView):
    """Re-read a stored backup and record whether it is still intact.

    Asynchronous, like a backup: the check reads (and for S3 downloads) the whole
    archive, which can take minutes. The result lands on the job row
    (``verified_at``, ``verification_ok``, ``verification_message``), which the
    UI already polls.
    """

    permission_classes = [IsAdmin]

    def post(self, request, pk):
        job = generics.get_object_or_404(BackupJob.objects.select_related("destination"), pk=pk)
        if not job.artifact_available:
            return Response(
                {"detail": "This backup has no file to check."}, status=status.HTTP_409_CONFLICT,
            )
        if not claim_verification(job.pk):
            return Response(
                {"detail": "This backup is already being checked."}, status=status.HTTP_409_CONFLICT,
            )
        try:
            transaction.on_commit(lambda: run_verify_job.delay(str(job.pk)))
        except Exception:  # noqa: BLE001
            logger.exception("Verification of backup %s could not be enqueued", job.pk)
            BackupJob.objects.filter(pk=job.pk).update(verify_started_at=None)
            return Response({"detail": "The check could not be queued. Please try again."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        job.refresh_from_db()
        return Response(BackupJobSerializer(job).data, status=status.HTTP_202_ACCEPTED)


class BackupJobArtifactView(APIView):
    """Delete a backup's file (the row stays, so the history does)."""

    permission_classes = [IsAdmin]

    def delete(self, request, pk):
        job = generics.get_object_or_404(BackupJob.objects.select_related("destination", "zev"), pk=pk)
        if not job.artifact_available:
            return Response({"detail": "This backup has no file to delete."}, status=status.HTTP_409_CONFLICT)
        if retention.is_in_use(job):
            return Response(
                {"detail": "A restore or a check is using this backup right now."}, status=status.HTTP_409_CONFLICT,
            )
        try:
            retention.delete_artifact(job, reason=retention.REASON_MANUAL, source=AuditEventSource.API, user=request.user)
        except DestinationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(status=status.HTTP_204_NO_CONTENT)


class BackupScheduleView(APIView):
    """The built-in schedule. A change is a governance decision: it decides when data leaves the instance."""

    permission_classes = [IsAdmin]

    def get(self, request):
        return Response(BackupScheduleSerializer(schedule.get_schedule()).data)

    def put(self, request):
        serializer = BackupScheduleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        before = schedule.get_schedule()
        after = schedule.set_schedule(
            enabled=data["enabled"], frequency=data["frequency"], hour=data["hour"], minute=data["minute"],
            day_of_week=data["day_of_week"],
        )
        fields = ("enabled", "frequency", "hour", "minute", "day_of_week")
        record_audit_event(
            request=request,
            action_category=AuditActionCategory.GOVERNANCE,
            action_type="backup_schedule.update",
            target_type="backups.BackupSchedule",
            target_id=schedule.TASK_NAME,
            target_display="Backup schedule",
            summary="Backup schedule " + ("enabled" if after["enabled"] else "disabled") + ".",
            changes=build_diff({k: before[k] for k in fields}, {k: after[k] for k in fields}, fields),
            metadata={"timezone": after["timezone"]},
        )
        return Response(BackupScheduleSerializer(after).data)


class BackupStatusView(APIView):
    """What the admin UI needs to say honestly whether backups are safe.

    ``encrypted`` is whether a key is *configured*, not whether the last archive
    was encrypted (each job records that itself): it drives the warning shown
    before anyone has run a backup. ``environment_credentials`` explains why a
    destination's stored S3 secret is being ignored. Staleness against a
    schedule arrives with the scheduler (phase 4).
    """

    permission_classes = [IsAdmin]

    def get(self, request):
        try:
            encrypted = crypto.encryption_configured()
            fingerprint = crypto.active_fingerprint()
            key_problem = ""
        except crypto.BackupCryptoError as exc:
            # A configured-but-unusable key must be visible, not read as "no key".
            # The message is one of the fixed sentences in crypto.py, never a
            # traceback, and never contains key material.
            encrypted, fingerprint, key_problem = False, "", str(exc)

        last_ok, last_failed = latest_jobs()
        health = backup_health()
        return Response({
            "encrypted": encrypted,
            "encryption_key_fingerprint": fingerprint,
            "encryption_key_problem": key_problem,
            "environment_credentials": bool(
                settings.BACKUP_S3_ACCESS_KEY_ID and settings.BACKUP_S3_SECRET_ACCESS_KEY
            ),
            "destinations_enabled": health["destinations_enabled"],
            "last_successful": BackupJobSerializer(last_ok).data if last_ok else None,
            "last_failed": BackupJobSerializer(last_failed).data if last_failed else None,
            "age_hours": health["age_hours"],
            "stale": health["stale"],
            "schedule_enabled": health["schedule_enabled"],
            "schedule_interval_hours": health["schedule_interval_hours"],
        })
