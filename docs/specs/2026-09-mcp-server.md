# Feature Spec: MCP server for AI assistants (iteration 1, read-only)

- Spec ID: SPEC-2026-mcp-server
- Status: In Progress
- Scope: Major
- Type: Feature
- Owners: Sebastian Plattner
- Created: 2026-09-29
- Target Release: 1.20
- Related Issues: [#830](https://github.com/splattner/openzev/issues/830)
- Related ADRs: [ADR 0025](../adr/0025-mcp-server-in-process-over-rest.md), ADR 0003 (role and ZEV scope), ADR 0010 (audit event stream)
- Impacted Areas: backend | docs

---

## 1. Problem and outcome

A ZEV manager's recurring work is checking and explaining structured data: is a period ready
to bill, why is an invoice higher than last time, what went wrong in an import, who changed a
tariff. Today that means clicking through the readiness cockpit, invoice detail, import logs,
metering analysis and the audit log, and combining the answers by hand.

Outcome: an admin or ZEV owner can connect an MCP-capable assistant (Claude Code, Claude
Desktop, Cursor, n8n, …) to their OpenZEV instance with an API key and ask those questions in
plain language. The assistant sees exactly what the same user sees in the REST API — nothing
more — and every tool call is traceable in the audit log.

## 2. Scope

### In scope

| Area | Details |
|---|---|
| Transport | `POST /api/v1/mcp/` — MCP Streamable HTTP, stateless, JSON responses only (ADR 0025) |
| Protocol | JSON-RPC 2.0: `initialize`, `notifications/initialized`, `ping`, `tools/list`, `tools/call`; batches |
| Auth | Existing API keys via `Authorization: Api-Key ozv_…` or `Authorization: Bearer ozv_…`; roles `admin`, `zev_owner` |
| Feature flag | `mcp_server_enabled`, default off; `404` while off |
| Tools | 8 read-only tools (§6) built on in-process sub-requests to existing REST GET endpoints |
| Audit | `AuditEventSource.MCP`; one `mcp.tool.call` event per `tools/call` |
| Throttling | One API-key throttle hit per MCP HTTP request; sub-requests are not throttled again |
| Docs | New user-guide chapter `19-ai-assistants.md`; `mkdocs.yml` nav; baseline spec updates (§11) |

### Out of scope

- OAuth 2.1 authorization server (discovery, DCR, PKCE, consent) — follow-up; needed for
  claude.ai custom connectors.
- Write tools (approve/send invoices, edit assignments, delete imports).
- Participant-facing tools.
- MCP resources/prompts (e.g. user guide as resources), SSE streams, server-initiated requests.
- Frontend UI. The flag appears automatically in **Admin → System settings → Feature flags**
  (descriptions come from the backend). A "Connect an assistant" helper in the UI is a
  follow-up.
- Feasibility scenarios, tariff tools.

## 3. Actors, permissions, and ZEV scope

| Actor | Capability |
|---|---|
| `admin` | All tools, all ZEVs (whatever the REST endpoints return for an admin) |
| `zev_owner` | All tools, own ZEVs only (enforced by the underlying REST views) |
| `participant` | `403` on every MCP request (JSON-RPC error, see §5.4) |
| `guest` / anonymous | `401` with `WWW-Authenticate: Bearer` |

Rules:

1. The MCP view's `authentication_classes = [McpApiKeyAuthentication]` — **no** cookie/JWT
   authentication. `permission_classes = [IsAuthenticated, IsZevOwnerOrAdmin]`.
2. Inactive users, expired or revoked keys: `401` exactly as `ApiKeyAuthentication`.
3. A `read_only` key is accepted: every iteration-1 tool is read-only. The MCP `POST` itself
   is not treated as a write (the read-only check in `ApiKeyAuthentication._enforce_scope` is
   *not* applied to the MCP endpoint; instead each tool declares `read_only = True`, and a
   future write tool must refuse a read-only key).
4. Tools may **only** dispatch sub-requests to the allow-listed GET endpoints in §6.9.
   Scoping, object permissions and 403/404 semantics come from those views unchanged.

## 4. Data model

### 4.1 `audit.AuditEventSource` — new choice

| Value | Label | Meaning |
|---|---|---|
| `mcp` | `MCP` | Request made by an AI assistant through the MCP endpoint, including its in-process sub-requests |

Migration in `audit/migrations/` (choices change on `AuditEvent.source`). Frontend
`AuditEvent['source']` union in `frontend/src/types/api.ts` gains `'mcp'`; add the source label
to every locale where the other sources are labelled (if any).

### 4.2 `accounts.FeatureFlag` — new flag

```python
MCP_SERVER_ENABLED = "mcp_server_enabled"

FeatureFlag.register(
    FeatureFlag.MCP_SERVER_ENABLED,
    default=False,
    description=(
        "Allow AI assistants to read OpenZEV data through the MCP endpoint (/api/v1/mcp/) "
        "using a user's API key. Answers are sent to the assistant's LLM provider, "
        "which may be a third party outside Switzerland."
    ),
)
```

No other model changes. No new tables.

## 5. Transport and protocol

### 5.1 Endpoint

`backend/mcp_server/` (Django app, label `mcp_server`, added to `INSTALLED_APPS`), mounted in
`config/urls.py` as `path("api/v1/mcp/", include("mcp_server.urls"))`, route name `mcp`.

| Method | Behaviour |
|---|---|
| `POST` | One JSON-RPC request, notification, or batch (array). |
| `GET` | `405` (`Allow: POST`) — no SSE stream in stateless mode. |
| `DELETE` | `405` — no sessions to terminate. |

Order of checks on every request:

1. Flag off → `404` (plain DRF `NotFound`), before authentication, so a disabled instance
   does not reveal the endpoint.
2. Authentication (§3) → `401`.
3. Role → `403`.
4. `Origin` header present and not in `CORS_ALLOWED_ORIGINS` / `CSRF_TRUSTED_ORIGINS` →
   `403` (DNS-rebinding guard required by the MCP transport spec; requests without `Origin`,
   i.e. non-browser clients, pass).
5. Throttle (`ApiKeyRateThrottle`, one hit).
6. Body must be JSON (`Content-Type: application/json`) → else JSON-RPC `-32700` with HTTP 400.
7. `MCP-Protocol-Version` header, if present, must be a supported version → else HTTP 400.

### 5.2 Responses

- Request(s) with an `id` → HTTP 200, `Content-Type: application/json`, the JSON-RPC response
  (or array for a batch, omitting notifications).
- Only notifications / responses → HTTP `202 Accepted`, empty body.
- No `Mcp-Session-Id` header is issued; a received one is ignored.

### 5.3 Methods

| Method | Result |
|---|---|
| `initialize` | `{"protocolVersion": <negotiated>, "capabilities": {"tools": {"listChanged": false}}, "serverInfo": {"name": "openzev", "title": "OpenZEV", "version": <app version>}, "instructions": <text, §5.5>}` |
| `notifications/initialized` | no response |
| `ping` | `{}` |
| `tools/list` | `{"tools": [<tool descriptor>…]}` — no pagination (`nextCursor` omitted) |
| `tools/call` | `{"content": [{"type": "text", "text": <JSON string>}], "structuredContent": <object>, "isError": false}` |
| anything else | error `-32601 Method not found` |

Supported protocol versions: `2025-06-18` (preferred), `2025-03-26`. `initialize` echoes the
client's `protocolVersion` if supported, otherwise answers with `2025-06-18`.

Tool descriptor: `name`, `title`, `description`, `inputSchema` (JSON Schema, `type: object`,
`additionalProperties: false`), `outputSchema` omitted in iteration 1,
`annotations: {"readOnlyHint": true, "openWorldHint": false}`.

The app version comes from the same source the admin system-health endpoint uses.

### 5.4 Errors

| Situation | Response |
|---|---|
| Malformed JSON | HTTP 400, `{"jsonrpc":"2.0","id":null,"error":{"code":-32700,"message":"Parse error"}}` |
| Not a JSON-RPC object | `-32600 Invalid Request` |
| Unknown method | `-32601` |
| Unknown tool / invalid arguments (schema) | `-32602 Invalid params`, `data.errors` lists field messages |
| Tool ran, sub-request answered 4xx | **Tool result** with `isError: true`, `content[0].text` = the view's error message (e.g. `"ZEV not found."`, `"Permission denied."`) — per MCP, tool-level failures are results, not protocol errors, so the model can react |
| Unexpected exception in a tool | `isError: true`, generic text `"Internal error while running <tool>."`; logged with traceback; audit status `failed` |
| HTTP-level 401/403/404 (§5.1) | Plain DRF error body, not JSON-RPC |

Batches are capped at 10 messages (`-32600` if more).

### 5.5 `instructions`

A short English text telling the assistant: data is scoped to the signed-in user; call
`list_zevs` first to find ZEV ids; dates are `YYYY-MM-DD`; amounts are CHF; energy is kWh;
readings are aggregated, raw 15-minute data is not available through MCP.

## 6. Tools

All tools live in `backend/mcp_server/tools/` (one module per tool, a registry in
`tools/__init__.py`). Each tool is a class with `name`, `title`, `description`,
`input_schema`, `read_only = True`, and `run(ctx, arguments) -> dict`. `ctx` is a
`ToolContext` with the authenticated `user`, the `api_key`, the outer `request`, and
`ctx.get(path, params) -> SubResponse` (§7).

Input validation: arguments are validated against `input_schema` with `jsonschema`
(already a dependency) before `run`; UUIDs and dates are validated for format too.

Output: every tool returns a JSON object. Lists are capped (caps below) and carry
`"truncated": true` plus the uncapped `total` when a cap bites. Money is returned as a string
decimal with two places (as the REST API does), energy as numbers in kWh rounded to 3 decimals.

### 6.1 `list_zevs`

Find the ZEVs the caller can see.

- Input: `{}` (no arguments).
- Sub-request: `GET /api/v1/zev/zevs/` (all pages, cap 100).
- Output: `{"zevs": [{"id", "name", "billing_interval", "start_date", "is_disabled", "participant_count"?}]}`
  — only fields the list endpoint already returns; `participant_count` only if present.

### 6.2 `period_readiness`

Can a billing period be billed, and what is blocking it.

- Input: `zev_id` (uuid, required); `period_start`, `period_end` (date, optional, both or
  neither). Without a period the cockpit period is used.
- Sub-requests: `GET /api/v1/invoices/invoices/readiness/?zev_id=…[&period_start&period_end]`;
  `GET /api/v1/invoices/invoices/attention/?zev_id=…`.
- Output:
  ```json
  {
    "zev_id": "…", "period": {"start": "…", "end": "…"} | null,
    "overall_status": "<from payload>",
    "steps": [{"key", "status", "count", "total"?, "failed"?, "detail"?}],
    "blocking": ["<step key>: <detail>", …],
    "attention": [<attention item, UI link fields removed>]  // cap 20
  }
  ```
  `blocking` lists steps whose status is not the payload's "done/ok" value. Drop `link` and
  other UI-routing fields. `period: null` responses pass their reason through.

### 6.3 `find_invoices`

Locate invoices before explaining one.

- Input: `zev_id` (uuid, required); `participant_query` (string, optional, case-insensitive
  substring of participant name); `period_start`/`period_end` (date, optional — invoices whose
  period overlaps); `status` (enum of `InvoiceStatus` values, optional); `limit` (1–50,
  default 20).
- Sub-requests: `GET /api/v1/invoices/invoices/?zev_id=…[&status=…]` paging until `limit`
  matches or the list ends (hard cap 10 pages). Filtering by participant name and period is
  done on the returned rows **unless** the list endpoint gains narrow-only filters for them —
  add `participant_id` / `period_from` / `period_to` query filters to `InvoiceViewSet` if that
  is simpler; document them in the invoice-lifecycle baseline spec.
- Output: `{"invoices": [{"id", "invoice_number", "participant_id", "participant_name", "period_start", "period_end", "status", "total_chf"}], "total"?, "truncated"?}`.

### 6.4 `explain_invoice`

Break down one invoice and compare it with the same participant's previous invoice.

- Input: `invoice_id` (uuid, required); `compare_previous` (bool, default true).
- Sub-requests: `GET /api/v1/invoices/invoices/<id>/`; for the comparison, the invoice list
  filtered to the same ZEV (and participant, if a filter exists) to find the most recent
  invoice of the same participant with `period_end < this.period_start` and status not
  `cancelled`, then `GET /api/v1/invoices/invoices/<prev_id>/`.
- Output:
  ```json
  {
    "invoice": {"id", "invoice_number", "participant_name", "period_start", "period_end", "status",
                "subtotal_chf", "vat_chf", "total_chf", "vat_rate"?},
    "lines": [{"type", "description", "quantity_kwh", "unit_price", "amount_chf"}],
    "by_type": {"<item type>": {"kwh", "amount_chf"}},
    "energy": {"local_kwh", "grid_kwh", "feed_in_kwh"?, "local_share_pct"},
    "previous": { …same "invoice" block… } | null,
    "change": {"total_chf", "total_pct", "by_type": {"<type>": {"kwh_delta", "amount_delta_chf"}},
               "days_in_period": [this, previous]} | null
  }
  ```
  Field names are mapped from the actual `InvoiceSerializer` / `InvoiceItemSerializer` fields;
  whatever the serializer does not expose is omitted rather than recomputed. `email_logs`,
  `access_link` and PDF fields are dropped.

### 6.5 `import_triage`

Summarise recent imports and what went wrong.

- Input: `zev_id` (uuid, optional); `since` (date, optional, default 30 days ago); `only_problems`
  (bool, default true: logs with errors or warnings or skipped rows); `limit` (1–20, default 10).
- Sub-request: `GET /api/v1/metering/import-logs/` (with `zev_id` if the endpoint supports it,
  otherwise filter rows), newest first, paging until enough rows (hard cap 5 pages).
- Output:
  ```json
  {"imports": [{"id", "created_at", "zev_name", "source", "filename", "imported_by",
                "rows_total", "rows_imported", "rows_overwritten", "rows_skipped",
                "error_count", "warning_count",
                "errors": ["…"],          // first 10, deduplicated by message
                "warnings": ["…"],        // first 10
                "metering_points": ["<meter ids mentioned in errors/warnings>"]}],
   "totals": {"imports", "with_errors", "with_warnings", "rows_skipped"}}
  ```

### 6.6 `consumption_summary`

Aggregated consumption, production and self-consumption.

- Input: `zev_id` (uuid, required); `date_from`, `date_to` (date, required, span ≤ 400 days);
  `bucket` (`day` | `month`, default `month`; `hour` not offered); `participant_id` (uuid,
  optional).
- Sub-request: `GET /api/v1/metering/readings/dashboard-summary/?zev_id&date_from&date_to&bucket[&participant_id]`.
- Output: the dashboard summary's totals (consumption, production, local/self-consumption,
  grid import, feed-in, self-consumption rate, self-sufficiency) plus a `series` list of at most
  `31` day buckets or `14` month buckets (`truncated` otherwise), with UI-only fields removed.
  Derived ratios are only included if the payload already carries them or they follow directly
  from its totals (`self_consumption_pct = local / production`, `self_sufficiency_pct = local / consumption`).

