# ADR 0040: Choose containers by task; one detail pane; validate on tariffs, then roll out

- Status: Accepted
- Date: 2026-10-15
- Updated: 2026-10-28
- Related specs: `2026-10-ui-patterns-and-component-catalog` (reference), `2026-10-tariff-split-view` (pilot), `2026-04-frontend-management-page-design` (reference), `2026-08-ui-redesign-pdf-style` (baseline)
- Related ADRs: 0032 (one visual language), 0014 (print-parity design system)

## Context

ADR 0032 settled how the app looks. It did not settle where content opens,
and the screens have drifted (details and evidence in the reference spec §1):

- Detail views are overlay drawers that cover part of the list they belong to
  (tariffs, audit log), or a modal by default (metering gaps). Each repeats or
  skips the same non-modal overrides.
- A tariff is viewed in a drawer but edited in a modal that opens on top of it.
- `FormModal` widths are set per call site with no scale.
- No dialog except the ZEV settings page guards unsaved input.
- Disclosure, labels and counts are decided screen by screen; some carry
  decoration that explains nothing ("In Bearbeitung", version and fee totals).

The audience is an occasional, non-technical community manager. The goal is a
UI that is consistent, intuitive, clean and free of unnecessary information:
learn how one list-and-detail works, and every other one works the same.
Consistency is a goal in itself, not only a code-quality concern.

## Decision

1. **Firm defaults, explained exceptions.** Each kind of task has one default
   container (reference spec §5). A deviation is allowed when it is commented
   with the reason, not silently chosen.
2. **One detail pane for list-and-detail.** A record opened from a list is
   shown in an in-flow pane that reserves space beside the list, so it never
   covers or cuts off the list. The pane has a viewing mode and an editing
   mode in the same place: Edit shows prefilled fields, Save or Cancel returns
   to viewing. On a narrow screen the pane replaces the list; X and the
   browser's Back button return to it. Overlay drawers are retired in favour of
   this pane (or, where there is no list, a dialog or an inline section).
3. **Nothing but a confirmation opens over a pane or a dialog.** No edit modal
   over a detail pane; sub-forms are inline sections. At most two layers.
4. **Unsaved input is always guarded.** Closing, navigating or selecting
   another record while a form has unsaved changes asks first
   (`ConfirmDialog`, "Discard changes?"). The guard is implemented once in the
   shared dialog and pane, not per form.
5. **Dialogs use a few named sizes** for new and migrated work, with a
   compact one preserved. Values are confirmed with screenshots before they
   become a contract.
6. **A page when the task outgrows a dialog, not because it has steps.**
   Needing its own navigation, substantial recovery, or more room than a
   dialog can give makes a page. Several steps alone do not. ZEV creation and
   the import wizard are decided against these criteria in the rollout.
7. **Show only information that helps.** A label or count earns its place by
   helping its audience understand, compare or act. Concrete problems are
   actionable text; routine state is not decorated.
8. **Share behaviour once it has two consumers.** Extract a component when
   repeated behaviour or configuration has real consumers (the detail pane
   once the tariff pilot and a second list use it; `AppTabs`; `Disclosure`).
   Themed Mantine form controls stay directly importable. Enforce what has
   landed with TypeScript and ordinary lint rules (a prop removed from the
   type, a `no-restricted-imports` rule once the replacement exists), not with
   a custom checking script.
9. **Validate on tariffs, then roll out on a plan.** The tariff screen is the
   pilot (`2026-10-tariff-split-view`). After its acceptance the remaining
   screens follow in the phases listed in the reference spec §11, each
   independently mergeable. Unlike an opportunistic "migrate when touched"
   policy, the phases are committed work with exit criteria.

## Consequences

Positive:
- One answer to "modal, pane or page?" that a contributor and a reviewer can
  cite.
- The list stays visible while a record is inspected or edited, with simple
  return navigation.
- Unsaved input is protected everywhere with one implementation.
- Fewer patterns to maintain: no overlay drawers, no stacked edit dialogs.
- Labels carry information instead of decoration.

Trade-offs:
- A reserved pane needs careful responsive layout and navigation-state
  handling, and a non-modal editor needs discard protection before selection
  changes as well as on dismissal.
- The tariff pilot is large (layout, history behaviour, editing in place,
  scope handling); creation of many-band and dynamic tariffs must be proven to
  fit before the pattern is generalised.
- Replacing the Valid / Upcoming / All tariff tabs and the overlay drawers
  changes shipped screens, so baseline specs and the user guide are updated
  with each phase.
- Screens stay varied until their phase lands.

## Alternatives considered

1. **Keep overlay drawers.** Covers part of the list and leaves two kinds of
   detail view.
2. **A separate edit dialog over a read-only panel.** Adds a layer; prefilled
   editing in the same place fits the task better.
3. **A routed page for every tariff editor and every wizard.** Adds navigation
   and migration work without demonstrated benefit for small tasks; a URL
   step does not retain a file, a preview or a running import.
4. **Normalise everything before validating.** Commits unrelated workflows to
   a pattern nobody has seen working.
5. **Migrate opportunistically, "when touched".** Leaves the app inconsistent
   indefinitely, which is the problem being solved.
6. **Ban direct Mantine imports and add a custom pattern-checking script.**
   A framework without a present payoff; the theme already styles form
   controls, and the compiler and linter cover what has landed.
7. **Free `maxWidth` per dialog.** What produced the current spread.

## Notes

The reference spec is `2026-10-ui-patterns-and-component-catalog`; the tariff
pilot and the audience-specific invoice labels have their own specs. The tariff
pilot shipped (#1081) and this ADR was accepted on 2026-10-28; the pane
breakpoint it produced is recorded in the pilot spec §11, the dialog sizes stay
provisional until phase 4. Revised after review by
@spalinger, whose proposal introduced the in-flow pane, the pilot-first order
and the usefulness rules for labels.
