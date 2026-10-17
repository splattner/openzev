# Feature Spec: UI patterns and component catalog

- Spec ID: SPEC-2026-10-ui-patterns
- Status: Draft
- Scope: Major
- Type: Change
- Owners: Core maintainers
- Created: 2026-10-15
- Updated: 2026-10-16
- Target Release: Ongoing reference; tariff pilot first (§11)
- Related Issues: n/a
- Related ADRs: [0039](../adr/0039-overlay-and-disclosure-pattern-rules.md), [0040](../adr/0040-overlay-wrappers-not-mantine-primitives.md), [0032](../adr/0032-one-visual-language-for-screen-and-documents.md)
- Impacted Areas: frontend, docs

---

This branch defines a proposal; it does not implement the UI described below.
The revised direction is a tariff pilot followed by gradual adoption, pending
validation and acceptance of ADRs 0039/0040. Existing accepted guidance remains
authoritative until the relevant replacement is accepted and implemented.
Baseline specs and the user guide continue to describe the shipped UI.

## 1. Problem and outcome

The primary audience is an occasional, nontechnical community manager.
The goal is understandable, predictable tasks with a useful overview and
reliable return navigation. Code consistency supports that goal; differing
widths or component imports alone do not justify changing a workflow.

`2026-08-ui-redesign-pdf-style` §15 defines the current visual system.
`2026-04-frontend-management-page-design` defines existing shared primitives
and management-page structure. This reference adds task-based container
choices, a component catalog, and form/action/feedback guidance.

### Current observations (2026-10-16, commit `ecb0c962`)

| Observation | Evidence and implication |
|---|---|
| Tariff detail covers part of the list | `TariffDetailDrawer.tsx` uses an overlay sized `clamp(720px, 60vw, 1080px)`. The uncovered list remains interactive, but space is not reserved for it. |
| The list already provides substantial pricing detail | `TariffCategorySections.tsx` shows prices, schedules, validity, notes and warnings; extra detail adds version history, actions and, for dynamic tariffs, charts and price records. |
| Tariff editing varies in complexity | `TariffFormModal.tsx` branches during creation, but an existing static-energy version can expose mainly dates and notes. Rename is one field; new-version and period tasks have their own dialogs. |
| Detail selection already supports links | `TariffsPage.tsx` stores series/version selection in URL parameters, but replaces history on open/close. The validity filter is local state. |
| Forms do not yet provide the proposed protection | Tariff forms lack a dirty-close guard; save errors are primarily toasts or a shared error banner. Submit is disabled while saving, but fields remain editable. |
| Existing responsive tables can be reused | Participants and invoices share the `table-card invoice-rows` treatment. Their container-based responsive rules support a list narrowed by a detail panel. |
| Other surfaces differ for real reasons | Audit and tariff drawers are non-modal; metering gaps uses Mantine's modal defaults. ZEV creation and imports have different steps, state and recovery needs. |

These observations are inputs to the pilot, not a backlog of mandatory
migrations. Static inline styles, component-owned buttons, native disclosures
and direct library imports must be assessed before being classified as defects.

## 2. Scope

### In scope for this proposal

| Area | Details |
|---|---|
| Container choice | Panels with viewing/editing modes, standalone short dialogs, pages when genuinely needed, and inline disclosure (§5–§6) |
| Tariff pilot | Table styling, current/upcoming/history hierarchy, reserved detail pane, mobile replacement view, and return navigation (§5.1) |
| Forms | Simple editing, discard protection, validation, pending and error behavior (§8) |
| Labels | Useful counts, quiet classifications, actionable issues and audience-specific statuses (§10) |
| Catalog and reuse | Existing primitives first; shared components only for demonstrated repetition (§4, §7) |
| Rollout and checks | Validate the tariff pilot before wider adoption; ordinary compiler/lint checks plus contextual review (§11–§12) |

### Out of scope

- UI implementation in this documentation branch.
- Broad visual redesign: palette, typography, badge shapes, shadows and brand
  tokens. The limited label-usage guidance in §10 is in scope; the visual
  baseline otherwise remains authoritative.