### 6.7 `data_gaps`

Which metering points have missing readings.

- Input: `zev_id` (uuid, required); `date_from`, `date_to` (date, optional, defaults as the
  endpoint: last 30 days); `only_incomplete` (bool, default true).
- Sub-request: `GET /api/v1/metering/readings/data-quality-status/?zev_id&date_from&date_to`.
- Output: `{"metering_points": [{"id", "meter_id", "participant"?, "completeness_pct", "missing_days", "gaps": [{"from", "to"}]}], "truncated"?}` — cap 50 points and 10 gaps each.

### 6.8 `audit_query`

Filtered audit events within the caller's scope.

- Input: `zev_id` (uuid, optional); `action_category` (enum of `AuditActionCategory`);
  `action_type` (string); `target_type` (string); `target_id` (string); `status` (enum of
  `AuditEventStatus`); `date_from`, `date_to` (date); `limit` (1–50, default 20).
  `q` is **not** exposed (admin-only on the endpoint; the structured filters suffice).
- Sub-request: `GET /api/v1/audit/events/?zev=…&…` (maps `zev_id` → `zev`).
- Output: `{"events": [{"id", "created_at", "actor", "source", "action_category", "action_type", "status", "target_type", "target_display", "summary", "changes"?}], "total"?, "truncated"?}` —
  `changes` included as the endpoint returns it (already redacted server-side); `metadata`,
  IP and user-agent fields dropped.

