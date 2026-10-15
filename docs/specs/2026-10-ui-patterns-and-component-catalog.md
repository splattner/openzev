# Reference Spec: UI patterns and component catalog

- Spec ID: SPEC-2026-10-ui-patterns
- Status: Draft
- Scope: Major
- Type: Change
- Owners: Core maintainers
- Created: 2026-10-15
- Target Release: Ongoing reference (rollout in §11)
- Related Issues: n/a
- Related ADRs: [0035](../adr/0035-overlay-and-disclosure-pattern-rules.md), [0032](../adr/0032-one-visual-language-for-screen-and-documents.md)
- Impacted Areas: frontend, docs

---

## 1. Problem and outcome

`2026-08-ui-redesign-pdf-style` §15 defines how the app *looks* (tokens, shell,
page anatomy, sheets, buttons, pills). `2026-04-frontend-management-page-design`
defines the shared primitives and the structure of a CRUD page. Neither says
**which container or component to use for a given job**, and the code shows it:

| Observation (2026-10-15) | Evidence |
|---|---|
| Ten different modal widths | `FormModal` is used in 33 files; 20 call sites set `maxWidth` explicitly, to 560 (×2), 600, 620, 640 (×6), 720, 760 (×2), 900, 960 (×3), 1000 (×2) or 1080px; the rest take the 600px default |
| Three drawers, three implementations | `TariffDetailDrawer`, `AuditEventDrawer`, `MeteringGapsDrawer` — raw Mantine `Drawer`; two share copy-pasted non-modal overrides, widths are `clamp(720px,60vw,1080px)`, `min(100vw,560px)`, `min(100vw,32rem)`; heading level `h3` vs Mantine title |
| A modal opened on top of a drawer | Tariff detail drawer → `TariffFormModal` / `TariffVersionModal` / `TariffPeriodFormModal` |
| Wizards inside modals | `ZevListPage` 4-step create plus a done screen (960px), `ImportWizardModal` (1080px) |
| Three disclosure mechanisms | native `<details>` (`BillingPeriodCard`, `BillingPeriodsPage`), hand-rolled `aria-expanded` buttons (`ZevEmailTemplateFields`, `RawMeteringTable`, `MeteringGapsDrawer`, `MeteringPointRow`, `TariffCategorySections`) |
| Library used directly in pages | 19 page/feature files import `@mantine/core` (`Tabs` ×9, `Switch`, `Drawer` ×3, `Skeleton`, `Menu`, `Popover`, `Chip`, `TextInput`, `Autocomplete`) |
| Button variants beyond the system | one `button danger`, one `button button-primary button-outline`, 151 `<button>` elements without the `button` class, 571 `style={{}}` props |

The outcome is a single reference a contributor (human or agent) can follow
when adding a page or dialog: **a decision rule for where content opens**, a
**catalogue of the components to use** (and which not to hand-roll), the
**standards for forms, actions, feedback and states**, and the **checks**
that keep it that way. Round 1 (this spec) is definition only. Round 2 (§11)
aligns existing code.

## 2. Scope

### In scope

| Area | Details |
|---|---|
| Container choice | Decision rule: dialog / modal / drawer / page / disclosure (§5, §6) |
| New shared components | `Drawer`, `Disclosure`, `AppTabs`, `FormModal` `size` (§7) |
| Standards | Forms (§8), actions (§9), feedback and states (§10) |
| Catalogue | One table of every shared component with *use when* / *do not use when* (§4) |
| Enforcement | Review checklist and an automated guard (§12) |
| Rollout | Inventory of known deviations, migration order (§11) |

### Out of scope

- Visual styling: tokens, colour, type, sheets, pills, buttons (SPEC-2026-08 §15 stays authoritative).
- Structure of a CRUD page and the behaviour of the existing primitives (SPEC-2026-04 stays authoritative; this spec links to it rather than copying it).
- PDF layout, backend, API shapes.
- Wrapping Mantine *form controls* (§7.4, ADR 0035 alternative 4).
- Implementing any of §7 or §11; this spec defines them.

