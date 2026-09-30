"""Small shared helpers for shaping tool output (SPEC-2026-mcp-server §6:
"energy as numbers in kWh rounded to 3 decimals"; money stays the string
decimal the REST API already returns)."""

from __future__ import annotations


def kwh(value) -> float | None:
    if value is None:
        return None
    return round(float(value), 3)


def chf(value) -> str | None:
    """Money is passed through as the string the serializer already
    returns — never recomputed, per SPEC-2026-mcp-server §6."""
    if value is None:
        return None
    return str(value)
