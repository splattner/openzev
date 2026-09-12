"""Minting and resolving the bearer link that onboards a participant.

Companion to ``accounts.magic_links``, which serves the same job for a
participant who already has an invoice in hand. This is for the participant
who does not yet: the operator sends this link at founding time or whenever a
new participant joins, before any bill exists to scan a QR from.

Unlike a magic link, this token is not consumed. See
``ParticipantOnboardingToken`` for why it is shaped as a reusable, revocable
bearer credential instead.
"""
import hmac
import secrets
from datetime import timedelta
from urllib.parse import quote

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import Participant, ParticipantOnboardingToken

PREFIX_BYTES = 8
SECRET_BYTES = 32

# A participant who bookmarks the link and reopens it every billing period
# should not write a row per visit, mirroring access_tokens.USE_RECORD_INTERVAL.
USE_RECORD_INTERVAL = timedelta(hours=1)


def generate() -> tuple[str, str]:
    """Return ``(prefix, secret)``."""
    return secrets.token_hex(PREFIX_BYTES), secrets.token_urlsafe(SECRET_BYTES)


def get_or_create_for_participant(participant: Participant) -> ParticipantOnboardingToken:
    """The active token for ``participant``, minting one if there is none.

    Get-or-create, not create: sending the link twice (or copying it after
    already having emailed it) must return the same link rather than silently
    invalidating the one already sitting in an inbox.
    """
    existing = participant.onboarding_tokens.filter(revoked_at__isnull=True).first()
    if existing is not None:
        return existing

    prefix, secret = generate()
    return ParticipantOnboardingToken.objects.create(
        participant=participant, prefix=prefix, secret=secret,
    )


def public_url(token: ParticipantOnboardingToken) -> str:
    """The URL emailed to the participant, or copied by the operator."""
    base = settings.FRONTEND_URL.rstrip("/")
    return f"{base}/join/{token.prefix}?s={quote(token.secret, safe='')}"


def resolve(prefix: str, secret: str) -> ParticipantOnboardingToken | None:
    """The active token for ``prefix`` whose secret matches, else ``None``.

    Every failure looks the same, for the same reason
    ``access_tokens.resolve`` gives: distinguishing "unknown link" from "wrong
    secret" is the one signal that would make walking the keyspace worth
    starting.
    """
    if not prefix or not secret:
        return None

    token = (
        ParticipantOnboardingToken.objects
        .select_related("participant__zev")
        .filter(prefix=prefix, revoked_at__isnull=True)
        .first()
    )
    if token is None:
        return None
    if not hmac.compare_digest(token.secret, secret):
        return None
    return token


def note_use(token: ParticipantOnboardingToken) -> bool:
    """Stamp ``last_used_at``, at most once per :data:`USE_RECORD_INTERVAL`.

    Returns whether the stamp was written, which doubles as the caller's audit
    signal — see ``access_tokens.note_use``, which this mirrors exactly.
    """
    now = timezone.now()
    if token.last_used_at is not None and now - token.last_used_at < USE_RECORD_INTERVAL:
        return False

    with transaction.atomic():
        updated = (
            ParticipantOnboardingToken.objects
            .filter(pk=token.pk)
            .filter(last_used_at=token.last_used_at)
            .update(last_used_at=now)
        )
    if updated:
        token.last_used_at = now
    return bool(updated)


def revoke(token: ParticipantOnboardingToken) -> None:
    """Kill this link. The next send or copy mints a fresh one."""
    token.revoked_at = timezone.now()
    token.save(update_fields=["revoked_at"])


def revoke_active_for_participant(participant: Participant) -> None:
    """Revoke whatever active link exists for ``participant``, if any.

    Called from ``unlink-account``: detaching the account must also kill the
    link, or the participant it was emailed to can simply click it again and
    land back in a freshly recreated account — unlinking would not have cut
    anything.
    """
    participant.onboarding_tokens.filter(revoked_at__isnull=True).update(
        revoked_at=timezone.now()
    )
