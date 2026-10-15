# ADR 0035: One rule for where content opens — dialog, drawer, page, disclosure

- Status: Proposed
- Date: 2026-10-15
- Related specs: `2026-10-ui-patterns-and-component-catalog` (reference), `2026-04-frontend-management-page-design` (reference), `2026-08-ui-redesign-pdf-style` (baseline)
- Related ADRs: 0032 (one visual language), 0014 (print-parity design system)

## Context

ADR 0032 settled how the app *looks*. It did not settle where a piece of
content *opens*, and the code has drifted:

- `FormModal` is used in 33 files; 20 call sites set one of ten different
  `maxWidth` values (560 to 1080px) and the rest take the 600px default.
  There is no size scale.
- Three detail drawers exist (tariffs, audit log, metering gaps), all raw
  Mantine `Drawer`s. Two repeat the same overrides (`trapFocus={false}`,
  `lockScroll={false}`, a hand-written shadow, `pointerEvents` hacks, a manual
  Escape handler); the third uses Mantine's defaults. Their widths, header
  markup and heading levels differ.
- A tariff is *viewed* in a drawer but *edited* in a `FormModal` that opens
  on top of it, so a modal sits above a non-modal drawer.
- Multi-step flows (ZEV creation: 4 steps plus a done screen; the import wizard) are modals of up to 1080px;
  other long forms are routed pages.
- Collapsible content uses three mechanisms: native `<details>` (2 places),
  hand-rolled `aria-expanded` toggles (6) and row expansion.
- 19 page/feature files import `@mantine/core` directly (`Tabs`, `Drawer`,
  `Switch`, `Menu`, `Popover`, …) while the specs only describe our own
  components.

The specs describe each pattern but never say when to choose it, so each new
page re-decides. Reviewers have nothing to cite.

## Decision

1. **A decision rule, not a catalogue of options.** The container for a piece
   of content follows from what the user is doing (spec §5):
   - confirm / destructive → `ConfirmDialog`;
   - a short, self-contained task that blocks the page → `FormModal`;
   - detail of a row the user stays in context with, and editing that same
     record → `Drawer`;
   - a long, multi-section or multi-step flow, or anything that deserves a
     URL → a routed page;
   - secondary content on the same page → a disclosure.
2. **The container of a record's detail is the container of its form.** A
   record with a detail drawer is created and edited *in that drawer* (the
   drawer switches from reading to editing in place). A modal never opens on
   top of a drawer; the only dialog allowed over a drawer is `ConfirmDialog`.
   A record with no detail view is created and edited in a `FormModal`.
3. **Drawers are non-modal.** They do not trap focus or lock scroll, so the
   user can step through a list while the drawer is open (the audit log and
   tariff behaviour today). Because a non-modal drawer can be left behind,
   one in edit mode guards unsaved changes with a `ConfirmDialog` before it
   is replaced or closed.
4. **Sizes come from a scale.** Modals use `sm` (640px, default), `md`
   (760px), `lg` (960px) and `xl` (1080px). Drawers use `md` (35rem) and `lg`
   (`clamp(720px, 60vw, 1080px)`). Pages pass a name, never a pixel value.
5. **Our component wraps the library.** Page and feature code does not
   render Mantine's overlay and navigation primitives (`Drawer`, `Tabs`)
   directly; it uses `Drawer` and `AppTabs` from `components/`. These
   wrappers own the behaviour (modality, Escape, z-index, shadow, header,
   close button, ARIA) so it is decided once. `Menu` is already wrapped by
   `ActionMenu`. Form controls (`TextInput`, `Autocomplete`,
   `DatePickerInput`, `Switch`, `Chip`) are themed centrally by
   `mantineTheme.ts` and stay importable directly for now.
6. **Disclosure has three named shapes**, each with one implementation:
   `Disclosure` (a section on a sheet, native `<details>`), row expansion
   (detail under a table row, `aria-expanded`/`aria-controls`) and
   show-more (truncated list). Choosing between row expansion and a drawer
   follows the rule in the spec (§6.3).
7. **The rules are checkable.** Spec §10 lists the guard (a `scripts/` check
   in the style of `check-frontend-hex.mjs`) and the review checklist
   (`pr-review` skill, PR template).

## Consequences

Positive:
- A new page has one answer to "modal, drawer or page?", and a reviewer can
  cite a rule instead of a preference.
- Behaviour that today lives in three copies (non-modal drawer overrides,
  Escape handling, closing-animation retention) lives in one component.
- The modal size scale removes ten ad hoc widths; one width change is one
  edit.
- Editing in the drawer removes the stacked modal-over-drawer case and its
  focus and z-index edge cases.

Trade-offs:
- Rule 2 needs real migration work: the tariff forms (`TariffFormModal`,
  `TariffVersionModal`, `TariffPeriodFormModal`) are large and would move
  into the drawer. Until then they are listed exceptions (spec §11).
- A non-modal drawer in edit mode needs a dirty-state guard, which a modal
  gets for free from blocking the page.
- Wrapping `Drawer` and `Tabs` is a small extra layer, and about 19 files change
  imports.
- Some existing modals sit between two sizes; they snap to the nearest and a
  few change width by up to 60px.

## Alternatives considered

1. Keep stacking a form modal on a drawer.
   - Two overlays with different modality at once, extra focus and z-index
     handling (`lib/zLayers.ts` exists because of one such clash), and the
     user cannot tell which one Escape closes.
2. Make drawers modal, like dialogs.
   - Breaks the log/tariff browsing flow the drawers exist for, and makes
     them heavier than the modal they replace.
3. Allow Mantine components freely in pages.
   - Behaviour is re-decided per page, which is the current drift.
4. Wrap every Mantine component, form controls included.
   - A speculative component framework with no present payoff; the theme
     already makes the controls consistent. Revisit if field behaviour
     starts to diverge.
5. A free `maxWidth` per modal.
   - What produced ten widths.

## Notes

Rollout and the inventory of existing deviations are in
`2026-10-ui-patterns-and-component-catalog` §11.
