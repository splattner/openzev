# Feature Spec: Frontend management page design and interaction patterns

- Spec ID: SPEC-2026-frontend-management-design
- Status: Approved
- Scope: Major
- Type: Change
- Owners: Core maintainers
- Created: 2026-04-05
- Target Release: Ongoing baseline
- Related Issues: n/a
- Related ADRs: n/a
- Impacted Areas: frontend, docs

---

## 1. Problem and outcome

The OpenZEV frontend had started to drift across management pages: similar CRUD
surfaces used different action hierarchies, some pages overloaded dense tables,
icon usage was inconsistent, and translated labels sometimes encoded visual
symbols such as leading `+` characters.

Recent cleanup work on invoices, participants, metering points, imports, and
tariffs converged on a clearer design direction. That direction should be
documented so future page work does not regress into one-off layouts.

**Outcome:** management pages use a consistent information hierarchy, action
model, icon treatment, confirmation flow, and responsive layout, while still
allowing page-specific structure such as tables, card lists, category sections,
or period selectors where the data shape requires it.

This spec is the reference spec for future CRUD and management-page cleanup work
in the frontend.

## 2. Scope

### In scope

| Area | Details |
|---|---|
| Page shell | Page header, summary toolbar, filters, card/table containers |
| Action hierarchy | Primary, secondary, overflow, destructive, modal footer actions |
| Icon treatment | Font Awesome icon + label buttons, fixed-width icon alignment |
| Page grouping patterns | When to use sections, nested cards, tables, DataGrid, or tabs |
| Shared primitives | `ActionMenu`, `ConfirmDialog`, `FormModal`, `BillingPeriodSelector` |
| I18n constraints | User-facing text in locale files only; translated labels must not encode visual symbols |
| Responsive behaviour | Management pages must remain usable on mobile and reduced-width layouts |
| Reference pages | `ParticipantsPage`, `MeteringPointsPage`, `InvoicesPage`, `ImportsPage`, `TariffsPage` |

### Out of scope

- Marketing or public-auth screens (`LoginPage`, verification, OAuth callback)
- Admin settings/editor screens that are document-like rather than CRUD management lists
- Backend API, serializer, permission, or data model changes
- A separate component library extraction or token system split from `index.css`

## 3. Actors, permissions, and ZEV scope

This spec does not introduce new roles. It standardizes the design of pages that
already rely on role-aware access and ZEV scoping.

| Actor | Capability |
|---|---|
| `admin` | Can access all management pages and uses the global ZEV selector when applicable |
| `zev_owner` | Can access owner-facing management pages scoped to owned ZEVs |
| `participant` | May see read-only or limited management surfaces such as metering data; CRUD-heavy pages remain hidden by route protection |

**Route guards currently covered by this spec:**

| Route | File | ProtectedRoute |
|---|---|---|
| `/participants` | `frontend/src/pages/ParticipantsPage.tsx` | `allowedRoles={['admin', 'zev_owner']}` |
| `/metering-points` | `frontend/src/pages/MeteringPointsPage.tsx` | authenticated route; page logic further limits available actions |
| `/tariffs` | `frontend/src/pages/TariffsPage.tsx` | `allowedRoles={['admin', 'zev_owner']}` |
| `/invoices` | `frontend/src/pages/InvoicesPage.tsx` | `allowedRoles={['admin', 'zev_owner']}` |
| `/imports` | `frontend/src/pages/ImportsPage.tsx` | `allowedRoles={['admin', 'zev_owner']}` |

**ZEV scoping rule:** when a page works on tenant-owned data, it must render
from already-scoped data in query results and additionally narrow to
`selectedZevId` where required. Frontend scoping is a UX guardrail and does not
replace backend permission enforcement.

## 4. Frontend design primitives

There is no backend data-model change for this spec. The design surface is
defined by shared frontend primitives and CSS contracts.

### 4.1 Shared components

| File | Export | Contract |
|---|---|---|
| `frontend/src/components/ActionMenu.tsx` | `ActionMenu` | Overflow action trigger for lower-priority row/card actions. Uses labelled menu items, optional icons, section headers, and danger styling. Default button class: `button button-secondary button-compact`. |
| `frontend/src/components/ConfirmDialog.tsx` | `useConfirmDialog`, `ConfirmDialog` | Required wrapper for destructive or high-impact actions. Supports `title`, `message`, `confirmText`, `cancelText`, `isDangerous`, and async confirm handlers. |
| `frontend/src/components/FormModal.tsx` | `FormModal` | Generic modal shell for CRUD forms and small workflow dialogs. |
| `frontend/src/components/BillingPeriodSelector.tsx` | `BillingPeriodSelector` | Specialized period-navigation control for invoice workflows; uses the same button language as management-page actions. |