- Backend behavior, API shapes, billing calculations, permissions and data models.
- PDF implementation or changes to existing issued documents. §10.3 records
  document-facing label decisions for separate follow-up.
- Automatic migration of audit/gaps drawers, ZEV creation, imports or every
  existing form. Each workflow needs its own assessment.
- Wrapping every Mantine control, compulsory footer renames, new custom
  pattern-checking scripts, or a fixed app-wide modal-width conversion.

Illustrative labels below must use translation keys in implementation.
Count-bearing messages use locale-aware pluralization when a count is useful.

## 3. Actors, permissions, and ZEV scope

Existing role and ZEV access rules remain unchanged. Read-only users can inspect
the same information; write actions are absent rather than presented as
disabled forms. Important issues remain visible even when the reader cannot fix
them. A fix is actionable only when authorized and available.

Account, community or capability changes must clear unauthorized selections,
detail data and drafts. Preserve `useWriteScope` protections: obsolete mutation
completions must not reopen detail, move focus, announce success or select data
in a replacement scope. Invalidate the originating community's queries as today.

## 4. Component catalog

Existing contracts live in SPEC-2026-04 §4.1–§4.3. Proposed reuse candidates
in §7 are not prerequisites for the pilot.

### 4.1 Page structure

| Need | Use |
|---|---|
| Page title, scope, description and page actions | `PageHeader` |
| Loading, error and content states | `PageState` + `PageSkeleton` |
| Community-scope handling | `ScopeGuard` |
| Mutually exclusive document-like views | Mantine `Tabs` with existing `app-tabs` classes; `AppTabs` if extracted (§7.4) |
| Mutually exclusive list filters | `FilterTabs`; counts only when useful (§10.1) |
| Period or interval | `PeriodSelector`, `YearPicker` |
| Filter row / list actions | `.filter-bar` / `Toolbar` |
| Useful KPI tiles | `StatCard` in `.stat-grid`; no totals added just to fill tiles |
| Tabular records | `DataTable` or existing billing/participant row-table classes |
| Empty list | `EmptyState`, with a permitted corrective action where useful |

Rows need a named keyboard-accessible activation control. Use links for routed
navigation and buttons for an in-place preview; row clicking is an additional
convenience. Do not expose navigation as `role="button"`.

### 4.2 Containers and actions

| Need | Use |
|---|---|
| Grouped page content | Existing `.card` / `.table-card` sheets |
| Named form-field group | `.form-section` + `.form-section-header` |
| Secondary content within a view | Native disclosure or existing row expansion (§6.3) |
| Record inspection/editing beside a list | Reserved panel with viewing/editing modes when both panes fit (§6.2) |
| Standalone short edit/create task without a detail panel | `FormModal` |
| Destructive or consequential confirmation | `ConfirmDialog` / `useConfirmDialog` |
| Secondary row/page actions | `ActionMenu` |
| Inline state or error message | `Notice` |
| Transient action feedback | `useToast`; never the sole persistent error record |
| Form footer | Existing `FormModalFooter` where suitable (§7.6) |
| Fields | Existing themed native/Mantine controls |
| Labels, issues and counts | Decide usefulness and audience before presentation (§10) |

Menus and pickers belong to their owning surface. Overlay z-indices come from
`lib/zLayers.ts`; an in-flow panel does not need a new overlay layer.

## 5. Decision rule: where does it open?

Choose the smallest surface that makes the task understandable. Container
choice follows actual content and use, not the name "create", "edit" or "wizard".
Equivalent tasks should behave consistently; explain meaningful exceptions.

| User task | Starting choice |
|---|---|
| View/edit a record with an existing detail panel | Viewing/editing modes in that same panel, with space reserved for the list |
| Short, self-contained task without a detail panel | Form dialog |
| Short additional information belonging to a row | Inline expansion |
| Secondary material most visits do not need | Disclosure |
| High-impact decision | Confirmation dialog |
| Work that genuinely outgrows a usable dialog, needs independent navigation or substantial recovery | Assess a page, with task-specific acceptance criteria |

