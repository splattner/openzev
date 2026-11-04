"""``notify()``: the one way a notification is raised (SPEC-2026-11-notification-center §4.2).

Called from the place where the event already happens. It resolves nothing
itself (callers pass the recipients, see ``recipients.py``), writes after the
surrounding transaction commits, and never lets a failure to write reach the
caller: a bell must not make an invoice fail to send.
"""

from __future__ import annotations

import logging
from typing import Iterable

from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import Notification, NotificationAudience
from .registry import EVENTS

logger = logging.getLogger(__name__)


def _normalise(recipients: Iterable, audience: str) -> list[tuple]:
    """Accounts, or ``(account, participant)`` pairs → pairs, validated against the audience."""
    pairs = []
    for item in recipients:
        account, participant = item if isinstance(item, tuple) else (item, None)
        if audience == NotificationAudience.PARTICIPANT and participant is None:
            raise ValueError("A participant notification needs the participation it is about.")
        if audience == NotificationAudience.MANAGER:
            participant = None
        pairs.append((account, participant))
    return pairs


def notify(
    type_key: str,
    *,
    zev,
    recipients: Iterable,
    payload: dict,
    target_id="",
    dedupe_key: str = "",
    exclude: Iterable = (),
) -> None:
    """Queue ``type_key`` for ``recipients`` once the current transaction commits.

    Unknown types and payload keys raise at once: they are programming errors,
    and the registry's whitelist is what keeps personal data out of payloads.
    Everything after that is best effort.
    """
    event = EVENTS.get(type_key)
    if event is None:
        raise ValueError(f"Unknown notification type {type_key!r}.")
    extra = set(payload) - event.payload_keys
    if extra:
        raise ValueError(f"Notification {type_key!r} does not take payload keys {sorted(extra)}.")
    pairs = _normalise(recipients, event.audience)
    excluded = {getattr(account, "pk", account) for account in exclude}
    pairs = [(account, participant) for account, participant in pairs if account.pk not in excluded]
    if not pairs or zev.is_disabled:
        return

    created_at = timezone.now()
    transaction.on_commit(
        lambda: _write(event, zev, pairs, dict(payload), str(target_id or ""), dedupe_key, created_at)
    )


def _write(event, zev, pairs, payload, target_id, dedupe_key, created_at) -> None:
    written = []
    for account, participant in pairs:
        try:
            row = _write_one(event, zev, account, participant, payload, target_id, dedupe_key, created_at)
        except Exception:
            logger.exception("Notification %s for account %s could not be written", event.key, account.pk)
            continue
        if row is not None:
            written.append(row)
    if written:
        _deliver(written)


def _write_one(event, zev, account, participant, payload, target_id, dedupe_key, created_at):
    for _attempt in range(2):
        try:
            with transaction.atomic():
                if dedupe_key and event.coalesce:
                    existing = (
                        Notification.objects.select_for_update()
                        .filter(recipient=account, dedupe_key=dedupe_key, read_at__isnull=True)
                        .first()
                    )
                    if existing is not None:
                        existing.payload = event.merge(existing.payload, payload) if event.merge else payload
                        existing.created_at = created_at
                        existing.save(update_fields=["payload", "created_at"])
                        return existing
                elif dedupe_key and Notification.objects.filter(recipient=account, dedupe_key=dedupe_key).exists():
                    return None
                return Notification.objects.create(
                    recipient=account,
                    zev=zev,
                    participant=participant,
                    audience=event.audience,
                    type=event.key,
                    payload=payload,
                    target_type=event.target_type,
                    target_id=target_id,
                    dedupe_key=dedupe_key,
                    created_at=created_at,
                )
        except IntegrityError:
            # A concurrent writer created the unread row first: coalesce into it on the retry.
            continue
    return None


def _deliver(notifications: list[Notification]) -> None:
    """Delivery-channel seam: the in-app row is the only channel today.

    An email (or push) channel hooks in here, so no call site has to change.
    """
