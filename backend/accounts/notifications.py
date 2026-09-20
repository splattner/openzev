"""Security notification emails: telling people when the way into their account
changes.

A hijacked account is usually noticed by its owner, not by the system — but only
if the owner is told. So every change to how an account is secured (a passkey or
authenticator added or removed, recovery codes regenerated, the password changed,
two-factor reset or sessions ended by an administrator) sends the account's own
address a short notice saying what happened, when, and from where.

Fixed system messages, deliberately not editable templates
(``EMAIL_TEMPLATE_DEFAULTS``): a notice an admin can reword is one that can be
made to stop saying what happened. They cannot be switched off for the same
reason. Sent through Celery so a slow mail server cannot hold up the request
that triggered them, and a failure to send never fails that request.

The email-change confirmation and notice live in ``emails.py``: they are part of
that flow, not a standalone notification.
"""

import logging
from datetime import datetime, timezone as dt_timezone

from django.conf import settings
from django.core.mail import EmailMessage
from django.utils import timezone

logger = logging.getLogger(__name__)

# The person's own doing, or an administrator's: what to do about it differs.
SELF = "self"
ADMIN = "admin"

# event → (subject, what happened, who to turn to). ``{detail}`` is the passkey's
# name where there is one.
EVENTS: dict[str, tuple[str, str, str]] = {
    "passkey_added": (
        "A passkey was added to your OpenZEV account",
        'A passkey ("{detail}") was added to your account.',
        SELF,
    ),
    "passkey_removed": (
        "A passkey was removed from your OpenZEV account",
        'The passkey "{detail}" was removed from your account.',
        SELF,
    ),
    "totp_enabled": (
        "An authenticator app was added to your OpenZEV account",
        "An authenticator app was set up as a second step when you sign in.",
        SELF,
    ),
    "totp_removed": (
        "The authenticator app was removed from your OpenZEV account",
        "The authenticator app was removed from your account.",
        SELF,
    ),
    "recovery_codes_regenerated": (
        "New recovery codes were generated for your OpenZEV account",
        "New recovery codes were generated. The previous ones no longer work.",
        SELF,
    ),
    "password_changed": (
        "Your OpenZEV password was changed",
        "The password of your account was changed. Your other devices were signed out.",
        SELF,
    ),
    "mfa_reset_by_admin": (
        "Two-factor authentication was reset on your OpenZEV account",
        "An administrator reset two-factor authentication on your account. Every passkey, "
        "the authenticator app and all recovery codes were removed, and you were signed out "
        "everywhere. You can sign in with your password and set two-factor up again.",
        ADMIN,
    ),
    "sessions_revoked_by_admin": (
        "You were signed out of OpenZEV everywhere",
        "An administrator signed your account out of every browser and device. "
        "Sign in again to continue.",
        ADMIN,
    ),
}

_ADVICE = {
    SELF: (
        "If this was you, no action is needed. If it was not, sign in and change your "
        "password, review the passkeys and authenticator app under My Account → Security, "
        "and contact your administrator."
    ),
    ADMIN: "If you did not expect this, contact your administrator.",
}


def compose(user, event: str, *, detail: str = "", when: str | None = None, ip: str | None = None) -> tuple[str, str]:
    """The subject and body for ``event`` — pure, so it is easy to test."""
    subject, what, audience = EVENTS[event]
    moment = _format_when(when)
    lines = [
        f"Hello {user.first_name}," if user.first_name else "Hello,",
        "",
        what.format(detail=detail),
        "",
        f"When: {moment}",
    ]
    if ip:
        lines.append(f"From: {ip}")
    lines += [
        "",
        _ADVICE[audience],
        "",
        "You receive this notice for every change to how your account is secured; it cannot be turned off.",
        "",
        "Best regards,",
        "OpenZEV",
    ]
    return subject, "\n".join(lines)


def _format_when(value: str | None) -> str:
    try:
        moment = datetime.fromisoformat(value) if value else timezone.now()
    except ValueError:
        moment = timezone.now()
    return moment.astimezone(dt_timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def notify(user, event: str, *, request=None, detail: str = "") -> None:
    """Tell ``user`` about a security-relevant change to their account.

    Call it as the last step of the action, once it has succeeded. Never raises:
    the action it reports has already happened, so a mail or broker problem must
    not turn it into an error response.
    """
    if event not in EVENTS:
        raise ValueError(f"Unknown security event: {event}")
    if not user.email or not user.is_active:
        return

    from .tasks import send_security_notification

    context = {
        "detail": detail,
        "when": timezone.now().isoformat(),
        # Set by the audit middleware; may be an internal address behind a proxy
        # that is not configured, in which case it is at worst uninformative.
        "ip": getattr(request, "audit_ip_address", None) if request is not None else None,
    }
    try:
        send_security_notification.delay(user.pk, event, context)
    except Exception:
        logger.exception("Could not queue the %s notification for user %s", event, user.pk)


def send(user, event: str, *, detail: str = "", when: str | None = None, ip: str | None = None) -> None:
    """Build and send one notification. Raises on a mail failure so the task can retry."""
    subject, body = compose(user, event, detail=detail, when=when, ip=ip)
    EmailMessage(subject=subject, body=body, from_email=settings.DEFAULT_FROM_EMAIL, to=[user.email]).send(
        fail_silently=False
    )