Multiple sections, several steps, charts or a large width are reasons to
inspect usability, not automatic page mandates. A short wizard may remain a
dialog. Substantial draft recovery needs a separate storage and navigation
decision; putting a step in the URL is not recovery.

### 5.1 Tariff pilot

**Files to start from:** `TariffsPage.tsx`, `TariffCategorySections.tsx/.css`,
`TariffDetailDrawer.tsx/.css`, `TariffToolbar.tsx`, the existing tariff form
dialogs, `useTariffCrud.ts` and `useTariffVersions.ts`, all under their current
`frontend/src/pages/` or `frontend/src/features/tariffs/` paths.

The route remains `/tariffs`. Keep the existing
`queryKeys.tariffs.series(selectedZevId || undefined)` query and
`fetchTariffSeries` client contract; no new backend response shape is required.

**Overview and information order**

- Show **Current**, then **Upcoming**, with **History** collapsed by default.
  Preserve the energy/grid fees/levies/metering category order inside each.
- A series with current and future versions can appear in both corresponding
  sections. Each row shows the relevant version, with the nearest upcoming
  version first. History provides access to past versions even when the same
  series still has a current version.
- Within details, prioritize current information, then future changes, then
  past versions. An explicitly selected historical/future version remains
  selected and is clearly identified. Full history and technical source
  information are available on demand; important warnings stay visible.
- Historical rows use readable grey styling and explicit historical context.
  They remain accessible and can expose permitted corrections. "Past" does
  not mean "disabled". A genuinely disabled record/action also states why,
  including when it is historical.
- Use plain validity dates instead of rounded validity pills. Do not add
  tariff/fee/band/version totals unless they help a concrete task (§10.1).

**Table and detail layout**

- Follow the existing participants/invoices table treatment, including sheet
  headers, aligned columns, row separators and action hierarchy.
- On suitable desktop widths, selecting a tariff opens its panel in viewing
  mode beside the list. It reserves space: it must not cover or cut off the
  list. Both panes scroll independently; the detail heading and X remain easy
  to reach.
- The narrowed list reflows using container width, like participants/invoices:
  a table where it fits and compact stacked rows where it does not. Preserve
  prices, units and their corresponding bands/schedules together. Add short
  visible labels only where needed to understand values after headers disappear.
- Tooltips explain ambiguous or truncated information; they are supplementary.
  Essential meaning remains available on touch, and explanatory interactions
  also support keyboard focus. The same principle should guide billing when
  that layout is next revisited; billing redesign is not part of this pilot.
- When two usable panes do not fit, including phones around 400px, the selected
  detail occupies the available tariff content area instead of the list. It is
  the same screen and detail body, with X to return; no new detail route is
  required. The same viewing/editing modes work at both widths, preserving an
  active draft across layout changes. The replaced list is hidden from the
  accessibility tree and tab sequence until it is shown again.
- Exact pane widths and the responsive breakpoint are pilot outputs, validated
  on a normal laptop and phone. Do not require a squeezed two-pane layout.

**Navigation and editing**

- Preserve existing `tariff`/`version` query-parameter deep links and unrelated
  query parameters. `tariff` uses the existing `seriesKeyOf` value (ZEV and
  name). Opening detail from the list creates one history step; switching
  tariffs within the open pane or changing the displayed version replaces
  that step. Browser Back returns to the list.
- X returns to the known originating list state. Direct entry has an explicit
  same-screen list fallback; do not navigate to an unrelated external origin.
  Back/Forward, X and reload must agree about the selection.
- Preserve available filters, ordering, list scroll and selection through
  inspection and panel editing. Closing the pane expands the list
  without losing its position. Do not add new sorting/filter features solely
  to satisfy this preservation requirement.
- Selecting a tariff starts in viewing mode. **Edit** replaces its detail
  body with prefilled fields in the same pane; the title and selected tariff
  stay recognizable. Only fields permitted by the existing API become editable;
  immutable identity fields retain their current restrictions.
