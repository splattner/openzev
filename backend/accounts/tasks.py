"""Celery tasks for account maintenance and account notifications."""

import smtplib
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from .models import OAuthExchangeCode, OAuthState, User


@shared_task
def cleanup_expired_oauth_tokens() -> dict[str, int]:
    """Delete expired OAuth states and exchange codes."""
    now = timezone.now()

    expired_state_cutoff = now - timedelta(minutes=10)
    expired_code_cutoff = now - timedelta(seconds=60)

    deleted_states, _ = OAuthState.objects.filter(created_at__lt=expired_state_cutoff).delete()
    deleted_codes, _ = OAuthExchangeCode.objects.filter(created_at__lt=expired_code_cutoff).delete()

    return {
        "deleted_states": deleted_states,
        "deleted_codes": deleted_codes,
    }


@shared_task(
    autoretry_for=(OSError, smtplib.SMTPException),
    retry_backoff=30,
    retry_kwargs={"max_retries": 3},
)
def send_security_notification(user_id: int, event: str, context: dict) -> None:
    """Email one security notice. Looked up by id at send time, so an account
    deleted, deactivated or left without an address in the meantime gets nothing."""
    from . import notifications

    user = User.objects.filter(pk=user_id, is_active=True).exclude(email="").first()
    if user is None:
        return
    notifications.send(
        user,
        event,
        detail=context.get("detail", ""),
        when=context.get("when"),
        ip=context.get("ip"),
    )
