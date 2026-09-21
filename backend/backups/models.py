"""Backup destinations and jobs (SPEC-2026-09-backup-and-restore §4).

``BackupJob`` follows the lifecycle ``ExportJob`` established in ADR 0017 —
``queued → running → completed / failed``, persisted before it is enqueued —
but is a separate model: an instance backup has no single ZEV, and its artifact
is far too large to travel as ``bytes`` the way an export's result does.
"""

import uuid
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from . import crypto
from .storage import validate_local_path


class BackupDestinationKind(models.TextChoices):
    LOCAL = "local", "Local directory"
    S3 = "s3", "S3-compatible storage"


class CredentialMode:
    """Where an S3 destination's credentials come from, in order of precedence."""

    ENVIRONMENT = "environment"
    STORED = "stored"
    INSTANCE_ROLE = "instance_role"


class BackupDestination(models.Model):
    """Where finished archives are written: a local directory or an S3 bucket.

    The S3 secret access key is stored Fernet-encrypted under
    ``BACKUP_ENCRYPTION_KEYS`` and is never serialized. When
    ``BACKUP_S3_ACCESS_KEY_ID`` / ``BACKUP_S3_SECRET_ACCESS_KEY`` are set they
    win over anything stored, so a hardened deployment keeps credentials out of
    the database entirely.
    """

    class Meta:
        ordering = ["name", "id"]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True)
    kind = models.CharField(max_length=10, choices=BackupDestinationKind.choices, default=BackupDestinationKind.LOCAL)
    enabled = models.BooleanField(default=True)

    # local
    path = models.CharField(max_length=500, blank=True, default="")

    # s3
    bucket = models.CharField(max_length=255, blank=True, default="")
    prefix = models.CharField(max_length=255, blank=True, default="")
    region = models.CharField(max_length=64, blank=True, default="")
    endpoint_url = models.URLField(max_length=500, blank=True, default="")
    access_key_id = models.CharField(max_length=128, blank=True, default="")
    secret_access_key_encrypted = models.BinaryField(blank=True, default=b"")
    server_side_encryption = models.CharField(max_length=20, blank=True, default="AES256")

    # How many finished backups of each kind (the whole instance, or one
    # community) to keep here; the sweep deletes older ones. ``0`` keeps
    # everything, so retention is something an administrator turns on, never a
    # default that deletes backups on its own.
    retention_count = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return self.name

    # ── credentials ──────────────────────────────────────────────────────────

    @property
    def has_stored_secret(self) -> bool:
        return bool(bytes(self.secret_access_key_encrypted or b""))

    @property
    def credential_mode(self) -> str:
        """``environment`` beats ``stored`` beats ``instance_role`` (boto3's default chain)."""
        if settings.BACKUP_S3_ACCESS_KEY_ID and settings.BACKUP_S3_SECRET_ACCESS_KEY:
            return CredentialMode.ENVIRONMENT
        if self.access_key_id and self.has_stored_secret:
            return CredentialMode.STORED
        return CredentialMode.INSTANCE_ROLE

    @property
    def secret_access_key(self) -> str:
        """The decrypted secret. Computed on access and never cached on the instance."""
        return crypto.decrypt_secret(bytes(self.secret_access_key_encrypted))

    def set_secret_access_key(self, value: str) -> None:
        """Encrypt and store ``value``; an empty value clears it.

        Raises ``ValidationError`` when a secret cannot be encrypted, because a
        secret that cannot be encrypted must not be storable.
        """
        if not value:
            self.secret_access_key_encrypted = b""
            return
        try:
            self.secret_access_key_encrypted = crypto.encrypt_secret(value)
        except crypto.BackupCryptoError as exc:
            raise ValidationError({"secret_access_key": str(exc)}) from exc

    # ── validation ───────────────────────────────────────────────────────────

    def clean(self):
        super().clean()
        errors: dict[str, str] = {}

        if self.kind == BackupDestinationKind.LOCAL:
            if not self.path:
                errors["path"] = "A local destination needs a directory path."
            else:
                problem = validate_local_path(self.path)
                if problem:
                    errors["path"] = problem
            for field in ("bucket", "prefix", "region", "endpoint_url", "access_key_id"):
                if getattr(self, field):
                    errors[field] = "This field applies to S3 destinations only."
            if self.has_stored_secret:
                errors["secret_access_key"] = "This field applies to S3 destinations only."
        elif self.kind == BackupDestinationKind.S3:
            if not self.bucket:
                errors["bucket"] = "An S3 destination needs a bucket."
            if self.path:
                errors["path"] = "This field applies to local destinations only."
            if self.prefix.startswith("/"):
                errors["prefix"] = "The prefix must not start with a slash."
            if bool(self.access_key_id) != self.has_stored_secret and not (
                settings.BACKUP_S3_ACCESS_KEY_ID and settings.BACKUP_S3_SECRET_ACCESS_KEY
            ):
                # Half a credential pair is never what anyone meant: it would
                # fall through to the instance role and fail confusingly later.
                errors["access_key_id"] = "Provide both the access key id and the secret, or neither."

        if errors:
            raise ValidationError(errors)

    @property
    def local_path(self) -> Path:
        return Path(self.path)