- Rename, Schedule price change and period changes use the same panel's
  focused editing mode, seeded from the selected record/version. **New tariff**
  opens the panel with a blank creation form. Reuse the existing form logic
  independently of its current modal shell; do not require an extra edit dialog.
- Save returns to viewing mode on the saved tariff/version. Cancel returns
  to the original viewing context, asking before discarding changed values.
  Cancelling creation restores the previous selection or the list when there
  was none. Test realistic creation and many-band changes before proposing a
  larger surface; there is no blanket move to routed forms.
- Guard unsaved changes before X, Cancel, Escape, browser Back, navigation or
  selecting another tariff/version. Choosing to stay preserves both the
  draft and original selection. Confirmations use the existing modal manager
  for focus and inertness; the editing panel itself remains non-modal.
- **Schedule price change** is the prominent task-oriented action for future
  prices; ordinary edits remain separate. Show the effective date and
  resulting prices before submission, without a redundant confirmation step.
- After a successful create or scheduled change, select the resulting
  tariff/version. Preserve selection through rename, including updating the
  name-derived series URL key. Obsolete scoped completions cannot select
  anything (§3). No billing/versioning semantics change is implied.
- Viewing/editing mode does not add another history entry. Reload warns about
  a dirty form and returns to the linked saved data in viewing mode; no draft
  recovery or additional editing route is introduced.

## 6. Interaction standards

### 6.1 Dialog

- Use the existing `FormModal` header, `h2`, divider and close control.
  Footer order is Cancel then the primary submit action.
- Use native `<form onSubmit>` and `type="submit"`; preserve Enter behavior
  in multiline and composite controls.
- X, Cancel, Escape, scrim click and in-app navigation share a dirty guard:
  changed unsaved values prompt **Discard changes?**; unchanged/read-only
  content closes immediately. Browser reload/tab close uses `beforeunload`.
- Explicit discard clears the short-form draft. Reopening starts from saved
  data/defaults. Reload warnings do not imply recovery after reload.
- Preserve existing `useDialogBehavior.ts` / `dialogInertness.ts` ownership,
  focus restoration and linked-popup behavior. Escape closes the topmost
  picker or confirmation before its parent.
- Standalone short tasks can still use dialogs. Records with a panel use
  its editing mode (§6.2). A discard/destructive confirmation can sit over
  either surface; underlying content is inert. Use an inline subsection
  for related sub-forms where practical instead of stacking edit dialogs.

### 6.2 Panel with viewing and editing modes

- The tariff panel is in-flow reserved layout, with no dimming scrim, page
  scroll lock or focus trap. Its presence does not hide part of the list.
- Render a region labelled by its `h2` title, without `aria-modal`. A muted
  facts line is optional when useful; there is no default status/count badge.
- In viewing mode, opening another record replaces the content immediately;
  editing first follows the dirty guard below. Move focus to the detail title
  on intentional open; return to the invoking control on close. If that
  control disappeared, use the list's heading as a usable fallback.
- Keep the record's primary action easy to find. Lower-frequency actions use
  the existing secondary/overflow hierarchy. Destructive actions require
  confirmation.
- Viewing mode is the default. Edit shows saved values as prefilled fields
  in the panel body, with Cancel/Save kept reachable. Saving returns to
  viewing the saved result; cancelling returns to the original context.
  Read-only users have no editing mode or write controls.
- The non-modal list stays available while editing. Before a selection/version
  change, dismissal or navigation would replace a dirty form, confirm discard.
  A rejected discard leaves the form and selection intact. Scope/access
  changes still clear unauthorized data immediately (§3).
- Move focus to the form's first editable field on entering edit mode and
  return to its initiating action on Cancel, or the saved record heading when
  that action no longer exists. Do not trap focus within the editing panel.
- A confirmation makes the panel, list and their unrelated popovers inert;
  popovers owned by the active dialog remain interactive. The panel does not
  independently change attributes owned by the modal manager.
- If an exit animation retains content, retain only through that exit and
  clear on scope/access change before rendering. Ignore a stale exit callback
  after reopening; never show a previous authorized record while new data is
  null. Do not add an animation or retention helper just to satisfy this rule.

