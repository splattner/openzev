"""Minting and resolving the bearer link that onboards a participant.

Companion to ``accounts.magic_links``, which serves the same job for a
participant who already has an invoice in hand. This is for the participant
who does not yet: the operator sends this link at founding time or whenever a
new participant joins, before any bill exists to scan a QR from.

Unlike a magic link, this token is not consumed. See
``ParticipantOnboardingToken`` for why it is shaped as a reusable, revocable
bearer credential with a bounded lifetime instead.
"""
import hmac
import secrets
from datetime import timedelta
from urllib.parse import quote

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import Participant, ParticipantOnboardingToken

PREFIX_BYTES = 8
SECRET_BYTES = 32

# A participant who bookmarks the link and reopens it every billing period
# should not write a row per visit, mirroring access_tokens.USE_RECORD_INTERVAL.
USE_RECORD_INTERVAL = timedelta(hours=1)

# Freshly minted links stay usable for 30 days.
ONBOARDING_LINK_LIFETIME = timedelta(days=30)


def default_expires_at(now=None):
    """When a token minted right now stops working."""
    return (now or timezone.now()) + ONBOARDING_LINK_LIFETIME


def generate() -> tuple[str, str]:
    """Return ``(prefix, secret)``."""
    return secrets.token_hex(PREFIX_BYTES), secrets.token_urlsafe(SECRET_BYTES)


def active_for_participant(participant: Participant):
    """Unrevoked links for ``participant``, live or expired."""
    return participant.onboarding_tokens.filter(revoked_at__isnull=True)


def revoke_active_for_user(user) -> int:
    """Revoke every unrevoked link on all participants linked to ``user``.

    Single UPDATE; returns the revoked count for the audit metadata.
    """
    return ParticipantOnboardingToken.objects.filter(
        participant__user=user, revoked_at__isnull=True
    ).update(revoked_at=timezone.now())


def get_or_create_for_participant(participant: Participant) -> ParticipantOnboardingToken:
    """The active token for ``participant``, minting one if there is none.

    Get-or-create, not create: sending the link twice (or copying it after
    already having emailed it) must return the same link rather than silently
    invalidating the one already sitting in an inbox.

    An expired token is revoked and replaced (new secret), never extended.

    Concurrent copy/send requests serialize on the participant row: the loser
    waits for the winner's commit, then returns the winner's link. The partial
    unique constraint stays as the backstop; a mint that still fails with no
    live winner is retried once before surfacing.
    """
    attempts = 2
    while True:
        try:
            with transaction.atomic():
                locked = Participant.objects.select_for_update().get(pk=participant.pk)
                existing = active_for_participant(locked).first()
                if existing is not None and not existing.is_expired:
                    return existing
                if existing is not None:
                    # Same savepoint as the mint: a failed insert rolls this back.
                    revoke(existing)
                prefix, secret = generate()
                return ParticipantOnboardingToken.objects.create(
                    participant=locked, prefix=prefix, secret=secret,
                    expires_at=default_expires_at(),
                )
        except IntegrityError:
            winner = active_for_participant(participant).first()
            if winner is not None and not winner.is_expired:
                return winner
            attempts -= 1
            if attempts <= 0:
                raise


def public_url(token: ParticipantOnboardingToken) -> str:
    """The URL emailed to the participant, or copied by the operator."""
    base = settings.FRONTEND_URL.rstrip("/")
    return f"{base}/join/{token.prefix}?s={quote(token.secret, safe='')}"


def resolve(prefix: str, secret: str) -> ParticipantOnboardingToken | None:
    """The active token for ``prefix`` whose secret matches, else ``None``.

    Every failure looks the same, for the same reason
    ``access_tokens.resolve`` gives: distinguishing "unknown link" from "wrong
    secret" is the one signal that would make walking the keyspace worth
    starting — and a disabled ZEV must not answer differently from either of
    those, or the link would tell its bearer something about the community's
    current state.
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
    # Compare first: checking the secret before expiry keeps wrong-secret
    # and expired links indistinguishable by timing.
    if not hmac.compare_digest(token.secret, secret):
        return None
    if token.is_expired or token.participant.zev.disabled_at is not None:
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


def revoke_active_for_participant(participant: Participant) -> int:
    """Revoke every unrevoked link for ``participant``, live or expired.

    Returns how many rows were revoked. Called from ``unlink-account`` and
    the password doors: detaching the account (or giving it a password) must
    also kill the link, or the mailed bearer credential keeps working.
    """
    return active_for_participant(participant).update(
        revoked_at=timezone.now()
    )
