# Feature Spec: Navigation regroup — task-first IA, canonical routes, scope-aware shell

- Spec ID: SPEC-2026-09-nav-regroup
- Status: In Progress (phases 1–2 shipped; phase 3 deferred)
- Genre: decision spec, not a baseline — current-state navigation behavior
  lives in `2026-03-community-and-access.md` §9; retire once the baselines
  fully cover what is described here
- Scope: Major
- Type: Change
- Owners: frontend, backend
- Created: 2026-09-05
- Related Specs: `2026-03-community-and-access.md` (§9 routing/nav is updated by
  this work), `2026-03-invoice-lifecycle-and-communication.md` (readiness/
  attention endpoints extend the invoice API), `2026-04-frontend-management-page-design.md`,
  `2026-08-ui-redesign-pdf-style.md` (shell tokens)
- Impacted Areas: frontend, backend (invoices), docs

> Self-contained record of the agreed navigation redesign. Supersedes the WIP
> handoff artifacts (tag `ux-audit-handoff-v1`, branch `wip/ui-ux-audit-handoff`
> — archival context only; nothing in this spec requires that branch). The
> visual mockup that accompanied the audit is intentionally not part of this
> record.

## 1. Problem and outcome

The sidebar was organised by role ("Manage (v)ZEV", "Admin Console") instead of
by task; the ZEV context selector was a secondary-looking dropdown in the top
right; the admin console was a second application of nine entries inside the
first. Outcome: a flat, task-first navigation (Dashboard · Metering · Billing ·
Reports · Setup · Feasibility · Platform), canonical routes with aliases for
every legacy URL, an explicit scope-aware shell (selected ZEV visible and
persistent; a readable "Platform administration" indicator under `/admin/*`),
and participant entries in participant vocabulary.

## 2. Scope

The rework ships the flat task-first navigation, canonical routes with
aliases for every legacy URL, the scope-aware shell, `/me/statement` as the
participant statement host, the additive `GET /auth/me` participant-context
fields (`zev_name` with a single membership, `zev_count`) shared with
statement membership resolution, and the admin "Manage" entry into a ZEV's scope.
Route/permission decisions are frozen in §3–§4, the navigation structure in
§5, shell behavior in §6. The readiness/attention contract (§7) is part of
the same rework and is recorded here so the endpoint and its consumers agree.
Likewise §8 records the
Reports CSV-export and Accounts/Templates-consolidation decisions as future
work, not shipped behavior.

## 3. Route decisions

Conventions: **canonical** = the route rendered in nav / linked in UI;
**alias** = legacy URL kept working via in-app redirect (aliases are
client-side redirects; server redirects are out of scope). Hub tab
addressing = sub-routes (not `?tab=`); the `:invoiceId` param name is kept.

### 3.1 Owner/admin routes

| Old | New (canonical) | Decision |
|---|---|---|
| `/` | `/` | keep |
| `/metering-data` | `/metering/chart` | alias → canonical |
| `/metering-data?tab=quality` | `/metering/quality` | alias → canonical (param stripped) |
| `/imports` | `/metering/imports` | alias → canonical (query preserved) |
| `/metering-points` | `/metering-points` | keep |
| `/invoices` | `/billing/invoices` | alias → canonical (query preserved) |
| `/invoices/:invoiceId` | `/billing/invoices/:invoiceId` | alias → canonical (param + query preserved) |
| `/reports` | `/reports` | keep; owner-only in nav (route still allows participants) |
| `/audit-logs` | `/audit-logs` | keep as Setup entry |
| `/participants`, `/tariffs`, `/zev-settings`, `/feasibility`, `/account` | unchanged | keep (Setup group / ungrouped / user menu) |

### 3.2 Participant routes

| Old | New (canonical) | Decision |
|---|---|---|
| `/` (participant branch) | `/` | keep |
| `/reports` (participant mode) | `/me/statement` | moved: canonical host of the self-service statement (ReportsPage participant branch; impersonating admins carry the participant role) |
| — | `/me/invoices` | shipped (phase 2): read-only list reusing the existing role-scoped backend list endpoint; no backend change, no new grant |
| `/metering-data` (own points) | `/metering/chart` | keep reachable; no participant sidebar entry (phase-2 sidebar is Dashboard · My invoices · Annual statement) |

