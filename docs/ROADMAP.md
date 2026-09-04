# OpenZEV Roadmap

This document tracks shipped features, active work, planned ideas, and deferred items across all parts of the platform. It is the single strategic view of where OpenZEV has been and where it is going.

## How to use this

- **Before starting work on a new feature**, check if it already appears here. If it does, read the linked spec or ADR before coding.
- **After shipping a feature**, move its entry to the `shipped` section and link the relevant spec/PR.
- **When a new idea surfaces**, add it as `idea` with a short description. Add a spec when you commit to it.
- This file does **not** replace specs or ADRs. It is the high-level index; specs carry implementation-grade detail.

## Status tags

| Tag | Meaning |
|---|---|
| `shipped` | Implemented and in production |
| `in-progress` | Branch or PR open |
| `planned` | Spec or ADR exists; not yet started |
| `idea` | No spec yet; worth exploring |
| `deferred` | Considered and explicitly postponed |
| `removed` | Was implemented, then superseded/removed; see notes for the replacement |

## Priority (unshipped only)

| Level | Meaning |
|---|---|
| `high` | Blocking or nearly blocking real users |
| `medium` | Meaningful value, reasonable effort |
| `low` | Nice to have; effort may exceed value |

---

## Competitive Landscape

> **⚠ Historical snapshot — dated May 2026.** This section records the competitive
> landscape and product/regulatory claims as of that date and may have aged. Treat
> it as research context only; current status lives below under each theme.

Research conducted May 2026. Primary source: **PVshare** (pvshare.ch) — the leading Swiss vZEV/LEG SaaS billing platform.

### PVshare at a glance

PVshare Cockpit is a closed, subscription-based SaaS (CHF ~30/participant/year) targeting self-managing vZEV/LEG responsible parties in Switzerland. Its strengths are:

- Fully automated data ingestion via swisseldex / SDAT-CH-Hub; billing on autopilot with manual approval gate.
- Supports both **vZEV** and **LEG** (Lokale Elektrizitätsgemeinschaft, new 2026 Swiss law).
- All participants get read-only self-service access to their own stats and invoices via email auto-linking (no admin invite flow required).
- Guided founding wizard with document templates for grid operator correspondence.
- Configurable billing interval (monthly → annual, changeable any time) — already matched in OpenZEV.
- Demand tariff (Leistungstarif, e.g. CKW) and HT/NT tariff support — OpenZEV has HT/NT but not demand tariffs.
- Day-exact proration for mid-period participant/meter changes — OpenZEV has validity windows; proration in billing engine needs validation.
- Status-check page: proactive, one-click config validation with fix hints.
- Partner/billing-service access model (third-party can manage ZEV on behalf of responsible party).

### OpenZEV differentiators

- **Open source / self-hosted** — no per-participant cost, no vendor lock-in, data sovereignty guaranteed.
- **Fine-grained audit log** — full event stream with actor, payload diff, async correlation.
- **Role hierarchy** — `admin`, `zev_owner`, `participant`, `guest` vs. PVshare's two-tier model.
- **Multi-ZEV admin** — single admin instance can govern many ZEVs across organizations.
- **API-first** — REST API allows custom integrations and automation scripts.

### Feature gaps identified

| PVshare feature | OpenZEV status | Roadmap action |
|---|---|---|
| LEG (Lokale Elektrizitätsgemeinschaft) support | Not supported | Added as `idea` — regulatory, new 2026 law |
| Demand tariff (Leistungstarif) | Not supported | Added as `idea` — needed for CKW/similar grids |
| Participant self-service onboarding via email auto-link | Admin invite only | Added as `idea` |
| Invoice run reject + auto-recalculate workflow | Approve/cancel only | Added as `idea` |
| Vacant unit auto-billing to ZEV responsible | Not explicit | Added as `idea` |
| Proactive status-check page for ZEV owners | Data quality badges only | Added as `idea` |
| Guided vZEV founding wizard with document templates | Setup wizard partial | Added as `idea` |
| vZEV profit/feasibility calculator | `shipped` | Multi-participant calculator with prefill from real ZEV data — see Invoicing & Billing |
| BFE reference market price auto-fetch (feed-in rate) | Manual tariff entry | Added as `idea` |
| CO₂ savings display in participant statistics | Not present | Added as `idea` |
| Partner / third-party billing access model | Not present | Added as `idea` |

