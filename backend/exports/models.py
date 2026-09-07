"""``ExportJob``: one persisted background export operation.

Records the lifecycle (``queued → running → completed / failed``), the
result file and its expiry; how each export type renders, is named and is
audited lives in :mod:`exports.exporters`. Files use the default media
storage that the web service and Celery worker both mount (ADR 0017).
"""

import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class ExportType(models.TextChoices):
    ANNUAL_STATEMENTS = "annual_statements", "Annual statements"


class ExportJobStatus(models.TextChoices):
    QUEUED = "queued", "Queued"
    RUNNING = "running", "Running"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"


class ExportJob(models.Model):
    """One asynchronous export operation.

    ``params`` carries the export-type-specific request, validated per type
    when the job is created; ``error_message`` only ever holds a user-safe
    summary.
    """

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["export_type", "zev", "created_at"]),
            models.Index(fields=["status", "started_at"]),
        ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    export_type = models.CharField(max_length=40, choices=ExportType.choices)
    zev = models.ForeignKey(
        "zev.Zev",
        on_delete=models.PROTECT,
        related_name="export_jobs",
    )
    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="export_jobs",
    )
    params = models.JSONField(default=dict, blank=True)

    status = models.CharField(
        max_length=20,
        choices=ExportJobStatus.choices,
        default=ExportJobStatus.QUEUED,
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    # When the sweep deletes the completed artifact (None until completion);
    # set at completion so later setting changes do not expire served files.
    # The row outlives the file, keeping the audit trail and "expired" state.
    file_expires_at = models.DateTimeField(null=True, blank=True)

    result_file = models.FileField(
        upload_to="exports/", max_length=255, null=True, blank=True,
    )
    generated_count = models.PositiveIntegerField(null=True, blank=True)
    omitted_count = models.PositiveIntegerField(null=True, blank=True)
    omitted_participant_ids = models.JSONField(default=list, blank=True)
    error_message = models.CharField(max_length=500, blank=True, default="")

    @property
    def expired(self) -> bool:
        """True once the completed artifact has passed its retention window."""
        if self.status != ExportJobStatus.COMPLETED or self.file_expires_at is None:
            return False
        return self.file_expires_at <= timezone.now()