Participant deep links that must not regress: `/metering-points` (read-only,
never gated on `canManage`), `/metering/chart`, `/billing/invoices/:invoiceId`
(own only, backend-enforced).

### 3.3 Admin routes

All `/admin/*` paths unchanged — this is a nav regroup, not a restructure.
`/admin/api-keys`, `/admin/invoices`, `/admin/pdf-templates`,
`/admin/email-templates`, `/admin/audit-logs` keep their pages. Legacy
`/admin/settings/*` redirects into `/admin/system-settings` tabs are unchanged.

## 4. Route → role guard matrix (frozen)

A = admin, O = zev_owner, P = participant. This matrix is cell-for-cell
identical to pre-regroup `allowedRoles` **except the two recorded exceptions**
below. Default-allow routes (no `allowedRoles`) are marked `*` and must stay
default-allow.

| Route (canonical) | A | O | P | Notes |
|---|---|---|---|---|
| `/` | Y | Y | Y | content differs per role |
| `/metering` (index) | Y | Y | Y* | alias → `/metering/chart`; the redirect inherits the target's guard |
| `/metering/chart` | Y* | Y* | Y* | default-allow; P: own points only, read-only |
| `/metering/quality` | Y | Y | N | **recorded exception 1** — was default-allow; quality shows whole-ZEV severity counts, participant names, overlap warnings (operator view; backend role-scoping, so a UX tightening, not a leak fix) |
| `/metering/imports` | Y | Y | N | owner-only tab |
| `/metering-points` | Y* | Y* | Y* | default-allow; P: read-only, no nav entry (deep link); never gate on `canManage` (that is the regression this row exists to prevent) |
| `/billing` (index) | Y | Y | — | alias → `/billing/invoices`; participants hit the invoices guard and land on `/` |
| `/billing/invoices` | Y | Y | N | owner-only tab |
| `/billing/invoices/:invoiceId` | Y* | Y* | Y* | default-allow; P: own invoices only (backend-enforced) |
| `/me/statement` | — | — | Y | **recorded exception 2** — participant-only canonical host of the existing self-service statement view (`allowedRoles=['participant']`; impersonating admins carry the participant role) |
| `/me/invoices` | — | — | Y | participant-only; shipped in phase 2 (read-only list reusing the existing role-scoped backend list endpoint; no new grant) |
| `/reports` | Y | Y | Y | route unchanged; NO participant nav entry (they use `/me/statement`) |
| `/participants`, `/tariffs`, `/zev-settings`, `/feasibility`, `/audit-logs` | Y | Y | N | Setup group / ungrouped |
| `/admin` + all `/admin/*` | Y | N | N | strictly admin |
| `/account` | Y | Y | Y | user menu, no sidebar entry |

Participant no-regression checklist: the P column above is the contract — `/`,
`/metering/chart`, `/metering-points`, `/billing/invoices/:invoiceId` (own),
`/me/invoices`, `/me/statement`, `/account` stay ALLOW.
Participant must-stay-deny (backend data boundaries): `/billing/*` (except own
`:id`), `/metering/quality`, `/metering/imports`, `/setup/*`, `/reports` nav
entry, `/admin/*`. Privacy: the participant benefit split (other households)
must never render in any P-ALLOW view.

Existing permissions are preserved except for the quality-route tightening
and the two new participant-only entry points, `/me/statement` and
`/me/invoices` (both frontend routes over existing role-scoped backend
endpoints); no backend permission changes anywhere in this change.

## 5. Navigation structure

```
Dashboard                          (all roles)
Metering        /metering/chart    (canManage; active on chart + quality)
Billing         /billing/invoices  (canManage; active on /billing/*)
Metering Imports /metering/imports (canManage)
Reports         /reports           (canManage)
My invoices     /me/invoices       (participant; phase 2 — own invoices, read-only)
Annual statement /me/statement     (participant)
SETUP (group)
  Participants, Metering points, Tariffs, ZEV settings, Audit logs   (canManage)
Feasibility                         (canManage, ungrouped)
PLATFORM (group, admin only)
  Overview, ZEVs, Accounts, API Keys, Invoices, System Settings,
  PDF Templates, Email Templates, Audit Logs                        (admin)
```

Phase 2 change: the transitional participant "My consumption" entry
(`/metering/chart`) folded into the participant dashboard — participants reach
it as Dashboard; the deep link still works. Participant nav is now Dashboard
· My invoices · Annual statement.

