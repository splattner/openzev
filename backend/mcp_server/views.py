"""``POST /api/v1/mcp/`` — the MCP Streamable HTTP transport, stateless
JSON-response mode (ADR 0025, SPEC-2026-mcp-server §5).

Hand-rolled JSON-RPC 2.0 dispatch: ``initialize``, ``notifications/initialized``,
``ping``, ``tools/list``, ``tools/call``. No ``mcp`` SDK dependency.
"""

from __future__ import annotations

import json
import logging
import time

import jsonschema
from django.conf import settings
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import FeatureFlag
from accounts.permissions import IsZevOwnerOrAdmin
from accounts.throttling import ApiKeyRateThrottle
from audit.models import AuditActionCategory, AuditEventStatus
from audit.services import record_audit_event

from .authentication import McpApiKeyAuthentication
from .protocol import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    MAX_BATCH,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    SUPPORTED_PROTOCOL_VERSIONS,
    error_response,
    negotiate_protocol_version,
    result_response,
    tool_result,
)
from .tools import TOOLS, ToolContext, ToolError

logger = logging.getLogger(__name__)

SERVER_NAME = "openzev"
SERVER_TITLE = "OpenZEV"

INSTRUCTIONS = (
    "OpenZEV data returned here is scoped to the signed-in user: an admin sees "
    "every ZEV, a ZEV owner only their own. Call list_zevs first to find a "
    "zev_id for the other tools. Dates are YYYY-MM-DD, amounts are CHF strings, "
    "energy is in kWh. Metering data is aggregated (daily/monthly buckets); raw "
    "15-minute readings are not available through MCP. Every tool is read-only."
)


