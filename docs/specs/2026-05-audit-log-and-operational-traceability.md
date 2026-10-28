<!-- markdownlint-disable MD060 -->

# Feature Spec: Audit log and operational traceability

- Spec ID: SPEC-2026-audit-log-traceability
- Status: Approved
- Scope: Major
- Type: Change
- Owners: Core maintainers
- Created: 2026-05-08
- Target Release: Ongoing
- Related Issues: n/a
- Related ADRs: 0008, 0010
- Impacted Areas: backend, frontend, async jobs, docs

---

## 1. Problem and outcome

OpenZEV currently provides domain-specific operational logs for metering imports
and invoice email delivery, but it does not provide a single cross-cutting audit
stream for privileged, billing-relevant, or destructive actions. This creates a
gap for operational investigations, incident analysis, and finance-sensitive
change traceability.

**Outcome:** OpenZEV gains a centralized append-only audit event stream for
high-risk write workflows. Admins can search all events; managers and viewers
can inspect and search events scoped to their communities, and the system records
who performed an action, which tenant it affected, whether it succeeded, and
which business fields changed.

This spec defines Audit Log v1 as a backend-first feature with a minimal admin
UI. It is sufficient to implement the first production-ready audit subsystem
without introducing a full compliance ledger or low-value read-access logging.

---

## 2. Scope

### In scope

| Area | Details |
|---|---|
| Central audit stream | New `AuditEvent` model storing immutable business audit records |
| Request attribution | Request ID, actor, IP, user agent, source, role snapshot |
| Tenant scoping | Audit events linked to a ZEV when the affected object is tenant-scoped |
| Diff capture | Whitelisted before/after field diffs for audited models |
| Workflow coverage | Auth, governance, participant, metering, tariff, invoice, import, and template write workflows |
| Async outcomes | Audit records emitted from Celery tasks for email/import results and failures |
| Audit API | List/detail endpoints with filters for admins and scoped read access for managers and viewers |
| Frontend audit UI | Admin audit log page with filtering and event detail viewer |
| Redaction policy | Explicit exclusion and masking rules for secrets and sensitive payloads |
| Rollout phases | Incremental implementation slices starting with backend foundation and invoice/governance coverage |

### Out of scope

- Read-access auditing for normal page/API views
- Full immutable compliance ledger semantics for every model save
- SIEM/webhook/export integrations
- Auditing raw uploaded file contents, rendered PDFs, or full email bodies
- Historical backfill of pre-feature changes

---

## 3. Actors, permissions, and ZEV scope

| Actor | Capability |
|---|---|
| `admin` | Read all audit events, filter globally, inspect security and tenant events |
| Manager or viewer community access | Read only audit events in communities returned by `zev.access.viewable_zev_ids(user)` |
| Participant link alone | No audit-log access |
| `guest` | No audit-log access |
| Celery/system | May emit audit events with `actor_user = null` and `source = system` or `source = celery` |

### Backend permission model

Audit endpoints are served under a new `audit` app.

| Endpoint area | Permission |
|---|---|
| `GET /api/v1/audit/events/` | `CanViewAuditEvents`: authenticated admin or account with manager/viewer community access; non-admin queryset limited to `viewable_zev_ids` |
| `GET /api/v1/audit/events/{id}/` | Same as list; object-level ZEV scope enforced |
| Audit creation | Internal only via service layer; no public POST endpoint |

### Frontend route protection

| Route | Guard |
|---|---|
| `/admin/audit` (`/admin/audit-logs` redirects) | `['admin']` |
| `/zev-settings/audit` (`/audit-logs` redirects) | `ZEV_SCOPE` (`admin`, `manager`, `viewer` shell roles), guarded on the parent settings hub |

The same read-only audit view (`AuditLogsPage({ scope })`) is rendered in two
hub tabs:

- admin scope as the Audit log tab of the admin Overview hub
  (`AdminOverviewHubPage tab="audit"`), with global visibility and search
  enabled,
- owner scope as the Audit log tab of the ZEV settings hub
  (`ZevSettingsPage tab="audit"`), with ZEV-scoped visibility and search
  enabled for accounts with community audit read access. The component accepts
  `embedded` to drop its standalone page header when mounted inside a tab;
  scopes never merge. Owner scope is locked
  to the global ZEV selection. Switching it clears draft/applied search, resets
  pagination and closes the drawer; no event request runs while the managed
  selection is loading, empty or lacks management-view access.

### ZEV resolution rules

The audit service resolves `zev` in this priority order:

1. Explicit `zev` argument passed by the caller.
2. Direct field on the target object (`obj.zev`).
3. Derived from related object graphs, including:
   - `Participant.zev`
   - `MeteringPoint.zev`
   - `MeteringPointAssignment.metering_point.zev`
   - `Invoice.zev`
   - `Tariff.zev`
4. `null` for global/system/auth events that are not tenant-specific.

---

## 4. Data model

### 4.1 AuditEvent

**Model:** `audit.models.AuditEvent`