### 4.2 CSS contracts

**File:** `frontend/src/index.css`

The following utility and shared classes define the current management-page
language and should be reused instead of ad hoc page-local CSS when possible:

| Class / group | Purpose |
|---|---|
| `.page-stack` | Vertical page layout spacing |
| `.card`, `.table-card`, `.stat-card` | Primary container surfaces |
| `.button`, `.button-secondary`, `.button-danger`, `.button-compact` | Shared button system |
| `.badge`, `.badge-neutral`, `.badge-info`, `.badge-success`, `.badge-danger`, `.badge-warning` | Small semantic status/category labels |
| `.actions-row`, `.actions-row-wrap`, `.actions-row-end` | Inline action layouts |
| `.participant-*`, `.metering-*`, `.tariff-*`, `.invoice-*` | Page-family-specific structural patterns that are already in active use |

### 4.3 Icon contract

- Use `FontAwesomeIcon` from `@fortawesome/react-fontawesome`.
- Action buttons that are visible in the main UI should use **icon + text**, not icon-only buttons.
- Use `fixedWidth` on action icons to align labels vertically.
- Do not embed symbols such as `+` in translated button labels when the button already renders an icon.
- Destructive actions use the trash icon; edit uses pen; create/add uses plus; import/export use upload/download; cancel/close uses x-mark; approval/save uses check when a stronger visual cue is useful.

## 5. API contracts

No backend API contract is introduced or modified by this spec.

This spec standardizes the presentation of existing TanStack Query-backed pages.
Each page continues to use its existing query keys and mutation functions.

## 6. Async and integration behavior

No Celery, integration, or backend workflow changes are introduced here.

Frontend interaction rules relevant to async work:

- A mutation must invalidate the page’s canonical query key(s) after success.
- Destructive or long-running flows should display a confirmation or modal before execution.
- Buttons must reflect pending state through disabled state and, when already implemented by the page, pending labels.

## 7. Frontend

### 7.1 Management page shell

Management pages should follow this high-level order:

1. Page header with title and one-sentence description.
2. Summary/action toolbar for counts, current context, and top-level create/import/export actions.
3. Filters when the page supports narrowing or searching records.
4. Main content using either a structured table/DataGrid or a card list, depending on record complexity.
5. Modals and confirm dialogs rendered at the end of the component tree.

### 7.2 Information architecture rules

#### A. When to use tables or DataGrid

Use a table/DataGrid when records are flat and users scan across repeated dense
columns.

Current examples:

- `frontend/src/pages/ImportsPage.tsx`
- `frontend/src/pages/InvoicesPage.tsx` (table remains, but cell density and action hierarchy are improved)

#### B. When to use card lists

Use cards when each record has multiple semantic sections, nested child records,
or badges and action groupings that do not fit well in fixed columns.

Current examples:

- `frontend/src/pages/ParticipantsPage.tsx`
- `frontend/src/pages/MeteringPointsPage.tsx`
- `frontend/src/pages/TariffsPage.tsx`

#### C. Sections versus tabs

Default rule:

- Use **sections** when categories are stable, low in count, and users benefit
  from scanning all groups on one page.
- Use **tabs** only when content is mutually exclusive, document-like, or too
  large to display simultaneously without harming comprehension.

Current application:

- `TariffsPage` uses category sections for `energy`, `grid_fees`, `levies`, and `metering`.
- `AdminEmailTemplatesPage` is a valid tab example because each tab is a separate template editor document.

### 7.3 Action hierarchy

Each record or page should expose actions in priority order:

| Level | Placement | Typical usage |
|---|---|---|
| Primary | Visible button in toolbar or card header | Create, assign, generate, open high-frequency workflow |
| Secondary | Visible compact button near primary | Edit, export, open chart, open protocol |
| Overflow | `ActionMenu` | Lower-frequency or contextual actions |
| Destructive | Visible only if high-frequency and obvious, otherwise overflow + confirm | Delete, clear data, remove assignment |

Rules:

- Avoid rendering many equal-weight buttons in every row.
- Destructive actions must use `ConfirmDialog`.
- If a record only has one frequent action and one destructive action, both may remain visible as compact buttons.
- If a page accumulates more than two non-destructive row actions, move lower-priority actions into `ActionMenu`.

### 7.4 Tariff page rules

**File:** `frontend/src/pages/TariffsPage.tsx`

- Route: `/tariffs`
- Query keys: `['tariffs']`, `['tariff-periods']`
- Structure:
  - summary toolbar at top
  - category sections in the order `energy`, `grid_fees`, `levies`, `metering`
  - tariff cards inside each category section
  - nested tariff-period list inside each tariff card
- The tariff card heading must place **billing mode** and **energy type** badges directly after the tariff name.
- Tariff periods remain nested under the parent tariff rather than in a separate global table.
- Tariff periods are shown only as an active workflow for energy tariffs. Fixed-fee tariffs show a hint instead of a period list CTA.

### 7.5 Shared page references

These pages define the current management-page reference set.

#### `ParticipantsPage`

- File: `frontend/src/pages/ParticipantsPage.tsx`
- Route: `/participants`
- Query keys: `['participants']`, `['zevs']`
- Pattern: summary toolbar, filters, participant cards, primary/secondary/overflow actions, badges, invitation handling.

#### `MeteringPointsPage`

- File: `frontend/src/pages/MeteringPointsPage.tsx`
- Route: `/metering-points`
- Query keys: `['participants']`, `['metering-points']`, `['metering-point-assignments']`
- Pattern: summary toolbar, filters, metering-point cards, nested assignment rows, direct and overflow actions, confirm flows.

#### `InvoicesPage`

- File: `frontend/src/pages/InvoicesPage.tsx`
- Route: `/invoices`
- Query key: `['invoice-period-overview', selectedZevId, period.period_start, period.period_end]`
- Pattern: period navigation via `BillingPeriodSelector`, batch toolbar, compact structured table rows, primary/secondary/overflow actions.

#### `ImportsPage`

- File: `frontend/src/pages/ImportsPage.tsx`
- Route: `/imports`
- Query keys: `['imports']`, `['zevs']`
- Pattern: top-level action card, DataGrid for import logs, per-row protocol/delete actions, destructive bulk-delete modal, import wizard modal.

### 7.6 I18n rules

- All visible user-facing copy in management pages must come from `react-i18next` locale files in `frontend/src/i18n/locales`.
- Strings must not include presentational prefixes or suffixes that belong to icons or layout.
- New sections, badges, empty states, and filter labels must be translated in all active locales: `en`, `de`, `fr`, `it`.

### 7.7 Responsive rules

- Summary stats must wrap rather than overflow.
- Card headers and row action groups must wrap on narrow screens.
- Multi-column detail grids must collapse cleanly to a single column where necessary.
- Buttons remain labelled on mobile; do not collapse primary CRUD flows to icon-only actions.

## 8. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| New pages revert to dense equal-weight row buttons | Medium | Reuse `ActionMenu`, compact buttons, and this spec’s action hierarchy |
| Tabs are overused for simple category groupings | Medium | Default to sections unless categories are truly mutually exclusive working contexts |
| Locale files encode icons or punctuation | Low | Keep strings semantic only; render visuals in components |
| Shared styling drifts into page-local one-offs | Medium | Extend `index.css` page-family blocks before inventing new local structures |
| Destructive actions ship without confirmation | High | Require `useConfirmDialog` + `ConfirmDialog` for delete/remove/clear workflows |

## 9. Test plan

### Frontend

- Build and type checks: `npm run build`
- Lint: `npm run lint`
- Manual verification on the reference pages:
  - page header and description are present
  - top-level create/import/export actions use icon + label buttons
  - destructive actions require confirmation
  - translated labels do not render duplicated `+` signs or icon text artifacts
  - mobile-width layouts wrap action groups and summary stats without overflow

### Acceptance criteria

- [ ] Management pages use a documented default shell: header, summary/actions, filters when needed, main content, modals.
- [ ] Visible CRUD actions use icon + text buttons with consistent semantics.
- [ ] The tariff page uses category sections instead of tabs for the four tariff categories.
- [ ] Billing mode and energy type badges render directly after the tariff name on tariff cards.
- [ ] New page work can reference this spec to choose between sections, tabs, tables, and cards without inventing a new pattern.