"""API-key authentication for the MCP endpoint.

Subclasses ``accounts.authentication.ApiKeyAuthentication`` rather than
duplicating it: every key rule (expiry, revocation, ``last_used_at``,
inactive-user check) must apply identically here, and re-implementing them
would be exactly the drift ADR 0003 exists to prevent. Two things differ from
the base class, both required by SPEC-2026-mcp-server §3 and §7:

- ``Bearer`` is accepted alongside ``Api-Key`` — many MCP clients can only
  send a bearer token.
- ``check_api_key_scope`` and the read-only method check are skipped: the MCP
  endpoint is not in the ``accounts`` app's URL-name allow-list at all (it
  would be denied outright), and read-only-ness is enforced per tool
  (``read_only = True`` on every iteration-1 tool) rather than per HTTP
  method, because the transport is always POST.
"""

from __future__ import annotations

from rest_framework import exceptions
from rest_framework.authentication import get_authorization_header

from accounts.authentication import ApiKeyAuthentication
from audit.models import AuditEventSource


class McpApiKeyAuthentication(ApiKeyAuthentication):
    """``Authorization: Api-Key ozv_…`` or ``Authorization: Bearer ozv_…``."""

    def authenticate(self, request):
        auth_header = get_authorization_header(request).split()
        if not auth_header:
            return None
        scheme = auth_header[0].lower()
        if scheme not in (b"api-key", b"bearer"):
            return None
        if len(auth_header) != 2:
            raise exceptions.AuthenticationFailed(
                "Invalid Authorization header. Expected '<scheme> <key>'."
            )

        try:
            raw_key = auth_header[1].decode("utf-8")
        except UnicodeError:
            raise exceptions.AuthenticationFailed("Invalid Authorization header encoding.")

        api_key = self._resolve_key(raw_key)
        user = api_key.user

        if not user.is_active:
            raise exceptions.AuthenticationFailed("User inactive or deleted.")

        self._mark_request(request, api_key)
        self._touch(api_key)
        return user, api_key

    def authenticate_header(self, request):
        return 'Bearer realm="openzev-mcp"'

    def _mark_request(self, request, api_key) -> None:
        """Label the request as MCP traffic, skipping the base class's
        ``_enforce_scope`` (accounts allow-list + read-only-by-method check).
        """
        request.audit_source = AuditEventSource.MCP
        request.api_key = api_key
        underlying = getattr(request, "_request", None)
        if underlying is not None:
            underlying.audit_source = AuditEventSource.MCP
            underlying.api_key = api_key
