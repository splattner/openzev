# Audit Log Implementation Tracker

> **⚠ Archived.** The audit-log initiative is fully implemented. All phases below
> are complete. This file is kept as historical implementation notes only; the
> canonical document is the completed baseline spec
> [2026-05-audit-log-and-operational-traceability.md](2026-05-audit-log-and-operational-traceability.md).

- Related spec: [2026-05-audit-log-and-operational-traceability.md](2026-05-audit-log-and-operational-traceability.md)
- Related ADRs:
  - [0008-security-and-audit-logging.md](../adr/0008-security-and-audit-logging.md)
  - [0010-centralized-audit-event-stream.md](../adr/0010-centralized-audit-event-stream.md)
- Owner: Core maintainers
- Last updated: 2026-05-09
- Status: Archived

## Purpose

This file is the execution checklist for the audit-log initiative.

Use it to track concrete progress across sessions and PRs without re-reading the full feature spec every time.

## Progress Summary

- [x] Phase 0 complete: Spec and ADR alignment
- [x] Phase 1 complete: Backend foundation
- [x] Phase 2 complete: High-risk workflow coverage
- [x] Phase 3 complete: Domain expansion
- [x] Phase 4 complete: Frontend UI
- [x] Phase 5 complete: Hardening

## Phase 0: Spec and Design (Complete)

### Phase 0 Deliverables

- [x] Feature spec created and approved for implementation baseline:
  [2026-05-audit-log-and-operational-traceability.md](2026-05-audit-log-and-operational-traceability.md)
- [x] Follow-up ADR created and indexed:
  [0010-centralized-audit-event-stream.md](../adr/0010-centralized-audit-event-stream.md)
- [x] Scope boundaries set (high-risk writes only, no read-audit in v1)
- [x] Redaction policy documented

### Phase 0 Exit Criteria

- [x] Spec and ADR cross-linked and lint-clean

## Phase 1: Backend Foundation

### Phase 1 Deliverables

- [x] Create new backend app: audit
- [x] Add model: AuditEvent with required indexes and constraints
- [x] Add serializers: AuditEventSerializer (read-only)
- [x] Add service module: record_audit_event, build_diff, infer_zev, redact_metadata
- [x] Add request middleware for audit context (request id, ip, user-agent, source)
- [x] Add API endpoints (read-only):
  - [x] GET /api/v1/audit/events/
  - [x] GET /api/v1/audit/events/{id}/
- [x] Register route include in backend config urls
- [x] Add tests for model/service/API base behavior

### Phase 1 Suggested File Targets

- backend/audit/apps.py
- backend/audit/models.py
- backend/audit/serializers.py
- backend/audit/services.py
- backend/audit/views.py
- backend/audit/urls.py
- backend/audit/tests.py
- backend/config/urls.py
- backend/config/settings.py

### Phase 1 Exit Criteria

- [x] Migration applies cleanly
- [x] Audit API is role-scoped (admin global, owner by zev, participant denied)
- [x] Secrets redacted in persisted metadata
- [x] Targeted audit test suite passes

## Phase 2: High-Risk Workflow Coverage

### Phase 2 Deliverables

- [x] Instrument invoice lifecycle actions (generate/approve/mark-sent/mark-paid/cancel/delete)
- [x] Instrument invoice email async flow (queued/sent/failed/retry)
- [x] Instrument governance mutations (app settings, VAT, feature flags, templates)
- [x] Instrument account-security mutations (impersonation, role changes, critical account updates)

### Phase 2 Suggested File Targets

- backend/invoices/views.py
- backend/invoices/tasks.py
- backend/accounts/views.py

### Phase 2 Exit Criteria

- [x] Covered actions create events with actor, target, status, summary, and diff
- [x] Failed/denied events recorded for destructive or guarded operations

## Phase 3: Domain Expansion

### Phase 3 Deliverables

- [x] Instrument participant CRUD and link/unlink flows
- [x] Instrument metering point + assignment CRUD and metering delete-data actions
- [x] Instrument tariff CRUD and tariff import/export mutations
- [x] Instrument import workflow start/result/failure beyond existing ImportLog

### Phase 3 Suggested File Targets

- backend/zev/views.py
- backend/tariffs/views.py
- backend/metering/views.py

### Phase 3 Exit Criteria

- [x] All listed domain mutations produce consistent audit events
- [x] Tenant scoping resolves correctly for nested targets

## Phase 4: Frontend UI

### Phase 4 Deliverables

- [x] Add API client module for audit endpoints
- [x] Add types in frontend api types
- [x] Add query keys under admin scope
- [x] Create AdminAuditLogsPage with list + detail and filters
- [x] Register route /admin/audit-logs in App routing
- [x] Add navigation entry in layout
- [x] Add i18n keys in en/de/fr/it

### Phase 4 Suggested File Targets

- frontend/src/lib/api/audit.ts
- frontend/src/types/api.ts
- frontend/src/lib/api/queryKeys.ts
- frontend/src/pages/AdminAuditLogsPage.tsx
- frontend/src/App.tsx
- frontend/src/components/Layout.tsx
- frontend/src/i18n/locales/en.ts
- frontend/src/i18n/locales/de.ts
- frontend/src/i18n/locales/fr.ts
- frontend/src/i18n/locales/it.ts

### Phase 4 Exit Criteria

- [x] Admin can filter and inspect audit records end-to-end
- [x] Non-admin route access correctly blocked

## Phase 5: Hardening

### Phase 5 Deliverables

- [x] Add owner-facing read-only audit view (scoped)
- [x] Validate payload size and event volume in realistic workloads
- [x] Tighten redaction allowlists based on observed data
- [x] Add retention/archival operational guidance (if needed)
- [x] Add final docs updates to baseline specs if behavior changed there

### Phase 5 Exit Criteria

- [x] Performance acceptable with index-backed list filters
- [x] No sensitive data leakage in stored audit events
- [x] End-to-end backend/frontend validation green

## Validation Commands

### Backend

- python -m pytest accounts/ zev/ tariffs/ metering/ invoices/ -q

### Frontend

- npm run lint
- npm run test:unit
- npm run build

## PR Tracking Notes

When opening implementation PRs for this initiative, include:

1. Completed checklist items from this file.
2. Which phase is being delivered.
3. Any spec or ADR deltas discovered during implementation.
4. Evidence of test commands and key results.