These are the tariff pilot's requirements. Other existing drawers keep their
interaction until separately assessed; there is no compulsory mobile route or
change from modal to non-modal for every drawer.

### 6.3 Disclosure

| Shape | Use | State |
|---|---|---|
| Section disclosure | Secondary content inside a sheet/form, history or technical detail | Native `details/summary`; usually closed initially |
| Row expansion | Information best understood beneath its row | A named button with `aria-expanded` and `aria-controls`; independent local state |
| Show more | A deliberately shortened list | Existing ghost button; explain what it reveals, with a count only if useful |

Reuse `MeteringPointRow` for row expansion and billing periods for collapsed
history. Actions alone do not force expansion into a drawer: existing
assignment rows already contain several actions. Choose a tab when content
replaces the working view; choose disclosure when it supplements that view.

### 6.4 Pages and longer workflows

Use the existing management-page shell when a task has demonstrated the need
for a page. Long forms can group related fields and keep the save action
reachable. A multi-step workflow needs a separate decision about steps,
navigation, drafts, files and job state before migration.

`ZevListPage` creation and `ImportWizardModal` are assessment candidates,
not committed page conversions. A URL step does not retain a File object,
preview, entered values or upload/import job. Specify what survives close,
Back, reload and a later visit if recovery is needed; do not introduce
persistent storage for every form by default.

## 7. Shared components: extract demonstrated repetition

### 7.1 Dialog sizing

Use a few shared named sizes chosen for content, preserving a genuinely
compact option. Do not snap every 480/520/560px dialog to a 640px minimum.
Exact widths/defaults require pilot screenshots before becoming a contract.
Existing responsive bounds and no-horizontal-overflow requirements remain.

`FormModal` currently accepts `maxWidth`. If a `size` API is introduced,
keep every intermediate build valid: preserve compatible existing callers
until migrated, or migrate all affected callers atomically. Width-only
changes must include visual checks. Other dialogs do not need migration
merely because the tariff pilot lands.

### 7.2 Panel and drawer reuse

Start with the existing tariff feature component and responsive row styles.
Extract shared layout, focus or dismissal behavior only when another real
consumer benefits. Do not build a generic Mantine `Drawer` wrapper as a
prerequisite for an in-flow tariff panel.

If existing overlay drawers are later consolidated, assess modal semantics,
focus, Escape ownership, retained data and scope clearing for each consumer.
Share behavior without silently changing metering gaps' modal interaction.

### 7.3 Disclosure reuse

Native `details/summary` and existing expansion buttons remain valid.
A small `Disclosure` component is appropriate when repeated styling pays
for it; do not replace every native disclosure or introduce a separate
show-more abstraction merely to normalize syntax.

### 7.4 Tabs reuse

An `AppTabs` wrapper may remove repeated Mantine class mappings
(`root: app-tabs`, `list: app-tabs-list`, `tab: app-tabs-tab`).
Preserve Mantine props, refs, keyboard behavior and `List`/`Tab`/`Panel`;
all panels remain under one root. Merge extra classes without losing shared
ones. Do not mandate a tab migration before the pilot is validated.

### 7.5 What stays direct

Existing `ActionMenu`, `PeriodSelector`, `CommunitySwitcher` and
`PageSkeleton` already own their library usage. Themed form controls remain
directly importable from Mantine. A wrapper needs repeated behavior or
configuration to consolidate; library usage alone is not a defect.

### 7.6 Footer reuse

The pilot provides a real non-modal form consumer for Cancel/Save.
Reuse `FormModalFooter` behavior where suitable; generalize its name/API only
as needed by that consumer. The panel owns placement and sticky positioning.
Do not rename every dialog consumer as an unrelated prerequisite or add a
general sticky/container-detection API.

## 8. Forms

### 8.1 Layout

Use existing `.form-grid`, `.grid-span-full` and `.form-section` patterns.
Short forms are one column where appropriate; larger layouts can use two
columns when they fit. Avoid nested cards around field groups. Labels,
helper text, required markers and control geometry follow the existing field
tokens and theme; do not adjust individual field sizes to solve page layout.

