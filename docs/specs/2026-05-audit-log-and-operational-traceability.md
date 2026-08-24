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
high-risk write workflows. Admins can search all events, ZEV owners can inspect
events scoped to their communities, and the system records who performed an
action, which tenant it affected, whether it succeeded, and which business
fields changed.

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
| Audit API | List/detail endpoints with filters for admins and scoped read access for ZEV owners |
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
| `zev_owner` | Read only audit events whose resolved `zev` belongs to the owner |
| `participant` | No audit-log access in v1 |
| `guest` | No audit-log access |
| Celery/system | May emit audit events with `actor_user = null` and `source = system` or `source = celery` |

### Backend permission model

Audit endpoints are served under a new `audit` app.

| Endpoint area | Permission |
|---|---|
| `GET /api/v1/audit/events/` | Authenticated admin or ZEV owner; queryset filtered by role |
| `GET /api/v1/audit/events/{id}/` | Same as list; object-level ZEV scope enforced |
| Audit creation | Internal only via service layer; no public POST endpoint |

### Frontend route protection

| Route | ProtectedRoute roles |
|---|---|
| `/admin/audit-logs` | `['admin']` in v1 |
| `/audit-logs` | `['admin', 'zev_owner']` in v1 |

The same read-only audit view is rendered in two scopes:

- admin scope at `/admin/audit-logs`, with global visibility and search
  enabled,
- owner scope at `/audit-logs`, with ZEV-scoped visibility and search disabled.

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
| `source` | `CharField(20)` | `api` | `api`, `api_key`, `celery`, `system`, `management_command` |
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

---

## 5. API contracts

The audit API is read-only. Events are created only by backend services.

### 5.1 URL registration

Add a new include in `backend/config/urls.py`:

| Path prefix | Include |
|---|---|
| `/api/v1/audit/` | `include('audit.urls')` |

### 5.2 Endpoints

| Endpoint | Method | Permission | Behaviour |
|---|---|---|---|
| `/api/v1/audit/events/` | GET | Authenticated admin or `zev_owner` | Paginated list with role-scoped filtering |
| `/api/v1/audit/events/{id}/` | GET | Authenticated admin or `zev_owner` | Single event detail if event is visible to actor |
| `/api/v1/audit/events/filter-options/` | GET | Authenticated admin or `zev_owner` | Unpaginated `{zevs, actors}` distinct options derived from the visible event queryset |

### 5.3 List query parameters

| Param | Type | Description |
|---|---|---|
| `actor_user` | int | Filter by actor user ID |
| `zev` | UUID | Filter by ZEV |
| `action_category` | string | Filter by category |
| `action_type` | string | Filter by exact action name |
| `target_type` | string | Filter by target model label |
| `target_id` | string | Filter by target primary key |
| `status` | string | Filter by event status |
| `date_from` | ISO date | Inclusive lower bound on `created_at` date |
| `date_to` | ISO date | Inclusive upper bound on `created_at` date |
| `q` | string | Case-insensitive summary/target search; admin-only in v1 |

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
2. ZEV owner: only events where `zev.owner == request.user`.
3. Events with `zev = null` are admin-only in v1.
4. Participant and guest users receive HTTP `403`.

---

## 6. Async and integration behavior

### 6.1 Request audit context

Add middleware in `backend/audit/middleware.py` to attach request-scoped audit
metadata:

| Property | Source |
|---|---|
| `request.audit_request_id` | Generated UUID or upstream `X-Request-ID` |
| `request.audit_ip_address` | Remote IP / forwarded-for handling per current deployment trust rules |
| `request.audit_user_agent` | Request header |
| `request.audit_source` | `api` |

The middleware must not persist events itself. It only prepares context for the
audit service.

### 6.2 Audit service API

**File:** `backend/audit/services.py`

Required functions:

| Function | Responsibility |
|---|---|
| `record_audit_event(...)` | Persist one normalized audit event |
| `build_diff(before, after, allowed_fields)` | Build field-level diff object |
| `infer_zev(obj)` | Resolve ZEV from heterogeneous target objects |
| `redact_metadata(metadata)` | Apply omission/masking policy |
| `snapshot_actor(user)` | Freeze actor display + role at event time |

`record_audit_event(...)` must accept either explicit request context or
explicit metadata for Celery/system workflows.

### 6.3 Initial workflow coverage matrix

The first implementation slices must instrument these existing modules:

| File | Coverage |
|---|---|
| `backend/accounts/views.py` | user create/update/delete, impersonation, password changes, email verification, feature flags, app settings, VAT changes |
| `backend/zev/views.py` | ZEV create/update/delete, participant CRUD, metering point CRUD, assignment CRUD |
| `backend/tariffs/views.py` | tariff CRUD, tariff preset import/export |
| `backend/invoices/views.py` | generate, generate-all, approve, mark-sent, mark-paid, cancel, delete, generate-pdf, send-email, retry-email |
| `backend/metering/views.py` | import preview/import commit/delete-data and import log–adjacent actions |
| `backend/invoices/tasks.py` | send-email queued/success/failure/retry outcome |

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

- Route: `/admin/audit-logs` for admin scope and `/audit-logs` for owner scope
- ProtectedRoute roles: `['admin']` for admin scope, `['admin', 'zev_owner']` for owner scope
- Query: `useQuery({ queryKey: queryKeys.admin.auditEvents(filters), queryFn: () => fetchAuditEvents(filters) })`
- Detail query: `useQuery({ queryKey: queryKeys.admin.auditEvent(eventId), queryFn: () => fetchAuditEvent(eventId), enabled: !!eventId })`
- Options query: `useQuery({ queryKey: queryKeys.admin.auditFilterOptions(), queryFn: fetchAuditFilterOptions })`

UI elements:

1. Date range filters.
2. ZEV select (options from `fetchAuditFilterOptions`/`queryKeys.admin.auditFilterOptions`;
   derived from the audit queryset itself, so the options match the visible
   event scope: owner scope shows only ZEVs the owner has events for, admin
   scope all ZEVs with events).
3. Actor select (options from the same `fetchAuditFilterOptions` endpoint —
   distinct users who actually acted on visible events, including owners and
   admins; `id` + `username` only, no email or names; unrelated accounts never
   appear).
4. Category/type/status filters.
5. Search input for summary/target lookup — admin-only: disabled for everyone
   except users with `role = 'admin'`, with the `searchRestricted` hint shown.
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

export interface AuditFieldChange {
  before: string | number | boolean | null | string[] | number[] | boolean[]
  after: string | number | boolean | null | string[] | number[] | boolean[]
}

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
  source: 'api' | 'api_key' | 'celery' | 'system' | 'management_command'
  ip_address: string | null
  user_agent: string
  summary: string
  reason: string
  changes_json: Record<string, AuditFieldChange>
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

- `frontend/src/App.tsx`
- `frontend/src/components/Layout.tsx`

Required changes:

1. Lazy-load the shared audit-log page component in `App.tsx`.
2. Register `/admin/audit-logs` under admin-only routes.
3. Register `/audit-logs` under admin or ZEV-owner routes.
4. Add a navigation entry in the admin section of the layout.
5. Add a navigation entry in the manage section for ZEV owners and admins.

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
| Owner-scoped visibility leaks cross-tenant events | High | Require resolved `zev` for owner-visible events and filter queryset by `zev.owner` |
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

---

## 10. Test plan

### Backend — `backend/audit/tests.py`

**`AuditEventModelTests`** (9 tests):

| Test | Asserts |
|---|---|
| `test_audit_event_orders_by_newest_first` | Default ordering is descending by `created_at` |
| `test_audit_event_persists_actor_and_target_snapshots` | Snapshot fields remain populated independently of related object display changes |
| `test_redaction_omits_secret_fields` | Secrets and masked fields are redacted before persistence |
| `test_redaction_truncates_large_strings_and_caps_collections` | Oversized values are capped before persistence |
| `test_record_audit_event_truncates_reason` | Long free-text reasons are truncated |
| `test_build_diff_uses_allowed_fields_only` | Diff helper excludes unapproved fields |
| `test_build_instance_snapshot_reads_fks_without_extra_queries` | Snapshots resolve FKs without extra queries |
| `test_audited_update_mixin_tracks_every_writable_serializer_field` | Audit mixin records every writable serializer field |
| `test_infer_zev_resolves_nested_objects` | ZEV resolution works for invoice/participant/assignment targets |

**`AuditEventApiTests`** (10 tests):

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
| `test_detail_returns_full_diff_and_metadata` | Detail response exposes structured payloads |

### Backend — workflow instrumentation

Coverage is implemented in `backend/audit/tests.py`:

**`AuditInstrumentationTests`** (3 tests): invoice approve, feature-flag
update, and impersonation-denied each emit an audit event with expected payload.

**`AuditPhase3InstrumentationTests`** (10 tests): participant link,
participant update, metering delete-readings, metering point + assignment
updates, tariff create/update, tariff period update, user update, and the
import-without-file failure each emit the correct audit event.

### Frontend

**File:** `frontend/src/lib/api/audit.ts` (client), `frontend/src/pages/AdminAuditLogsPage.tsx` (page)

- `frontend/tests/api-audit.test.ts` for client request/response handling.
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