### 6.9 Allowed sub-request endpoints

The dispatcher refuses (raises, → tool `isError`) any path not matching this list, and any
method other than `GET`:

| Tool | Path (URL name) |
|---|---|
| `list_zevs` | `/api/v1/zev/zevs/` (`zev-list`) |
| `period_readiness` | `invoice-readiness`, `invoice-attention` |
| `find_invoices`, `explain_invoice` | `invoice-list`, `invoice-detail` |
| `import_triage` | `importlog-list` |
| `consumption_summary` | `meterreading-dashboard-summary` |
| `data_gaps` | `meterreading-data-quality-status` |
| `audit_query` | `audit-event-list` |

The allow-list is keyed by resolved URL name, not by path string.

## 7. In-process sub-requests (`mcp_server/dispatch.py`)

```python
@dataclass
class SubResponse:
    status: int
    data: Any          # parsed JSON (response.data)

def dispatch_get(outer_request, path: str, params: dict) -> SubResponse
```

1. Build a Django `HttpRequest` via `django.test.RequestFactory`-equivalent construction
   (plain `HttpRequest` with `method="GET"`, `path`, `GET = QueryDict` of `params`, `META`
   copied from the outer request for `REMOTE_ADDR`, `HTTP_USER_AGENT`, `HTTP_X_REQUEST_ID`,
   server name/port). No cookies, no `Authorization` header.