### 8.2 Validation, saving and drafts

- First validate on submit, then update affected errors as the user corrects
  those fields. Do not show errors during the first entry into a field.
  Native constraints and server validation still apply.
- Show field errors by the field. Map server field errors there too; show
  non-field failures in a persistent `Notice` within the form. A toast
  alone is insufficient. Keep values and focus the first invalid field when
  applicable; keep a general error readable when no field is invalid.
- During save, visibly show progress, prevent duplicate submissions and
  temporarily prevent further edits while leaving values readable. Mark the
  form busy. On success, return the panel to viewing mode on the resulting
  selection (§5.1), or close a standalone dialog. On failure, retain the form,
  values and error for correction/retry.
- Preserve mutation scope and lifetime handling. Closing a form cannot be
  described as cancelling a request already sent. If dismissal/navigation is
  offered during a pending save, explain that it may still complete; apply
  its completion only to the originating scope and current editing instance.
- Short tariff forms need discard protection, not persistent drafts.
  Explicit discard resets; reopening reads saved data. Longer workflow
  recovery remains a separate assessment (§6.4).

### 8.3 Actions

Reuse the existing footer behavior: Cancel as `type="button"`, then the primary
`type="submit"` button. The existing footer disables submit during
pending; the owning form supplies progress, field locking, dirty guard and
error behavior. Retain native submit semantics.

Use task-oriented labels such as Save changes, Create tariff or Schedule
price change. Destructive operations stay separate from the save footer and
require `ConfirmDialog`.

## 9. Actions

SPEC-2026-04's hierarchy remains the reference: primary, secondary, overflow,
destructive. Reuse existing `.button` variants and `ActionMenu`; do not
reformat component-owned controls into action buttons indiscriminately.

- One clear primary action per header/toolbar or task context.
- Frequent row actions use the shared compact outlined treatment.
- Lower-frequency actions go in overflow; destructive actions are quiet until
  the explicit confirmation.
- Keep visible labels on primary mobile actions.
- Disabled controls explain why, near the control when needed for understanding.
  Tooltips can supplement that explanation but must not be the only route to
  essential information.

## 10. Feedback, labels and states

### 10.1 Usefulness before decoration

A label or count earns its place by helping its audience understand, compare
or act. Being present in the data model is not sufficient.

| Information | Proposed treatment |
|---|---|
| Counts | Omit by default. Add only for a concrete task, such as meaningful filtered populations or affected records; not decorative tariff/fee/band/version totals. |
| Classification, such as participant roles | Quiet neutral tags like the existing participant role tags are acceptable where they help identify the record. Plain metadata text is also valid. |
| Ordinary dates and validity | Plain, understandable dates/text; historical records are visibly muted but readable. |
| Useful workflow distinctions | Keep precise neutral labels where they help distinguish records; avoid repeating a status already established by a section heading. |
| Generic normal state | Omit redundant decoration such as a coloured "In Bearbeitung" that adds no useful next-step information. |
| Concrete issue | Concise warning/error text linked to a useful explanation or corrective action when available and permitted. |
| Success | Transient confirmation when useful; do not mark every healthy record with a green badge. |

The existing participants **Kein Messpunkt** treatment is the attention
reference: red issue text, a real link/action for authorized users, and no
filled capsule. A destination should help resolve that specific issue.
Read-only users still see the issue and useful explanation, without a false
click affordance. Not every important issue has an immediate fix.

Routine state does not automatically earn colour. Keep warning/error meaning
and text together; never rely on colour alone. Neutral classification tags
remain valid. This proposal changes usage guidance, not the global badge
shape or palette.

### 10.2 Feedback and wording

| Situation | Component / behavior |
|---|---|
| Initial structured loading | `PageSkeleton` |
| Bounded operation | Local progress indication, keeping useful content visible |
| Background refresh | Preserve content; warning beside cached data if refresh fails |
| Content query failure | `PageState` / `Notice` with retry |
| Empty content | `EmptyState`, with an authorized helpful action |
| Form failure | Persistent inline field errors or `Notice`; preserve values |
| Action completion | Brief `useToast`, without duplicating permanent page information |