## 3. Actors, permissions, and ZEV scope

No change. Permission-dependent visibility of actions follows SPEC-2026-04 §3
and the page's role rules; a read-only role sees the same container with the
write actions absent (never a disabled form).

## 4. Component catalogue

Contracts of existing components live in SPEC-2026-04 §4.1 (and `index.css`
classes in §4.2); this table says **when** to reach for them. A row marked
**new** is defined in §7.

### 4.1 Page structure

| Need | Use | Do not |
|---|---|---|
| Page title, scope kicker, description, page-level actions | `PageHeader` | hand-written `<h1>` or `.page-header` markup |
| A page's loading / error / content states | `PageState` + `PageSkeleton` | a "Loading…" text card |
| Community scope handling | `ScopeGuard` | re-implementing "no community" branches |
| Mutually exclusive views of one subject (document-like) | `AppTabs` (**new**; today `Tabs` + `app-tabs` classNames) | hand-rolled tab strips; tabs for a filter (use `FilterTabs`) |
| Counted, mutually exclusive filters of a list | `FilterTabs` | `AppTabs` |
| Period / interval | `PeriodSelector`, `YearPicker` | bare date inputs for billing periods |
| Row of filters + period | `.filter-bar` | a sheet around filters |
| List actions on the page | `Toolbar` | ad hoc flex rows |
| KPI tiles | `StatCard` in `.stat-grid` | custom number tiles |
| Tabular records | `DataTable`, or the row-table classes for billing/participant/tariff lists | `<table>` without the table classes |
| Empty list | `EmptyState` | free text in a `.card` |

### 4.2 Content containers

| Need | Use | Reference |
|---|---|---|
| Grouped content on a page | `.card` / `.table-card` sheet with a `.card-header` or `.section-title` | SPEC-2026-08 §15.3 |
| Named group of fields in a form | `.form-section` + `.form-section-header` | §8 |
| Secondary content on the same page | `Disclosure` (**new**) | §6.3 |
| Inline message about state | `Notice` | §10 |
| Transient result of an action | `useToast` | §10 |

### 4.3 Overlays

| Need | Use | Reference |
|---|---|---|
| Confirm or destructive action | `ConfirmDialog` / `useConfirmDialog` | §5 |
| Short task that blocks the page | `FormModal` with a `size` | §5, §7.1 |
| Detail of / edit a record, list stays usable | `Drawer` (**new**) | §5, §7.2 |
| Long, multi-section, multi-step or linkable flow | routed page | §5 |
| Menu of row/page actions | `ActionMenu` | §9 |
| Small contextual panel anchored to a control | Mantine `Popover` wrapped by the owning component (e.g. `PeriodSelector`, `CommunitySwitcher`) | — |

Popovers, menus and date pickers outrank a modal through `lib/zLayers.ts`
(`Z_MODAL` 1000 < `Z_POPOVER` 1100 < `Z_TOAST` 1200); a new overlay takes its
z-index from there, never a literal.

### 4.4 Actions and fields

| Need | Use |
|---|---|
| Any button | `.button` plus one variant (§9); never a bare `<button>` for a visible action |
| Row/page overflow actions | `ActionMenu` |
| Form footer | `FormModalFooter` (**to be generalised for drawers and pages, §8.3**) |
| Text-like inputs, selects, date fields | native fields or Mantine controls as themed by `mantineTheme.ts`; never set field height with `size` |
| Status label | `.badge-*` for state, `.badge-tag` for attributes (SPEC-2026-04 §4.2) |

## 5. Decision rule: where does it open?

Read top to bottom; take the first row that fits.

