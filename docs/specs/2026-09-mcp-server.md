# Feature Spec: MCP server for AI assistants (iteration 1, read-only)

- Spec ID: SPEC-2026-mcp-server
- Status: Completed
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
| Auth | Existing API keys via `Authorization: Api-Key ozv_…` or `Authorization: Bearer ozv_…`; an admin, or an account with a manager or viewer grant (`HasZevReadAccess`, #761) |
| Feature flag | `mcp_server_enabled`, default off; `404` while off |
| Tools | 10 read-only tools (§6) built on in-process sub-requests to existing REST GET endpoints |
| Audit | `AuditEventSource.MCP`; one `mcp.tool.call` event per `tools/call` |
| Throttling | One API-key throttle hit per MCP HTTP request; sub-requests are not throttled again |
| Docs | New user-guide chapter `19-ai-assistants.md`; `mkdocs.yml` nav; baseline spec updates (§11) |

### Out of scope

- OAuth 2.1 authorization server (discovery, DCR, PKCE, consent) — follow-up; needed for
  claude.ai custom connectors.
- Write tools (approve/send invoices, edit assignments, delete imports).
- Participant-facing tools.
- MCP resources/prompts (e.g. user guide as resources), SSE streams, server-initiated requests.
- Frontend UI. The flag appears automatically in **Platform → Settings → Functions**
  (descriptions come from the backend). A "Connect an assistant" helper in the UI is a
  follow-up.
- Feasibility scenarios, tariff tools.

## 3. Actors, permissions, and ZEV scope

| Actor | Capability |
|---|---|
| `admin` | All tools, all ZEVs (whatever the REST endpoints return for an admin) |
| manager / viewer | All tools, the ZEVs it holds a grant for only (enforced by the underlying REST views) |
| participant, or an account with no relation | `403` on every MCP request (JSON-RPC error, see §5.4) |
| anonymous | `401` with `WWW-Authenticate: Bearer` |

Rules:

1. The MCP view's `authentication_classes = [McpApiKeyAuthentication]` — **no** cookie/JWT
   authentication. `permission_classes = [IsAuthenticated, HasZevAccess]`.
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
| `GET` | `405` (`Allow: POST`) for an authenticated caller — no SSE stream in stateless mode. An *unauthenticated* `GET` (or `DELETE`) answers `401` instead of `405`: like every other DRF view in this codebase, the authentication/permission pipeline (`APIView.initial`) runs before the method-not-allowed check, so a caller with no credentials never learns from the HTTP status alone that only `POST` is accepted. |
| `DELETE` | `405` (authenticated) / `401` (unauthenticated) — no sessions to terminate. |

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

The app version is `settings.OPENZEV_VERSION` (empty string by default; falls back to
`"dev"` in the `initialize` response when unset) — the same setting `backups/archive.py`
records in a backup manifest as `openzev_version`. There is no dedicated admin
system-health endpoint in this codebase; that was a misstatement in an earlier draft
of this spec.

### 5.4 Errors

| Situation | Response |
|---|---|
| Malformed JSON | HTTP 400, `{"jsonrpc":"2.0","id":null,"error":{"code":-32700,"message":"Parse error"}}` |
| Not a JSON-RPC object | `-32600 Invalid Request` |
| Unknown method | `-32601` |
| Unknown tool / invalid arguments (schema) | `-32602 Invalid params`, `data.errors` lists field messages |
| Tool ran, sub-request answered 4xx | **Tool result** with `isError: true`, `content[0].text` = the view's error message (e.g. `"ZEV not found."`, `"Permission denied."`) — per MCP, tool-level failures are results, not protocol errors, so the model can react |
| Tool ran, a business rule was violated (e.g. `consumption_summary`'s 400-day span cap, §6.6) | Same shape as the row above — a `ToolError` raised by the tool's own `run()`, not a JSON Schema violation, so it is `isError: true` rather than `-32602` |
| Unexpected exception in a tool | `isError: true`, generic text `"Internal error while running <tool>."`; logged with traceback; audit status `failed` |
| HTTP-level 401/403/404 (§5.1) | Plain DRF error body, not JSON-RPC |

Batches are capped at 10 messages (`-32600` if more).

### 5.5 `instructions`

A short English text telling the assistant: data is scoped to the signed-in user; call
`list_zevs` first to find ZEV ids and `list_participants` to find participant ids; dates are `YYYY-MM-DD`; amounts are CHF; energy is kWh;
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
- Output: `{"zevs": [{"id", "name", "billing_interval", "start_date", "is_disabled"}], "truncated"?, "total"?}`
  — `is_disabled` is derived from the serializer's `disabled_at` (`is_disabled = disabled_at is not None`);
  `ZevSerializer` has no `participant_count` field, so it is not offered (computing it would mean the tool
  querying the ORM itself, which ADR 0025 rules out).

### 6.1a `list_participants`

Who is in a ZEV, and which metering points they are assigned to. The only way for an
assistant to obtain a `participant_id` for `consumption_summary` / `find_invoices`
without the participant already having an invoice.

- Input: `zev_id` (uuid, required); `query` (string, optional, case-insensitive substring of
  `full_name`, which includes the title, e.g. "Ms. Anna Consumer"); `active_on` (date, optional,
  default today); `include_inactive` (bool, default false — when true, `active_on` is ignored and
  former/future participants are included); `limit` (1–100, default 50).
- Sub-requests: `GET /api/v1/zev/zevs/<zev_id>/` first — the participant list answers an empty
  page for a ZEV the caller cannot see, which would read as "no participants", so the detail
  request surfaces the view's own 404/403 as a tool error instead; then
  `GET /api/v1/zev/participants/?zev_id=…` (hard cap 5 pages) and
  `GET /api/v1/zev/metering-point-assignments/?zev_id=…` (hard cap 10 pages), joined on
  `participant`.
- Filtering: a participant is kept when `valid_from <= active_on` and (`valid_to` is null or
  `valid_to >= active_on`). Assignments are **not** filtered by date — a participant's full
  assignment history is returned so move-in/move-out questions can be answered.
- Output:
  ```json
  {"participants": [{"id", "full_name", "valid_from", "valid_to", "has_account",
                     "onboarding_status",
                     "metering_points": [{"meter_id", "meter_type", "valid_from", "valid_to"}]}],
   "active_on"?: "YYYY-MM-DD", "truncated"?: true, "total"?: int}
  ```
  Sorted by `full_name` (case-insensitive); assignments by `valid_from`. `has_account` is
  `ParticipantSerializer.user is not None`; `onboarding_status` is passed through
  (`not_sent`/`sent`/`active`/`revoked`/`expired`); `meter_id`/`meter_type` come from the
  participant row's nested `metering_points`. **Deliberately omitted** although the REST
  response carries them: `email`, `phone`, `title`, address fields,
  `account_username`, onboarding link expiry — contact data the assistant does not need and that
  would otherwise be sent to the LLM provider (§1, privacy note in the user guide).
  `truncated`/`total` appear when `limit` cut the list or either sub-list hit its page cap.

### 6.2 `period_readiness`

Can a billing period be billed, and what is blocking it.

- Input: `zev_id` (uuid, required); `period_start`, `period_end` (date, optional, both or
  neither — enforced with JSON Schema `dependentRequired`, so "one but not the other" is a
  `-32602` before any sub-request runs). Without a period the cockpit period is used.
- Sub-requests: `GET /api/v1/invoices/invoices/readiness/?zev_id=…[&period_start&period_end]`;
  `GET /api/v1/invoices/invoices/attention/?zev_id=…`.
- Output:
  ```json
  {
    "zev_id": "…", "period": {"start": "…", "end": "…", "interval": "…"} | null,
    "next_action": "<from payload, e.g. \"approve\", \"none\">",
    "steps": [{"key", "status", "count", "total"?, "failed"?, "detail"?, "detail_data"?}],
    "blocking": ["<step key>: <detail or status>", …],
    "attention": [<attention item, UI link fields removed>],  // cap 20
    "attention_truncated"?: true,
    "setup"?: {…}, "awaiting_first_period"?: true, "caught_up"?: true
  }
  ```
  The readiness payload has no `overall_status` field — the equivalent is `next_action`
  (`invoices.readiness._select_next_action`: `"none"` or one of `fix_metering`, `fix_assignments`,
  `fix_tariffs`, `generate`, `review_generation_conflicts`, `approve`, `send`, `track_payments`),
  passed through unchanged. `blocking` lists steps whose `status` is `"warn"` or `"todo"` (the two
  "not done yet" values in `invoices.readiness.StepResult` — the other two are `"ok"` and `"done"`),
  formatted as `"<key>: <detail>"` (falling back to the bare status if the step carries no `detail`).
  `link` is dropped from every step and every attention item; `assignment_link`/`billing_settings_link`/`issuer_link`
  are dropped from `setup` the same way. `period: null` responses pass their reason through as extra
  top-level keys (`setup`, `awaiting_first_period`, `caught_up`) exactly as the underlying endpoint
  returns them, minus the same link fields.

### 6.3 `find_invoices`

Locate invoices before explaining one.

- Input: `zev_id` (uuid, required); `participant_id` (uuid, optional — from
  `list_participants`; narrows server-side); `participant_query` (string, optional,
  case-insensitive substring of participant name); `period_start`/`period_end` (date, optional — invoices whose
  period overlaps); `status` (enum of `InvoiceStatus` values, optional); `limit` (1–50,
  default 20).
- Sub-requests: `GET /api/v1/invoices/invoices/?zev_id=…[&participant_id=…&status=…&period_from=…&period_to=…]`
  paging until `limit` matches or the list ends (hard cap 10 pages). `period_start`/`period_end`
  arguments map onto the `period_from`/`period_to` narrow-only filters added to `InvoiceViewSet`
  for this tool (documented in `2026-03-invoice-lifecycle-and-communication.md` §5.1).
  `participant_query` has no server-side equivalent (it is a case-insensitive substring, not an
  exact id) and is applied to the returned rows: when it is given, the tool fetches without a
  `limit` (still capped at 10 pages) so the name filter sees the full candidate set before
  `limit` truncates the result.
- Output: `{"invoices": [{"id", "invoice_number", "participant_id", "participant_name", "period_start", "period_end", "status", "total_chf"}], "total"?, "truncated"?}`.
  `participant_id` is the raw `InvoiceListSerializer.participant` relation field stringified
  (the un-rendered sub-response leaves FK fields as `uuid.UUID` instances, not strings — every
  tool that reads a relation field converts it explicitly rather than relying on the eventual
  HTTP JSON renderer to do it).

### 6.4 `explain_invoice`

Break down one invoice and compare it with the same participant's previous invoice.

- Input: `invoice_id` (uuid, required); `compare_previous` (bool, default true).
- Sub-requests: `GET /api/v1/invoices/invoices/<id>/`; for the comparison, the invoice list
  filtered to the same ZEV and participant (`zev_id`, `participant_id`, `period_to` = this
  invoice's `period_start`) — relying on `Invoice.Meta.ordering = ["-period_end", ...]` to put
  the most recent candidate first — skipping the current invoice, any row with
  `status == "cancelled"`, and any row whose `period_end >= this.period_start`, then
  `GET /api/v1/invoices/invoices/<prev_id>/` for the first survivor.
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
- Sub-request: `GET /api/v1/metering/import-logs/` — `ImportLogViewSet` has **no** `zev_id`
  query filter, so `zev_id`/`since`/`only_problems` are all applied to the returned rows
  (already newest-first, `ImportLog.Meta.ordering`), paging until enough rows (hard cap 5 pages).
  `row["zev"]` is the raw FK value (a `uuid.UUID`, not a string) and is stringified before
  comparing against the `zev_id` argument.
- Output:
  ```json
  {"imports": [{"id", "created_at", "zev_name", "source", "filename", "imported_by",
                "rows_total", "rows_imported", "rows_overwritten", "rows_skipped",
                "error_count", "warning_count",
                "errors": ["…"],          // first 10, deduplicated by message
                "warnings": ["…"],        // first 10
                "metering_points": ["<meter ids mentioned in errors/warnings>"]}],
   "totals": {"imports", "with_errors", "with_warnings", "rows_skipped"},
   "truncated"?: true}
  ```
  `imported_by` is `ImportLogSerializer.imported_by_display` (the human-readable name, not the
  user id). `error_count`/`warning_count` are `len(errors)`/`len(warnings)` — `ImportLogSerializer`
  has no such fields. `metering_points` is extracted from the error/warning text with a regex for
  meter-id-shaped tokens (upper-case alphanumeric segments joined by at least two dashes); it is a
  best-effort read of free text, not a structured field the importer emits. `totals` are computed
  over every row matching the filters, before the `limit` cap — the ZEV-wide error/warning
  counts stay meaningful even when `imports` itself is truncated.

### 6.6 `consumption_summary`

Aggregated consumption, production and self-consumption, for the whole ZEV (with a
per-participant breakdown) or for one participant.

- Input: `zev_id` (uuid, required); `date_from`, `date_to` (date, required); `bucket`
  (`hour` | `day` | `month`, default `month`; `hour` only for spans of at most 7 days — a longer
  span with `bucket=hour` is a `ToolError`); `participant_id` (uuid, optional).
  The span (`date_to - date_from`, inclusive) is validated at *run time*, not by the JSON
  Schema (dates aren't arithmetic-comparable in JSON Schema): a span over 400 days, or
  `date_to` before `date_from`, is a `ToolError` (`isError: true`), not a `-32602` schema
  error.
- Sub-request: `GET /api/v1/metering/readings/dashboard-summary/?zev_id&date_from&date_to&bucket[&participant_id]`.
- Output:
  ```json
  {
    "zev_id", "date_from", "date_to", "bucket",
    "totals": {"consumed_kwh", "produced_kwh", "imported_kwh", "exported_kwh",
               "self_consumed_kwh", "self_consumption_pct", "self_sufficiency_pct",
               "has_behind_meter_generation"},
    "series": [{"bucket", "consumed_kwh", "produced_kwh", "imported_kwh", "exported_kwh"}],
    "participants"?: [{"participant_id", "participant_name", "consumed_kwh", "from_zev_kwh",
                       "from_grid_kwh", "produced_kwh", "local_share_pct", "has_behind_meter_generation"}],
    "participants_truncated"?, "participants_total"?,
    "participant_id"?, "participant_name"?, "note"?, "truncated"?
  }
  ```
  `owner_dashboard_summary` (`metering/analytics.py`) returns `totals`/`timeline` keyed by
  `consumed_kwh`/`produced_kwh`/`imported_kwh`/`exported_kwh` — there is no `local_kwh` or
  `self_consumption_rate` field on the endpoint itself, so the tool derives them:
  `self_consumed_kwh = consumed_kwh - imported_kwh`,
  `self_consumption_pct = 100 * self_consumed_kwh / produced_kwh` (`null` if `produced_kwh` is 0),
  `self_sufficiency_pct = 100 * self_consumed_kwh / consumed_kwh` (`null` if `consumed_kwh` is 0).
  `series` is the payload's `timeline`, capped at 168 entries for `bucket=hour`, 31 for
  `bucket=day` or 14 for `bucket=month` (`truncated: true` if the cap bit). Buckets are the
  endpoint's own: days and months are Swiss civil days and months, hours are Swiss hours (ADR 0026).

  **Per-participant breakdown** (only without `participant_id`): `participants` is the payload's
  `participant_stats` (already sorted by `total_consumed_kwh` descending), capped at 50
  (`participants_truncated: true` and `participants_total` if the cap bit), mapped as
  `consumed_kwh ← total_consumed_kwh`, `produced_kwh ← total_produced_kwh`, `from_zev_kwh`,
  `from_grid_kwh` passed through, and `local_share_pct = 100 * from_zev_kwh / consumed_kwh`
  (`null` if nothing was consumed). Names and ids only — no contact data (§6.1a). When `participant_id` is given, the
  endpoint's own totals/timeline are already scoped to that participant (not the whole ZEV);
  `participant_id`/`participant_name` echo `selected_participant_id`/`selected_participant_name`
  from the payload, and no `participants` breakdown is returned.

  **Behind-the-meter generation** (SPEC-2026-behind-the-meter-generation §5.6): each
  `participants[]` entry carries the endpoint's own `has_behind_meter_generation` (personally
  holds a metering point with generation behind it for at least one reading in the range), and
  `local_share_pct` is `null` when it is true — a meter with generation behind it records only
  surplus and residual grid draw, so a flagged holder's local share would be misleading.
  `totals.has_behind_meter_generation` is the endpoint's `zev_has_behind_meter_generation` for the
  ZEV-wide call; with `participant_id`, it is that participant's own flag (looked up in
  `participant_stats`), and when true `totals.self_sufficiency_pct` is also `null`. ZEV-wide kWh
  and rates are otherwise unaffected by the flag — only the per-participant rate is suppressed.

  **Participant without readings:** `owner_dashboard_summary` only swaps in the selected
  participant's totals/timeline when that participant has readings in the range; otherwise it
  leaves the **ZEV-wide** totals in place and returns `selected_participant_name: null`. The tool
  detects that (`participant_name is None`) and returns zeroed `totals` (with
  `has_behind_meter_generation: false`), an empty `series` and a `note`, rather than attributing
  the whole ZEV's consumption to the participant.

### 6.6a `consumption_profile`

A participant's average day: 24 hourly averages split into ZEV (local) energy and grid import.

- Input: `zev_id`, `participant_id`, `date_from`, `date_to` (all required; span ≤ 400 days,
  checked at run time as a `ToolError` like §6.6). `participant_id` is required because the
  endpoint only computes a profile for a named participant when called by an admin or owner.
- Sub-request: `GET /api/v1/metering/readings/hourly-profile/?zev_id&participant_id&date_from&date_to`
  (`meterreading-hourly-profile`). A foreign ZEV (`403`) or a participant outside the ZEV (`404`)
  comes back as a tool error with the view's message.
- Output:
  ```json
  {"zev_id", "participant_id", "date_from", "date_to",
   "profile": [{"hour": 0-23, "from_zev_kwh", "from_grid_kwh", "total_kwh"}] | null,
   "average_daily_kwh", "average_daily_from_zev_kwh", "local_share_pct",
   "has_behind_meter_generation", "peak_hour",
   "note"?: "…"}
  ```
  `profile` rows pass `hour`/`from_zev_kwh`/`from_grid_kwh` through from
  `metering.analytics.compute_hourly_profile` (already averaged per day over the range) and add
  `total_kwh`. `average_daily_*` are the sums over the 24 rows; `peak_hour` is the hour with the
  largest `total_kwh` (`null` when total is 0). `has_behind_meter_generation`
  (SPEC-2026-behind-the-meter-generation §5.6) is `compute_hourly_profile`'s own flag: the named
  participant personally held a metering point with generation behind it for at least one
  consumption reading in the range. `local_share_pct` is `from_zev / total` (`null` when total is
  0 **or** the flag is true — a flagged participant's local share would be misleading, since the
  meter records only surplus and residual grid draw). When the endpoint answers
  `hourly_profile: null` (no readings), the tool returns `profile: null` with a `note` instead of
  24 zero rows (and `has_behind_meter_generation` is not included). `hour`
  is passed through exactly as the endpoint (and the dashboard chart) computes it.

### 6.7 `data_gaps`

Which metering points have missing readings.

- Input: `zev_id` (uuid, required); `date_from`, `date_to` (date, optional, defaults as the
  endpoint: last 30 days); `only_incomplete` (bool, default true).
- Sub-request: `GET /api/v1/metering/readings/data-quality-status/?zev_id&date_from&date_to`.
- Output: `{"metering_points": [{"id", "meter_id", "participant"?, "completeness_pct", "missing_days", "gaps": [{"from", "to"}]}], "truncated"?}` — cap 50 points and 10 gaps each.
  `completeness_pct` is the endpoint's `data_completeness`; `missing_days = total_days - days_with_data`;
  `gaps[].from`/`.to` are the endpoint's `gaps[].start_date`/`.end_date`. `only_incomplete` filters
  the returned rows to `data_completeness < 100` (the endpoint has no such filter of its own).

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
| `list_participants` | `zev-detail`, `participant-list`, `meteringpointassignment-list` |
| `period_readiness` | `invoice-readiness`, `invoice-attention` |
| `find_invoices`, `explain_invoice` | `invoice-list`, `invoice-detail` |
| `import_triage` | `importlog-list` |
| `consumption_summary` | `meterreading-dashboard-summary` |
| `consumption_profile` | `meterreading-hourly-profile` |
| `data_gaps` | `meterreading-data-quality-status` |
| `audit_query` | `audit-event-list` |

The allow-list is keyed by resolved URL name, not by path string.

## 7. In-process sub-requests (`mcp_server/dispatch.py`)

```python
@dataclass
class SubResponse:
    status: int
    data: Any          # response.data, un-rendered (see the note on relation fields below)

def dispatch_get(outer_request, path: str, params: dict | None, *,
                  allowed_url_names: frozenset[str], api_key, user,
                  on_dispatch=None) -> SubResponse
```

`allowed_url_names`, `api_key` and `user` are explicit keyword arguments rather than read off
`outer_request` — the caller (a tool, through `ToolContext.get`/`get_all`) already has its own
allow-list and the resolved `request.user`/`request.auth` from the outer MCP call, and passing
them explicitly keeps `dispatch_get` free of any assumption about what kind of object
`outer_request` is (raw `HttpRequest` or wrapped DRF `Request` — both work; only `outer_request`'s
`META`/`audit_request_id`/`audit_ip_address`/`audit_user_agent` are read from it). `on_dispatch` is
an optional no-arg callback invoked once per actual sub-request (used by `ToolContext` to count
`subrequests` for the audit event, §8).

**Un-rendered `.data` and relation fields.** Because `response.data` is read before DRF renders
it to JSON, a `ForeignKey`/`PrimaryKeyRelatedField` value (e.g. `Invoice.zev`, `Invoice.participant`,
`ImportLog.zev`) is a raw `uuid.UUID` instance, not the string the real HTTP response would carry —
only fields DRF serializes explicitly as strings (a model's own `UUIDField` primary key, any
`DateField`/`DateTimeField`) are already strings in `.data`. Every tool that reads a relation field
converts it with `str(...)` before comparing or forwarding it as a sub-request parameter; the final
JSON-RPC response is unaffected either way, since `rest_framework.utils.encoders.JSONEncoder`
converts `UUID`/`Decimal` when the outer view's `Response` is eventually rendered.

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

79 tests across four modules (`backend/mcp_server/tests/__init__.py` makes it a package;
fixtures live in `backend/mcp_server/tests/conftest.py` — an autouse `mcp_server_enabled`
fixture, `admin_mcp_client`/`owner_mcp_client`, and `rpc`/`call_tool` request helpers built
on `APIClient`).

| Module | Count | Classes | Covers |
|---|---|---|---|
| `test_transport.py` | 28 | `TestFeatureFlagGate`, `TestMethodNotAllowed`, `TestAuthentication`, `TestRole`, `TestOrigin`, `TestBodyParsing`, `TestBatch`, `TestInitialize`, `TestPing`, `TestToolsList`, `TestToolsCall` | flag off → 404 (unauthenticated and with a valid key); `GET`/`DELETE` → 405 (authenticated); no auth → 401 with `WWW-Authenticate`; cookie JWT alone → 401; `Api-Key` and `Bearer` both accepted; revoked/expired key → 401; participant → 403; admin/owner → 200; untrusted `Origin` → 403, no `Origin` passes, trusted `Origin` passes; malformed JSON → `-32700`/400; non-object message → `-32600`; unknown method → `-32601`; batch (mixed request + notification), batch > 10 → `-32600`, notification-only → 202 with empty body; `initialize` version negotiation (requested-and-supported, and fallback for unsupported); `ping`; `tools/list` returns exactly the 10 tools, all `readOnlyHint: true`; unknown tool and invalid arguments → `-32602` with `data.errors` |
| `test_dispatch.py` | 5 | `TestAllowList`, `TestForcedAuth`, `TestThrottleSkip` | non-allow-listed URL raises `DispatchError`; an allow-listed URL succeeds; a sub-request resolves data as the forced user (proves `_force_auth_user`/`_force_auth_token` took effect); `ApiKeyRateThrottle.get_cache_key` returns `None` when `mcp_subrequest` is set and a real cache key otherwise |
| `test_tools.py` | 40 | `TestListZevs`, `TestListParticipants`, `TestPeriodReadiness`, `TestFindInvoices`, `TestExplainInvoice`, `TestImportTriage`, `TestConsumptionSummary`, `TestConsumptionProfile`, `TestDataGaps`, `TestAuditQuery` | one class per tool: happy-path shape; owner cannot see another owner's ZEV/invoice (`isError` with the view's own message, e.g. "Permission denied.", no data leaked); admin sees any ZEV; invalid arguments → `-32602`; caps/truncation (`find_invoices`, `import_triage`); `explain_invoice` previous-invoice selection skips a cancelled invoice and picks the correct prior period, and `compare_previous: false` skips the lookup; `import_triage` extracts meter ids from error text and respects `only_problems`; `consumption_summary` span > 400 days is a `ToolError` (`isError: true`, not `-32602` — see §6.6), the ZEV-wide call returns a per-participant breakdown sorted by consumption with `local_share_pct` and no contact fields, a `participant_id` call is scoped and has no breakdown, a participant without readings gets zeroed totals and a `note` (not the ZEV's totals), `bucket=hour` works within 7 days and is a `ToolError` beyond, and a net-metered participant gets `has_behind_meter_generation: true`, `local_share_pct: null`, and `totals.has_behind_meter_generation: true` (`test_net_metered_participant_has_null_local_share`, SPEC-2026-behind-the-meter-generation); `data_gaps` marks a meter with zero readings fully incomplete; `list_participants` returns assignments and none of the contact fields, filters by `query` and `active_on` (and `include_inactive`), caps with `truncated`/`total`, and gives an owner naming another owner's ZEV a tool error with no participant data; `find_invoices` `participant_id` narrows server-side; `consumption_profile` returns 24 rows with the correct peak hour, daily average and local share, `profile: null` plus a note without readings, `-32602` without `participant_id`, a tool error for a participant of another ZEV or another owner's ZEV, and a `ToolError` for a span over 400 days |
| `test_audit.py` | 6 | `TestToolCallAudit` | successful call recorded with `source = mcp`, `mcp.Tool`/tool-name target, `api_key_prefix`/`duration_ms`/`subrequests` in metadata; `zev_id` argument attaches the `Zev` row only when it is visible to the caller (an owner naming another owner's ZEV gets `zev = null` **and** `status = denied`, not a leak); a failed tool call is recorded `failed` or `denied`; `tools/list` and `initialize` write no `mcp.tool.call` event |

`accounts/test_throttling.py` gains `McpSubrequestThrottleTests` (1 test,
`test_one_mcp_call_costs_one_throttle_hit_regardless_of_fan_out`): with a 2-request budget,
two `period_readiness` calls (two sub-requests each) both succeed and a third is throttled —
proving the sub-requests inside a call never count on their own.

`invoices/test_invoice_list_filter.py` gains `InvoiceParticipantAndPeriodFilterTests` (7
tests) for the `participant_id`/`period_from`/`period_to` narrow-only filters added to
`InvoiceViewSet` for `find_invoices`/`explain_invoice` (§6.3/§6.4).

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