| Field | Type | Default | Constraints / Notes |
|---|---|---|---|
| `id` | `UUIDField` | auto | Primary key |
| `created_at` | `DateTimeField` | auto_now_add | Indexed |
| `actor_user` | `ForeignKey(User)` nullable | `null` | `SET_NULL`; for authenticated human actor when available |
| `actor_role_snapshot` | `CharField(20)` | `""` | Role value at time of action; not derived dynamically |
| `actor_display` | `CharField(255)` | `""` | Username or human-readable label persisted for history |
| `zev` | `ForeignKey(Zev)` nullable | `null` | `SET_NULL`; indexed |
| `action_category` | `CharField(40)` | required | Indexed; enum-like values listed in §4.2 |
| `action_type` | `CharField(80)` | required | Indexed; machine-readable action name |
| `target_type` | `CharField(120)` | required | Django-style label such as `invoices.Invoice` |
| `target_id` | `CharField(64)` | `""` | Stringified PK for heterogeneous model support |
| `target_display` | `CharField(255)` | `""` | Human-readable object label snapshot |
| `status` | `CharField(20)` | `success` | `success`, `failed`, `denied`, `queued`, `started` |
| `request_id` | `CharField(64)` nullable | `null` | Correlates all events in one request/job |
| `correlation_id` | `CharField(64)` nullable | `null` | Optional cross-request correlation for async follow-up |
| `source` | `CharField(20)` | `api` | `api`, `api_key`, `invoice_link`, `onboarding_link`, `celery`, `system`, `management_command`, `mcp` |
| `ip_address` | `GenericIPAddressField` nullable | `null` | Request-derived; blank for system tasks |
| `user_agent` | `TextField` | `""` | Request-derived; may be truncated to 500 chars before save |
| `summary` | `CharField(500)` | required | Human-readable event summary for list UI |
| `reason` | `TextField` | `""` | Optional operator-supplied reason for destructive/admin actions |
| `changes_json` | `JSONField` | `{}` | Structured field diff payload; shape defined in §4.3 |
| `metadata_json` | `JSONField` | `{}` | Small structured metadata; redacted before persistence |

**Ordering:** `['-created_at']`

**Indexes:**

| Index | Fields |
|---|---|
| `audit_event_created_at_idx` | `created_at` |
| `audit_event_zev_created_at_idx` | `zev`, `created_at` |
| `audit_event_actor_created_at_idx` | `actor_user`, `created_at` |
| `audit_event_action_category_created_at_idx` | `action_category`, `created_at` |
| `audit_event_target_lookup_idx` | `target_type`, `target_id`, `created_at` |
| `audit_event_status_created_at_idx` | `status`, `created_at` |

**Constraints and behavior:**

1. Audit events are append-only from application code.
2. No view, serializer, or admin action may update or delete an `AuditEvent` in
   normal runtime workflows.
3. Retention or archival operations, if introduced later, must be implemented as
   explicit management/ops tooling rather than ordinary CRUD.

**Serializer:** `AuditEventSerializer` — fields:
`id`, `created_at`, `actor_user`, `actor_role_snapshot`, `actor_display`,
`zev`, `action_category`, `action_type`, `target_type`, `target_id`,
`target_display`, `status`, `request_id`, `correlation_id`, `source`,
`ip_address`, `user_agent`, `summary`, `reason`, `changes_json`, `metadata_json`

Read-only: all fields.

### 4.2 Enumerated values

The implementation may use `TextChoices` or module-level constants, but the API
surface and stored values must match these values.

**Action categories:**

| Value | Meaning |
|---|---|
| `auth` | Login, password, verification, impersonation |
| `governance` | ZEV settings, feature flags, VAT, app settings |
| `participant` | Participant CRUD and account link/unlink |
| `metering` | Metering point and assignment CRUD, reading deletion |
| `tariff` | Tariff and tariff period mutations |
| `invoice` | Invoice lifecycle and generation actions |
| `import` | Import start/result/failure events |
| `template` | Email/PDF template changes |
| `system` | Security-sensitive system actions without a business domain |

**Status values:**

| Value | Meaning |
|---|---|
| `started` | Long-running process started |
| `queued` | Async action queued |
| `success` | Action completed successfully |
| `failed` | Action attempted but failed |
| `denied` | Authorization or guardrail prevented the action |

### 4.3 `changes_json` structure

`changes_json` stores a field-level diff using a predictable object shape:

```json
{
  "field_name": {
    "before": "old value",
    "after": "new value"
  }
}
```

Rules:

1. Only whitelisted business fields are included.
2. Values are serialized to API-safe primitives: string, number, boolean, null,
   or short arrays of primitives.
3. High-volume or sensitive fields are omitted entirely.
4. For create/delete flows, one side of the diff may be `null`.

### 4.4 Redaction and omission policy

The audit service must redact or omit these fields from `changes_json` and
`metadata_json`:

| Field / data type | Rule |
|---|---|
| Passwords, reset tokens, JWTs, OAuth secrets | Omit entirely |
| `client_secret`, SMTP credentials, secret keys | Omit entirely |
| IBAN values | Mask all but trailing 4 characters |
| Email template body content | Store summary metadata only, not full body |
| PDF template HTML content | Store template name and content hash only |
| Uploaded file contents | Omit entirely |
| User notes / free-text comments | Exclude by default unless explicitly required |

Redaction recursively traverses dictionaries, lists and tuples, including nested
before/after diff values. Keys are compared case-insensitively against
`SENSITIVE_KEYS` (password, user_password, token, access_token, refresh, access,
client_secret, secret_key, email_host_password, authorization, api_key,
api_key_value, push_token, refresh_token), plus
body/template keys (`email_body_template`, `body`, `template_content`, `content`).
Fields named `iban` or ending in `_iban` retain only the final four characters;
values of four characters or fewer are fully masked. Diff sides inherit their
field’s masking policy.
Safe strings are capped at 500 characters; lists/tuples at 20 entries;
dictionaries at 50 input entries at every level, including the root. An extra
truncation marker records omitted input entries. `build_diff` compares raw values;
`record_audit_event` normalizes metadata and diffs once before persistence.
Trusted API-key attribution survives truncation and overrides caller values.
Diff sides remain explicit even when empty or fully redacted.


---

## 5. API contracts

The audit API is read-only. Events are created only by backend services.
An **audit reader** is an authenticated admin or an account with an active
manager/viewer grant or a managing party role. Non-admin reads are community-scoped.