Prefer the concrete condition or next step over vague workflow text.
"Processing…" describes work actually running; it should not substitute for
"Awaiting review" or another known condition. Existing overview
"In Bearbeitung" is an example to revisit, not a homepage change in the pilot.
Keep important explanations visible and include an action when one exists.

### 10.3 Audience-specific invoice labels (separate implementation)

| Audience / surface | Decision |
|---|---|
| Staff management interface | Useful internal Draft/Approved/Sent/Paid distinctions can remain, quietly presented. |
| Participant-facing screens | Focus on meaningful payment information, such as Payment due, Overdue or Paid, using reliable current data. |
| Ordinary issued invoice document | No status label. Internal approval/delivery states belong in staff UI; current payment status belongs in the participant screen. |
| Draft or cancelled document | A prominent plain Draft or Cancelled marking, sufficient to explain how to interpret the document. |

This branch records the audience rule only. The default invoice PDF currently
prints its status unconditionally; it has no separate prominent draft or
cancelled marking. PDF changes, custom-template implications and accurate
handling of stored documents need separate invoice-lifecycle work. Do not
silently regenerate issued PDFs or imply that a stored PDF reflects live
payment state. Update the owning baseline, templates, translations and tests
when that follow-up is implemented.

## 11. Rollout and risks

### 11.1 Order of work

1. **Revise the proposal (this branch).** Record the agreed direction in this
   reference and proposed ADRs. Keep current-behavior baselines and user-guide
   instructions accurate; do not describe the pilot as already shipped.
2. **Tariff pilot.** Reuse the existing feature components to implement §5.1
   and relevant form/label behavior. Deliver complete navigation, responsive
   layout and scope/access handling together, without changing tariff billing
   semantics or requiring new detail routes.
3. **Validate before generalizing.** Review realistic screenshots and actual
   interactions on a normal laptop and phone (§12). Record chosen widths and
   breakpoint, and revise the proposal where real examples expose problems.
4. **Accept proven guidance.** Resolve ADR status after pilot validation.
   Incorporate a short review checklist without changing the existing CI
   policy. Apply component rules only when the components exist.
5. **Adopt gradually.** New work uses the accepted patterns. Existing screens
   migrate when meaningfully changed; do not turn every known difference into
   an immediate migration obligation. Extract shared components when repeated
   use pays for them.

With the pilot implementation, update affected sections of
`2026-03-tariffs-and-billing-engine.md`,
`2026-04-frontend-management-page-design.md` and
`2026-08-ui-redesign-pdf-style.md`. Update
`2026-03-community-and-access.md` if its documented URL/history behavior
changes, and the matching user-guide chapter. Regenerate guide screenshots as
a set using the existing screenshot workflow when needed.

### 11.2 Assessment candidates, not compulsory migrations

| Candidate | What must be assessed before changes |
|---|---|
| Audit detail / metering gaps | Actual browsing needs, modal semantics, mobile behavior and reuse payoff |
| ZEV create / import wizard | Fit, meaningful work at risk, files/jobs, recovery and navigation; several steps alone do not require pages |
| Dialog widths | Content fit and screenshots; preserve compact cases |
| Tabs / disclosures / footer | Repeated configuration or a real additional consumer, not naming consistency alone |
| Overview status decoration / billing narrow labels | Useful information, meaningful actions and comprehension when those screens are revisited |
| Invoice document labels | Recipient usefulness, draft/cancelled markings, stored-document and custom-template implications |

### 11.3 Risks

| Risk | Mitigation |
|---|---|
| Split view is cramped on ordinary laptops | Validate real widths and reflow; switch to one visible pane when both cannot be useful |
| Navigation loses place or exits the app unexpectedly | Preserve list state; distinguish in-app open from direct entry; test X, Back, Forward and reload |
| Historical grey looks disabled | Keep text readable, historical context explicit and permitted actions accessible; explain actual disablement separately |
| New badge guidance is mistaken for a global restyle | Restrict implementation to the pilot; track other screens and PDF work separately |
| Shared abstractions precede useful behavior | Start in feature code; extract demonstrated repetition after validation |
| Old data or delayed saves affect a new scope | Retain existing write-scope guards and clear unauthorized selection/drafts immediately |

