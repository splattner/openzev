from __future__ import annotations

import ipaddress
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterable
from uuid import UUID

from .constants import REQUEST_ID_PATTERN
from .models import AuditEvent, AuditEventSource, AuditEventStatus


SENSITIVE_KEYS = {
    "password",
    "token",
    "refresh",
    "access",
    "client_secret",
    "secret_key",
    "email_host_password",
    "authorization",
}

MAX_AUDIT_STRING_LENGTH = 500
MAX_AUDIT_LIST_ITEMS = 20
MAX_AUDIT_DICT_ITEMS = 50


def _truncate_text(value: str, limit: int = MAX_AUDIT_STRING_LENGTH) -> str:
    if len(value) <= limit:
        return value
    return f"{value[: limit - 3]}..."


def _to_primitive(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        if isinstance(value, str):
            return _truncate_text(value)
        return value
    if isinstance(value, (date, datetime, Decimal, UUID)):
        return str(value)
    if isinstance(value, list):
        normalized = [_to_primitive(v) for v in value[:MAX_AUDIT_LIST_ITEMS]]
        if len(value) > MAX_AUDIT_LIST_ITEMS:
            normalized.append(f"...(+{len(value) - MAX_AUDIT_LIST_ITEMS} more)")
        return normalized
    if isinstance(value, tuple):
        return _to_primitive(list(value))
    if isinstance(value, dict):
        normalized = {str(k): _to_primitive(v) for k, v in list(value.items())[:MAX_AUDIT_DICT_ITEMS]}
        if len(value) > MAX_AUDIT_DICT_ITEMS:
            normalized["..."] = f"+{len(value) - MAX_AUDIT_DICT_ITEMS} more"
        return normalized
    return str(value)


def _mask_iban(value: str) -> str:
    value = value.replace(" ", "")
    if len(value) <= 4:
        return "****"
    return f"****{value[-4:]}"


def redact_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    if not metadata:
        return {}

    redacted: dict[str, Any] = {}
    for key, value in metadata.items():
        lower_key = key.lower()
        if lower_key in SENSITIVE_KEYS:
            continue
        if lower_key in {"email_body_template", "body", "template_content", "content"}:
            continue
        if "iban" in lower_key and isinstance(value, str):
            redacted[key] = _mask_iban(value)
            continue
        if isinstance(value, dict):
            nested = redact_metadata(value)
            if nested:
                redacted[key] = nested
            continue
        if isinstance(value, list):
            redacted[key] = _to_primitive(value)
            continue
        redacted[key] = _to_primitive(value)
    return redacted


def build_diff(before: dict[str, Any] | None, after: dict[str, Any] | None, allowed_fields: Iterable[str]) -> dict[str, Any]:
    before = before or {}
    after = after or {}
    diff: dict[str, Any] = {}
    for field in allowed_fields:
        old_value = _to_primitive(before.get(field))
        new_value = _to_primitive(after.get(field))
        if old_value != new_value:
            diff[field] = {"before": old_value, "after": new_value}
    return diff


def build_instance_snapshot(instance: Any, fields: Iterable[str]) -> dict[str, Any]:
    """Capture ``fields`` off a model instance for use with :func:`build_diff`.

    Foreign keys are read from their ``<field>_id`` attribute so the snapshot
    stays a plain scalar and no related row has to be fetched.
    """
    snapshot: dict[str, Any] = {}
    for field in fields:
        fk_attr = f"{field}_id"
        if hasattr(instance, fk_attr):
            fk_value = getattr(instance, fk_attr)
            snapshot[field] = str(fk_value) if fk_value is not None else None
        else:
            snapshot[field] = getattr(instance, field, None)
    return snapshot


def infer_zev(target: Any):
    if target is None:
        return None

    if hasattr(target, "_meta") and getattr(target._meta, "label", "") == "zev.Zev":
        return target

    for attr in ("zev",):
        zev = getattr(target, attr, None)
        if zev is not None:
            return zev

    participant = getattr(target, "participant", None)
    if participant is not None:
        participant_zev = getattr(participant, "zev", None)
        if participant_zev is not None:
            return participant_zev

    metering_point = getattr(target, "metering_point", None)
    if metering_point is not None:
        metering_point_zev = getattr(metering_point, "zev", None)
        if metering_point_zev is not None:
            return metering_point_zev

    return None


def snapshot_actor(user) -> dict[str, Any]:
    if not user or not getattr(user, "is_authenticated", False):
        return {"actor_user": None, "actor_role_snapshot": "", "actor_display": ""}

    display = user.email or user.get_full_name() or user.username
    return {
        "actor_user": user,
        "actor_role_snapshot": getattr(user, "role", ""),
        "actor_display": display,
    }


# Column limits from ``AuditEvent``. Free-text, display, and correlation
# fields are truncated so a long label can never cost the row; lookup
# identifiers (``target_id`` etc.) are left intact so a violation still
# surfaces instead of silently corrupting a reference.
MAX_SUMMARY_LENGTH = 500
MAX_DISPLAY_LENGTH = 255
MAX_CORRELATION_ID_LENGTH = 64
MAX_USER_AGENT_LENGTH = 500


def _coerce_ip_address(value: Any) -> str | None:
    """Return ``value`` when it fits an ``inet`` column, else ``None``.

    Covers non-middleware callers (Celery, management commands) whose context
    never passed through ``config.client_ip``. Scoped IPv6 is excluded because
    PostgreSQL's ``inet`` type cannot store zone identifiers.
    """
    if value is None:
        return None
    candidate = str(value).strip()
    if not candidate:
        return None
    try:
        addr = ipaddress.ip_address(candidate)
    except ValueError:
        return None
    if getattr(addr, "scope_id", None):
        return None
    return candidate


def _sanitize_request_context(
    request_id: Any, ip_address: Any, user_agent: Any
) -> tuple[str | None, str | None, str]:
    """Drop invalid request context before insert; never raise."""
    if not isinstance(request_id, str) or not REQUEST_ID_PATTERN.fullmatch(request_id):
        request_id = None
    return (
        request_id,
        _coerce_ip_address(ip_address),
        _truncate_text(str(user_agent or ""), limit=MAX_USER_AGENT_LENGTH),
    )


def record_audit_event(
    *,
    action_category: str,
    action_type: str,
    target_type: str,
    summary: str,
    target=None,
    target_id: str = "",
    target_display: str = "",
    status: str = AuditEventStatus.SUCCESS,
    request=None,
    user=None,
    zev=None,
    source: str = AuditEventSource.API,
    correlation_id: str | None = None,
    changes: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    reason: str = "",
):
    request_id = None
    ip_address = None
    user_agent = ""
    request_source = source

    if request is not None:
        request_id = getattr(request, "audit_request_id", None)
        ip_address = getattr(request, "audit_ip_address", None)
        user_agent = getattr(request, "audit_user_agent", "")
        request_source = getattr(request, "audit_source", source)
        if user is None:
            user = getattr(request, "user", None)

        # An action taken with an API key is attributed to the credential as
        # well as the person, so a leaked key's blast radius is reconstructable
        # without correlating timestamps by hand.
        api_key = getattr(request, "api_key", None)
        if api_key is not None:
            metadata = {
                **(metadata or {}),
                "api_key_id": str(api_key.pk),
                "api_key_name": api_key.name,
            }

    actor_snapshot = snapshot_actor(user)

    resolved_zev = zev or infer_zev(target)
    if resolved_zev is None and zev is None and request is not None:
        # Best effort for callers that only pass tenant ID in metadata.
        potential_zev = (metadata or {}).get("zev")
        if hasattr(potential_zev, "id"):
            resolved_zev = potential_zev

    # Invalid request context is dropped before insert; a real database
    # failure propagates so the surrounding transaction rolls back.
    request_id, ip_address, user_agent = _sanitize_request_context(
        request_id, ip_address, user_agent
    )

    return AuditEvent.objects.create(
        actor_user=actor_snapshot["actor_user"],
        actor_role_snapshot=actor_snapshot["actor_role_snapshot"],
        actor_display=_truncate_text(actor_snapshot["actor_display"], limit=MAX_DISPLAY_LENGTH),
        zev=resolved_zev,
        action_category=action_category,
        action_type=action_type,
        target_type=target_type,
        target_id=str(target_id or ""),
        target_display=_truncate_text(str(target_display or ""), limit=MAX_DISPLAY_LENGTH),
        status=status,
        request_id=request_id,
        correlation_id=(
            _truncate_text(str(correlation_id), limit=MAX_CORRELATION_ID_LENGTH)
            if correlation_id is not None
            else None
        ),
        source=request_source,
        ip_address=ip_address,
        user_agent=user_agent,
        summary=_truncate_text(summary, limit=MAX_SUMMARY_LENGTH),
        reason=_truncate_text(reason or "", limit=2000),
        changes_json=redact_metadata(changes or {}),
        metadata_json=redact_metadata(metadata or {}),
    )