2. `match = resolve(path)`; refuse if `match.url_name` not in the tool's allow-list.
   Set `request.resolver_match = match`.
3. Forced authentication: `request._force_auth_user = outer.user`,
   `request._force_auth_token = outer.auth` (the `ApiKey`).
4. Marking: `request.audit_source = AuditEventSource.MCP`, `request.api_key = api_key`,
   `request.mcp_subrequest = True`; propagate the outer request id so audit events from a
   sub-request share the MCP call's request id.
5. `response = match.func(request, *match.args, **match.kwargs)`; if it has
   `render`, do not render — read `response.data`. Return `SubResponse(response.status_code, response.data)`.
6. Paginated list responses (`{"count","next","results"}`) are followed by a helper
   `dispatch_get_all(…, max_pages)` that re-dispatches with `page=n`.

`ApiKeyRateThrottle.get_cache_key` returns `None` when `getattr(request, "mcp_subrequest", False)`
is true (read from the DRF request's underlying `HttpRequest`), so one MCP call costs one
throttle hit regardless of fan-out.

`McpApiKeyAuthentication` (in `mcp_server/authentication.py`) subclasses
`ApiKeyAuthentication`: accepts keyword `Api-Key` or `Bearer` with an `ozv_` key; skips
`check_api_key_scope` and the `read_only` method check for the MCP endpoint (rule 3 in §3);
sets `audit_source = "mcp"` instead of `"api_key"`; `authenticate_header` returns
`'Bearer realm="openzev-mcp"'`. It still calls `_touch`.

## 8. Audit

One event per `tools/call` (not for `initialize`, `ping`, `tools/list`):

| Field | Value |
|---|---|
| `action_category` | `system` |
| `action_type` | `mcp.tool.call` |
| `source` | `mcp` |
| `status` | `success`, `failed` (tool `isError` from a 4xx or exception), `denied` (sub-request 403) |
| `zev` | the `zev_id` argument when present and visible to the caller, else `null` |
| `target_type` / `target_id` / `target_display` | `mcp.Tool` / tool name / tool name |
| `summary` | `"<tool> called via MCP by <user email>"` (plus `" (failed)"` etc.) |
| `metadata` | `{"tool": name, "arguments": <validated args>, "api_key_prefix": prefix, "duration_ms": int, "subrequests": int}` — through the existing `redact_metadata` |

Written with `audit.services.record_audit_event(request=outer_request, …)`.

## 9. Configuration

| Setting | Env var | Default | Meaning |
|---|---|---|---|
| `MCP_MAX_BATCH` | — (constant) | 10 | JSON-RPC batch cap |
| throttle | `API_KEY_THROTTLE_RATE` | `600/hour` | shared with other key traffic |

No new env vars.

## 10. Tests (`backend/mcp_server/tests/`)

| Module | Covers |
|---|---|
| `test_transport.py` | flag off → 404 (even unauthenticated); GET/DELETE → 405; no auth → 401 with `WWW-Authenticate`; cookie JWT only → 401; participant key → 403; `Api-Key` and `Bearer` both accepted; revoked/expired key → 401; foreign `Origin` → 403; parse error; invalid request; unknown method; batch (mixed request + notification); batch > 10; notification-only → 202; `initialize` version negotiation; `ping`; `tools/list` returns the 8 tools with `readOnlyHint` |
| `test_dispatch.py` | non-allow-listed URL refused; non-GET refused; sub-request sees forced user and `audit_source = mcp`; one throttle hit per MCP call regardless of sub-requests |
| `test_tools.py` | per tool: happy path shape; owner cannot see another owner's ZEV (`isError` with the view's message, no data leaked); admin sees any ZEV; invalid arguments → `-32602`; caps/truncation (`find_invoices`, `import_triage`, `data_gaps`, `audit_query`); `explain_invoice` previous-invoice selection skips cancelled and later invoices; `consumption_summary` span > 400 days rejected |
| `test_audit.py` | `mcp.tool.call` event recorded with source `mcp`, zev, key prefix, status success/failed/denied; no event for `tools/list` |