class BackupJobScope(models.TextChoices):
    INSTANCE = "instance", "Whole instance"
    ZEV = "zev", "One ZEV"


class BackupJobTrigger(models.TextChoices):
    MANUAL = "manual", "Manual"
    SCHEDULED = "scheduled", "Scheduled"
    PRE_RESTORE = "pre_restore", "Before a restore"


class BackupJobStatus(models.TextChoices):
    QUEUED = "queued", "Queued"
    RUNNING = "running", "Running"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"


class BackupJob(models.Model):
    """One backup operation and, once it completes, the artifact it produced.

    ``manifest_json`` mirrors the archive's manifest so the UI can say what a
    backup holds without fetching it. ``error_message`` only ever holds a
    user-safe summary.
    """

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["status", "started_at"]),
            models.Index(fields=["scope", "created_at"]),
        ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    scope = models.CharField(max_length=10, choices=BackupJobScope.choices, default=BackupJobScope.INSTANCE)
    # SET_NULL so a safety backup outlives the community it protected.
    zev = models.ForeignKey("zev.Zev", on_delete=models.SET_NULL, null=True, blank=True, related_name="backup_jobs")
    trigger = models.CharField(max_length=12, choices=BackupJobTrigger.choices, default=BackupJobTrigger.MANUAL)
    destination = models.ForeignKey(
        BackupDestination, on_delete=models.SET_NULL, null=True, blank=True, related_name="jobs",
    )
    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="backup_jobs",
    )

    status = models.CharField(max_length=20, choices=BackupJobStatus.choices, default=BackupJobStatus.QUEUED)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    archive_name = models.CharField(max_length=255, blank=True, default="")
    archive_location = models.CharField(max_length=1000, blank=True, default="")
    archive_bytes = models.BigIntegerField(null=True, blank=True)
    archive_sha256 = models.CharField(max_length=64, blank=True, default="")
    encrypted = models.BooleanField(default=False)
    encryption_key_fingerprint = models.CharField(max_length=16, blank=True, default="")
    manifest_json = models.JSONField(default=dict, blank=True)
    error_message = models.CharField(max_length=500, blank=True, default="")

    # ── retention (SPEC §6.4) ────────────────────────────────────────────────
    # Only a safety backup expires by date; other backups are kept until the
    # destination's ``retention_count`` or an administrator removes them. The row
    # outlives its file, so the history stays readable.
    file_expires_at = models.DateTimeField(null=True, blank=True)
    artifact_deleted_at = models.DateTimeField(null=True, blank=True)
    artifact_deleted_reason = models.CharField(max_length=10, blank=True, default="")

    # ── verification: the latest re-read of the stored file ──────────────────
    # ``verify_started_at`` is the claim while a verification runs.
    verify_started_at = models.DateTimeField(null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    verification_ok = models.BooleanField(null=True, blank=True)
    verification_message = models.CharField(max_length=500, blank=True, default="")

    def __str__(self) -> str:
        return f"{self.scope} backup {self.pk} ({self.status})"

    @property
    def artifact_available(self) -> bool:
        """A finished backup whose file has not been deleted."""
        return self.status == BackupJobStatus.COMPLETED and self.artifact_deleted_at is None


class RestoreJob(models.Model):
    """One restore of a single community, and the plan it worked from.

    Whole-instance restore is a command run at the shell and leaves an audit
    event, not a row (SPEC-2026-09-backup-and-restore, deviation 11): every
    ``RestoreJob`` is a per-ZEV restore, so there is no ``mode``.

    ``target_zev_id`` is deliberately not a foreign key. A restore may recreate a
    community that has since been deleted, so the target need not exist when the
    job is created, and the row must keep describing it afterwards.
    """

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["status", "target_zev_id"])]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    target_zev_id = models.UUIDField(db_index=True)
    target_zev_name = models.CharField(max_length=200, blank=True, default="")
    source_backup = models.ForeignKey(
        BackupJob, on_delete=models.SET_NULL, null=True, blank=True, related_name="restores",
    )
    # A path or URI given on the command line, where there is no BackupJob row.
    source_description = models.CharField(max_length=500, blank=True, default="")
    # Defaults to the safe value: creating a job never destroys anything by accident.
    dry_run = models.BooleanField(default=True)
    force = models.BooleanField(default=False)

    status = models.CharField(max_length=20, choices=BackupJobStatus.choices, default=BackupJobStatus.QUEUED)
    plan_json = models.JSONField(default=dict, blank=True)
    safety_backup = models.ForeignKey(
        BackupJob, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    safety_destination = models.ForeignKey(
        BackupDestination, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="restore_jobs",
    )

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    error_message = models.CharField(max_length=500, blank=True, default="")

    def __str__(self) -> str:
        return f"restore of {self.target_zev_name or self.target_zev_id} ({self.status})"
