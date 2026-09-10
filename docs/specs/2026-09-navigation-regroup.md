# Feature Spec: Navigation regroup — task-first IA, canonical routes, scope-aware shell

- Spec ID: SPEC-2026-09-nav-regroup
- Status: Accepted
- Genre: decision spec, not a baseline — current-state navigation behavior
  lives in `2026-03-community-and-access.md` §9; retire once the baselines
  fully cover what is described here
- Scope: Major
- Type: Change
- Owners: spalinger
- Created: 2026-09-05
- Related Specs: `2026-03-community-and-access.md` (§9 routing/nav is updated by
  this work), `2026-04-frontend-management-page-design.md`,
  `2026-08-ui-redesign-pdf-style.md` (shell tokens)
- Impacted Areas: frontend, docs

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
§5, shell behavior in §6. The readiness/attention contract (§7) is recorded
here so a future endpoint and its consumers agree — the contract is agreed,
the implementation is future work, not this phase. Likewise §8 records the
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
| — | `/me/invoices` | agreed: read-only list reusing the existing role-scoped backend list endpoint; no backend change, no new grant |
| `/metering-data` (own points) | `/metering/chart` | keep reachable, no nav entry for participants beyond "My consumption" |

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
| `/me/invoices` | — | — | Y | agreed target state (read-only list reusing the existing role-scoped backend list endpoint); not routable in this change |
| `/reports` | Y | Y | Y | route unchanged; NO participant nav entry (they use `/me/statement`) |
| `/participants`, `/tariffs`, `/zev-settings`, `/feasibility`, `/audit-logs` | Y | Y | N | Setup group / ungrouped |
| `/admin` + all `/admin/*` | Y | N | N | strictly admin |
| `/account` | Y | Y | Y | user menu, no sidebar entry |

Participant no-regression checklist: the P column above is the contract — `/`,
`/metering/chart`, `/metering-points`, `/billing/invoices/:invoiceId` (own),
`/me/statement`, `/account` stay ALLOW.
Participant must-stay-deny (backend data boundaries): `/billing/*` (except own
`:id`), `/metering/quality`, `/metering/imports`, `/setup/*`, `/reports` nav
entry, `/admin/*`. Privacy: the participant benefit split (other households)
must never render in any P-ALLOW view.

Existing permissions are preserved except for the quality-route tightening
and the new participant-only `/me/statement` entry point; no backend
permission changes anywhere in this change.

## 5. Navigation structure

```
Dashboard                          (all roles)
Metering        /metering/chart    (canManage; active on chart + quality)
Billing         /billing/invoices  (canManage; active on /billing/*)
Metering Imports /metering/imports (canManage)
Reports         /reports           (canManage)
My consumption  /metering/chart    (participant)
Annual statement /me/statement     (participant)
SETUP (group)
  Participants, Metering points, Tariffs, ZEV settings, Audit logs   (canManage)
Feasibility                         (canManage, ungrouped)
PLATFORM (group, admin only)
  Overview, ZEVs, Accounts, API Keys, Invoices, System Settings,
  PDF Templates, Email Templates, Audit Logs                        (admin)
```

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

`GET /api/v1/readiness?zev_id=UUID[&period_start&period_end | &periods=all]` —
period readiness for the cockpit, badges and Periods-tab dots. Parameterless
form resolves the cockpit period server-side (most recent ENDED period not
fully SENT) and returns it in `period`; explicit dates serve single-period
views; `periods=all` returns a ReadinessList (one entry per billing period,
newest first) so the Periods tab needs one call. First-run: `period:null` plus
a `setup` block (`settings_complete`, `metering_points`, `participants`,
`tariffs` counts) when master data is empty — the dashboard picks cockpit vs.
setup checklist from this alone.

`Readiness` = `{ period: Period | null, steps: ReadinessStep[], next_action,
[setup] }`; `Period` = `{ start, end, interval }` (interval ∈ monthly |
quarterly | semi_annual | annual); `ReadinessStep` = `{ key, status, count,
[total], [failed], [detail], [link] }` with `StepKey` ∈ metering | assignments |
tariffs | generated | approved | sent | paid and `StepStatus` ∈ ok | warn |
todo | done (never `blocked` from data quality — gating is soft). `detail`
strings are reused verbatim in the Generate confirm dialog.

`GET /api/v1/attention?zev_id=UUID` — ZEV-level cross-period items
(deliberately NOT period-scoped: missing next-quarter tariff, overdue from
older periods, failed emails, validity warnings, setup incompleteness), one
stable URL for the nav badge query. `AttentionItem` = `{ type, [invoice_id],
[participant_id], period: Period | null, link, [label] }` with `type` ∈
metering_gaps | assignment_gaps | tariff_missing | email_failed |
invoice_overdue | participant_validity | setup_incomplete. Every item carries
its own period ref so links render with period context.

Badge rule: every badge states its period (default: the cockpit period, in the
tooltip). Nav badges and the Periods-tab dot read the same `steps[]`.

## 8. Key decisions (review trail)

1. Group labels: Operations heading dropped — Metering / Billing / Reports
   stand ungrouped; Setup group uses the noun form per locale.
2. Reports analytical views are future work: the closed owner list
   (self-consumption over time, energy balance, participant benefit split)
   and a CSV export action per view are recorded for a later phase.
   Shipped: PDF downloads only (annual statement, ZIP, financial summary).
3. Deferred scope: the setup-completeness checklist; the cross-period email
   aggregate waits on `last_email_status`.
4. The readiness/attention contract (§7) was agreed up front so a future
   endpoint and its consumers don't drift; the endpoint itself is future work.
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
   page eyebrows (no header chip — it was removed with the scope-aware shell).
- `frontend/tests/route-guard-matrix.test.ts` — §4 matrix against `AppRoutes`
  for all three roles (DENY lands on `/`).
- `frontend/tests/route-aliases.test.ts` — alias redirects preserve query and
  params; the alias-pinned param (e.g. the settings `tab`) survives an
  incoming query trying to hijack it; `?tab=quality` maps to the guarded
  route; `tab` is always stripped.
- `frontend/tests/nav-guards.test.ts` — `ProtectedRoute` in isolation.
- `frontend/tests/zev-manage-action.test.ts` — Manage on `/admin/zevs` selects
  the ZEV and navigates.
- `frontend/tests/invoice-detail-back-link.test.ts` — participant return goes
  to the dashboard, owner keeps the invoices return.
- `frontend/tests/metering-tab-state.test.ts` — chart/quality tab state on the
  shared `MeteringChartPage` instance; Data Quality meter links route to
  `/metering/chart` with the selected meter and period query state preserved.
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