Existing `accounts/test_throttling.py` / `test_api_keys.py` gain a case for the
`mcp_subrequest` throttle skip. Final test names and counts are filled in here after
implementation.

## 11. Documentation and spec updates

- New user-guide chapter `docs/user-guide/19-ai-assistants.md` ("Connecting an AI assistant"):
  what it is, privacy note (data goes to the assistant's LLM provider; admin must enable the
  flag), enabling the flag, creating a read-only API key, client configuration examples
  (Claude Code `claude mcp add --transport http openzev https://<host>/api/v1/mcp/ --header "Authorization: Bearer ozv_…"`,
  a generic JSON config, n8n MCP Client node), example questions, the tool list, limits
  (no raw 15-min data, no writes, OAuth-only clients not yet supported), revoking access.
  Add to `mkdocs.yml` nav and `docs/user-guide/README.md`. Cross-link from `16-api-keys.md`.
- `2026-05-audit-log-and-operational-traceability.md`: `source` choices and TS union gain `mcp`;
  `mcp.tool.call` event.
- `2026-03-admin-governance-and-settings.md`: new feature flag.
- `2026-03-community-and-access.md`: MCP authentication path (API key as bearer on `/api/v1/mcp/` only).
- `2026-03-invoice-lifecycle-and-communication.md`: only if new invoice-list filters are added.
- `AGENTS.md`: list this spec under completed feature specs once shipped.

## 12. Follow-ups (not in this iteration)

1. OAuth 2.1 authorization server with protected-resource metadata
   (`/.well-known/oauth-protected-resource`), DCR, PKCE and a consent screen, so claude.ai
   connectors work.
2. Write tools with explicit confirmation, dispatching to existing `POST` workflow actions and
   refusing read-only keys.
3. Participant tools (own invoices, own consumption).
4. User guide as MCP resources; tariff comparison; feasibility scenarios.
5. "Connect an AI assistant" panel in the frontend (URL + config snippet).
