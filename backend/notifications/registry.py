"""The notification event types (SPEC-2026-11-notification-center §4.2).

Every type a ``notify()`` call may use is declared here, with who it is for,
what its payload may hold and how repeats are treated. Declaring the payload
keys is what keeps personal data out: ``notify()`` rejects any other key.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .models import NotificationAudience


@dataclass(frozen=True)
class EventType:
    key: str
    audience: str
    target_type: str = ""
    payload_keys: frozenset = field(default_factory=frozenset)
    # Security-style types that must never become mutable once preferences exist.
    mandatory: bool = False
    # With a ``dedupe_key``: True updates an unread notification in place, False
    # creates nothing when the recipient already has one ("once").
    coalesce: bool = False
    # How a coalesced payload absorbs the new one: ``merge(old, new) -> payload``.
    merge: Callable[[dict, dict], dict] | None = None


def _merge_day_range(old: dict, new: dict) -> dict:
    merged = dict(new)
    firsts = [value for value in (old.get("first_day"), new.get("first_day")) if value]
    lasts = [value for value in (old.get("last_day"), new.get("last_day")) if value]
    if firsts:
        merged["first_day"] = min(firsts)
    if lasts:
        merged["last_day"] = max(lasts)
    return merged


def _event(key, audience, target_type, payload_keys, **options) -> EventType:
    return EventType(key, audience, target_type, frozenset(payload_keys), **options)


_PARTICIPANT = NotificationAudience.PARTICIPANT
_MANAGER = NotificationAudience.MANAGER

EVENTS: dict[str, EventType] = {
    event.key: event
    for event in (
        _event(
            "invoice.sent", _PARTICIPANT, "invoice", ("invoice_number", "period_start", "period_end", "document_id")
        ),
        _event("document.delivered", _PARTICIPANT, "document", ("document_id", "kind", "title")),
        _event("invoice.paid", _PARTICIPANT, "invoice", ("invoice_number",)),
        _event(
            "metering.data", _PARTICIPANT, "metering_point", ("meter_id", "first_day", "last_day"),
            coalesce=True, merge=_merge_day_range,
        ),
        _event("import.finished", _MANAGER, "import_log", ("import_log_id", "source", "rows_imported", "rows_skipped", "issues")),
        _event("import.failed", _MANAGER, "import_log", ("import_log_id", "source", "rows_skipped", "issues")),
        _event("invoices.generated", _MANAGER, "period", ("period_start", "period_end", "created", "failed")),
        _event("invoices.generation_failed", _MANAGER, "period", ("period_start", "period_end")),
    )
}
