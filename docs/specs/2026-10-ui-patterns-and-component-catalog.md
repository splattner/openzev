# Reference Spec: UI patterns and component catalog

- Spec ID: SPEC-2026-10-ui-patterns
- Status: Draft
- Scope: Major
- Type: Change
- Owners: Core maintainers
- Created: 2026-10-15
- Updated: 2026-10-17
- Target Release: Ongoing reference; tariff pilot first, then the phases in §11
- Related Issues: n/a
- Related ADRs: [0040](../adr/0040-overlay-and-disclosure-pattern-rules.md), [0032](../adr/0032-one-visual-language-for-screen-and-documents.md)
- Related specs: [tariff split view (pilot)](2026-10-tariff-split-view.md), [audience-specific invoice labels](2026-10-audience-specific-invoice-labels.md)
- Impacted Areas: frontend, docs

---

This document defines target guidance. Phase 1 (the tariff pilot) is
implemented (see [tariff split view](2026-10-tariff-split-view.md) §11 for the
values it recorded). Phase 2 (the shared `FormModal` `size` and dirty guard,
`Disclosure`, `AppTabs`) is implemented and described in
[SPEC-2026-04](2026-04-frontend-management-page-design.md); the `DetailPane`
extraction waits for its second consumer (phase 3). Until a later rollout phase
(§11) lands, the baseline specs and the user guide stay authoritative for the
screens that phase covers.

## 1. Problem and outcome

The primary audience is an occasional, non-technical community manager. The
goal is a UI that is **consistent, intuitive, clean and free of unnecessary
information**: understandable tasks, a useful overview, and reliable return
navigation. Consistency is a goal in itself. Someone who has learned how
opening and editing a record works on one list should find it works the same
on every list, and a contributor adding a page should have one default to
follow instead of re-deciding.

`2026-08-ui-redesign-pdf-style` §15 defines how the app *looks*;
`2026-04-frontend-management-page-design` defines the shared primitives and a
CRUD page's structure. Neither says which container to use for a given job, and
the code shows it.

### Current observations (2026-10-17)

| Observation | Evidence |
|---|---|
| Detail views cover the list they belong to | `TariffDetailDrawer` (`clamp(720px, 60vw, 1080px)`) and `AuditEventDrawer` (`min(100vw, 560px)`) are overlays on top of their list. The list stays clickable but no space is reserved for it. |
| Three drawers, three behaviours | The tariff and audit drawers share copy-pasted non-modal overrides (`trapFocus={false}`, `lockScroll={false}`, a hand-written shadow, a manual Escape handler). `MeteringGapsDrawer` uses Mantine's modal defaults. Headings, widths and header markup differ. |
| View and edit live in different places | A tariff is viewed in the drawer and edited in `TariffFormModal` / `TariffVersionModal` / `TariffPeriodFormModal`, which open on top of it. |
| Dialog widths have no scale | `FormModal` is used in 38 files. 24 call sites set `maxWidth` to one of twelve values (480 ×2, 520, 560 ×2, 600, 620, 640 ×7, 720, 760 ×2, 900, 960 ×3, 1000 ×2, 1080px); the rest take the 600px default. |
| Unsaved input is rarely guarded | Only `ZevSettingsPage` guards it (`useBlocker`, `zevUnsavedGuard`). Tariff and other dialogs close without asking. |
| Wizards sit in dialogs | `ZevListPage` creation (4 steps plus a done screen, 960px) and `ImportWizardModal` (1080px). |
| Three disclosure mechanisms | Native `<details>` (`BillingPeriodCard`, `BillingPeriodsPage`), hand-rolled `aria-expanded` buttons (`ZevEmailTemplateFields`, `RawMeteringTable`, `MeteringGapsDrawer`, `MeteringPointRow`, `TariffCategorySections`). |
| Information without a use | Counts and decoration that explain nothing (tariff, fee and version totals; a coloured "In Bearbeitung" on the overview). The participants "Kein Messpunkt" fix link is the model to follow. |
| Repeated library configuration | `Tabs` with the same `app-tabs` class mapping is configured in nine files; `Drawer` three times. |
| Existing responsive tables are reusable | Participants and invoices share `.table-card.invoice-rows`, whose rules are container queries (`@container (max-width: 46rem)` and `28rem`, `frontend/src/styles/pages/invoice-rows.css`). A list narrowed by a pane can reuse them. |