## 12. Validation and enforcement

### Pilot acceptance

Use realistic examples: a simple fixed fee, current plus scheduled prices,
historical and genuinely disabled entries/actions, multiple bands, and an
extensive dynamic tariff. Check ordinary laptop widths and around 400px,
as well as the chosen layout boundary.

| Scenario | Required observation |
|---|---|
| Overview hierarchy | Current then Upcoming, collapsed History; correct prices/version in each section; no gratuitous counts |
| Historical / disabled | Grey but readable history; separate explicit reason for true disablement |
| Desktop split view | List stays fully visible, reflows by container width, and scrolls independently from details |
| Narrow view | One usable pane, X returns to the list, no horizontal overflow or detached price/unit/schedule |
| Value comprehension | Short labels only where needed; touch/focus-accessible explanations; long translations wrap |
| Detail selection | Direct links and reload show intended series/version; Back/Forward and X retain correct list state |
| Editing | Prefilled fields in the same panel; Save/Cancel return to viewing, table remains available; mobile reflow preserves the draft |
| Save / failure | Visible pending state, no duplicate submit or lost late edits, result selected; errors and values remain on failure |
| Dirty dismissal | Panel guards X, Cancel, Escape, Back, navigation and tariff/version selection; standalone dialogs also guard scrim; reload warning; explicit discard resets |
| Scope / async lifetime | Old-scope data cleared, late completions cannot select/reopen unrelated detail or replace a newer edit; rename preserves selection |
| Keyboard | Named row controls, correct focus targets, no panel focus trap, picker Escape before parent, modal ownership intact |

Use screenshots for human design review and browser assertions for behavior;
screenshots alone do not prove keyboard operation, inertness or restoration.
Add focused tests near affected tariff and dialog tests during implementation;
this proposal does not claim those tests already exist.

Run frontend CI checks for the pilot:
`npm run lint`, `npm run lint:style`,
`node ../scripts/check-frontend-hex.mjs`, `npm run test:unit`,
`npm run build`. Use the pinned Node version. Check the running dev stack
at desktop/phone widths, inspect console errors, and include keyboard operation
and long translated labels. Preserve existing accessibility requirements.
Retain the WCAG 2.2 AA baseline: appropriate semantics, visible keyboard focus,
focus not obscured, target-size requirements, forced-colour support, and text
alongside meaningful colours. Announce progress/results appropriately without
duplicating notifications.

### Lightweight enforcement

Use TypeScript and ordinary lint rules for contracts that have actually landed.
An import restriction is appropriate only when an accepted wrapper exists,
covers its consumers and preserves their behavior; scope exceptions narrowly
with an explanation. Do not ban every direct Mantine import or introduce a new
pattern-checking script. Review container choice and label usefulness in context.

### Proposed review checklist

- [ ] The task uses the simplest usable container; a meaningful exception is explained.
- [ ] The panel leaves the list usable, including at narrow widths.
- [ ] Existing components/styles are reused; new abstractions have real consumers.
- [ ] Forms preserve context, protect unsaved work and show actionable errors.
- [ ] Labels/counts help their audience; issues have useful next steps where available.
- [ ] Permissions, scope transitions, keyboard access and translated text remain correct.
- [ ] The changed workflow has appropriate automated checks and visual/behavior review.

### Acceptance criteria for this documentation branch

- [x] Spec and proposed ADRs agree on the tariff split view with viewing/editing modes and gradual adoption.
- [x] Proposed behavior is clearly separated from current implementation.
- [x] Other drawers, wizards and footer names are assessment candidates, not mandatory migrations.
- [x] Badge usage and recipient-facing document decisions are recorded with implementation scope explicit.
- [x] Existing catalog entries and evidence resolve to the referenced code.
- [x] No new UI, route, wrapper, lint restriction or PDF change is claimed as shipped.
