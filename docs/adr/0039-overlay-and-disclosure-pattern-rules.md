# ADR 0039: Choose containers by task; validate the tariff split view first

- Status: Proposed
- Date: 2026-10-15
- Updated: 2026-10-16
- Related specs: `2026-10-ui-patterns-and-component-catalog` (reference), `2026-04-frontend-management-page-design` (reference), `2026-08-ui-redesign-pdf-style` (baseline)
- Related ADRs: 0032 (one visual language), 0014 (print-parity design system), 0040 (selective component reuse)

## Context

The UI baseline describes visual treatment, and the management-page reference
describes existing primitives. Container choice still needs guidance grounded
in real tasks. The primary audience is an occasional community manager;
consistency is useful when it improves understanding and preserves context.

The tariff list already shows pricing and schedules, while its large overlay
covers part of that list. Tariff forms vary: rename is one field, ordinary
version editing can be mainly dates/notes, and creation or many-band work can
be larger. Neither a multi-step label nor several sections alone proves that
a task needs a routed page.

## Decision

1. **Use the simplest usable surface.** Records with a detail panel are edited
   in that panel; standalone short tasks can use dialogs. Secondary content
   uses disclosure/row expansion; substantial workflows need a page only when
   fit, navigation or recovery requirements justify it. Equivalent tasks
   should behave consistently, with explained exceptions.
2. **Validate tariffs first.** Desktop tariffs use a pane with viewing/editing
   modes that reserves space beside the list. The list follows the existing
   participants/invoices table treatment and reflows by available width.
   List and detail scroll independently; neither covers the other.
3. **Use the same detail on narrow screens.** When both panes cannot be useful,
   details replace the visible list within the tariff screen. X and browser
   Back restore the list state. Opening detail adds one history step;
   record/version changes within the pane replace that step. Deep links remain supported,
   with an explicit same-screen fallback for direct entry.
4. **View and edit in the same pane.** Selecting a tariff starts in viewing
   mode. Edit shows prefilled fields in that body; Save returns to the saved
   result and Cancel returns to the previous viewing context. New tariff
   starts with a blank form; scheduling, rename and period changes use the
   same panel's focused forms. Existing API field restrictions remain.
   Before closing, navigating or selecting another record/version would
   discard unsaved work, confirm discard. The existing modal manager owns
   confirmation focus and inertness. No extra editing dialog or blanket
   tariff create/edit page migration is required.
5. **Present useful information first.** Current tariffs precede upcoming
   prices; history is collapsed and visually historical. Important warnings
   stay visible. Counts, statuses and decorations need a useful audience/task.
6. **Adopt only after validation.** Pilot screenshots and behavior checks on
   laptops/phones precede generalization. Other drawers and wizards keep
   their existing behavior until separately assessed. Shared size choices
   preserve compact dialogs; exact values require visual validation.

The detailed interaction, label, form and acceptance rules live in the
reference spec (§5–§12). This ADR remains Proposed until pilot validation;
this branch implements no UI changes.

## Consequences

Positive:
- The list remains useful during inspection, with simple return navigation.
- Viewing and editing share the same place, without an extra edit dialog.
- The pilot tests the proposed rules before imposing migration costs elsewhere.

Trade-offs:
- Reserved panes need careful responsive layout and navigation-state handling.
- Non-modal editing needs discard protection before selection changes as well
  as dismissal/navigation. Validation and safe async completion still apply.
- Existing screens remain varied during gradual adoption.

## Alternatives considered

1. **Keep a wide overlay over the tariff list.** It leaves only part of the
   list visible and weakens the overview the panel is meant to preserve.
2. **Create tariff detail routes at every narrow breakpoint and route all
   tariff editors.** Adds navigation/migration work without demonstrated
   benefit for small tasks. A page remains an option for genuinely extensive work.
3. **Use a separate edit dialog over a read-only panel.** Keeps viewing simple,
   but adds another surface. Prefilled editing in the same pane better fits
   the desired straightforward tariff workflow.
4. **Normalize every screen before validating.** Code uniformity alone does
   not establish usability and commits unrelated workflows prematurely.