These are inputs to the rules below. A difference is a defect when it makes a
task harder to understand or to repeat; the rollout (§11) removes them in a
planned order.

## 2. Scope

### In scope

| Area | Details |
|---|---|
| Container choice | Dialog, detail pane, page, disclosure, confirmation: defaults, exceptions, limits on stacking (§5, §6) |
| Shared components | What exists, what to reuse, what to extract once it has consumers (§4, §7) |
| Standards | Forms, actions, feedback, labels and counts (§8–§10) |
| Rollout | Committed phases with exit criteria (§11) |
| Checks | Review checklist, tests, TypeScript and lint rules (§12) |

### Out of scope

- Visual styling: palette, type, badge shapes, shadows, brand tokens (SPEC-2026-08 §15 stays authoritative).
- The tariff screen's own behaviour: [tariff split view](2026-10-tariff-split-view.md).
- Invoice and document labels: [audience-specific invoice labels](2026-10-audience-specific-invoice-labels.md).
- Backend behaviour, API shapes, billing calculations, permissions, data models.
- Wrapping every Mantine control, or a custom pattern-checking script (ADR 0040 decision 8).

Illustrative labels below must use translation keys in implementation.
Count-bearing messages use locale-aware pluralisation.

## 3. Actors, permissions, and ZEV scope

Existing role and ZEV access rules are unchanged. A read-only user sees the
same container with the write controls absent, not a disabled form. Important
issues stay visible even to a reader who cannot fix them; a fix is offered only
when authorised and available.

Account, community or capability changes clear unauthorised selections, detail
data and drafts. Keep the `useWriteScope` protections: an obsolete mutation
completion must not reopen detail, move focus, announce success or select data
in a replacement scope. Invalidate the originating community's queries as today.

## 4. Component catalogue

Contracts of existing components are in SPEC-2026-04 §4.1–§4.3; this table says
when to reach for each. **new** marks a component defined in §7.

### 4.1 Page structure

| Need | Use | Do not |
|---|---|---|
| Title, scope kicker, description, page actions | `PageHeader` | hand-written `<h1>` / `.page-header` |
| Loading, error, content | `PageState` + `PageSkeleton` | a "Loading…" text card |
| Community scope handling | `ScopeGuard` | re-implementing "no community" branches |
| Mutually exclusive document-like views | `AppTabs` (**new**, §7.4) | hand-rolled tab strips; tabs for filters |
| Counted, mutually exclusive list filters | `FilterTabs`; counts only when they help (§10.1) | `AppTabs` |
| Period or interval | `PeriodSelector`, `YearPicker` | bare date inputs for billing periods |
| Filter row / list actions | `.filter-bar` / `Toolbar` | ad hoc flex rows |
| KPI tiles | `StatCard` in `.stat-grid`, no totals added to fill space | custom tiles |
| Tabular records | `DataTable`, or the `.table-card.invoice-rows` row-table classes | bare `<table>` without table classes |
| Empty list | `EmptyState` with an authorised corrective action | free text in a `.card` |

Rows need a named, keyboard-accessible activation control: a link for routed
navigation, a button for an in-place preview. Row click is an extra
convenience. Do not expose navigation as `role="button"`.

### 4.2 Containers and actions