### 5.1 URL registration

Add a new include in `backend/config/urls.py`:

| Path prefix | Include |
|---|---|
| `/api/v1/audit/` | `include('audit.urls')` |

### 5.2 Endpoints

| Endpoint | Method | Permission | Behaviour |
|---|---|---|---|
| `/api/v1/audit/events/` | GET | Audit reader; community-scoped unless admin | Paginated list with role-scoped filtering |
| `/api/v1/audit/events/{id}/` | GET | Audit reader; community-scoped unless admin | Single event detail if event is visible to actor |
| `/api/v1/audit/events/filter-options/` | GET | Audit reader; community-scoped unless admin | Unpaginated `{zevs, actors}` distinct options derived from the visible event queryset |

### 5.3 List query parameters

| Param | Type | Description |
|---|---|---|
| `actor_user` | int | Filter by actor user ID |
| `zev` | UUID | Filter by ZEV |
| `action_category` | string | Filter by category |
| `action_type` | string | Filter by exact action name; maximum 80 characters |
| `target_type` | string | Filter by target model label; maximum 120 characters |
| `target_id` | string | Filter by target primary key; maximum 64 characters |
| `status` | string | Filter by event status |
| `date_from` | ISO date | Inclusive lower bound on `created_at` date |
| `date_to` | ISO date | Inclusive upper bound on `created_at` date |
| `q` | string | Case-insensitive substring search across summary, target_display and action_type within existing read scope; maximum 50 Unicode code points after trimming; blank means no search |

Text filters are trimmed. Over-limit nonblank filters return HTTP `400`; `%`,
`_`, backslashes, quotes and markup remain literal search text. Search OR
conditions are applied to the visibility-scoped queryset, including pagination
counts. Default: 60 list requests/minute/account, configured by
`AUDIT_LIST_THROTTLE_RATE`. All list requests share this budget across communities,
sessions, API keys and MCP. Existing per-key limits also apply. Exhaustion returns
HTTP `429` with `Retry-After`; detail and filter-options retain their existing
throttles.

### 5.4 List response shape

```json
{
  "count": 2,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": "uuid",
      "created_at": "2026-05-08T12:00:00Z",
      "actor_user": 1,
      "actor_role_snapshot": "admin",
      "actor_display": "admin@example.com",
      "zev": "uuid-or-null",
      "action_category": "invoice",
      "action_type": "invoice.approve",
      "target_type": "invoices.Invoice",
      "target_id": "uuid",
      "target_display": "INV-00042",
      "status": "success",
      "request_id": "req-uuid",
      "correlation_id": null,
      "source": "api",
      "summary": "Approved invoice INV-00042 for participant Jane Doe.",
      "reason": "",
      "changes_json": {
        "status": { "before": "draft", "after": "approved" }
      },
      "metadata_json": {
        "participant_id": "uuid",
        "period_start": "2026-05-01",
        "period_end": "2026-05-31"
      }
    }
  ]
}
```

### 5.5 View implementation

**Files:**

- `backend/audit/views.py`
- `backend/audit/serializers.py`
- `backend/audit/urls.py`

Proposed classes:

| Class | Responsibility |
|---|---|
| `AuditEventListView` | Paginated filtered list |
| `AuditEventDetailView` | Detail retrieval |
| `AuditEventFilterSet` or equivalent helper | Parse query params and apply queryset filters |

### 5.6 Queryset rules

1. Admin: unrestricted queryset.
2. Managers and viewers: only events in `zev.access.viewable_zev_ids(user)` (active manager/viewer grants or active issuer/representative party roles).
3. Events with `zev = null` are admin-only in v1.
4. Non-admin accounts without community audit read access receive HTTP `403` (`CanViewAuditEvents`).

---

## 6. Async and integration behavior

### 6.1 Request audit context

Add middleware in `backend/audit/middleware.py` to attach request-scoped audit
metadata:

| Property | Source |
|---|---|
| `request.audit_request_id` | Upstream `X-Request-ID` only when it matches `^[A-Za-z0-9._:-]{1,64}$`; otherwise a server-generated UUID4 (never truncate a client value) |
| `request.audit_ip_address` | `config.client_ip.client_ip(request)`: `REMOTE_ADDR` when `NUM_PROXIES=0` or `X-Forwarded-For` is absent; otherwise the entry `-min(NUM_PROXIES, number of entries)` in the comma-separated header, stripped of whitespace |
| `request.audit_user_agent` | Request header, truncated to 500 chars before save |
| `request.audit_source` | `api`; overridden per request by `ApiKeyAuthentication` (`api_key`), `McpApiKeyAuthentication` and MCP sub-requests (`mcp`), and the public invoice/onboarding-link views (`invoice_link`, `onboarding_link`) |

The middleware must not persist events itself. It only prepares context for the
audit service.