| # | The user is… | Container | Why |
|---|---|---|---|
| 1 | Confirming or cancelling a destructive or high-impact action | `ConfirmDialog` | Small, blocking, one decision. Required for every destructive action (SPEC-2026-04 §7.3) |
| 2 | Looking at, or editing, a record **in a list they stay in** (they will open the next one) | `Drawer` — reading and editing in the same drawer | Keeps the list in view and usable; one container per record (rule A) |
| 3 | Doing a short, self-contained task, creating a record with no detail view, or answering a single question | `FormModal` | Blocks the page on purpose; ends in Save/Cancel |
| 4 | Working through a long form (more than ~12 fields or more than one `form-section`), several steps, a flow with its own sub-states, or anything someone might link to or reload | Routed page | Needs a URL, room, the browser's back button and the `ScopeGuard` |
| 5 | Reading secondary content that belongs to what is on screen | Disclosure (§6.3) | No new surface, no context loss |

Rules that cut across the table:

- **A. The container of a record's detail is the container of its form.**
  If the record has a detail drawer, create and edit happen in that drawer
  (§7.2: *reading* ↔ *editing* mode, same width, same header). If it has no
  detail view, create and edit use `FormModal`. Do not give one record both.
- **B. Nothing stacks on a drawer except `ConfirmDialog`.** A modal never opens
  from a drawer. A popover or menu inside a drawer is fine.
- **C. At most two layers.** Modal over page, or `ConfirmDialog` over modal /
  drawer. A form that needs a sub-form (e.g. a dynamic source inside a tariff)
  uses an inline sub-section or a disclosure, not a second modal; the sole
  existing stack (`TariffFormModal` → `DynamicSourceFormModal`) is a listed
  exception (§11).
- **D. A wizard is a page.** More than one step means rule 4. A modal may
  show a fixed two-part flow (e.g. choose a file → confirm) only when both
  parts fit `lg`; anything longer or with step state the user can lose on
  reload is a page.
- **E. If a modal needs `xl`, ask whether it is a page.** `xl` is for wide
  read-mostly content (tables, previews, import review), not for long forms.
- **F. Create buttons.** The page's primary create action opens the same
  container as edit (rule A) — `+ New tariff` opens the drawer in
  *editing* mode on a blank record.
- **G. Mobile.** A `Drawer` and a modal take the full width at ≤ 768px
  (the `min(100vw, …)` already in the scale); nothing is hidden behind
  hover.

## 6. Interaction standards

### 6.1 Modal (`FormModal`)

- Title in the header (`h2`), close button, header closes with the documents'
  rule (SPEC-2026-08 §15.3). Footer is a right-aligned `.dialog-actions`:
  **Cancel** (`button-secondary`) then the primary action. The primary button
  is a `type="submit"` of the modal's `<form>`; Enter submits.
- Escape and scrim click close it unless the form is dirty, in which case
  closing asks first (`ConfirmDialog`, "Discard changes?"). A modal with no
  editable fields closes without asking.