Tabs are route-driven navigation, not query-string or component-local state:
each hub tab is its own route with its own
guard; the hub renders only the tabs the current role passes. Group labels are
decided per locale: en/de `Setup`, fr `Configuration`, it `Configurazione`;
`Platform` / `Plattform` / `Plateforme` / `Piattaforma` (noun forms, never
imperatives). Ungrouped standalone links get extra top clearance
(`.nav-standalone`) so Feasibility does not read as the Setup group's last
entry; the Setup group itself gets the same clearance above its label
(`.nav-section-start`) so it separates from the ungrouped links above it as
clearly as from what follows it. The divider line stays reserved for the
Platform group break.

## 6. Scope-aware shell

- The ZEV switcher lives at the top of the sidebar for `canManage` roles
  (inline expander; expands-first when collapsed; auto-closes on entry into
  platform scope) **only when there is something to switch** — several managed
  communities, or none (empty state). With exactly one managed community the
  switcher is unmounted (there is nothing to switch and the sidebar has no
  room to spare). Participants get no switcher.
- Every ZEV-scoped page header carries the selected ZEV name as an eyebrow
  above the page title, regardless of how many communities are managed —
  the name is page context, not only switcher context. Participants see the
   same eyebrow when they hold a single membership (`zev_count == 1` on
   `GET /auth/me/`): their community name comes from `zev_name`
   (their membership, not the invoice list — the previously dropped
   invoice-sourced static name depended on billing having run; the membership
   is stable). With several memberships no single name matches the displayed
   scope, so dashboard and metering pages show no eyebrow; the statement page
   keeps the label because both downloads serve that membership.
- Selected ZEV / platform context is **persistent**: a context block
  (brand + switcher or platform chip) outside the scrolling nav — in the
  drawer above it. On short viewports the block may scroll so the open
  switcher stays usable. There is no header scope chip — the page eyebrows
  carry the ZEV name.
- Platform scope (`/admin/*`): the shell adds `shell-scope-platform`; the
  switcher is unmounted in favour of a translated "Platform administration"
  chip (`nav.platformScope`) in the context block. No
  tenant name is displayed on platform pages. Every `/admin/*` page header
  repeats the same platform label as its eyebrow instead of a community
  name or a role name, so all nine platform pages read uniformly.
  Entering a ZEV's scope from platform scope goes through **Manage** on
  `/admin/zevs` (sets `selectedZevId` + jumps to `/`).
- Active nav state is exposed to assistive tech: the active entry carries
  `aria-current` alongside its visual class. An exact match uses
  `aria-current="page"`; a hub entry active on a sub-route (e.g. Metering on
  `/metering/quality`) uses `aria-current="true"` so screen readers do not
  announce the parent as the current document.
- The impersonation banner with "Stop impersonating" survives the redesign.

## 7. Readiness / attention API contract

Recorded here so the endpoint and its consumers agree.

`GET /api/v1/invoices/invoices/readiness/?zev_id=UUID[&period_start&period_end
| &periods=all]` — period readiness for the cockpit and the (phase-3) Periods
tab. Parameterless form resolves the cockpit period server-side — the most
recent ENDED period that still needs the operator — and returns it in
`period`; explicit dates serve single-period views; `periods=all` returns a
ReadinessList (one entry per billing period, newest first) so the Periods tab
needs one call.

"Still needs the operator" is judged against what the period actually
requires, so a period can never be resolved away by its own partial progress:

- the period contains a DRAFT or APPROVED invoice (the workflow is waiting at
  approve or send), **or**
- a **billable participant** — active in the period *and* holding at least one
  meter assignment in it, i.e. exactly the membership the period overview
  lists as a row — has **no invoice at all** for the period. A batch
  generation that only invoiced part of the period therefore keeps the period
  open even after those invoices are sent.