| Need | Use |
|---|---|
| Grouped page content | `.card` / `.table-card` sheet |
| Named group of fields | `.form-section` + `.form-section-header` |
| Record shown or edited beside its list | **Detail pane** (**new**, §6.2) |
| Short self-contained task | `FormModal` with a `size` (§6.1, §7.1) |
| Confirmation, discard, destructive step | `ConfirmDialog` / `useConfirmDialog` |
| Secondary content in a view | `Disclosure` (**new**) or row expansion (§6.3) |
| Row/page overflow actions | `ActionMenu` |
| Inline message about state | `Notice` |
| Transient result of an action | `useToast`; never the only record of a failure |
| Form footer | `FormModalFooter`, generalised for the pane (§7.6) |
| Fields | native or Mantine controls as themed by `mantineTheme.ts` |

Menus and pickers belong to their owning surface. Overlay z-indices come from
`lib/zLayers.ts` (`Z_MODAL` < `Z_POPOVER` < `Z_TOAST`); the in-flow pane needs
no overlay layer.

## 5. Decision rule: where does it open?

Take the first row that fits. These are defaults: use them unless there is a
reason, and when there is, say so in a code comment naming the rule.

| # | The user is… | Default container |
|---|---|---|
| 1 | Confirming, discarding or taking a destructive step | `ConfirmDialog` |
| 2 | Looking at or editing a record they opened from a list | **Detail pane**, viewing and editing in the same place |
| 3 | Doing a short, self-contained task, or creating a record that has no detail view | `FormModal` |
| 4 | Reading something short that belongs to a row | Row expansion |
| 5 | Reading secondary material most visits do not need | Disclosure |
| 6 | Working on something that outgrows a dialog (§6.4) | Routed page |

Rules that cut across the table:

- **A. One home per record.** Detail and form for the same record live in the
  same place. A record with a detail pane is created and edited in it; there is
  no separate edit dialog over a pane.
- **B. Only a confirmation opens over a pane or dialog.** Discard and destructive
  confirmations may. A sub-form is an inline section, not a second dialog.
  Popovers, menus and pickers inside a surface are fine. At most two layers.
- **C. No overlay drawers.** A detail that belongs to a list uses the pane. A
  detail with no list beside it (for example one opened from a chart) is a
  dialog or an inline section. The existing overlay drawers are retired in
  phase 3 (§11).
- **D. Size or steps alone do not make a page.** Several sections, several
  steps, a chart or a wide layout are reasons to *check* usability (§6.4), not
  to move to a page automatically.
- **E. A narrow screen shows one surface at a time.** Two panes that cannot both
  be useful become one: the detail replaces the list, with X and Back to return.
- **F. Create opens the same container as edit.** "New tariff" opens the pane
  with a blank form.

## 6. Interaction standards

### 6.1 Dialog (`FormModal`)