IP selection follows DRF's throttle identity hop selection. Empty, invalid, or
scoped IPv6 addresses are stored as `NULL`; scoped IPv6 is excluded because
PostgreSQL's `inet` type cannot store zone identifiers. The default is zero
trusted hops. Deployment values and proxy requirements are documented in
[the chart README](../../charts/openzev/README.md#reverse-proxies-and-num_proxies).

### 6.2 Audit service API

**File:** `backend/audit/services.py`

Required functions:

| Function | Responsibility |
|---|---|
| `record_audit_event(...)` | Persist one normalized audit event |
| `build_diff(before, after, allowed_fields)` | Build field-level diff object |
| `infer_zev(obj)` | Resolve ZEV from heterogeneous target objects |
| `redact_metadata(metadata)` | Apply omission/masking policy |
| `snapshot_actor(user)` | Freeze actor display + role at event time; omit the actor FK when `user.pk` is `None` |

`record_audit_event(...)` must accept either explicit request context or
explicit metadata for Celery/system workflows.

Invalid request context is dropped before insert (`request_id` must match
`REQUEST_ID_PATTERN`, unparseable IPs become `NULL`, display fields are
truncated to their column limits); database failures propagate so the
surrounding transaction rolls back. The audit write is never silently dropped.

**Impersonation attribution.** `record_audit_event` adds `metadata["impersonated_by"]` from
`request.impersonator_id`, stamped by `CookieJWTAuthentication` after JWT validation. This avoids
reading `request.auth` while authentication is still running. The impersonated account remains
the actor; explicit caller attribution is preserved. Ordinary sessions and API keys add no marker.
Both account and external credential refusals record `auth.impersonation.refused` (`DENIED`).

Mixin-driven events (`AuditedUpdateMixin`, `AuditedCreateDestroyMixin` in
`backend/audit/mixins.py`) run the model write and the audit insert inside
one `transaction.atomic()` block, so a failing audit insert rolls back the
mutation it describes. The update mixin reads its before-snapshot outside
that block, so the recorded diff is best-effort under concurrent writes.
Password setup/change/recovery also write their audit event inside the credential
transaction; audit failures roll back password/session/link changes and the post-commit
notification. The `recover_password` management command likewise wraps trusted
recovery and `auth.password.recovered` auditing in one transaction; an audit failure
rolls back its password, session and link/code retirement. Initial setup records the actual prior pending-change flag. MFA login
events distinguish `first_factor` (`password`/`participant_link`) and `second_factor`
(`totp`/`recovery_code`); the existing `method` key is retained, with
`participant_link+totp` for link/TOTP logins.
Grant PATCH/DELETE, party-role changes, account deletion and participant account
link/unlink keep the mutation and success audit in one transaction. Denied account
deletion events are recorded after rollback. If authorization refresh discovers
that the caller was deleted during a lock wait, it clears the stale in-memory
primary key; the denied event keeps the caller's display and role snapshot with
`actor_user = null`, and the request returns 403. Grant POST and invitation resend
record delivery outcomes after committing access/token changes; those audit failures
cannot roll back the earlier commit. Other manual workflow audit boundaries remain
follow-up work unless their feature spec defines an atomic transaction.

### 6.3 Initial workflow coverage matrix

The first implementation slices must instrument these existing modules:

| File | Coverage |
|---|---|
| `backend/accounts/views.py` | user create/update/delete, impersonation, password changes, email verification, feature flags, app settings, VAT changes |
| `backend/zev/views.py` | ZEV create/update/delete, participant CRUD, metering point CRUD, assignment CRUD |
| `backend/tariffs/views.py` | tariff CRUD, tariff preset import/export |
| `backend/invoices/views.py` | generate, generate-all, approve, mark-sent, mark-paid, cancel, delete, generate-pdf, send-email, retry-email |
| `backend/metering/views.py` | import preview/import commit/delete-data and import log–adjacent actions |
| `backend/invoices/tasks.py` | send-email queued/success/failure/retry outcome, including a `FAILED` `invoice.email_task` event when pre-send PDF conflicts exhaust all retries |
| `backend/metering/supplementary/views.py` | `supplementary_source.revoke_push_token` (category `metering`, metadata `prefix`; never the token), see SPEC-2026-tokens-and-keys §5.3 |
| `backend/analytics/views.py` | `analytics_token.create` and `analytics_token.revoke` (category `auth`, target `analytics.AnalyticsToken`, `zev` set; metadata never carries the secret); series reads are not audited, see SPEC-2026-analytics-dataset-api §8 |
| `backend/mcp_server/views.py` | `mcp.tool.call` (category `system`, source `mcp`) once per MCP `tools/call` — success/failed/denied; see SPEC-2026-mcp-server §8 |

### 6.4 Async event rules

1. API endpoints that queue async work record a `queued` or `started` event in
   the request transaction.
2. Celery task completion records a follow-up `success` or `failed` event using
   the same `correlation_id` where available.
3. Async audit events may use `actor_user = null` when no authenticated user is
   present in task context, but should preserve initiating actor metadata in
   `metadata_json` or `correlation_id` when passed from the request layer.

### 6.5 Denied action logging

The system should record `denied` audit events only for security-relevant or
destructive actions where the application has enough context to identify the
target and action, such as:

- forbidden invoice deletion,
- forbidden invoice lifecycle transitions,
- forbidden impersonation attempt,
- forbidden global-settings update.

Ordinary permission denials for generic list/read requests are excluded in v1 to
avoid noise.

---

## 7. Frontend

### 7.1 AuditLogsPage

**File:** `frontend/src/pages/AdminAuditLogsPage.tsx`

- Route: admin scope at `/admin/audit` (Overview hub tab), owner scope at
  `/zev-settings/audit` (ZEV settings hub tab); the legacy routes
  `/admin/audit-logs` and `/audit-logs` redirect there
- ProtectedRoute roles: `['admin']` for admin scope, `ZEV_SCOPE`
  (`['admin', 'manager', 'viewer']` shell roles, #761) for owner scope (guard
  on the parent settings hub)
- `embedded` prop: drops the page header when mounted inside a hub tab
- Query: `useQuery({ queryKey: queryKeys.admin.auditEvents(filters), queryFn: () => fetchAuditEvents(filters) })`
- Detail query: `useQuery({ queryKey: queryKeys.admin.auditEvent(eventId), queryFn: () => fetchAuditEvent(eventId), enabled: !!eventId })`
- Options query: `useQuery({ queryKey: queryKeys.admin.auditFilterOptions(), queryFn: fetchAuditFilterOptions })`

UI elements:

1. Date range filters.
2. ZEV select, admin scope only (options from `fetchAuditFilterOptions`/
   `queryKeys.admin.auditFilterOptions`, derived from the audit queryset
   itself, so the options match the visible event scope). The owner scope
   has no community selector: the request `zev` is the globally selected
   community.
3. Actor select (options from the same `fetchAuditFilterOptions` endpoint —
   distinct users who actually acted on visible events, including owners and
   admins; `id` + `username` only, no email or names; unrelated accounts never
   appear).
4. Category/type/status filters.
5. Search input for summary/target/action-type lookup in both scopes. Platform
   scope requires an admin; community scope requires `isZevScope`, a resolved
   selected community and completed selection loading. Draft text applies on
   Enter or blur, is trimmed and limited to 50 Unicode code points (frontend
   `Array.from`, backend `len`). Oversized drafts show a translated inline error
   and do not apply. Empty search clears `q`. Applying resets page 1; Clear
   clears draft and applied text. Community switches clear both before requesting
   the new scope, so no new-community request carries the old query. Backend
   validation errors are displayed using `formatApiError`.
6. Dense table with timestamp, summary, ZEV (name resolved from the options
   query, raw UUID as fallback), category, action, target, actor, status.
7. Pagination row (page label + Zurück/Weiter buttons) below the table,
   rendered only when the result spans more than one page: DRF
   PageNumberPagination returns `next = previous = null` exactly when
   `count <= PAGE_SIZE` (50), so on single-page results the pager is hidden
   entirely instead of showing two permanently disabled buttons. When shown,
   Zurück is disabled on the first page and Weiter on the last page
   (`!data.previous` / `!data.next`).
8. Detail drawer or modal showing summary, reason, diff, and metadata.

The page follows the same admin CRUD/table conventions used by existing admin
pages and should reuse shared components where available.

The view names its platform or selected-community scope. Community Audit/Export
navigation and draft retention are described in
`2026-08-zev-transfer-archive.md` §9.

`action_category`, `action_type`, `target_type` and `target_id` filters read
from the URL and update via `usePageNavigation`. Category values validate
against `AUDIT_ACTION_CATEGORIES`; other values are passed to the API
filters. The three text inputs keep editable drafts and commit them to the URL
on Enter or blur; category selection applies immediately. External URL changes
synchronize the drafts. Pagination and other controls stay local.
Unchanged search submissions preserve pagination. Clear discards unfinished
drafts; ordinary blur applies them. List requests and filter options require
resolved audit access; community views also require a matching selected community.
Manual Refresh and Retry use the same list eligibility guard. List queries
retry network/server failures up to three times, skip HTTP 4xx retries and do not
refetch on window focus; error feedback offers a guarded manual retry.
A change in effective URL filters or owner community scope resets pagination to page 1 and closes
the selected event before the new query runs. Unrelated query/hash changes do
not reset those states. Reload restores URL filters; edits replace history,
so Back does not undo individual filter edits. Clear removes contextual keys,
resets local filters and closes the drawer, retaining unrelated query/hash and
the selected community.
Source activity links supply `target_type=tariffs.DynamicTariffSource` and
`target_id`; Backup links supply `action_category=system` (all system events,
not exclusively backups).

Initial event loading uses `PageSkeleton tableRows`; failure uses `Notice`
with retry. Cached events remain visible on refetch failure, and a failed
empty result is not also presented as an empty dataset.
Each event summary is a keyboard-operable button opening its detail drawer;
clicking the row remains available.

**Deep-linking an actor** (`?actor=<id>&actorUsername=<username>`, admin scope
only): consumed when received — sets `filters.actorUser`, resets page/selection, remembers
`actorUsername` in local state, then strips both params from the URL
(`usePageNavigation.updateParams`, replacing history and preserving hash), the same consume-then-clear
pattern the Participants page uses for `?focus=`. `actorUsername` exists only
to label the selection when the account has no audit history yet: the actor
`<select>`'s options come from `fetchAuditFilterOptions`, which lists only
accounts that have actually acted on a *visible* event, so a freshly created
or otherwise event-less account would not appear there and the dropdown would
show no visible selection despite the filter being applied correctly. A
synthetic `{id, username: actorUsername}` option is merged into the list
(`actorOptions`, memoized) whenever the linked id is not already present.
Source of the link: **View activity** on an admin accounts row
(`AdminAccountsPage`, §6.4) — `navigate('/admin/audit?actor=<id>&actorUsername=<username>')`.
Filters by *actor*, not *target*: "what has this account done", not "what was
done to it" — the latter is reachable manually via the Target type/Target ID
filters (`accounts.User` / the account's id) but has no dedicated shortcut.

### 7.2 API client functions

**File:** `frontend/src/lib/api/audit.ts`

| Function | Method | Endpoint |
|---|---|---|
| `fetchAuditEvents(params)` | GET | `/audit/events/` |
| `fetchAuditEvent(eventId)` | GET | `/audit/events/{id}/` |
| `fetchAuditFilterOptions()` | GET | `/audit/events/filter-options/` |

### 7.3 Query keys

**File:** `frontend/src/lib/api/queryKeys.ts`

Add:

```typescript
auditEvents: (filters?: unknown) => ['admin', 'audit-events', filters ?? {}] as const,
auditEvent: (eventId: string) => ['admin', 'audit-event', eventId] as const,
auditFilterOptions: () => ['admin', 'audit-events', 'filter-options'] as const,
```

These keys belong under `queryKeys.admin`.

### 7.4 TypeScript types

**File:** `frontend/src/types/api.ts`

```typescript
export type AuditActionCategory =
  | 'auth'
  | 'governance'
  | 'participant'
  | 'metering'
  | 'tariff'
  | 'invoice'
  | 'import'
  | 'template'
  | 'system'

export type AuditEventStatus = 'started' | 'queued' | 'success' | 'failed' | 'denied'

export interface AuditEvent {
  id: string
  created_at: string
  actor_user: number | null
  actor_role_snapshot: string
  actor_display: string
  zev: string | null
  action_category: AuditActionCategory
  action_type: string
  target_type: string
  target_id: string
  target_display: string
  status: AuditEventStatus
  request_id: string | null
  correlation_id: string | null
  source: 'api' | 'api_key' | 'invoice_link' | 'onboarding_link' | 'celery' | 'system' | 'management_command' | 'mcp'
  ip_address: string | null
  user_agent: string
  summary: string
  reason: string
  changes_json: Record<string, unknown>
  metadata_json: Record<string, unknown>
}

export interface AuditEventFilters {
  actor_user?: number
  zev?: string
  action_category?: AuditActionCategory
  action_type?: string
  target_type?: string
  target_id?: string
  status?: AuditEventStatus
  date_from?: string
  date_to?: string
  q?: string
}

export interface AuditFilterOptions {
  zevs: { id: string; name: string }[]
  actors: { id: number; username: string }[]
}
```

### 7.5 Navigation and route registration

**Files:**

- `frontend/src/components/AppRoutes.tsx`
- `frontend/src/components/Layout.tsx`
- `frontend/src/pages/AdminOverviewHubPage.tsx`
- `frontend/src/pages/ZevSettingsPage.tsx`

The admin Overview hub embeds `AuditLogsPage scope="admin"` at `/admin/audit`
under an admin-only guard. ZEV settings embeds `AuditLogsPage scope="owner"`
at `/zev-settings/audit` under an admin/owner guard. Both pass `embedded` to
omit the standalone page header. Legacy `/admin/audit-logs` and `/audit-logs`
URLs redirect to these tabs; there are no standalone audit sidebar entries.
See `2026-03-community-and-access.md` §9 for the navigation contract.

---

## 8. Implementation phases

### Phase 0 — Spec and design

1. Create this spec.
2. Confirm action coverage, redaction rules, and permission model.
3. Record the centralized audit-stream architecture in ADR 0010.

### Phase 1 — Backend foundation

1. Add new `audit` Django app.
2. Implement `AuditEvent` model, serializers, services, middleware, and URLs.
3. Add migration and indexes.
4. Add read-only API endpoints.

### Phase 2 — High-risk workflow coverage

Instrument these first:

1. invoice lifecycle mutations,
2. invoice email async flows,
3. app settings / VAT / feature flags / template changes,
4. user role and impersonation actions.

### Phase 3 — Domain expansion

Add participant, metering point, assignment, tariff, and import mutation
coverage.

### Phase 4 — Frontend UI

1. Add admin audit log page.
2. Wire list/detail queries and filters.
3. Add i18n keys for labels, categories, and statuses.

### Phase 5 — Hardening

1. Validate event volume and payload size.
2. Review redaction policy with real data.
3. Add retention/archival guidance in docs if needed.

---

## 9. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Over-auditing low-value events creates noise | High | Restrict v1 to high-risk writes and async outcomes |
| Sensitive values accidentally persisted | High | Central redaction helper and field allowlists per model |
| Generic model signals lose business context | High | Use explicit service calls in view/service workflows instead of relying primarily on signals |
| Owner-scoped visibility leaks cross-tenant events | High | Filter the base queryset by `zev.access.viewable_zev_ids`; apply search and structured filters only to that scope |
| Event rows become too large | Medium | Keep `changes_json` and `metadata_json` compact, avoid raw blobs/templates |
| Async actions cannot be correlated to initiating request | Medium | Persist `request_id` and pass `correlation_id` into Celery payloads where relevant |
| Audit API becomes slow under growth | Medium | Add indexes from day one and keep list/search filter set limited |

### 9.1 Operational retention guidance

Audit events are operational history, not an infinite compliance archive.
Retention or archival, if introduced later, should use explicit maintenance
jobs or archival tooling rather than in-place mutation of existing rows.
Default operational retention should be long enough to cover invoice, account,
and tenant troubleshooting windows, then move older records to an archive or
remove them under controlled maintenance procedures.

The one slice that is automated is the network detail: `AuditEvent.ip_address`
and `user_agent` are blanked (the event row itself stays) once an event is older
than `PRIVACY_AUDIT_NETWORK_RETENTION_DAYS` (default 365, `0` keeps them), by the
daily privacy sweep — see
[`2026-10-privacy-retention-sweep.md`](2026-10-privacy-retention-sweep.md). The
sweep leaves a `system` / `privacy.swept` event with its counts. Retention of
the event rows themselves is still not implemented.

---

### Operational limits and follow-up

- Cache-backed throttling does not bound concurrent query work. Substring search
  and pagination counts can scan many rows; measure representative PostgreSQL
  query plans and latency before choosing search indexes.
- Deeply nested metadata can exceed Python's recursion limit and fail an audit
  write, rolling back a surrounding business transaction. A depth cap remains a
  separate hardening task.
- Historical rows are unchanged; production history has not been assessed.
  Before deployment, the deployment owner must inventory affected list/scalar
  IBAN payloads, identify their readers and record a remediation decision.
  Rotate credentials if exposure is confirmed; assess cleanup separately.

## 10. Test plan

### Backend — `backend/audit/tests.py`

**`AuditEventModelTests`** (19 tests):

| Test | Asserts |
|---|---|
| `test_audit_event_orders_by_newest_first` | Default ordering is descending by `created_at` |
| `test_audit_event_persists_actor_and_target_snapshots` | Snapshot fields remain populated independently of related object display changes |
| `test_audit_event_preserves_deleted_actor_snapshot` | A deleted actor's display and role persist with no user FK |
| `test_redaction_omits_secret_fields` | Credential keys and aliases are removed case-insensitively |
| `test_redaction_masks_only_iban_fields` | IBAN fields are masked without altering notes or holder/history fields |
| `test_redaction_caps_stringified_values_before_persistence` | Custom values and Decimal strings respect the string cap |
| `test_redaction_preserves_empty_diff_sides` | Empty and fully redacted sides remain explicit in persisted diffs |
| `test_redaction_truncates_large_strings_and_caps_collections` | Oversized values are capped before persistence |
| `test_redaction_recurses_through_lists_tuples_and_diffs` | Nested secrets are omitted and IBANs masked in persisted metadata and before/after diffs |
| `test_redaction_caps_root_and_nested_dictionaries` | Root/nested dictionaries and persisted diffs retain accurate truncation counts |
| `test_redaction_recomputes_marker_shaped_user_values` | Marker-shaped input cannot forge truncation counts |
| `test_scalar_iban_diffs_are_masked_before_persistence` | Scalar IBAN diff sides are masked in persisted events |
| `test_api_key_attribution_survives_oversized_and_spoofed_metadata` | Trusted attribution survives oversized caller metadata and overrides spoofed values |
| `test_record_audit_event_truncates_reason` | Long free-text reasons are truncated |
| `test_build_diff_uses_allowed_fields_only` | Diff helper excludes unapproved fields |
| `test_build_diff_compares_untruncated_values` | Differences beyond the stored string cap still register |
| `test_build_instance_snapshot_reads_fks_without_extra_queries` | Snapshots resolve FKs without extra queries |
| `test_audited_update_mixin_tracks_every_writable_serializer_field` | Audit mixin records every writable serializer field |
| `test_infer_zev_resolves_nested_objects` | ZEV resolution works for invoice/participant/assignment targets |

**`AuditEventApiTests`** (18 tests):

| Test | Asserts |
|---|---|
| `test_admin_can_list_all_audit_events` | Admin sees global and tenant events |
| `test_zev_owner_sees_only_owned_zev_events` | Owner queryset is tenant-scoped |
| `test_owner_cannot_access_global_event_with_null_zev` | Non-admin cannot view global events |
| `test_participant_cannot_access_audit_api` | Participant receives 403 |
| `test_list_filters_by_category_status_and_date_range` | Filtering behavior matches request params |
| `test_list_filters_by_zev_and_actor_user` | List filters by `zev` and `actor_user` params, singly and combined |
| `test_filter_options_admin_sees_all_zevs_and_actors` | Options expose all ZEVs and distinct actors, unpaginated |
| `test_filter_options_owner_scoped_to_own_community` | Owner options only include own ZEVs and actors who acted there (participant, owner, admin) |
| `test_filter_options_participant_forbidden` | Participant receives 403 on options endpoint |
| `test_search_preserves_scope_and_combined_filters` | Matching foreign/global events stay out of results and counts; structured filters cannot widen scope; admins search globally |
| `test_search_matches_each_field` | All three fields match case-insensitively |
| `test_search_treats_input_literally` | Wildcard/SQL-looking/markup/Unicode input remains literal |
| `test_search_ignores_blank_and_trims_input` | Blank returns unfiltered rows; surrounding spaces do not change matches |
| `test_search_validates_text_length_boundaries` | 50-code-point boundary and exact-filter length bounds |
| `test_search_rejects_invalid_structured_filters` | Invalid structured filters return 400 alongside search |
| `test_search_allows_viewer_and_party_derived_manager` | Existing viewer and managing-party read access permits search |
| `test_search_denies_missing_expired_future_and_revoked_access` | No access, inactive grant windows and revoked grants deny search |
| `test_detail_returns_full_diff_and_metadata` | Detail response exposes structured payloads |

**`AuditEventThrottleTests`** (4 tests):

| Test | Asserts |
|---|---|
| `test_cookie_search_budget_is_shared_across_filters_and_api_keys` | Cookie and API-key requests share an account budget across filters and keys |
| `test_users_have_separate_budgets_and_detail_options_are_unaffected` | Other accounts have independent budgets; list exhaustion does not throttle detail/options |
| `test_existing_api_key_budget_still_applies` | Existing per-key throttling is retained alongside the account limit |
| `test_budget_recovers_after_retry_after` | HTTP 429 includes Retry-After and requests resume after the window expires |

### Backend — workflow instrumentation

Coverage is implemented in `backend/audit/tests.py`:

**`AuditInstrumentationTests`** (3 tests): invoice approve, feature-flag
update, and impersonation-denied each emit an audit event with expected payload.

**`AuditPhase3InstrumentationTests`** (10 tests): participant link,
participant update, metering delete-readings, metering point + assignment
updates, tariff create/update (creating an energy tariff with `initial_periods` also records one `tariff_period.create` per band), tariff period update, user update, and the
import-without-file failure each emit the correct audit event.

### Backend — `backend/audit/test_request_context.py` (14 tests)

| Test | Asserts |
|---|---|
| `test_request_id_boundaries` | Absent/empty/65-char/space/`<`/newline `X-Request-ID` yield a server UUID; valid and 64-char values pass through (middleware level, subtests) |
| `test_long_user_agent_is_truncated` | 600-char user agent is truncated to 500 chars |
| `test_long_request_id_is_replaced_with_server_uuid` | 65-char `X-Request-ID` yields a server UUIDv4; response 2xx |
| `test_missing_request_id_generates_server_uuid` | Absent `X-Request-ID` yields a server UUIDv4; response 2xx |
| `test_invalid_forwarded_for_results_in_null_ip` | `X-Forwarded-For: notanip` with `NUM_PROXIES=1` yields `ip_address=None`; response 2xx |
| `test_valid_request_id_and_ip_are_preserved` | Valid `X-Request-ID` / IP pass through unchanged |
| `test_invalid_context_is_dropped_before_insert` | Overlong request ID, garbage IP, and long user agent are sanitized without a retry |
| `test_invalid_context_succeeds_inside_atomic_block` | Sanitized insert succeeds inside `transaction.atomic()` (no `TransactionManagementError`) |
| `test_overlong_display_fields_are_truncated` | Overlong `actor_display` / `summary` / `target_display` / `correlation_id` are capped to column limits |
| `test_failed_audit_rolls_back_model_change` | `record_audit_event` raising `DatabaseError` rolls back the PATCH |
| `test_create_emits_audit_event` / `test_failed_audit_rolls_back_create` | POST emits `participant.create`; audit failure rolls the create back |
| `test_destroy_emits_audit_event` / `test_failed_audit_rolls_back_destroy` | DELETE emits `participant.delete`; audit failure rolls the delete back |

### Backend — `backend/audit/test_summary_parity.py`

**`AuditSummaryParityTests`**: participant, metering point, and metering point
assignment create/delete each emit the event the hand-written blocks produced
before `AuditedCreateDestroyMixin` replaced them — same action type, summary,
`target_display`, and metadata (create-only extras such as `meter_type` stay
create-only):

| Test | Asserts |
|---|---|
| `test_participant_create_summary` / `test_participant_destroy_summary` | `participant.create`/`participant.delete` with `full_name` display and `zev_id` metadata |
| `test_metering_point_create_summary` / `test_metering_point_destroy_summary` | `metering_point.create`/`metering_point.delete` with `meter_id` display; `meter_type` in create metadata only |
| `test_metering_assignment_create_summary` / `test_metering_assignment_destroy_summary` | `metering_assignment.create`/`metering_assignment.delete` with `str(pk)` display; `metering_point_id` in create metadata only |

### Backend — client-IP and proxy trust boundary

Client-IP coverage lives in `backend/config/test_client_ip.py`:
`ClientIpHelperTests` (10 tests) covers zero/one/two-hop selection, missing
headers, short chains, malformed, empty, IPv6, and scoped addresses, plus the
fail-closed `REMOTE_ADDR` fallback when the setting is missing;
`ClientIpThrottleAgreementTests` (3) checks `client_ip()` agrees with DRF's
`SimpleRateThrottle.get_ident()` at 0, 1, and 2 hops from the single
`REST_FRAMEWORK["NUM_PROXIES"]` setting; `AuditMiddlewareIpTests` (2) checks
middleware propagation; `AuditIpPersistenceTests` (1) checks
malformed-address persistence as NULL. `ForwardedForThrottleTests` in
`backend/accounts/test_throttling.py` (3) covers production zero-hop wiring
and forwarded-header throttle buckets. `ProxyTrustBoundaryTests` in
`backend/config/test_proxy_trust_boundary.py` (8) checks deployment
configuration invariants, including the Helm schema constraint on
`backend.numProxies`.

### Frontend

**File:** `frontend/src/lib/api/audit.ts` (client), `frontend/src/pages/AdminAuditLogsPage.tsx` (page)

- `frontend/src/lib/api/audit.ts` has no standalone client test; the page tests
  below stub its `fetchAuditEvents` / `fetchAuditEvent` / `fetchAuditFilterOptions`
  and drive the page through the client's contract.
- `frontend/tests/audit-log-scope.test.ts` for the owner scope binding:
  request carries the selected community, switching rescopes and resets
  page/drawer, clearing filters keeps the scope, no request without a
  selection, admin scope keeps its own selector, and source links supply visible
  target filters from the first request. Mounted contextual-filter changes reset
  pagination/drawer while unrelated URL edits retain them; Clear retains URL context.
  Text typing, including `q`, remains local until Enter/blur, and new actor
  intents close details. Search tests cover manager/viewer/admin community access,
  draft/applied search clearing on community changes with no carried-over query,
  Unicode length limits, participant-only list/options denial, unchanged search
  pagination, pointer Clear without an intermediate request, keyboard blur, HTTP 4xx
  feedback without retries, guarded Refresh/Retry, and escaped markup rendering.
- `frontend/tests/zev-settings-tabs.test.ts` checks that a community switch from
  audit page 3 resets the scoped view to page 1 and closes the old drawer.
- Component/manual validation via `npm run lint`, `npm run build`, and
  `npm run test:unit`.

### Acceptance criteria

- [x] A new append-only `AuditEvent` model is defined with actor, target, ZEV,
      summary, status, and structured diff fields.
- [x] Audit events are written through an explicit service layer with redaction
      and ZEV-resolution helpers.
- [x] The backend exposes read-only audit list/detail endpoints with admin and
      owner-scoped visibility rules.
- [x] Invoice lifecycle, governance settings, account security, and import/email
      async workflows emit audit events in the first rollout slices.
- [x] The frontend provides an admin audit-log page with filters and event
      detail inspection.
- [x] Sensitive secrets, template bodies, raw files, and credentials are not
      stored in audit payloads.
- [x] Oversized audit payloads are truncated or capped before persistence.
- [x] Audit retention guidance exists for long-term operational maintenance.

<!-- markdownlint-enable MD060 -->

Import-log deletion emits one event per affected community. Log counts retain
their original scope; billable/held counts and capped slot samples use the
point's current scope. Legacy moved history never inserts another community's
reading details into the original log community's event. Authorization runs
before waiting for affected-community billing locks and again after waiting.