Sent/paid are trailing states, not gates (an old period over one unpaid
invoice must not pin the cockpit); cancelled invoices are withdrawn and count
as work neither here nor in any step. An invoice covers only its exact
`(period_start, period_end)`: after an interval change a sent January
invoice must not count for the Jan–Mar quarter that shares its start date.
One qualification: a period whose every day is already covered by sent/paid
invoices from an earlier interval counts as settled — paid monthly invoices
must not reopen as regeneration work under a later quarterly interval (the
engine refuses to rewrite them). Partial locked coverage is neither settled
nor ordinary generation: a billable participant with no exact-period invoice
whose period overlaps approved/sent/paid invoices (the engine's
`locked_overlapping_invoices` rule — draft/cancelled overlaps stay
replaceable) is a `generation_conflicts` warn step with
`next_action: review_generation_conflicts`, carrying per-participant conflict
identities (participant id/name plus conflicting invoice id/number/status/
start/end, first three shown, accurate total count). Conflicted participants
leave the `generated` missing set — the InvoicesPage row action links to the
locked invoice instead of offering Generate, and batch counts exclude them
(the batch task itself still attempts every active participant and isolates
per-participant failures, so a conflict surfaces as a recorded failure
there). Generation eligibility is authoritative per period-overview row, not
per cockpit list: each row without a live exact-period invoice carries
`generation_eligibility` (`eligible` | `covered` | `blocked` with the first
covering/locking invoice id+number), computed from one bounded overlap
query. The InvoicesPage primary actions, regeneration menu items and batch
counts all read the rows — there is no second readiness request gating the
table, so a slow or failed readiness payload can never re-expose an
unqualified Generate button. The cockpit's `conflicts` list stays a
display-truncated summary (first three, `conflict_count` authoritative). A pending (draft/approved) invoice from an earlier interval is never
lost either — its own period stays a cockpit candidate even when it no
longer aligns with the current interval.
The scan walks the whole bounded history (anchor =
`max(zev.start_date, 2020-01-01)`, no window cap) so older open work is never
hidden behind truncation; aligned period starts are on or after the start
date, so a community created mid-period has no partial first period (the
frontend rejects pre-start periods).

When no period needs work the three states below are distinguished by flags so
the dashboard never conflates them (note: only two of them carry
`period: null` — the caught-up state has a period):

- **setup** — master data (participants + metering points) is empty;
  `period: null` plus a `setup` block (see below);
- **awaiting_first_period** — master data exists but no billing period has
  ended yet (the community was created inside the current period or its
  partial first period was skipped); `period: null`, but the `setup` block
  is still present so assignment/IBAN guidance shows before the first
  period ends;
- **caught_up** — no ended period has open work under the cockpit rule (no
  draft/approved invoice anywhere and every billable participant is
  invoiced); the response carries the most recent ended period with
  `caught_up: true`. Its steps are recomputed readiness and may still show
  trailing items — unpaid invoices, data warnings — which never gate
  resolution.

`setup` = `{ complete, reason, assignment_link, billing_settings_complete,
billing_settings_link, settings_complete, metering_points, participants,
tariffs }` and is readiness-state, not period-state: `complete` is false only
for actionable omissions — empty master data (`reason: no_master_data`) or
active participants with no current-or-future billable assignment (`reason:
no_billable_assignment`, readings-independent so first-run ZEVs are caught;
`assignment_link` is `/metering-points`). A blank IBAN is advisory only:
`billing_settings_complete: false` with `billing_settings_link`
(`/zev-settings`) without failing `complete` or gating generation.
Parameterless responses (cockpit period and caught-up) always carry `setup`,
so the IBAN warning stays visible beside normal period work; explicit-period
responses never do — a historical zero-billable period (before membership,
ended memberships, inactive communities) stays `generated: done` without
setup guidance. Existing invoice workflow remains visible when current
master data is incomplete.

RBAC mirrors `period-overview`: `zev_id` required and a valid UUID (400),
unknown ZEV 404, other owners and participants 403 (`IsZevOwnerOrAdmin`).
Period params must arrive as a pair (400), be strict `YYYY-MM-DD` (400 —
compact forms like `20260801` are rejected even though Python parses them),
`start ≤ end` (400), span at most five years (400), and lie inside the
representable band `1900-01-01..9998-12-31` (400 — the period helpers step
months and add days, so an explicit `9999-…` end must not overflow into a
500). `periods=all` returns the union of current-calendar periods and exact invoice
periods inside the supported history — computed from one shared dataset plus
one distinct-pairs invoice query, so its query count is constant, not per
period — and reports `history_from`, `total_periods` and `truncated` (true
only when the ZEV predates the 2020 floor) instead of silently capping the
list. Entries deduplicate by both dates, sort newest-first by `(end, start)`
(a January monthly row coexists with its Jan–Mar quarter), and each entry
runs the same explicit-period rules (list entry steps/`next_action` equal the
explicit request for that date pair). Entries carry provenance:
`period.source` ∈ calendar | invoice, and `period.interval` keeps the
configured interval only when the entry's exact dates align to the current
calendar — custom ranges are never mislabeled as aligned quarters.
Cancelled-only invoice periods stay discoverable inside the normal history
window. The list and the cockpit share discovery rules; the cockpit keeps
its ended-period selection policy.