- Header `h2`, divider and close button as today. Footer: Cancel
  (`button-secondary`, `type="button"`) then the primary action
  (`type="submit"` of the dialog's native `<form onSubmit>`). Preserve Enter in
  multiline and composite controls.
- **Sizes.** A few named sizes, chosen for content, with a compact one
  preserved. Provisional values, confirmed by screenshots before they become a
  contract: `xs` 480px (one to three fields: record a payment, refund, correct an
  invoice), `sm` 600px (the current default, so default callers do not change),
  `md` 760px, `lg` 960px, `xl` 1080px (wide read-mostly content such as price
  history or import review). `ConfirmDialog` stays 400px. Responsive bounds
  (90% width, 90dvh) and the no-horizontal-overflow requirement stay. Existing
  widths map to the nearest size in phase 4 (480/520 → `xs`; 560–640 → `sm`;
  720/760 → `md`; 900/960 → `lg`; 1000/1080 → `xl`); a width change is checked
  visually.
- **Dirty guard (universal).** X, Cancel, Escape, scrim click and in-app
  navigation ask **Discard changes?** when the form has unsaved changes, and
  close immediately when it has none or is read-only. Browser reload or tab
  close uses `beforeunload`. The guard is implemented once in `FormModal` (a
  `dirty` signal from the form) and reused by the pane, not written per form.
  Explicit discard resets the draft; reopening starts from saved data. A reload
  warning does not imply recovery after reload.
- Focus, stacking, inertness and restoration: SPEC-2026-04 §4.1
  ([dialog behavior](2026-04-frontend-management-page-design.md#dialog-behavior)),
  owned by `useDialogBehavior.ts` / `dialogInertness.ts`. Escape closes the
  topmost picker or confirmation before its parent.

### 6.2 Detail pane

The pane is the one pattern for a record opened from a list. The tariff screen
is its first implementation and defines its details
([tariff split view](2026-10-tariff-split-view.md)); the contract below is what
every adopter shares.

- **In flow, not an overlay.** On a wide screen the pane sits beside the list and
  reserves its space: no dimming scrim, no scroll lock, no focus trap, and it
  never covers or cuts off the list. List and pane scroll independently; the
  pane's heading and X stay easy to reach.
- **Narrow screens** (phones, or whenever two usable panes do not fit): the
  selected detail takes the content area and the list is hidden from the
  accessibility tree and tab sequence until shown again. X and browser Back
  return to the list with its filters, ordering and scroll intact. It is the
  same screen and the same detail body, not a new route. Exact widths and the
  breakpoint are pilot outputs.
- **Viewing is the default.** Edit replaces the body with prefilled fields in the
  same pane; the title and selected record stay recognisable. Save returns to
  viewing the saved result; Cancel returns to the original context. Read-only
  users have no editing mode.
- **Semantics.** A region labelled by its `h2` title, without `aria-modal`.
  An optional muted facts line; no default status or count badge. Focus moves
  to the title on an intentional open, to the first editable field on entering
  edit mode, and back to the invoking control on close or Cancel (or to the
  list heading if that control is gone).
- **Dirty guard.** Before closing, navigating (including Back), or selecting
  another record while the form is dirty, ask to discard. Choosing to stay keeps
  both the draft and the selection. Scope or access changes clear drafts and
  selections immediately (§3).
- **A confirmation** makes the pane, the list and their unrelated popovers inert
  through the existing modal manager; the pane never sets those attributes itself.
- **Exit animation.** If content is retained through a closing animation, retain
  it only through that exit, clear it on scope or access change, and ignore a
  stale exit callback after reopening. Do not add an animation just for this.
- **Deep links.** The selection lives in the URL where one exists today.
  Opening from the list adds one history step; switching record or version in
  the open pane replaces it; viewing/editing mode adds none.

### 6.3 Disclosure

| Shape | Use | Implementation |
|---|---|---|
| Section disclosure | Secondary content in a sheet or form: history, technical detail, a field reference | `Disclosure` (native `details/summary`), usually closed |
| Row expansion | Short information best read beneath its row (assignments under a metering point) | A named button with `aria-expanded` and `aria-controls`; independent state per row (`MeteringPointRow` is the reference) |
| Show more | A deliberately shortened list | A `button-ghost` toggle that says what it reveals, with a count only if useful |

Actions alone do not force a row expansion into a pane: assignment rows already
carry several. Choose a **tab** when the content replaces the working view;
choose a **disclosure** when it supplements it.

### 6.4 Pages and longer workflows

A task becomes a page when it needs its own navigation or a URL worth sharing,
needs substantial recovery (a draft, a file, a running job), or genuinely needs
more room than a dialog at `lg` gives. Use the management-page shell
(SPEC-2026-04 §7.1); long forms group fields in `.form-section`s with a
reachable save action.

Several steps do **not** make a page by themselves. A short two-part flow can
stay a dialog. A step in the URL is not recovery: it retains no `File`, preview,
entered values or upload/import job. If a flow needs recovery, specify what
survives close, Back, reload and a later visit, and decide the storage; do not
persist every form by default. `ZevListPage` creation and `ImportWizardModal` are
decided against these criteria in phase 5 (§11).

## 7. Shared components

Extract a component when repeated behaviour or configuration has real
consumers and a concrete maintenance payoff. Keep intermediate builds valid.

### 7.1 `FormModal` `size`

A `size` prop replaces `maxWidth` (values in §6.1; shipped in phase 2 with `maxWidth` kept as a deprecated override until phase 4 maps the last caller). Migrate all affected callers
in one change, or keep both props valid until the last caller moves; remove
`maxWidth` from the type at the end so the old API is a compile error.

### 7.2 Detail pane

Start in the tariff feature code (`TariffDetailDrawer` becomes the pane) and the
existing responsive row styles. Extract a shared `DetailPane` layout, focus and
dismissal behaviour when the second consumer (the audit log) adopts it.
Consolidate the existing overlay drawers by assessing each one's modal
semantics, focus, Escape ownership and retained data; do not silently change
metering gaps' current modal interaction.

### 7.3 `Disclosure`

A small component over native `details/summary` with one `.disclosure` style,
when the repeated styling pays for it. Existing `.overview-period-details` /
`.overview-period-history` become modifiers or go. Show-more and row-expansion
buttons share one `.disclosure-toggle` style.

### 7.4 `AppTabs`

A thin wrapper over Mantine `Tabs` that fixes the class mapping (`root:
app-tabs`, `list: app-tabs-list`, `tab: app-tabs-tab`) and re-exports
`List`/`Tab`/`Panel`. Preserve Mantine's props, refs, keyboard behaviour and
compound components; merge extra classes without dropping the shared ones; all
panels stay under one root.

### 7.5 What stays direct

`ActionMenu`, `PeriodSelector`, `CommunitySwitcher` and `PageSkeleton` own their
library use. Themed form controls (`TextInput`, `Autocomplete`,
`DatePickerInput`, `Switch`, `Chip`) stay importable from Mantine in pages:
`mantineTheme.ts` already makes them consistent. Add a wrapper for a control
only if two screens begin to configure it differently.

### 7.6 Footer

`FormModalFooter` becomes the Cancel/Save footer for the pane as well. Generalise
its name and API only as the pane needs (the pane owns placement and sticky
positioning); do not rename every dialog caller as a prerequisite, and do not add
a general container-detection API.

## 8. Forms

### 8.1 Layout

Use `.form-grid`, `.grid-span-full` and `.form-section`. Short forms are one
column; larger layouts use two when they fit. No nested cards around field
groups. Label above the control, helper below it, error below that; required
fields use the shared marker. Never solve a layout problem with a per-field
`size` (SPEC-2026-04 §4.2).

### 8.2 Validation, saving and drafts

- Validate on submit first; after that, update affected errors as the user
  corrects them. Do not show errors during first entry into a field. Native
  constraints and server validation still apply.
- Show field errors by the field, and map server field errors there. A
  non-field failure is a persistent `Notice` inside the form; a toast alone is
  not enough. A failed save keeps values, focuses the first invalid field, and
  keeps a general error readable when no field is invalid.
- While saving: visible progress, no duplicate submission, further edits
  temporarily prevented with values still readable, the form marked busy. On
  success the pane returns to viewing the result (or a dialog closes); on
  failure the form, values and error stay for retry.
- Closing a form does not cancel a request already sent. If dismissal is offered
  during a pending save, say the save may still complete, and apply its
  completion only to the originating scope and the current editing instance.
- Short forms need a discard guard, not persistent drafts (§6.1).

### 8.3 Actions

Cancel is `type="button"`, then the primary `type="submit"`. Use task-oriented
labels (Save changes, Create tariff, Schedule price change). Destructive
operations stay out of the footer and use `ConfirmDialog`.

## 9. Actions

SPEC-2026-04 §7.3 stays the reference: primary, secondary, overflow, destructive.

- One clear primary action per header, toolbar or task context.
- Frequent row actions use the compact outlined treatment (`button-outline
  button-compact`); lower-frequency ones go to `ActionMenu`; destructive row
  actions are quiet until hover and always confirm.
- The `button` base class plus one variant is required on every visible action
  (`button-primary`, `-secondary`, `-outline`, `-ghost`, `-danger`; `-compact`
  in rows). The two stray forms (`button danger`, `button button-primary
  button-outline`) are errors. Component-owned controls (tab, menu item,
  switch) are not reformatted into action buttons.
- Visible labels on primary mobile actions. Disabled controls say why, near the
  control; a tooltip may supplement but is never the only route.

## 10. Feedback, labels and states

### 10.1 Usefulness before decoration

A label or count earns its place by helping its audience understand, compare or
act. Being in the data model is not enough.

| Information | Treatment |
|---|---|
| Counts | Omit by default. Show them for a concrete task, such as a filtered population or affected records; not as tariff, fee, band or version totals. |
| Classification (participant roles, meter type) | A quiet neutral `.badge-tag`, or plain metadata text. |
| Ordinary dates and validity | Plain, readable text; history visibly muted but readable. |
| A useful workflow distinction | A precise neutral label, not repeating a state the section heading already gives. |
| Generic normal state | No decoration (a coloured "In Bearbeitung" that tells nothing). |
| A concrete problem | Short warning or error text with a link to its fix when one exists and the user may use it. |
| Success | A transient confirmation; do not mark every healthy record green. |

The participants **Kein Messpunkt** treatment is the reference for a problem:
red issue text, a real link for authorised users, no filled capsule; a read-only
user sees the same text without a click affordance. Routine state does not earn
colour, colour never carries meaning alone, and neutral tags stay valid. This is
usage guidance; badge shape and palette do not change.

### 10.2 Feedback and wording

| Situation | Component / behaviour |
|---|---|
| Initial structured loading | `PageSkeleton` |
| Bounded operation | Local progress, content kept visible |
| Background refresh failed | Keep cached content, show a warning beside it |
| Content query failed | `PageState` / `Notice` with retry |
| Empty content | `EmptyState` with an authorised action |
| Form failure | Inline field errors or `Notice`; keep values |
| Action completed | Brief `useToast`, not duplicating permanent page information |

Prefer the concrete condition or next step over vague workflow text:
"Processing…" only for work that is running, not as a stand-in for "Awaiting
review". Keep important explanations visible and add an action when one exists.

## 11. Rollout

Each phase is independently mergeable and has an exit criterion. The sequence is
committed work, not a backlog of optional migrations. With each phase, update
the affected baseline specs (`2026-03-tariffs-and-billing-engine`,
`2026-04-frontend-management-page-design`, `2026-08-ui-redesign-pdf-style`, and
`2026-03-community-and-access` if URL or history behaviour changes) and the
matching user-guide chapter; regenerate guide screenshots as a set.

| Phase | Work | Exit criterion |
|---|---|---|
| 0 | This documentation | Spec and ADR 0040 reviewed |
| 1 | **Tariff pilot** ([tariff split view](2026-10-tariff-split-view.md)): list treatment, pane with viewing and editing, phone behaviour, the dirty guard | Pilot acceptance passes on a laptop and a phone; widths and breakpoint recorded; ADR 0040 accepted |
| 2 | **Shared pieces:** `FormModal` `size` and universal dirty guard; `Disclosure`; `AppTabs`; the pane's shared parts once a second consumer exists | Components exist with tests; all `FormModal`s guarded |
| 3 | **Retire overlay drawers:** audit log to the pane; metering gaps to a dialog or inline section (decided with screenshots); remove raw `Drawer` use and add the `no-restricted-imports` rule | No page or feature imports `Drawer` from Mantine |
| 4 | **Dialog sizes:** map each explicit `maxWidth` to a size with screenshots; remove `maxWidth` from the type | `maxWidth` no longer compiles |
| 5 | **Wizards:** decide ZEV creation and the import wizard against §6.4 | Each flow's outcome recorded; changes implemented |
| 6 | **Label and count sweep:** overview status decoration, decorative counts, generic pills, actionable issues, billing's narrow labels | §10.1 holds on every screen audited |
| 7 | **Buttons and inline styles:** stray variants, missing `button` class, static `style={{}}` into CSS | Two stray forms gone; no static presentation in `style` where a class exists |
| 8 | **Invoice labels** ([spec](2026-10-audience-specific-invoice-labels.md)) | Per that spec |

### Risks

| Risk | Mitigation |
|---|---|
| The split view is cramped on ordinary laptops | Validate real widths and reflow; switch to one visible pane when two cannot be useful |
| Navigation loses place or leaves the app | Preserve list state; distinguish in-app open from direct entry; test X, Back, Forward, reload |
| Non-modal editing lets the user walk away from a draft | Universal dirty guard before selection changes and navigation |
| Many-band or dynamic tariff creation does not fit a pane | Make "does creation fit?" an explicit pilot go/no-go; the fallback is a page for that task only |
| A shared abstraction precedes useful behaviour | Start in feature code, extract at the second consumer |
| Old data or a delayed save affects a new scope | Keep the `useWriteScope` guards; clear selection and drafts on scope change |
| Rules harden into dogma where a case really differs | A deviation is allowed with a comment naming the rule and the reason |

## 12. Validation and enforcement

- **Per phase:** `npm run lint`, `npm run lint:style`,
  `node ../scripts/check-frontend-hex.mjs`, `npm run test:unit`,
  `npm run build`, on the pinned Node version. Check the running dev stack at
  desktop and phone (~400px) widths, read the console, exercise the keyboard, and
  use long translated labels.
- **Screenshots** are for human design review; behaviour (keyboard operation,
  inertness, restoration) is asserted in browser or unit tests near the affected
  components. Extend `form-modal.test.ts` (size, dirty guard) and add tests for
  the pane and `Disclosure` when they land. This document does not claim they
  exist.
- **Accessibility baseline:** WCAG 2.2 AA: semantics, visible focus, focus not
  obscured, target size, forced colours, text alongside colour; announce progress
  and results once.
- **Enforcement uses the compiler and ordinary lint.** Remove a prop from the type
  when its replacement lands (`maxWidth`); add `no-restricted-imports` for
  Mantine `Drawer` (phase 3) and for the raw `Tabs` mapping once `AppTabs` covers
  its consumers, with narrowly scoped, explained exceptions. No custom
  pattern-checking script. Container choice and label usefulness are reviewed in
  context.

### Review checklist (PR template and the `pr-review` skill)

- [ ] The container follows §5, or a deviation is commented with the rule and reason.
- [ ] A record opened from a list uses the pane; nothing but a confirmation opens over a pane or dialog.
- [ ] Forms protect unsaved work and show actionable errors.
- [ ] Existing components and styles are reused; a new abstraction has real consumers.
- [ ] Labels and counts help their audience; problems link to a fix where one is available.
- [ ] Permissions, scope changes, keyboard access and translated text stay correct.
- [ ] The changed workflow has automated checks and visual review at desktop and phone width.

### Acceptance criteria for this documentation change

- [ ] Reference spec, tariff pilot spec, invoice-labels spec and ADR 0040 agree.
- [ ] Proposed behaviour is clearly separated from what is shipped.
- [ ] The rollout phases have exit criteria.
- [ ] Every catalogue entry and observation resolves to code.
- [ ] No UI, route, wrapper or lint rule is claimed as shipped.

## 13. Open questions

1. Audit-log detail: pane beside the log, as the tariff list? (Phase 3.)
2. Metering gaps: dialog or inline section? It opens from the chart page with no list beside it. (Phase 3.)
3. Dialog size values and the pane's breakpoint: confirmed by pilot screenshots.
4. ZEV creation and the import wizard: dialog or page, against §6.4. (Phase 5.)
5. Row click: open the pane everywhere, or only through a named control so text selection and copy keep working?
