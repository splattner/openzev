import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

# ``oza_<prefix>_<secret>``: marks a leaked token as an analytics token and keeps
# it from parsing as an API key (``ozv``) or a push token (``ozs``).
TOKEN_NAMESPACE = "oza"


class AnalyticsToken(models.Model):
    """A read-only credential for the analytics dataset of one ZEV or one participant.

    It exists for tools that cannot hold a user session (Grafana's Infinity
    datasource, a spreadsheet refresh) and should not hold a whole API key
    either: it reaches ``/api/v1/analytics/series/`` and nothing else, for the
    ZEV it names (or, with ``participant`` set, only that participant's rows).
    Only the hash is stored; the secret is shown once at creation.

    A token never exceeds its creator: every request re-checks that
    ``created_by`` can still see what the token is scoped to, so a manager who
    loses their grant takes their tokens with them.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, help_text="What this token is used for.")
    zev = models.ForeignKey("zev.Zev", on_delete=models.CASCADE, related_name="analytics_tokens")
    participant = models.ForeignKey(
        "zev.Participant",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="analytics_tokens",
        help_text="Narrow the token to this participant's own rows. Empty: the whole ZEV.",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="analytics_tokens"
    )
    # Stored in clear: it identifies the token, it is not a secret.
    prefix = models.CharField(max_length=16, unique=True, db_index=True)
    hashed_key = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "id"]
        indexes = [models.Index(fields=["created_by", "-created_at"], name="analyticstoken_creator_idx")]

    def __str__(self):
        return f"{self.name} ({self.prefix})"

    def clean(self):
        if self.participant_id is not None and self.participant.zev_id != self.zev_id:
            raise ValidationError({"participant": "The participant belongs to another ZEV."})

    @property
    def is_expired(self) -> bool:
        return self.expires_at is not None and timezone.now() >= self.expires_at

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    @property
    def is_active(self) -> bool:
        return not self.is_revoked and not self.is_expired