`Readiness` = `{ period: Period | null, steps: ReadinessStep[], next_action,
setup, [awaiting_first_period], [caught_up] }` (`setup` rides every
parameterless response; explicit-period ones never carry it); `Period` =
`{ start, end, interval }` (interval ∈ monthly | quarterly | semi_annual |
annual). `ReadinessStep` = `{ key, status, count, [total], [failed],
[detail], [link], [detail_data] }` with `StepKey` ∈ metering | assignments |
tariffs | generated | generation_conflicts | approved | sent | paid and
`StepStatus` ∈ ok | warn | todo | done (never `blocked` from data quality —
gating is soft). Single-period and bulk readiness run one shared
implementation over an explicitly loaded dataset (`BulkData`): single
requests load their bounded period, list requests load the history span
once, both call the same step computations, so list/single parity holds
structurally. Counts are
real: `count` is what the step is about (affected points for metering,
readings for assignments, invoices present/waiting for the workflow steps)
and `total` is the denominator that step is judged against — billable
participants for `generated`, the period's active (non-cancelled) invoices
for approve/send/paid, active points for metering, days in the period for
tariffs. `failed` (sent step) is the number of invoices whose **newest**
email attempt failed — unresolved failures, so a later successful delivery
clears the step and repeated failures collapse to one. Both single-period and
bulk readiness exclude paid/cancelled invoices from failed-delivery counts;
all other invoices in the exact period contribute, including older duplicates.
The `tariffs` step is
priced per energy type, not per validity window: every configured energy
type must have a usable price band each day (a tariff with its bands removed
prices nothing, and one type's pricing never masks another), and a
percentage tariff additionally requires a priced grid rate on the days it
applies. `link` opens the page
where the step's action lives and is present for data steps and steps with
actionable rows (generated/approve/send with work, paid once anything is
sent); a downstream step that is merely waiting on an upstream one (send
while drafts await approval, paid before anything is sent) has no link.
`detail` strings are English API
fallbacks that the UI never renders; `detail_data` carries the structured
fields (`missing_days`/`meters`/`more_meters`, `unassigned_readings`/
`unassigned_days`, `ranges`/`more_ranges`, `missing`/
`missing_participants`/`more_missing`, `unpaid`) the four locales translate
from, plus `conflict_count`/`conflicts`/`more_conflicts` for the conflict
step. `next_action` ∈ fix_metering | fix_assignments | fix_tariffs |
generate | review_generation_conflicts | approve | send | track_payments |
none — the first step that
needs the user in workflow order (data warns before invoice todos);
`next_action` is never `none` while an open step exists.

`GET /api/v1/invoices/invoices/attention/?zev_id=UUID` — ZEV-level
cross-period items only (deliberately NOT period-scoped: unresolved failed
emails from any period, overdue invoices, participant-validity endings) — the
one stable URL the phase-3 nav-badge query will read. Tariff coverage, the
cockpit period's metering/assignment gaps and setup incompleteness are
readiness-step concerns and are deliberately NOT repeated here (they were
attention types until the attention card merged into the cockpit card).
The alert list remains visible during readiness loading/failure and in
setup/awaiting-first-period states. Attention loading/failure is reported
independently of readiness.
`AttentionItem` = `{ id, type, [invoice_id], [participant_id], period:
Period | null, link, [label], [structured fields] }` with `type` ∈
email_failed | invoice_overdue | participant_validity. Every item carries its
own period ref (null for participant-validity items) so links render with
period context. `id` is a type-prefixed composite of record identity —
`email_failed:<invoice id>`, `invoice_overdue:<invoice id>`,
`participant_validity:<participant id>` — so keys are stable under re-sorting
and never collide when the same invoice appears in two items or a delivery
failed repeatedly. Failed-email items aggregate to one per invoice and appear
only while the **newest** attempt failed (a later successful delivery or an
in-flight retry clears them). `link` for invoice-scoped items opens the
invoice's **billing period** page — the retry and mark-paid actions live on
the period rows, not on the read-only detail route (the detail route is the
fallback only when the invoice has no period dates). The UI localizes from
the structured fields (`invoice_number`/`recipient`/`due_date`/
`participant_name`/`valid_to`/`expired`); `label` is an English API fallback,
never rendered. Email items are capped at the 20 newest unresolved; overdue
items are capped at 20, most overdue due date first. On the dashboard the
items render as a cross-period alert list inside the cockpit card, between
the step list and the next-action footer (empty → hidden); there is no
standalone attention card.

Badge rule (phase 3): every badge states its period (default: the cockpit
period, in the tooltip). Nav badges and the Periods-tab dot read the same
`steps[]`/attention payload — this change ships the payloads and the
cockpit/attention UI, and **explicitly defers the sidebar badges** to phase 3.

Invoice list responses carry `last_email_status` (status of the newest
`EmailLog` per invoice) via a subquery annotation on the list queryset — one
SELECT, no per-row N+1, no prefetch. The period overview full-serializes its
rows from one queryset that annotates `last_email_status` and prefetches
`items` and `email_logs`, so a poll stays at a bounded query count however
many rows carry invoices; retrieve/workflow echoes reuse the full serializer
with `items`/`email_logs` prefetched (a single per-object fallback applies
only when no annotation was attached).

## 8. Key decisions (review trail)

1. Group labels: Operations heading dropped — Metering / Billing / Reports
   stand ungrouped; Setup group uses the noun form per locale.
2. Reports analytical views are future work: the closed owner list
   (self-consumption over time, energy balance, participant benefit split)
   and a CSV export action per view are recorded for a later phase.
   Shipped: PDF downloads only (annual statement, ZIP, financial summary).
3. Deferred scope: the setup-completeness checklist (`setup.settings_complete`
   is hardcoded `true` — a settings-completeness metric is phase-3 scope) and
   the sidebar nav badges. The badges are described here so the payload they
   will read is stable: the readiness `steps[]` and the attention endpoint
   ship in this change, the badge UI itself does not.
4. The readiness/attention contract (§7) was agreed up front so the endpoint
   and its consumers don't drift.
5. `/me/statement` is the canonical participant host of the existing
   self-service view (not an alias of a Billing tab); participant nav never
   says "Billing" — operator vocabulary is never reused for participants.
6. Absorbing participant-mode Reports content (own consumption, own ZEV
   share, own cost-vs-grid) into the participant dashboard is future work;
   the participant benefit split (other households) is excluded by design.
   Shipped: the participant consumption view on the dashboard; statement
   and summary downloads in Reports.
7. Assignment gaps (a meter with no valid participant for part of the period)
   are the ZEV-specific cockpit failure mode; overlapping assignments need no
   check (model rejects them on save).
8. Audit-log nesting constraints (done): the `zev` param is locked to the
   selected ZEV for multi-ZEV owners — the owner view has no independent
   community selector, switching resets page/drawer, and no request fires
   without a valid selection; admin-only text search kept; platform/owner
   scopes never merged.
9. Admin "Accounts & Participants" renamed to "Accounts" (participants are
   per-ZEV; the admin page is users/roles/impersonation) — done. Folding API
   keys into Accounts and the single Templates list are future work.
10. Leftover role-era wording `nav.manageZev` ("Manage (v)ZEV") survives as the
    switcher section title; renaming it is deferred to the participant identity
    work.

## 9. Test plan

- `frontend/tests/layout-nav.test.ts` — flat-nav visibility per role,
  collapsed switcher naming, impersonation banner, `aria-current` alignment
  (incl. `/metering/quality`), the sidebar scope chip (platform vs ZEV) and
  page eyebrows (no header chip — it was removed with the scope-aware shell);
  menus expose `aria-expanded`/`aria-controls` and close on Escape.
- `frontend/tests/route-guard-matrix.test.ts` — §4 matrix against `AppRoutes`
  for all three roles (DENY lands on `/`).
- `frontend/tests/route-aliases.test.ts` — alias redirects preserve query and
  params; the alias-pinned param (e.g. the settings `tab`) survives an
  incoming query trying to hijack it; `?tab=quality` maps to the guarded
  route; `tab` is always stripped.
- `frontend/tests/nav-guards.test.ts` — `ProtectedRoute` in isolation.
- `frontend/tests/zev-manage-action.test.ts` — Manage on `/admin/zevs` selects
  the ZEV and navigates.
- `frontend/tests/invoice-detail-back-link.test.ts` — the detail return link
  follows its origin: dashboard/open-invoice links return to `/`, links from
  My invoices return to `/me/invoices`, and a participant with no recorded
  origin falls back to `/me/invoices`; owners keep the invoices return,
  now with the period they came from.
  (`?period_start&?period_end` preserved via link state).
- `frontend/tests/metering-tab-state.test.ts` — chart/quality tab state on the
  shared `MeteringChartPage` instance; Data Quality meter links route to
  `/metering/chart` with the selected meter and legacy `from`/`to` period
  query state preserved, while selector changes write canonical
  `period_start`/`period_end` keys.
- `frontend/tests/dead-i18n-keys.test.ts` + `locale-parity.test.ts` — nav.*
  keys live and translated in all four locales.
- `frontend/tests/audit-log-scope.test.ts` — owner audit-logs request scope
  follows the global selection (switch rescopes + resets page/drawer,
  clear-filters keeps the scope, no request without a selection); admin
  scope keeps its own community selector.
- `frontend/screenshots/layout-overflow.spec.ts` — with ten communities and
  the switcher open, the sidebar navigation keeps a usable height, the footer
  stays reachable, and the list stays usable enough to scroll and select a
  community (desktop 1440×600, landscape 1280×400 and 740×390, mobile drawer
  390×600; probe communities are created inside cleanup protection and
  deleted afterwards). Needs the seeded stack.

Phase 2 additions:

- `backend/invoices/test_readiness.py` — deterministic (clock pinned via a
  threaded `today` through the pure helpers): cockpit-period resolution
  (draft/approved gate, partial-batch-generation gate, sent/paid/cancelled
  trailing, empty ZEV → null), interval-switch leftovers (a newer leftover
  draft outranks an older ungenerated aligned period, an unended period under
  the new interval falls back to ended leftovers, and the parameterless
  endpoint resolves them with the real default clock — regression for the
  `today=None` TypeError), step statuses per data condition, unresolved-
  email-failure handling (retry-to-success clears), attention ids and item
  emission (invoice items pick the newest attempt in SQL, never N+1 ZEV
  fetches; participant-validity warnings use one Exists annotation),
  participant-validity warnings incl. finite assignments, endpoint
  RBAC/param validation (bad UUID 400, out-of-band dates 400), the three
  readiness forms plus `periods=all` metadata (bulk/single parity counts
  readings, not days — several readings on one orphan day count as several —
  and the query budget is constant), settled interval transitions (fully
  paid months do not reopen as regeneration work; a partial settle stays
  open; paid subperiods never swallow a leftover draft), percentage-tariff
  coverage (an expired percentage leaves its type uncovered; a valid one
  prices it through the grid — single and bulk agree), duplicate
  invoice selection (single and bulk pick the same newest invoice), and
  month/interval edge cases (February, 30-day months, year rollover, all
  four billing intervals). Single and bulk share one implementation over an
  explicitly loaded dataset, so parity holds structurally. Generation
  conflicts (`GenerationConflictTests`: partial paid/sent/approved overlap is
  `review_generation_conflicts` with conflicted participants out of the
  `generated` missing set; draft/cancelled overlap keeps ordinary
  generation; mixed participants preserve valid work; the engine refusal is
  pinned and leaves the locked invoice untouched). Historical periods
  (`HistoricalPeriodListTests`: monthly rows survive a quarterly switch with
  `source: invoice`, same-start periods coexist, newest-first `(end, start)`
  ordering, list/explicit steps parity, stable list query count as history
  grows). Setup guidance (`InitialSetupGuidanceTests`: unassigned setup is
  not caught_up with an assignment destination; blank IBAN stays
  discoverable beside normal work; completed setup clears; historical
  zero-billable explicit periods carry no setup block; conflict identities
  are ZEV-scoped). Partial settled coverage is a conflict now, not ordinary
  generation (`test_partially_settled_period_is_a_conflict`); the caught-up
  response carries a completed `setup` block, and the awaiting-first-period
  response keeps incomplete setup visible
  (`test_waiting_first_period_keeps_incomplete_setup`).
- `backend/invoices/test_period_overview.py` — a participant whose
  assignment ended keeps a row while they hold an invoice for the period;
  with neither assignment nor invoice they drop out; rows serialize with
  bounded queries (prefetch + annotation).
- `backend/zev/tests.py` — legacy demo duplicates that carry invoices are
  cleared (invoice-first delete around the PROTECT) instead of raising
  `ProtectedError`.
- `frontend/tests/readiness-cockpit.test.ts` — cockpit stepper (period label,
eight steps, open-step links only on warn/todo, first-run checklist,
failure state), generation-conflict rendering with its destination link,
setup/billing-settings guidance beside period work, cockpit cross-period alerts (empty → hidden; localized
rendering from structured fields, English fallback never shown),
  MyInvoicesPage (own
  invoice rows incl. rows without PDFs — PDF button conditional, unscoped
  fetch, empty state only when the backend returns none; multi-membership participants
  see the issuing community per row).
- `frontend/tests/community-eyebrow.test.ts` — the statement page keeps the
  membership label with several memberships (recorded §6 exception); My
  invoices shows the community eyebrow with a single membership. Awaiting-first-
  period / caught-up rendering and the clickable next-action destination
  are covered at the model level (backend) and stay on the seeded-browser
  checklist.
- `frontend/tests/participant-form-modal-focus.test.ts` — the modal half of
  the participant deep-link contract: `?focus=<id>&field=valid_to` focuses
  the validity field once the modal opens; plain edits never steal focus.
  Consuming the URL, filter-clear and scroll on ParticipantsPage itself is
  exercised on the seeded-browser checklist.
- `backend/invoices/test_serializers.py` —
  `test_list_does_not_query_the_tables_it_no_longer_serializes` updated:
  `last_email_status` must arrive via the subquery annotation inside the one
  list SELECT, never as standalone email-log queries (no per-row N+1).
  Newest-tie order is explicit everywhere (`-created_at`, `-id`): the list
  and period-overview subqueries, the overview invoice pick, and the
  serializer fallback agree with readiness/attention.
- `backend/invoices/test_readiness.py` — cancelled-only periods stay open
  (single and bulk `generated` steps report todo; cockpit resolution skips
  cancelled invoices), overdue attention capped at 20 most-overdue-first,
  attention endpoint rejects participants (403), cockpit exact-month pinned.
- `frontend/tests/billing-period-alignment.test.ts` — the range helpers
  behind the destination contracts: `billingPeriodFromRange` (aligned,
  floor-checked links), `billingRangeFromParams` (custom metering ranges,
  kept verbatim — the URL is authoritative and only malformed input falls
  back), `invoiceRangeFromParams` (the invoices-page bound: historical
  periods from an earlier billing interval stay reachable once they start
  after the community, pre-start ranges fall back), `recentBillingPeriods`
  (whole-period presets never offer periods before the community's first
  one) and `firstAlignedBillingPeriod` (the floor that stops the
  previous-period button) — with calendar-valid range checks (leap years)
  and rejected malformed / reversed / impossible dates (2026-02-30);
  `firstAlignedBillingPeriod` additionally pins semi-annual/annual boundaries.
- `frontend/tests/participant-form-modal-focus.test.ts` — the participant
  deep-link focus contract: `?focus=<id>&field=valid_to` opens the edit
  modal with the validity field focused; plain edits never steal focus.
- `frontend/tests/route-guard-matrix.test.ts` — `/me/invoices` row (participant
  only).
- `frontend/tests/layout-nav.test.ts` — participant nav is Dashboard · My
  invoices · Annual statement; no `nav.myConsumption` entry.

## 10. Acceptance criteria

1. Every legacy URL in §3 still works via alias; canonical routes render in
   nav and links.
2. The §4 matrix holds cell-for-cell for all roles (exceptions recorded there
   only).
3. Selected-ZEV/platform context is visible without scrolling, collapsing, or
   opening the mobile drawer at normal viewport heights (context block; page
   eyebrows name the selected ZEV); on short viewports see item 7.
4. Platform scope shows a readable translated indicator, never a tenant name.
5. Active navigation state is exposed via `aria-current` and matches the
   visual state on every route, including hub sub-routes.
6. No hardcoded user-facing strings; all four locales carry every nav key.
7. An open community list never collapses the sidebar navigation to zero at
   short viewports — the switcher keeps reserved space and the containing
   area scrolls, so nav, footer, and every community stay reachable
   (`layout-overflow.spec.ts`).
8. All frontend unit tests, `npm run build`, and lint pass.
