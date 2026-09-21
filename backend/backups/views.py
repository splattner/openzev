"""Backup API (SPEC-2026-09-backup-and-restore §5). Admin-only, throughout.

Nothing here is ZEV-scoped: a backup spans the instance, so these views use
``IsAdmin`` directly rather than ``ZevScopedQuerySetMixin`` — an owner restoring
"their" ZEV would be acting on rows from a snapshot holding every community.
"""

import logging
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.http import FileResponse
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsAdmin
from audit.models import AuditActionCategory, AuditEventStatus
from audit.services import build_diff, build_instance_snapshot, record_audit_event

from . import crypto
from .models import BackupDestination, BackupJob, BackupJobStatus
from .serializers import BackupDestinationSerializer, BackupJobCreateSerializer, BackupJobSerializer
from .storage import DestinationError, probe_destination
from .tasks import ACTION_FAILED, run_backup_job

logger = logging.getLogger(__name__)

# The secret is deliberately not tracked: the audit diff must never carry a
# credential, and "rotated" is recorded as a boolean instead.
DESTINATION_TRACKED_FIELDS = (
    "name", "kind", "enabled", "path", "bucket", "prefix", "region", "endpoint_url",
    "access_key_id", "server_side_encryption",
)

_ENQUEUE_FAILED = "The backup could not be queued. Please try again."


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

    def perform_destroy(self, instance):
        destination_id, name = str(instance.pk), instance.name
        instance.delete()
        # Deleting a destination never deletes archives already written there;
        # the jobs keep their recorded location.
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

        last_ok = (
            BackupJob.objects.select_related("destination", "zev")
            .filter(status=BackupJobStatus.COMPLETED).order_by("-completed_at").first()
        )
        last_failed = (
            BackupJob.objects.select_related("destination", "zev")
            .filter(status=BackupJobStatus.FAILED).order_by("-completed_at", "-created_at").first()
        )
        age_hours = (
            round((timezone.now() - last_ok.completed_at).total_seconds() / 3600, 1) if last_ok else None
        )
        return Response({
            "encrypted": encrypted,
            "encryption_key_fingerprint": fingerprint,
            "encryption_key_problem": key_problem,
            "environment_credentials": bool(
                settings.BACKUP_S3_ACCESS_KEY_ID and settings.BACKUP_S3_SECRET_ACCESS_KEY
            ),
            "destinations_enabled": BackupDestination.objects.filter(enabled=True).count(),
            "last_successful": BackupJobSerializer(last_ok).data if last_ok else None,
            "last_failed": BackupJobSerializer(last_failed).data if last_failed else None,
            "age_hours": age_hours,
        })
