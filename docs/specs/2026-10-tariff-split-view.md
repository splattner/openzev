# Feature Spec: Tariff split view (pilot for the detail pane)

- Spec ID: SPEC-2026-10-tariff-split-view
- Status: Draft
- Scope: Major
- Type: Change
- Owners: Core maintainers
- Created: 2026-10-17
- Target Release: Phase 1 of the UI patterns rollout
- Related Issues: n/a
- Related ADRs: [0040](../adr/0040-overlay-and-disclosure-pattern-rules.md)
- Related specs: [UI patterns and component catalog](2026-10-ui-patterns-and-component-catalog.md) (§6.2 pane contract, §11 rollout), `2026-03-tariffs-and-billing-engine`, `2026-08-ui-redesign-pdf-style` §15.3, `2026-09-dynamic-tariffs`, `2026-09-percentage-tariff-bands`
- Impacted Areas: frontend, docs

---

This is a proposal; it does not describe the shipped tariff screen. The overview
hierarchy and tariff list described here **replace** the shipped Valid /
Upcoming / All tabs and the overlay detail drawer (SPEC-2026-08 §15.3); the
maintainers accept changing shipped design where it makes the screen more
consistent, clear and less cluttered. The baseline specs and the user guide are
updated with the implementation (§9). No backend behaviour changes.

The detail-pane contract (reserved layout, viewing and editing modes, narrow
behaviour, dirty guard, semantics) lives in the reference spec §6.2; this spec
applies it to tariffs and records what is specific to them. The tariff screen
is deliberately the first adopter: it validates the pattern on a hard case
before the rest of the app follows.

## 1. Problem and outcome

| Observation (commit `ecb0c962`) | Implication |
|---|---|
| `TariffDetailDrawer.tsx` is an overlay sized `clamp(720px, 60vw, 1080px)` | The list stays clickable but space is not reserved, so part of it is covered. |
| `TariffCategorySections.tsx` already shows prices, schedules, validity, notes and warnings per row | The pane adds version history, actions and, for dynamic tariffs, charts and price records; it does not repeat the row. |
| Editing varies in size: `TariffFormModal.tsx` branches during creation, an existing static-energy version can expose mainly dates and notes, rename is one field, new-version and period tasks have their own dialogs | One editing surface has to cover a one-field rename and a many-band creation. |
| `TariffsPage.tsx` stores `tariff` / `version` in the URL but uses `replace: true` on open and close; the validity filter is local state | Back does not return to the list; deep links already exist and are kept. |
| Tariff forms have no dirty-close guard; save errors are toasts or a shared banner; submit disables but fields stay editable | The reference spec §6.1 and §8.2 apply. |
| Participants and invoices share `.table-card.invoice-rows` and container-query reflow | The narrowed tariff list can reuse them. |

Outcome: a tariff is opened beside its list, inspected and edited in the same
place, and the list never disappears behind it.

## 2. Scope

### In scope

| Area | Details |
|---|---|
| Overview | Current, Upcoming, collapsed History; plain validity dates; table treatment (§4) |
| Pane | Viewing and editing in one pane; narrow behaviour; navigation (§5) |
| Editing | Create, edit, rename, schedule a price change, periods (§6) |
| Labels | Counts and badges on the tariff screen (§4) |

### Out of scope

- Billing and tariff calculation, versioning semantics, API shapes and permissions.
- The tariff overview PDF and its scope choice at download (unchanged).
- Other drawers, wizards and dialogs (later phases of the rollout).
- Billing's layout. The tooltip rule in §4 should guide it when it is next revisited.

## 3. Actors, permissions, and ZEV scope