class _JsonRpcError(Exception):
    def __init__(self, code: int, message: str, data=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


_NO_RESPONSE = object()


def _server_version() -> str:
    return settings.OPENZEV_VERSION or "dev"


class McpView(APIView):
    """The single MCP endpoint. Restricted to POST — GET/DELETE answer 405,
    since stateless mode has no SSE stream and no session to terminate.
    """

    http_method_names = ["post"]
    authentication_classes = [McpApiKeyAuthentication]
    permission_classes = [IsAuthenticated, IsZevOwnerOrAdmin]
    throttle_classes = [ApiKeyRateThrottle]

    # ── request gate (SPEC-2026-mcp-server §5.1) ──────────────────────────

    def initial(self, request, *args, **kwargs):
        # 1. Flag off -> 404, before authentication, so a disabled instance
        # reveals nothing. This replaces (rather than extends) APIView's own
        # initial() so the Origin/DNS-rebinding check (step 4) can sit
        # between permissions and throttling, which DRF has no hook for.
        if not FeatureFlag.is_enabled(FeatureFlag.MCP_SERVER_ENABLED):
            raise NotFound()

        self.format_kwarg = self.get_format_suffix(**kwargs)
        neg = self.perform_content_negotiation(request)
        request.accepted_renderer, request.accepted_media_type = neg
        version, scheme = self.determine_version(request, *args, **kwargs)
        request.version, request.versioning_scheme = version, scheme

        # 2 + 3. Authentication -> 401, role -> 403.
        self.perform_authentication(request)
        self.check_permissions(request)
        # 4. Origin / DNS-rebinding guard.
        self._check_origin(request)
        # 5. Throttle.
        self.check_throttles(request)

    def _check_origin(self, request) -> None:
        origin = request.META.get("HTTP_ORIGIN")
        if not origin:
            # Non-browser clients (the expected MCP callers) send no Origin
            # at all and pass unconditionally.
            return
        allowed = set(getattr(settings, "CORS_ALLOWED_ORIGINS", None) or [])
        allowed |= set(getattr(settings, "CSRF_TRUSTED_ORIGINS", None) or [])
        if origin not in allowed:
            raise PermissionDenied("Origin not allowed.")

    def _check_protocol_version_header(self, request) -> Response | None:
        # 7. MCP-Protocol-Version header, if present, must be supported.
        header = request.META.get("HTTP_MCP_PROTOCOL_VERSION")
        if header and header not in SUPPORTED_PROTOCOL_VERSIONS:
            return Response(
                error_response(None, INVALID_REQUEST, f"Unsupported MCP-Protocol-Version: {header}"),
                status=400,
            )
        return None

    # ── transport ──────────────────────────────────────────────────────

    def post(self, request, *args, **kwargs):
        version_error = self._check_protocol_version_header(request)
        if version_error is not None:
            return version_error

        # 6. Body must be JSON.
        try:
            raw = request.body.decode("utf-8") if request.body else "null"
            body = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            return Response(error_response(None, PARSE_ERROR, "Parse error"), status=400)

        if isinstance(body, list):
            if not body:
                return Response(error_response(None, INVALID_REQUEST, "Invalid Request"), status=200)
            if len(body) > MAX_BATCH:
                return Response(
                    error_response(None, INVALID_REQUEST, f"Batch exceeds {MAX_BATCH} messages"),
                    status=200,
                )
            messages, is_batch = body, True
        else:
            messages, is_batch = [body], False

        responses = [
            outcome for outcome in (self._handle_message(request, m) for m in messages) if outcome is not None
        ]

        if not responses:
            # Notifications and/or responses only -> no content.
            return Response(status=202)
        return Response(responses if is_batch else responses[0], status=200)

    def _handle_message(self, request, message) -> dict | None:
        msg_id = message.get("id") if isinstance(message, dict) else None

        # A message that fails basic JSON-RPC structure cannot be trusted as
        # an intentional notification (id-less on purpose) — it always gets
        # an error response, per JSON-RPC 2.0's own handling of invalid
        # Request objects (id: null when the id itself could not be read).
        if (
            not isinstance(message, dict)
            or message.get("jsonrpc") != "2.0"
            or not isinstance(message.get("method"), str)
        ):
            return error_response(msg_id, INVALID_REQUEST, "Invalid Request")

        has_id = "id" in message
        method = message["method"]
        params = message.get("params") or {}
        if not isinstance(params, dict):
            return error_response(msg_id, INVALID_PARAMS, "params must be an object")

        try:
            result = self._dispatch_method(request, method, params)
        except _JsonRpcError as exc:
            return error_response(msg_id, exc.code, exc.message, exc.data) if has_id else None
        except Exception:
            logger.exception("Unhandled error processing MCP method %s", method)
            return error_response(msg_id, INTERNAL_ERROR, "Internal error") if has_id else None

        if result is _NO_RESPONSE or not has_id:
            return None
        return result_response(msg_id, result)

    # ── JSON-RPC methods (SPEC-2026-mcp-server §5.3) ──────────────────────

    def _dispatch_method(self, request, method: str, params: dict):
        handler = {
            "initialize": self._method_initialize,
            "notifications/initialized": self._method_initialized,
            "ping": self._method_ping,
            "tools/list": self._method_tools_list,
            "tools/call": self._method_tools_call,
        }.get(method)
        if handler is None:
            raise _JsonRpcError(METHOD_NOT_FOUND, "Method not found")
        return handler(request, params)

    def _method_initialize(self, request, params: dict) -> dict:
        requested = params.get("protocolVersion")
        negotiated = negotiate_protocol_version(requested)
        return {
            "protocolVersion": negotiated,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "title": SERVER_TITLE, "version": _server_version()},
            "instructions": INSTRUCTIONS,
        }

    def _method_initialized(self, request, params: dict):
        return _NO_RESPONSE

    def _method_ping(self, request, params: dict) -> dict:
        return {}

    def _method_tools_list(self, request, params: dict) -> dict:
        return {"tools": [tool.descriptor() for tool in TOOLS.values()]}

    def _method_tools_call(self, request, params: dict) -> dict:
        tool_name = params.get("name")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            raise _JsonRpcError(INVALID_PARAMS, "arguments must be an object")

        tool = TOOLS.get(tool_name)
        if tool is None:
            raise _JsonRpcError(INVALID_PARAMS, f"Unknown tool: {tool_name}")

        errors = self._validate_arguments(tool, arguments)
        if errors:
            raise _JsonRpcError(INVALID_PARAMS, "Invalid arguments", data={"errors": errors})

        api_key = request.auth
        if not tool.read_only and getattr(api_key, "read_only", False):
            raise _JsonRpcError(INVALID_PARAMS, "This tool requires a key that is not read-only")

        started = time.monotonic()
        ctx = ToolContext(request=request, user=request.user, api_key=api_key)
        try:
            structured = tool.run(ctx, arguments)
        except ToolError as exc:
            self._audit_tool_call(
                request, tool, arguments, api_key, ctx,
                status=AuditEventStatus.DENIED if exc.status == "denied" else AuditEventStatus.FAILED,
                duration_ms=int((time.monotonic() - started) * 1000),
                outcome_suffix=" (failed)" if exc.status != "denied" else " (denied)",
            )
            return tool_result(text=exc.message, structured={"error": exc.message}, is_error=True)
        except Exception:
            logger.exception("Unhandled error running MCP tool %s", tool.name)
            self._audit_tool_call(
                request, tool, arguments, api_key, ctx,
                status=AuditEventStatus.FAILED,
                duration_ms=int((time.monotonic() - started) * 1000),
                outcome_suffix=" (failed)",
            )
            message = f"Internal error while running {tool.name}."
            return tool_result(text=message, structured={"error": message}, is_error=True)

        self._audit_tool_call(
            request, tool, arguments, api_key, ctx,
            status=AuditEventStatus.SUCCESS,
            duration_ms=int((time.monotonic() - started) * 1000),
            outcome_suffix="",
        )
        return tool_result(text=json.dumps(structured, default=str), structured=structured, is_error=False)

    @staticmethod
    def _validate_arguments(tool, arguments: dict) -> list[str]:
        validator_cls = jsonschema.validators.validator_for(tool.input_schema)
        validator = validator_cls(tool.input_schema, format_checker=jsonschema.FormatChecker())
        return [
            f"{'/'.join(str(p) for p in error.path) or '(root)'}: {error.message}"
            for error in sorted(validator.iter_errors(arguments), key=str)
        ]

    def _audit_tool_call(self, request, tool, arguments, api_key, ctx, *, status, duration_ms, outcome_suffix):
        user = request.user
        zev = self._resolve_zev_for_audit(arguments.get("zev_id"), user)
        summary = f"{tool.name} called via MCP by {user.email or user.username}{outcome_suffix}"
        record_audit_event(
            request=request,
            action_category=AuditActionCategory.SYSTEM,
            action_type="mcp.tool.call",
            target_type="mcp.Tool",
            target_id=tool.name,
            target_display=tool.name,
            summary=summary,
            status=status,
            zev=zev,
            metadata={
                "tool": tool.name,
                "arguments": arguments,
                "api_key_prefix": getattr(api_key, "prefix", ""),
                "duration_ms": duration_ms,
                "subrequests": ctx.subrequest_count,
            },
        )

    @staticmethod
    def _resolve_zev_for_audit(zev_id, user):
        if not zev_id:
            return None
        from zev.models import Zev

        qs = Zev.objects.all() if user.is_admin else Zev.objects.filter(owner=user)
        return qs.filter(pk=zev_id).first()