- Focus, stacking, inertness and restoration: SPEC-2026-04 §4.1
  ([dialog behavior](2026-04-frontend-management-page-design.md#dialog-behavior)).
- `size` instead of `maxWidth` (§7.1).

### 6.2 Drawer

- Anchored right, full height, non-modal: no focus trap, no scroll lock, no
  dimming scrim; the page behind stays usable. Escape closes it when focus is
  inside it. Opening another record **swaps the contents** in place.
- Header: `h2` title, optional one muted facts line, optional status pill,
  close button; it closes with the same rule as the modal header. Actions
  specific to the record (Edit, New version, Delete…) sit in the body's first
  `.actions-row`, primary first, destructive ones quiet and behind
  `ConfirmDialog` (§9).
- **Reading mode** is the default. **Editing mode** replaces the body with a
  form (§8) and a sticky footer (Cancel / Save); the header stays so the user
  knows which record is being edited. Saving returns to reading mode on the
  saved record; Cancel returns without saving.
- **Dirty guard.** A drawer in editing mode with changes confirms before it is
  closed, or before the selection changes to another record
  (`ConfirmDialog`, "Discard changes?"). A drawer in reading mode never asks.
- Because it is non-modal, the drawer is exposed as a labelled complementary
  region, not as a modal dialog (verify in implementation, §7.2).
- Closing animation: the drawer keeps showing the last record until it has
  slid out (the pattern `TariffDetailDrawer` and `MeteringGapsDrawer`
  hand-roll); `useRetained` (§7.2) does this once.

### 6.3 Disclosure — three shapes

| Shape | Use when | Implementation | State |
|---|---|---|---|
| **Section disclosure** | Secondary content inside a sheet or form that most visits do not need (completed history, details, a field reference) | `Disclosure` (**new**), native `<details>`/`<summary>` | closed by default; not in the URL |
| **Row expansion** | One row reveals a short block directly beneath it that shares the row's context; several may be open (assignments under a metering point) | chevron `button.button-ghost.button-compact` with `aria-expanded` and `aria-controls` → a detail row; the whole pattern keeps `MeteringPointRow` as the reference implementation | local; independent per row |
| **Show more** | A list longer than the screen needs (first 3 gaps) | a `button-ghost` toggle with `aria-expanded`/`aria-controls` and a count ("Show all 12") | local |

**Row expansion or drawer?** If the detail has its own actions, a chart or
table, more than about a screenful of content, or needs to be compared while
the list stays scrolled, it is a **drawer** (rule 2). If it is a short
read-mostly block with at most one action, it is **row expansion**.
**Disclosure or tab?** If the user needs the content *instead of* the main
content, it is a tab; if they need it *beside* it, a disclosure.

### 6.4 Page (rule 4)

A routed page follows the SPEC-2026-04 §7.1 shell. Long forms group into
`.form-section`s on one or more sheets and save with a single sticky action
row; a multi-step flow shows its steps as a numbered list at the top of the
page and keeps the current step in the URL (`?step=`), so Back and reload
work. Leaving with unsaved changes asks (`ConfirmDialog`).

## 7. New and changed components (to implement in Round 2)

### 7.1 `FormModal`: `size`

**File:** `frontend/src/components/FormModal.tsx`

| `size` | `max-width` | Typical content |
|---|---|---|
| `sm` (default) | 640px | up to ~8 fields, one column or a 2-column `.form-grid`, short workflows, bulk-delete / link-account style dialogs |
| `md` | 760px | forms with a read-only summary beside the fields, two `.form-section`s |
| `lg` | 960px | wide forms, two-part flows, previews |
| `xl` | 1080px | wide read-mostly content: price history, import review (rule E) |

`maxWidth` is removed from the props; a call site passes a size name or
nothing. `.form-modal` keeps `width: 90%` and `90dvh` (SPEC-2026-04 §4.2).
`ConfirmDialog` stays 400px and is not sized by the caller. Existing widths
snap to the nearest size: 560/600/620/640 → `sm`; 720/760 → `md`; 900/960 →
`lg`; 1000/1080 → `xl`.

### 7.2 `Drawer`

**File:** `frontend/src/components/Drawer.tsx`

```typescript
interface DrawerProps {
    opened: boolean
    onClose: () => void
    title: ReactNode            // rendered as the h2; also names the region
    meta?: ReactNode            // one muted facts line under the title
    badge?: ReactNode           // at most one state pill
    size?: 'md' | 'lg'          // default 'md'
    children: ReactNode         // body; the caller renders reading/editing mode
    footer?: ReactNode          // sticky; used in editing mode (Cancel / Save)
    returnFocusRef?: RefObject<HTMLElement | null>
}
```

| `size` | Width | Typical content |
|---|---|---|
| `md` | `min(100vw, 35rem)` | key/value detail, a short list, a short form (audit event, metering gaps) |
| `lg` | `clamp(720px, 60vw, 1080px)` | rich detail with a table or chart and an edit form (tariff series) |

Owns, once: non-modal behaviour (`trapFocus={false}`, `lockScroll={false}`,
pointer events on the panel only), the overlay shadow token (`--shadow-overlay`;
the raw `rgba` literal in today's drawers goes), `Z_DRAWER` in
`lib/zLayers.ts` (below `Z_MODAL`, so a `ConfirmDialog` outranks it), the
Escape handler (only when focus is inside the drawer or its linked popups,
consistent with `lib/popupKeyboard.ts`), the header anatomy of §6.2, the
close button (`aria-label` `common.close`) and the ARIA role. Sizing goes
through Mantine's `size` prop, not `styles.content.width`: the drawer's
`flex-basis` otherwise wins (the cause of the 440px bug noted in
`AuditEventDrawer`).

Helper: `useRetained<T>(value: T | null): T | null` in
`frontend/src/lib/useRetained.ts` returns the last non-null value so content
survives the closing animation.

**ARIA is to be verified, not assumed:** Mantine's drawer sets
`role="dialog"` with `aria-modal`; the wrapper must remove `aria-modal` for a
non-modal drawer and label the region by its title. Cover it in the test plan
(§12).

### 7.3 `Disclosure`

**File:** `frontend/src/components/Disclosure.tsx`

```typescript
interface DisclosureProps {
    summary: ReactNode
    defaultOpen?: boolean       // default false
    children: ReactNode
    className?: string
}
```

Renders `<details className="disclosure">` with a `<summary>`; the chevron,
focus ring and hover come from one `.disclosure` rule in `index.css`.
`.overview-period-details` and `.overview-period-history` become modifiers or
disappear. Show-more and row expansion keep their buttons (§6.3) but take their
classes from one `.disclosure-toggle` helper.

### 7.4 `AppTabs`

**File:** `frontend/src/components/AppTabs.tsx`

A thin wrapper over Mantine `Tabs` that fixes the `classNames` mapping
(`root: 'app-tabs'`, `list: 'app-tabs-list'`, `tab: 'app-tabs-tab'`) and
re-exports `List`, `Tab`, `Panel`. Contract unchanged from SPEC-2026-04 §4.1
(all panels under one root, real `tabpanel`s, no hand-rolled strips). Pages
and features import `AppTabs`, not `Tabs` from `@mantine/core`.

### 7.5 What stays direct

`ActionMenu` already wraps `Menu`; `PeriodSelector`, `CommunitySwitcher` and
`PageSkeleton` keep their Mantine imports because they *are* the wrappers.
Form controls (`TextInput`, `Autocomplete`, `DatePickerInput`, `Switch`,
`Chip`, `Popover` inside a field) remain importable from `@mantine/core` in
page/feature code: `mantineTheme.ts` already makes them consistent and the
cost of a wrapper per control is not paid back yet. If two pages start to
configure the same control differently, add a wrapper then.

## 8. Forms

### 8.1 Layout

- One `<form>` per container; native `<form onSubmit>`; the primary action is
  its `type="submit"` button.
- Fields sit in `.form-grid` (2 columns, collapsing to 1 at narrow widths);
  a field that needs the full row uses `.grid-span-full`. One column inside a
  `sm` modal or a drawer when the labels are long.
- More than one topic → `.form-section` with a `.form-section-header` kicker
  (as in `ZevGeneralSettingsFields`). No nested cards inside a form.
- Label above the control, optional helper text below it, error below the
  helper (the Mantine `InputWrapper` order that `mantineTheme.ts` also
  applies to native fields). Required fields are marked with the shared
  required marker, never with free text in the label.
- Field height, radius, label and helper type come from the field tokens;
  never solve a layout problem with a per-field `size` (SPEC-2026-04 §4.2).

### 8.2 Validation and errors

- Validate on submit and, per field, on blur after the field was touched;
  show the message under the field. A server error that belongs to a field is
  mapped onto it; one that does not is a `Notice` (role `alert`) at the top of
  the form.
- A failed submit never closes the container, keeps the values and moves
  focus to the first invalid field.
- Pending state disables only the submit button and sets `aria-busy`; the
  form stays readable.

### 8.3 Footer

`FormModalFooter` becomes `FormFooter` (same props plus `sticky`), usable in a
modal, a drawer (sticky, bottom of the panel) and a page (sticky action row).
Cancel is always `button-secondary` on the left of Save; the labels are
`common.cancel` and `common.save` (or `common.create` for a new record). A
destructive action does not live in the footer; it is a quiet button in the
body or an `ActionMenu` item, behind `ConfirmDialog`.

## 9. Actions

The hierarchy table of SPEC-2026-04 §7.3 stays authoritative (primary →
secondary → overflow → destructive). Added here:

| Level | Class | Notes |
|---|---|---|
| Page primary | `button button-primary` | at most one per page header or toolbar |
| Row / card main action | `button button-outline button-compact` | SPEC-2026-08 §15.3 |
| Secondary | `button button-secondary` (`button-compact` in rows and drawers) | |
| Tertiary / toggles | `button button-ghost` (`button-compact`) | disclosure, show more |
| Destructive in a row | `button button-secondary button-destructive` or a compact `button-danger` | quiet until hover |
| Destructive in `ConfirmDialog` | solid `button-danger` | |

- The `button` base class is required on every visible action; a bare
  `<button>` is only for controls with their own component (tab, menu item,
  switch). The two stray forms (`button danger`, `button button-primary
  button-outline`) are errors.
- Icon + text is the default (SPEC-2026-04 §4.3); icon-only needs an
  accessible name and a tooltip.
- More than two non-destructive actions on a row → `ActionMenu` (SPEC-2026-04
  §7.3).

## 10. Feedback and states

| Situation | Component | Rule |
|---|---|---|
| Page or panel is loading | `PageSkeleton` | never a text "Loading…" |
| A content query failed | `PageState` / `Notice` (role `alert`) with retry | cached data may stay visible beside a warning (SPEC-2026-04 §4.1) |
| Nothing to show | `EmptyState` (CTA when the user can fix it) | |
| A form or step needs attention | `Notice` inside the container, near the cause | |
| An action completed or failed in the background | `useToast` (`success`, `error`, `info`) | short; never the only record of a failure the user must act on |
| A state of a record | `.badge-*` (state) / `.badge-tag` (attribute) | colour means state only |
| A destructive or irreversible step | `ConfirmDialog` | names the object and the consequence |

## 11. Risks, rollout, and known deviations

### 11.1 Rollout (Round 2, each step independently mergeable)

1. **Components:** add `Drawer`, `useRetained`, `Disclosure`, `AppTabs`,
   `FormModal` `size`, `FormFooter`, `Z_DRAWER`; tests (§12). No page changes.
2. **Modals:** replace every explicit `maxWidth` with a `size` (20 call sites; the mapping
   in §7.1). Remove `maxWidth` from the props.
3. **Drawers:** move `AuditEventDrawer` and `MeteringGapsDrawer` onto
   `Drawer` (read-only, small); then `TariffDetailDrawer`.
4. **Tariff edit into the drawer** (rule A): fold `TariffFormModal`,
   `TariffVersionModal` and `TariffPeriodFormModal` into the drawer's editing
   mode; this is the largest change and removes the modal-over-drawer case.
5. **Disclosure:** convert the two `<details>` and the hand-rolled toggles
   (§6.3).
6. **Tabs:** swap the nine `Tabs` imports for `AppTabs`.
7. **Buttons and inline styles:** fix the two stray variants, add the base
   class to bare action `<button>`s, move static `style={{}}` into
   `index.css` (SPEC-2026-04 §4.2 already allows this per page).
8. **Wizards:** decide per flow (rule D): `ZevListPage` create wizard
   (4 steps plus done, 960px) and `ImportWizardModal` (1080px) are candidates for
   pages.

### 11.2 Known deviations until migrated

| Deviation | Rule | Plan |
|---|---|---|
| `TariffFormModal`, `TariffVersionModal`, `TariffPeriodFormModal` open over `TariffDetailDrawer` | A, B | step 4 |
| `TariffFormModal` → `DynamicSourceFormModal` | C | inline sub-section in step 4 |
| `ZevListPage` 4-step create modal, `ImportWizardModal` | D | step 8 |
| Ten `FormModal` widths | §7.1 | step 2 |
| Three drawer implementations | §7.2 | step 3 |
| 9 direct `Tabs` imports, 3 direct `Drawer` imports in pages/features | §7.4 | steps 3, 6 |

### 11.3 Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Editing in the drawer is a large change for the tariff forms | Medium | Own PR (step 4); the modals stay until it lands, so nothing is blocked |
| Non-modal drawer plus a dirty form lets the user navigate away unnoticed | Medium | Dirty guard (§6.2) with a test |
| Snapping widths changes a few dialogs by up to 60px | Low | Screenshot the affected modals in Round 2 |
| The rules harden into dogma where a case really differs | Low | A deviation is allowed with a comment naming the rule and the reason; the guard (§12) supports an inline allow |
| Mantine's drawer ARIA may not be correctable through props | Medium | Verify first (§7.2); fall back to a thin custom panel for the non-modal case |

## 12. Test plan and enforcement

### Frontend (Round 2)

- `frontend/tests/drawer.test.ts`: non-modal (no focus trap, page behind not
  inert, no scroll lock); no `aria-modal`; labelled by its title; Escape closes
  it only when focus is inside; content is retained through close; both sizes
  map to the specified widths; dirty guard blocks close and selection change.
- `frontend/tests/disclosure.test.ts`: closed by default, `defaultOpen`, toggles
  with Enter and Space, summary is the focus target.
- `frontend/tests/form-modal.test.ts` (extend): `size` maps to the four widths;
  default is `sm`; `maxWidth` is no longer accepted.
- `frontend/tests/app-tabs.test.ts`: class mapping and `aria-controls`
  resolution.
- Browser tests for a `ConfirmDialog` opened from a drawer (focus returns to
  the drawer's opener, drawer inert only while the dialog is open).
- Standard checks: `npm run lint`, `npm run lint:style`,
  `node ../scripts/check-frontend-hex.mjs`, `npm run test:unit`, `npm run build`.

### Guard

`scripts/check-ui-patterns.mjs`, run in `pr-quality.yml` next to the hex
sweep, fails on:

1. `@mantine/core` imports of `Drawer` or `Tabs` outside `components/`;
2. `maxWidth=` on `FormModal`;
3. a `className="button …"` using a class outside the §9 table;
4. `<Drawer` rendered under `pages/` or `features/` (use the component).

A line may opt out with `// ui-patterns-allow: <rule>, <reason>`; each allow is
listed by the script's summary so they stay visible. Rules not checkable by
text (A–G) are enforced by review.

### Review checklist (PR template and the `pr-review` skill)

- [ ] The container for each new piece of content follows §5 (or a deviation is
  commented with the rule and the reason).
- [ ] New dialogs use a `size` from §7.1; new drawers a `size` from §7.2.
- [ ] No modal opens from a drawer other than `ConfirmDialog`.
- [ ] Buttons follow §9; forms follow §8; states and messages follow §10.
- [ ] Shared components from §4 are used instead of re-implemented.
- [ ] User-facing text is translated.

### Acceptance criteria

- [ ] A contributor can pick the container for a new feature from §5 alone.
- [ ] Every shared component in `frontend/src/components/` appears in §4 or in
  SPEC-2026-04 §4.1.
- [ ] `AGENTS.md` links this spec next to the management-page reference spec.
- [ ] Round 2 steps 1–3 are merged and the guard passes with no allow other
  than those listed in §11.2.

## 13. Open questions

1. **Tariff creation.** Rule F makes `+ New tariff` open the drawer in editing
   mode. A tariff has a long form (billing mode, bands, dynamic source); rule 4
   says "long → page". Should tariff create/edit be a page (`/tariffs/:id`)
   with the drawer as a read-only preview, instead of editing in the drawer?
2. **Drawer on mobile.** At ≤ 768px an `lg` drawer is a full-screen sheet. Is a
   full-screen drawer-with-form acceptable, or should editing navigate to a
   page on phones?
3. **`DataTable` row click.** Should a row click open the drawer everywhere (as
   tariffs do), or only through a named link, to keep text selection and
   copy working?
