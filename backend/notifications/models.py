"""In-app notifications (SPEC-2026-11-notification-center).

A notification is an *event* addressed to one account about one ZEV. It stores
the event type and a small payload, never rendered text: the frontend renders
it in the viewer's language, and no personal data is copied into a row that
outlives its source.
"""

import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class NotificationAudience(models.TextChoices):
    MANAGER = "manager", "Manager"
    PARTICIPANT = "participant", "Participant"


class Notification(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    zev = models.ForeignKey("zev.Zev", on_delete=models.CASCADE, related_name="notifications")
    participant = models.ForeignKey(
        "zev.Participant",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="notifications",
        help_text="The participation a participant-audience notification is about; empty for managers.",
    )
    audience = models.CharField(max_length=12, choices=NotificationAudience.choices)
    type = models.CharField(max_length=40, help_text="A key of notifications.registry.EVENTS.")
    payload = models.JSONField(default=dict, blank=True, help_text="Ids, dates and counts only; no amounts or names.")
    target_type = models.CharField(max_length=40, blank=True, default="")
    target_id = models.CharField(max_length=64, blank=True, default="")
    dedupe_key = models.CharField(max_length=120, blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["recipient", "read_at", "-created_at"], name="notif_recipient_unread"),
            models.Index(fields=["zev"], name="notif_zev"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["recipient", "dedupe_key"],
                condition=~models.Q(dedupe_key="") & models.Q(read_at__isnull=True),
                name="notifications_one_unread_per_dedupe_key",
            ),
            models.CheckConstraint(
                condition=models.Q(audience="manager", participant__isnull=True)
                | models.Q(audience="participant", participant__isnull=False),
                name="notifications_participant_matches_audience",
            ),
        ]

    def __str__(self):
        return f"{self.type} → {self.recipient_id}"
