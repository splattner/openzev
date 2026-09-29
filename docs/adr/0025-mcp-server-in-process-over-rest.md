# ADR 0025: The MCP server runs inside Django and answers through the REST views

- Status: Proposed
- Date: 2026-09-29

## Context

[#830](https://github.com/splattner/openzev/issues/830) asks for a Model Context Protocol (MCP)
server so a ZEV manager can ask an AI assistant (Claude, ChatGPT, n8n agents, …) questions
about their own OpenZEV data: can a period be billed, why is an invoice higher, what went wrong
in an import. The spec for the first, read-only iteration is
[`2026-09-mcp-server.md`](../specs/2026-09-mcp-server.md).

Four questions have to be settled before any tool is written, and each one has consequences
beyond the MCP feature:

1. **Where the server runs.** OpenZEV is self-hosted. The backend is a synchronous Django app
   served by gunicorn (`config.wsgi`), behind the frontend's nginx. Anything that needs its own
   process, port, or ASGI server is one more thing every self-hoster has to deploy.
2. **How tools reach the data.** Tenant isolation lives in the DRF layer: permission classes
   (`IsZevOwnerOrAdmin`, `BaseZevScopedPermission`), `ZevScopedQuerySetMixin`, and a handful of
   per-view checks (`_resolve_zev` in `invoices/views_readiness.py`, the owner check in
   `dashboard_summary`). ADR 0003 made this the single place access is enforced. A second copy
   of those rules inside MCP tools would drift the first time either side changes.
3. **How the caller authenticates.** The MCP authorization spec expects OAuth 2.1 for remote
   servers. OpenZEV is an OAuth *client* today (`accounts/views_oauth.py`, login via external
   providers), not an authorization server. It does have per-user, revocable, optionally
   read-only API keys (`accounts/api_keys.py`, `ApiKeyAuthentication`) that already mark their
   requests `audit_source = "api_key"`.
4. **Which MCP transport and SDK.** The official `mcp` Python SDK is built on Starlette/ASGI
   and an async session manager. The Streamable HTTP transport itself, in its stateless form,
   is a single `POST` endpoint carrying JSON-RPC 2.0 and answering with `application/json`.

## Decision

**1. In-process, one endpoint, off by default.** The MCP server is a Django app (`backend/mcp_server/`, named so it cannot shadow the PyPI `mcp` package)
mounted at `POST /api/v1/mcp/`. It implements the MCP *Streamable HTTP* transport in its
**stateless JSON-response** mode: every request is one JSON-RPC message (or batch), every
response is `application/json`; no `Mcp-Session-Id`, no SSE stream, `GET` answers
`405 Method Not Allowed` as the transport permits. It is served by the existing gunicorn
workers. It is gated by a new feature flag, `mcp_server_enabled`, default **off**; while off
the endpoint answers `404`, so an instance that never opted in exposes nothing new.

**2. Tools call the REST views in-process; they never query the ORM for data.** Each tool is
a thin adapter that issues one or more *internal GET sub-requests* to existing REST endpoints
(e.g. `/api/v1/invoices/invoices/readiness/`), resolved with `django.urls.resolve` and
dispatched to the resolved view function directly — no HTTP, no network hop. The sub-request
is authenticated as the MCP caller through DRF's own forced-authentication hook
(`_force_auth_user` / `_force_auth_token` on the underlying `HttpRequest`, which
`rest_framework.request.Request.__init__` honours), so the view runs its normal permission
classes, queryset scoping, serializers and audit hooks for that user. The tool then
**reshapes and trims** the JSON the view returned (aggregating, dropping UI-only fields,
capping list lengths). The only ORM access in `backend/mcp_server/` is the auth/flag plumbing
(`ApiKey`, `FeatureFlag`, `AuditEvent` writes via `audit.services`).

Where an endpoint lacks a narrowing filter a tool needs, the filter is added to the REST
endpoint (narrow-only, documented in its baseline spec) rather than worked around in the tool.

**3. First iteration authenticates with API keys; OAuth comes later.** The endpoint's only
authentication class accepts the caller's existing OpenZEV API key in either
`Authorization: Api-Key ozv_…` or `Authorization: Bearer ozv_…` form (many MCP clients can
only send a bearer token). Cookie/JWT sessions are **not** accepted on the MCP endpoint: an
assistant is not a browser, and refusing cookies removes the CSRF surface entirely. All
existing key rules apply unchanged: expiry, revocation, `last_used_at`, per-key throttle, and
the owner's role. Only `admin` and `zev_owner` may use it in this iteration. A full OAuth 2.1
authorization server (discovery metadata, dynamic client registration, PKCE, a consent
screen) is a separate follow-up, needed for connectors such as claude.ai that cannot send a
static header.

**4. No MCP SDK dependency.** The JSON-RPC layer (`initialize`, `notifications/initialized`,
`ping`, `tools/list`, `tools/call`) is implemented directly in a DRF `APIView`, roughly 200
lines, against protocol version `2025-06-18` (and accepting `2025-03-26`). This avoids pulling
an ASGI stack and an async runtime into a WSGI app for what is, in stateless mode, a
request/response RPC.

**5. MCP traffic is labelled in the audit log.** A new `AuditEventSource.MCP = "mcp"` marks
both the MCP request and every sub-request it makes. Each `tools/call` records one
`mcp.tool.call` audit event (category `system`) naming the tool, the scoped ZEV, the API key
prefix and the outcome, so "what did the assistant look at?" is answerable from the audit log.
Sub-requests that already audit themselves carry `source = mcp` as well.

## Consequences

Positive:
- Self-hosters get the feature with no new service, port or process: flip the flag, create an
  API key, paste a URL into the assistant.
- Access control has exactly one implementation. A tool cannot return data the same user could
  not fetch from the REST API, and a future fix to a permission class fixes MCP too.
- A leaked MCP credential is an ordinary API key: visible in **Account → API keys**, revocable
  on its own, read-only if created that way, and traceable in the audit log.
- Write tools (a later iteration) inherit the workflow checks for free by dispatching to the
  existing `POST` actions (`approve`, `send-all`, …).

Trade-offs:
- In-process sub-requests cost more than direct service calls (serializer work, DRF request
  construction). Acceptable for read tools answering one question at a time; tools cap their
  fan-out.
- Tool output is coupled to REST response shapes. A change to e.g. the readiness payload
  needs the matching tool adapter and its tests updated — the MCP tests are the tripwire.
- Sub-requests bypass `ApiKeyAuthentication`, so they do not re-run
  `check_api_key_scope`. This is safe because the tool registry only dispatches to a fixed,
  reviewed list of non-`accounts` GET endpoints, and the MCP endpoint itself enforces the key's
  `read_only` flag and throttle once per MCP call.
- Clients that only speak OAuth (claude.ai custom connectors) cannot connect until the OAuth
  follow-up lands; Claude Code, Claude Desktop (via a bridge), n8n, Cursor and similar work
  with a bearer header today.
- Hand-rolled protocol code must be kept in step with MCP revisions ourselves.

## Alternatives considered

1. **Separate MCP service (Python SDK or Node) calling the REST API over HTTP.**
   - Cleanest isolation, but every self-hoster gets another container, port and reverse-proxy
     rule, and the service needs its own credential story. The in-process adapter gives the
     same "only through the API" guarantee without the deployment cost.
2. **Tools call domain services (`compute_readiness`, `owner_dashboard_summary`) directly.**
   - Faster and smaller payloads, but the permission and scoping checks that sit in the views
     (`_resolve_zev`, `scope_queryset`, the owner check in `dashboard_summary`) would have to be
     duplicated in each tool. That is exactly the drift ADR 0003 exists to prevent, and #830
     asks for it explicitly not to happen.
3. **Official `mcp` Python SDK mounted via ASGI.**
   - Brings Starlette, anyio and an async session manager into a WSGI deployment, and the
     stateful Streamable HTTP mode assumes sticky sessions that multiple gunicorn workers do
     not give us. Revisit if we need server-initiated messages (sampling, elicitation) or SSE
     progress streams.
4. **OAuth 2.1 authorization server from day one.**
   - Required eventually, but it is a security-sensitive subsystem of its own (DCR, PKCE,
     consent UI, token storage and revocation) and would delay the read-only tools that tell us
     whether the feature is worth extending. API keys are already a reviewed, revocable,
     audited credential.
5. **Accept cookie/JWT sessions on the MCP endpoint too.**
   - No real client needs it, and it would reopen CSRF considerations on a `POST` endpoint.

## Notes

- Follow-ups tracked in the spec §12: OAuth 2.1 authorization server, participant tools,
  write tools with confirmation, user-guide chapters as MCP resources.
- Privacy: enabling the flag lets users send personal and consumption data to a third-party
  LLM provider of *their* choosing. The flag description and the user guide say so, in line
  with the disclosure approach of #796.
