"""JSON-RPC 2.0 constants and error helpers for the MCP transport.

SPEC-2026-mcp-server §5. Hand-rolled rather than the ``mcp`` SDK (ADR 0025
decision 4) — this is the whole protocol surface iteration 1 needs:
``initialize``, ``notifications/initialized``, ``ping``, ``tools/list``,
``tools/call``.
"""

from __future__ import annotations

SUPPORTED_PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26")
PREFERRED_PROTOCOL_VERSION = "2025-06-18"

MAX_BATCH = 10

# JSON-RPC 2.0 reserved error codes.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


def error_object(code: int, message: str, data=None) -> dict:
    error = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return error


def error_response(request_id, code: int, message: str, data=None) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": error_object(code, message, data),
    }


def result_response(request_id, result) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def negotiate_protocol_version(requested: str | None) -> str:
    if requested in SUPPORTED_PROTOCOL_VERSIONS:
        return requested
    return PREFERRED_PROTOCOL_VERSION


def tool_result(*, text: str, structured: dict, is_error: bool = False) -> dict:
    return {
        "content": [{"type": "text", "text": text}],
        "structuredContent": structured,
        "isError": is_error,
    }
