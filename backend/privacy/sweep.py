"""Retention for personal data that would otherwise be kept forever (SPEC-2026-10-privacy-retention-sweep).

Three things are swept, each by its own window in settings, and ``0`` turns a
step off so an operator opts in to nothing they did not ask for:

* **Audit network details.** ``AuditEvent.ip_address`` and ``user_agent`` are
  blanked once an event is older than ``PRIVACY_AUDIT_NETWORK_RETENTION_DAYS``.
  The event itself — who did what to which record, and when — stays: this
  scrubs two fields, not the audit history.
* **Invoice email recipients.** ``EmailLog.recipient`` and ``error_message``
  (an SMTP error repeats the address) are blanked after
  ``PRIVACY_EMAIL_LOG_RETENTION_DAYS``. The row is kept, not deleted: the
  newest log per invoice drives the readiness cockpit's "delivery failed" item,
  so deleting it would quietly clear that item for a still-open invoice.
* **Spent one-time tokens.** Verification, magic-link and onboarding tokens
  that are consumed, revoked or expired are deleted ``PRIVACY_TOKEN_GRACE_DAYS``
  after they stopped being usable. A token that can still be used is never
  selected, whatever the grace.

Every step is idempotent and only touches rows that still hold something, so a
second run reports zero.
"""

from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from accounts.models import MAGIC_LINK_LIFETIME, EmailVerificationToken, MagicLinkToken
from audit.models import AuditActionCategory, AuditEvent, AuditEventSource
from audit.services import record_audit_event
from invoices.models import EmailLog
from zev.models import ParticipantOnboardingToken

ACTION_SWEPT = "privacy.swept"

STEPS = ("audit_network", "email_log", "tokens")


def _days(name: str) -> int:
    return max(int(getattr(settings, name, 0) or 0), 0)


def _audit_network(now, dry_run: bool) -> int:
    days = _days("PRIVACY_AUDIT_NETWORK_RETENTION_DAYS")
    if not days:
        return 0
    rows = AuditEvent.objects.filter(created_at__lt=now - timedelta(days=days)).exclude(
        ip_address__isnull=True, user_agent=""
    )
    if dry_run:
        return rows.count()
    return rows.update(ip_address=None, user_agent="")


def _email_log(now, dry_run: bool) -> int:
    days = _days("PRIVACY_EMAIL_LOG_RETENTION_DAYS")
    if not days:
        return 0
    rows = EmailLog.objects.filter(created_at__lt=now - timedelta(days=days)).exclude(
        recipient="", error_message=""
    )
    if dry_run:
        return rows.count()
    return rows.update(recipient="", error_message="")


def _spent_tokens(now, dry_run: bool) -> dict[str, int]:
    """Delete tokens that have been unusable for longer than the grace window."""
    days = _days("PRIVACY_TOKEN_GRACE_DAYS")
    if not days:
        return {}
    cutoff = now - timedelta(days=days)

    verification = Q(consumed_at__lt=cutoff)
    for purpose, lifetime in EmailVerificationToken.LIFETIMES.items():
        verification |= Q(purpose=purpose, created_at__lt=cutoff - lifetime)

    querysets = {
        "email_verification": EmailVerificationToken.objects.filter(verification),
        "magic_link": MagicLinkToken.objects.filter(
            Q(consumed_at__lt=cutoff) | Q(created_at__lt=cutoff - MAGIC_LINK_LIFETIME)
        ),
        "onboarding": ParticipantOnboardingToken.objects.filter(
            Q(revoked_at__lt=cutoff) | Q(expires_at__lt=cutoff)
        ),
    }
    if dry_run:
        return {name: qs.count() for name, qs in querysets.items()}
    return {name: qs.delete()[0] for name, qs in querysets.items()}


def sweep(*, dry_run: bool = False, source: str = AuditEventSource.CELERY) -> dict:
    """Apply every enabled retention window.

    Returns the per-step counts. Outside a dry run, a sweep that changed
    something leaves one ``privacy.swept`` audit event with those counts, so
    the scrubbing itself is traceable; an idle sweep leaves nothing.
    """
    now = timezone.now()
    tokens = _spent_tokens(now, dry_run)
    report = {
        "dry_run": dry_run,
        "audit_network": _audit_network(now, dry_run),
        "email_log": _email_log(now, dry_run),
        "tokens": tokens,
    }
    report["total"] = report["audit_network"] + report["email_log"] + sum(tokens.values())

    if report["total"] and not dry_run:
        record_audit_event(
            action_category=AuditActionCategory.SYSTEM,
            action_type=ACTION_SWEPT,
            target_type="privacy.RetentionSweep",
            target_display="Privacy retention sweep",
            summary=f"Privacy sweep scrubbed or deleted {report['total']} record(s).",
            source=source,
            metadata={key: report[key] for key in ("audit_network", "email_log", "tokens")},
        )
    return report