Unchanged. A viewer reads only: no Edit, version, rename, duplicate, delete or
band controls (#761), but the same pane and the same warnings. Scope and access
changes clear the selection, the pane and any draft immediately; an obsolete
completion must not select or reopen anything (`useWriteScope`, reference spec §3).

## 4. Overview

**Files to start from:** `TariffsPage.tsx`, `TariffCategorySections.tsx/.css`,
`TariffDetailDrawer.tsx/.css`, `TariffToolbar.tsx`, the tariff form dialogs,
`useTariffCrud.ts`, `useTariffVersions.ts`. The route stays `/tariffs`; the
`queryKeys.tariffs.series(selectedZevId || undefined)` query and
`fetchTariffSeries` contract are unchanged.

- Show **Current**, then **Upcoming**, with **History** collapsed by default,
  keeping the energy / grid fees / levies / metering category order inside each.
  This replaces the `FilterTabs` Valid / Upcoming / All view (`TariffListView`).
- A series with current and future versions can appear in both sections. Each
  row shows the relevant version; in Upcoming, the nearest upcoming version
  first. History gives access to past versions even when the series has a
  current one.
- In the pane, current information comes first, then future changes, then past
  versions. An explicitly selected past or future version stays selected and is
  clearly identified. Full history and technical source detail are on demand;
  important warnings stay visible.
- Historical rows are grey but readable, with explicit historical context. They
  stay accessible and can expose permitted corrections: past does not mean
  disabled, and a genuinely disabled record or action says why.
- Plain validity dates, not rounded validity pills. No tariff, fee, band or
  version totals unless they help a concrete task (reference spec §10.1).
  Warnings beside the name stay: a gap, a failed price fetch.
- Follow the participants/invoices table treatment: sheet header, aligned
  columns, row separators, action hierarchy. The list reflows by container
  width: a table where it fits, compact stacked rows where it does not.
  Prices, units and their bands or schedules stay together; add short visible
  labels only where the values are unclear once headers disappear.
- Tooltips explain ambiguous or truncated information but are supplementary:
  essential meaning is available on touch, and explanatory interactions also
  work with the keyboard.
- Rows have a named, keyboard-accessible control that opens the pane (the name
  button, as today); row click is an extra. The tariff overview PDF's scope
  (valid or all) stays chosen at download.

## 5. The pane

### 5.1 Layout

- On a suitable desktop width, selecting a tariff opens its pane in viewing mode
  beside the list, reserving space. Both scroll independently; the heading and X
  stay reachable.
- When two usable panes do not fit, including phones around 400px, the selected
  detail takes the tariff content area and the list is hidden from the
  accessibility tree and tab order until shown again. Same screen, same detail
  body, X to return; no new route. The viewing and editing modes work at both
  widths and an active draft survives a change of layout.
- Exact widths and the breakpoint are pilot outputs, validated on a normal
  laptop and a phone. Do not require a squeezed two-pane layout.

### 5.2 Navigation

- Keep the `tariff` / `version` query parameters and unrelated parameters.
  `tariff` uses the existing `seriesKeyOf` value (ZEV and name).
- Opening detail from the list creates one history step. Switching tariff in the
  open pane or changing the displayed version replaces that step. Browser Back
  returns to the list. Viewing/editing mode adds no history entry.
- X returns to the originating list state. Direct entry has an explicit
  same-screen list fallback; never navigate to an unrelated external origin.
  Back, Forward, X and reload agree about the selection.
- Preserve filters, ordering, list scroll and selection through inspection and
  editing; closing the pane lets the list expand without losing its position. Do
  not add sorting or filter features just to satisfy this.
- Reload with a dirty form warns, then returns to the linked saved data in
  viewing mode. No draft recovery and no editing route.

## 6. Editing in the pane

- Selecting a tariff starts in viewing mode. **Edit** replaces the body with
  prefilled fields; the title and selected tariff stay recognisable. Only
  fields the API already permits are editable; immutable identity fields keep
  their restrictions.
- Rename, **Schedule price change** and period changes use the pane's focused
  editing mode, seeded from the selected record and version. **New tariff** opens
  the pane with a blank creation form. Reuse the existing form logic
  (`useTariffForms.ts`) independently of the dialog shell; there is no extra edit
  dialog.
- **Save** returns to viewing on the saved tariff or version. **Cancel** returns
  to the original viewing context, asking before discarding changed values.
  Cancelling creation restores the previous selection, or the list if there was
  none.
- The dirty guard (reference spec §6.2) covers X, Cancel, Escape, browser Back,
  navigation and selecting another tariff or version. Staying keeps the draft
  and the original selection. Confirmations use the modal manager; the pane
  itself stays non-modal.
- **Schedule price change** is the prominent task-oriented action for future
  prices; ordinary edits remain separate. Show the effective date and the
  resulting prices before submission, without a redundant confirmation step.
- After a create or a scheduled change, select the resulting tariff or version.
  Rename keeps the selection and updates the name-derived series key in the URL.
  No billing or versioning semantics change.
- **Go/no-go for creation.** Test realistic creation before committing: a simple
  fixed fee, a many-band tariff, and a dynamic tariff that needs a dynamic
  source (today `TariffFormModal` opens `DynamicSourceFormModal` over itself;
  the pane has no second dialog, so the source becomes an inline section). If a
  creation task does not fit a pane, that task alone moves to a page; it is not a
  reason to keep the overlay for everything.

## 7. Forms, saving and errors

Reference spec §8 applies: validate on submit then on correction, field errors by
the field, a persistent `Notice` for non-field failures, visible pending state
with values readable, no duplicate submission, retained form on failure. A
pending save that outlives the pane applies only to its originating scope and
editing instance.

## 8. Pilot acceptance

Use realistic data: a simple fixed fee, current plus scheduled prices, a
historical entry, a genuinely disabled action, multiple bands, and an extensive
dynamic tariff. Check ordinary laptop widths, about 400px, and the chosen layout
boundary.

| Scenario | Required observation |
|---|---|
| Overview hierarchy | Current, then Upcoming, collapsed History; correct price and version in each; no gratuitous counts |
| Historical / disabled | Grey but readable history; a separate explicit reason for true disablement |
| Wide layout | List fully visible, reflows by container width, scrolls independently of the pane |
| Narrow layout | One usable pane, X returns to the list, no horizontal overflow, no detached price, unit or schedule |
| Comprehension | Short labels only where needed; touch- and focus-accessible explanations; long translations wrap |
| Selection | Direct links and reload show the intended series and version; Back, Forward and X keep the list state |
| Editing | Prefilled fields in the same pane; Save and Cancel return to viewing, the table stays available; a layout change keeps the draft |
| Save / failure | Visible pending state, no duplicate submit or lost late edits, result selected; values and error stay on failure |
| Dirty dismissal | X, Cancel, Escape, Back, navigation and tariff/version selection are guarded; staying keeps draft and selection; reload warns; explicit discard resets |
| Scope / async | Old-scope data cleared; late completions cannot select or reopen unrelated detail or replace a newer edit; rename keeps selection |
| Creation | The three creation cases of §6 fit, or the exception is recorded |
| Keyboard | Named row controls, correct focus targets, no pane focus trap, picker Escape before parent, modal manager ownership intact |

Screenshots serve human review; browser assertions prove keyboard operation,
inertness and restoration. Add focused tests near the tariff and dialog tests
(this document does not claim they exist). Run the frontend CI commands listed
in the reference spec §12.

## 9. Documentation to update with the implementation

- `2026-03-tariffs-and-billing-engine` (screen behaviour),
  `2026-04-frontend-management-page-design` (pane, shared components),
  `2026-08-ui-redesign-pdf-style` §15.3 (the tariff list and its filter tabs),
  and `2026-03-community-and-access` if URL or history behaviour is documented
  there.
- The matching user-guide chapter and its screenshots, regenerated as a set.
- ADR 0040 moves to Accepted when the acceptance in §8 passes.

## 10. Risks

| Risk | Mitigation |
|---|---|
| The split view is cramped on a laptop | Real-width validation; one visible pane when two cannot be useful |
| Back or X loses the user's place | Test X, Back, Forward and reload; list state preserved |
| Grey history reads as disabled | Readable text, explicit context, accessible corrections; disablement explained separately |
| Creating a many-band or dynamic tariff does not fit a pane | Go/no-go in §6; page for that task only |
| A late save lands in the wrong scope | `useWriteScope`; clear on scope change |