---

## Themes

- [Invoicing & Billing](#invoicing--billing)
- [Metering & Data Quality](#metering--data-quality)
- [Participants & Community](#participants--community)
- [Audit & Traceability](#audit--traceability)
- [Access & Auth](#access--auth)
- [Admin & Governance](#admin--governance)
- [Participant Self-Service](#participant-self-service)
- [Platform & Ops](#platform--ops)

---

## Invoicing & Billing

| Feature | Status | Priority | Notes / Spec |
|---|---|---|---|
| Invoice lifecycle state machine (draft → approved → sent → paid → cancelled) | `shipped` | — | [spec](specs/2026-03-invoice-lifecycle-and-communication.md) |
| Per-participant invoice generation for a billing period | `shipped` | — | [spec](specs/2026-03-invoice-lifecycle-and-communication.md) |
| Bulk `generate-all` invoices for an entire ZEV (async via Celery) | `shipped` | — | [spec](specs/2026-03-invoice-lifecycle-and-communication.md), [ADR 0011](adr/0011-async-bulk-invoice-generation.md) |
| Batch approve / cancel / delete invoices | `shipped` | — | — |
| Invoice PDF generation with Swiss QR-Rechnung, savings chart, and hourly profile | `shipped` | — | [spec](specs/2026-03-invoice-lifecycle-and-communication.md) |
| DB-stored PDF template with admin editor and revert-to-default | `shipped` | — | [spec](specs/2026-03-invoice-lifecycle-and-communication.md) |
| Invoice bulk export — ZIP download of all period PDFs (`POST /invoices/invoices/download-pdfs/`) | `shipped` | — | [spec](specs/2026-03-invoice-lifecycle-and-communication.md) |
| Asynchronous invoice email delivery via Celery (3 retries, `EmailLog`) | `shipped` | — | [spec](specs/2026-03-invoice-lifecycle-and-communication.md) |
| Email retry for failed `EmailLog` entries | `shipped` | — | — |
| Per-ZEV customizable email subject/body templates with 6 interpolation variables | `shipped` | — | [spec](specs/2026-03-invoice-lifecycle-and-communication.md) |
| Timestamp-level energy allocation billing engine (local vs. grid split) | `shipped` | — | [spec](specs/2026-03-tariffs-and-billing-engine.md) |
| Producer credit allocation (local-consumption credit + feed-in compensation) | `shipped` | — | [spec](specs/2026-03-tariffs-and-billing-engine.md) |
| Six billing modes (energy, % of grid, monthly fee, yearly fee, per-meter monthly/yearly) | `shipped` | — | [spec](specs/2026-03-tariffs-and-billing-engine.md) |
| Time-band pricing with time-of-day, weekday, and month windows | `shipped` | — | HT/NT plus seasonal bands (#527) and three-or-more bands per tariff (#528) — [spec](specs/2026-03-tariffs-and-billing-engine.md) |
| Four tariff categories (energy, grid fees, levies, metering) | `shipped` | — | [spec](specs/2026-03-tariffs-and-billing-engine.md) |
| Tariff-only JSON export/import (tariff preset) | `removed` | — | Superseded by whole-ZEV transfer — [spec](specs/2026-08-zev-transfer-archive.md), [guide](user-guide/17-zev-transfer.md) |
| Tariff import from the grid operator's Art. 7b publication (VSE/AES standard, URL fetch, previewed and per-entry selected) | `shipped` | — | [spec](specs/2026-09-vse-tariff-import.md), #507 |
| VAT application with validity-windowed VAT rate table | `shipped` | — | [spec](specs/2026-03-tariffs-and-billing-engine.md) |
| Annual financial report for tax purposes | `shipped` | — | — |
| Period overview with strict daily completeness checking | `shipped` | — | [spec](specs/2026-03-invoice-lifecycle-and-communication.md) |
| Contract PDF (multi-language, tariff rates, metering points, billing interval) | `shipped` | — | — |
| vZEV feasibility / profitability calculator (aggregate or per-participant, energy-flow topology, self-consumption & internal-price sensitivity, payback/ROI/NPV, prefill of a real ZEV's participants, measured self-consumption, and all-in tariffs) | `shipped` | — | [guide](user-guide/13-feasibility-calculator.md) |
| Scheduled invoice auto-generation (cron-triggered, per-ZEV billing interval) | `idea` | `medium` | Would remove the manual "generate all" step each month |
| Payment reference number (QRR / SCOR) on the invoice QR bill | `idea` | `medium` | Needed for automated bank reconciliation; the QR bill already ships, the structured reference does not — #536 |
| Dynamic tariffs (`tariffForm: dynamic`) | `idea` | `low` | Price served by an external time series; the standard defines it as a bare URL with no response schema, so it needs a real operator endpoint to build against — #530 |
| Invoice data export — CSV export of invoice line items | `idea` | `low` | Useful for external accounting software |
| Mark invoice as disputed / on-hold state | `idea` | `low` | Would require an extra lifecycle state and guard |
| Credit note / corrective invoice generation | `idea` | `low` | Complex billing edge case; needs dedicated spec |
| Send invoice email from custom SMTP sender per ZEV | `idea` | `low` | Currently uses system-wide SMTP settings |
| Invoice run reject + auto-recalculate workflow | `idea` | `medium` | PVshare: reject a run, fix config, confirm → system auto-rebuilds run in 1–2 days; smoother than manual regenerate |
| Vacant unit auto-billing to ZEV responsible | `idea` | `medium` | When no participant assignment exists for a unit in a period, bill the ZEV owner automatically (PVshare parity) |
| LEG (Lokale Elektrizitätsgemeinschaft) billing model | `planned` | `high` | New Swiss law since 2026; LEG bills only internally-exchanged energy; grid operator settles remainder directly — fundamentally different from vZEV model — [spec](specs/2026-06-leg-billing-model.md) |

---

## Metering & Data Quality

| Feature | Status | Priority | Notes / Spec |
|---|---|---|---|
| `MeterReading` model with kWh, direction, resolution, import source, batch UUID | `shipped` | — | [spec](specs/2026-03-metering-import-and-quality.md) |
| CSV / Excel import with two format profiles and configurable column mapping | `shipped` | — | [spec](specs/2026-03-metering-import-and-quality.md) |
| SDAT-CH (ebIX XML) Swiss VNB metering data import | `shipped` | — | [spec](specs/2026-03-metering-import-and-quality.md) |
| Preview / dry-run workflow for CSV imports | `shipped` | — | [spec](specs/2026-03-metering-import-and-quality.md) |
| Skip-existing and overwrite write modes | `shipped` | — | — |
| `ImportLog` per-import operational log with row counts and per-row errors | `shipped` | — | [spec](specs/2026-03-metering-import-and-quality.md) |
| Import log deletion (single + bulk, cascades readings) | `shipped` | — | — |
| Chart data endpoint (aggregated energy by direction, bucketed day/hour/month) | `shipped` | — | — |
| Data quality status (green/yellow/red gap detection with gap spans) | `shipped` | — | [spec](specs/2026-03-metering-import-and-quality.md) |
| Energy flow Sankey chart (ZEV-level production/consumption overview) | `shipped` | — | — |
| Data completeness alerts — notify ZEV owner when metering gap detected | `idea` | `high` | Proactive; prevents invoice blocking surprises |
| Flag holder-less readings in data-quality status | `shipped` | — | PR #396; unassigned readings surfaced per metering point |
| Automated SDAT-CH polling / scheduled import from VNB | `idea` | `medium` | Removes manual upload step for SDAT customers |
| Bulk meter reading export (CSV/Excel) for a period and ZEV | `idea` | `medium` | Needed for external analysis and audit |
| Anomaly / outlier detection on imported readings | `idea` | `low` | Flag unusually high/low values before billing |
| Real-time or near-real-time metering ingestion (MQTT / push API) | `deferred` | — | Significant infrastructure change; out of scope for current architecture |
| Demand tariff (Leistungstarif) support | `idea` | `high` | Monthly peak-demand billing (CHF/kW); CKW introduced in 2025; required for some Swiss grids. Peak kW *is* derivable from stored readings (`energy_kwh × 4` at 15-minute resolution); what is missing is a billing mode, an engine pass, and a decision on whose peak is billed — #529 |
| BFE reference market price auto-fetch | `idea` | `low` | Automatically retrieve Swiss federal BFE quarterly PV feed-in reference price so ZEV owners don't need to look it up manually |

---

## Participants & Community

| Feature | Status | Priority | Notes / Spec |
|---|---|---|---|
| ZEV CRUD (admin-scoped and owner-scoped) | `shipped` | — | [spec](specs/2026-03-metering-point-management.md) |
| Admin ZEV creation wizard (creates ZEV + owner + participant + meters in one transaction) | `shipped` | — | [spec](specs/2026-03-metering-point-management.md) |
| Self-setup for self-registered ZEV owners | `shipped` | — | — |
| Grid operator (VNB) picked from the official ElCom list instead of typed | `shipped` | — | PR #519 |
| Participant CRUD with validity window | `shipped` | — | [spec](specs/2026-03-metering-point-management.md) |
| Participant invitation (reset password + email with temporary credentials) | `shipped` | — | — |
| Participant account linking / unlinking | `shipped` | — | [spec](specs/2026-03-metering-point-management.md) |
| Auto-create user account on participant creation | `shipped` | — | — |
| Participant contract PDF (metering points, tariffs, billing interval, notes) | `shipped` | — | Versioned contract snapshots on download (PR #443) |
| Participant status indicator | `shipped` | — | — |
| Participant location map (OpenStreetMap building outlines, geocoded from address) | `shipped` | — | [ADR 0012](adr/0012-participant-geocoding-via-nominatim.md) |
| `MeteringPoint` CRUD (consumption, production, bidirectional types) | `shipped` | — | [spec](specs/2026-03-metering-point-management.md) |
| Assignment-only validity model (`MeteringPointAssignment` with date range) | `shipped` | — | [ADR 0009](adr/0009-remove-direct-meteringpoint-participant-fk.md) |
| `MeteringPointAssignment` CRUD with overlap/containment validation | `shipped` | — | [spec](specs/2026-03-metering-point-management.md) |
| Bulk participant import from CSV | `idea` | `medium` | Useful when onboarding large ZEVs; reduces manual data entry |
| Participant move between ZEVs | `idea` | `low` | Complex; requires data migration of assignments and readings |
| ZEV merge (combine two ZEVs into one) | `idea` | `low` | Rare edge case; needs dedicated spec |
| Participant self-service onboarding via email auto-link | `idea` | `medium` | PVshare model: ZEV owner records participant email; participant visits onboarding URL and creates account → auto-linked without admin invite flow |
| Guided ZEV founding wizard with grid-operator document templates | `idea` | `medium` | Step-by-step process for new ZEV setup including document templates for VNB correspondence; PVshare key differentiator |
| Partner / third-party billing access model | `idea` | `low` | Allow a solar installer or billing service partner to manage a ZEV on behalf of the responsible party; requires scoped delegation role |

---

## Audit & Traceability

| Feature | Status | Priority | Notes / Spec |
|---|---|---|---|
| Centralized `AuditEvent` model (append-only, 6 indexes, actor/target/ZEV/status snapshots) | `shipped` | — | [spec](specs/2026-05-audit-log-and-operational-traceability.md), [ADR 0010](adr/0010-centralized-audit-event-stream.md) |
| Request attribution middleware (request ID, IP, user agent) | `shipped` | — | — |
| ZEV resolution from heterogeneous target objects | `shipped` | — | — |
| Payload hardening (string cap 500 chars, list cap 20, reason cap 2000, IBAN masking, secret omission) | `shipped` | — | — |
| Field diff capture (`build_diff` with whitelisted fields) | `shipped` | — | — |
| Workflow coverage: invoice lifecycle, email, account/user, ZEV, participant, metering, tariff, import, templates | `shipped` | — | — |
| Async audit events from Celery tasks (`queued`/`success`/`failed`, linked by `correlation_id`) | `shipped` | — | — |
| Audit read-only API (paginated list + detail, admin-global and ZEV-owner-scoped) | `shipped` | — | — |
| Audit list filters (actor, ZEV, category, action type, target type/id, status, date range, text search) | `shipped` | — | — |
| Frontend audit log page (admin + owner scope, filters, paginated table, detail with diff viewer) | `shipped` | — | — |
| Audit log export (CSV or JSON) for a filtered time range | `idea` | `medium` | Useful for compliance reviews and incident hand-off |
| Participant-scoped audit view (show own actions to participant role) | `deferred` | — | Explicitly deferred to v2 in spec |
| Full-text search on audit list for ZEV owners | `deferred` | — | Admin-only in v1 by design; revisit if owner needs grow |
| Configurable retention / automated archival job | `idea` | `low` | Operational guidance exists; automation not yet implemented |
| SIEM / webhook / streaming export of audit events | `deferred` | — | Out of scope for v1 |
| Audit historical backfill (pre-feature changes) | `deferred` | — | Explicitly out of scope |

---

## Access & Auth

| Feature | Status | Priority | Notes / Spec |
|---|---|---|---|
| JWT authentication (SimpleJWT; email or username login) | `shipped` | — | [spec](specs/2026-03-community-and-access.md) |
| Role hierarchy: `admin`, `zev_owner`, `participant`, `guest` | `shipped` | — | [spec](specs/2026-03-community-and-access.md) |
| ZEV-scoped permission classes enforced at object level | `shipped` | — | [ADR 0003](adr/0003-role-and-zev-scope-enforcement.md) |
| Self-registration for ZEV owners with email verification | `shipped` | — | [spec](specs/2026-03-community-and-access.md) |
| Email verification (24h token, auto-issues JWT on success) | `shipped` | — | — |
| Forced password change redirect on first login | `shipped` | — | — |
| Password change (authenticated, old-password verification) | `shipped` | — | — |
| Initial password set for admin-created accounts | `shipped` | — | — |
| Admin impersonation (with impersonator identity preserved in token) | `shipped` | — | [spec](specs/2026-03-community-and-access.md) |
| OAuth authentication with configurable redirect URL | `shipped` | — | Client secret write-only (PR #432); CSRF enforcement for cookie JWT sessions (PR #446) |
| Feature flag to disable self-registration globally | `shipped` | — | — |
| Admin-only restriction on `/auth/users/` endpoint | `shipped` | — | PR #430 |
| Upload parsing hardening (zip bombs, parse loops, size caps) | `shipped` | — | PR #449; [spec](specs/2026-03-metering-import-and-quality.md) §4.4 |
| `ProtectedRoute` with `allowedRoles` on all frontend routes | `shipped` | — | — |
| Two-factor authentication (TOTP) | `idea` | `medium` | Security improvement for admin and ZEV owner accounts |
| Session management page (list and revoke active tokens) | `idea` | `low` | Useful for security-conscious owners |
| Per-user API keys for automated integrations | `shipped` | — | Owner-managed keys with revoke; backend key auth + throttling — [guide](user-guide/16-api-keys.md) |
| Admin console for API key management | `shipped` | — | PR #409 |
| External SSO / enterprise IdP (SAML, OIDC beyond current OAuth) | `deferred` | — | Out of scope; requires significant auth infrastructure work |

---

## Admin & Governance

| Feature | Status | Priority | Notes / Spec |
|---|---|---|---|
| Global `AppSettings` singleton (date format; loaded at frontend boot) | `shipped` | — | [spec](specs/2026-03-admin-governance-and-settings.md) |
| VAT rate table with validity windows and `active_for_day()` lookup | `shipped` | — | [spec](specs/2026-03-admin-governance-and-settings.md) |
| ZEV billing settings (interval, invoice prefix/counter/language, bank IBAN, VAT number) | `shipped` | — | [spec](specs/2026-03-admin-governance-and-settings.md) |
| Admin revenue dashboard (ZEV/participant/invoice counts, revenue totals, recent invoices) | `shipped` | — | [spec](specs/2026-03-admin-governance-and-settings.md) |
| Feature flag management (admin toggle via API and UI) | `shipped` | — | [spec](specs/2026-03-admin-governance-and-settings.md) |
| User account management by admin (CRUD, safety block on linked participant delete) | `shipped` | — | — |
| PDF template editor for invoice and contract templates | `shipped` | — | — |
| Sample data generator management command | `shipped` | — | — |
| ZEV-level contract notes for contract PDF | `shipped` | — | — |
| System health dashboard (job queue depth, failed tasks, DB health) | `idea` | `medium` | Operational visibility without needing server access |
| Scheduled job status page (Celery task history, retry counts) | `idea` | `medium` | Currently not visible in UI; requires Celery backend query |
| Admin notification for critical errors (email/webhook on job failure) | `idea` | `low` | Proactive alerting without polling UI |
| Multi-country tax engines (beyond Swiss model) | `deferred` | — | Requires significant billing engine redesign |

---

## Participant Self-Service

| Feature | Status | Priority | Notes / Spec |
|---|---|---|---|
| Participant dashboard (own energy split: local vs. grid, daily timeline, key totals) | `shipped` | — | — |
| Average consumption chart | `shipped` | — | — |
| Own metering point data view and energy charts | `shipped` | — | — |
| Own invoice list and read access (status, amounts, PDF download) | `shipped` | — | — |
| Contract PDF self-download | `shipped` | — | — |
| Profile self-management (name, email) | `shipped` | — | — |
| Password self-service (initial set + change) | `shipped` | — | — |
| Participant audit log view (own actions only) | `deferred` | — | Deferred to v2; requires role-scoped audit queryset extension |
| Participant energy export (own readings as CSV) | `idea` | `medium` | Useful for personal tax filings or energy monitoring |
| Participant invoice dispute / comment channel | `idea` | `low` | Would require a messaging/comment thread model |
| Participant notification preferences (email opt-in/out per event type) | `idea` | `low` | Currently no per-participant notification settings |
| CO₂ savings display in participant dashboard | `idea` | `low` | Show estimated CO₂ avoided from local solar consumption; engagement feature seen in German EaaS platforms |
| Proactive status-check page for ZEV owners | `idea` | `medium` | Single-page diagnostic view showing config completeness, metering data health, tariff coverage, and pending actions with fix hints (PVshare's strongest UX differentiator) |

---

## Platform & Ops

| Feature | Status | Priority | Notes / Spec |
|---|---|---|---|
| Multi-tenant architecture (all data ZEV-scoped, object-level enforcement) | `shipped` | — | [ADR 0003](adr/0003-role-and-zev-scope-enforcement.md) |
| Async job processing with Celery + Redis (email delivery, retries, correlation) | `shipped` | — | [ADR 0004](adr/0004-async-invoice-email-delivery.md) |
| UTC storage and explicit timezone handling | `shipped` | — | [ADR 0007](adr/0007-timezone-policy.md) |
| Docker Compose local development setup (backend, frontend, DB, Redis, Celery) | `shipped` | — | — |
| Helm chart for Kubernetes deployment | `shipped` | — | — |
| Single-container fullstack Dockerfile with nginx | `shipped` | — | — |
| Automated release pipeline with SBOM attachment | `shipped` | — | — |
| 4-locale i18n (English, German, French, Italian) across all frontend text | `shipped` | — | — |
| Frontend management page design system (documented conventions, shared components) | `shipped` | — | [spec](specs/2026-04-frontend-management-page-design.md) |
| Backend test suite (pytest, per-app test modules) | `shipped` | — | — |
| Production database backup / restore guidance | `idea` | `high` | No documented procedure; critical for production deployments |
| Helm chart maturity (resource limits, liveness probes, secrets management) | `idea` | `medium` | Current chart is functional but minimal |
| Observability — structured application logging and metrics endpoint | `idea` | `medium` | No Prometheus metrics or structured log format today |
| End-to-end test suite (Playwright or similar) | `idea` | `medium` | Playwright is used for automated user-guide screenshots; no interactive end-to-end coverage of user flows yet |
| Frontend component-level unit tests | `shipped` | — | `npm run test:unit` (Vitest) covers API helpers, reducers and page-level logic |
| Rate limiting on sensitive API endpoints | `shipped` | — | Auth endpoints throttled per IP; import endpoints throttled 60/h/user; transfer archive endpoints throttled 20/h/user; API key auth counts against budget |
| Automated security dependency scanning (Dependabot / Snyk) | `idea` | `low` | Renovate is configured for updates; no security-focused CVE scanning |
| Multi-region or multi-instance deployment guidance | `deferred` | — | Single-instance model assumed; stateful session and Celery design would need review |
