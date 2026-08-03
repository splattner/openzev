import uuid

from django.conf import settings
from django.db import models


class AuditActionCategory(models.TextChoices):
    AUTH = "auth", "Auth"
    GOVERNANCE = "governance", "Governance"
    PARTICIPANT = "participant", "Participant"
    METERING = "metering", "Metering"
    TARIFF = "tariff", "Tariff"
    INVOICE = "invoice", "Invoice"
    IMPORT = "import", "Import"
    TEMPLATE = "template", "Template"
    SYSTEM = "system", "System"


class AuditEventStatus(models.TextChoices):
    STARTED = "started", "Started"
    QUEUED = "queued", "Queued"
    SUCCESS = "success", "Success"
    FAILED = "failed", "Failed"
    DENIED = "denied", "Denied"


class AuditEventSource(models.TextChoices):
    API = "api", "API"
    # A request authenticated with an API key. Distinct from ``API`` so an
    # action taken by a script is traceable to the credential that took it,
    # not only to the person who owns it.
    API_KEY = "api_key", "API key"
    CELERY = "celery", "Celery"
    SYSTEM = "system", "System"
    MANAGEMENT_COMMAND = "management_command", "Management command"


class AuditEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    actor_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="audit_events",
        null=True,
        blank=True,
    )
    actor_role_snapshot = models.CharField(max_length=20, blank=True, default="")
    actor_display = models.CharField(max_length=255, blank=True, default="")

    zev = models.ForeignKey(
        "zev.Zev",
        on_delete=models.SET_NULL,
        related_name="audit_events",
        null=True,
        blank=True,
    )

    action_category = models.CharField(max_length=40, choices=AuditActionCategory.choices)
    action_type = models.CharField(max_length=80)
    target_type = models.CharField(max_length=120)
    target_id = models.CharField(max_length=64, blank=True, default="")
    target_display = models.CharField(max_length=255, blank=True, default="")
    status = models.CharField(
        max_length=20,
        choices=AuditEventStatus.choices,
        default=AuditEventStatus.SUCCESS,
    )

    request_id = models.CharField(max_length=64, blank=True, null=True)
    correlation_id = models.CharField(max_length=64, blank=True, null=True)
    source = models.CharField(
        max_length=20,
        choices=AuditEventSource.choices,
        default=AuditEventSource.API,
    )
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    user_agent = models.TextField(blank=True, default="")

    summary = models.CharField(max_length=500)
    reason = models.TextField(blank=True, default="")
    changes_json = models.JSONField(default=dict, blank=True)
    metadata_json = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["created_at"], name="audit_evt_created_idx"),
            models.Index(fields=["zev", "created_at"], name="audit_evt_zev_created_idx"),
            models.Index(fields=["actor_user", "created_at"], name="audit_evt_actor_created_idx"),
            models.Index(
                fields=["action_category", "created_at"],
                name="audit_evt_actcat_created_idx",
            ),
            models.Index(fields=["target_type", "target_id", "created_at"], name="audit_evt_target_lookup_idx"),
            models.Index(fields=["status", "created_at"], name="audit_evt_status_created_idx"),
        ]

    def __str__(self):
        target = f"{self.target_type}:{self.target_id}" if self.target_id else self.target_type
        return f"{self.action_type} [{self.status}] ({target})"
