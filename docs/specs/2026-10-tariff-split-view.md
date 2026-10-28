# Feature Spec: Tariff split view (pilot for the detail pane)

- Spec ID: SPEC-2026-10-tariff-split-view
- Status: Implemented; ADR 0040 accepted 2026-10-28 (a screen-reader pass and forced-colours check are still open, §11)
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

This describes the tariff screen as implemented for phase 1 of the UI patterns
rollout. The overview hierarchy and the in-flow pane **replaced** the Valid /
Upcoming / All tabs and the overlay detail drawer (SPEC-2026-08 §15.3); the
baseline specs and the user guide were updated with the implementation (§9).
No backend behaviour changes. §1 records the observations the change started
from (commit `ecb0c962`); §11 records what the pilot decided.

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
- ADR 0040 moved to Accepted on 2026-10-28, with the checks listed as not yet verified in §11 still open.

## 10. Risks

| Risk | Mitigation |
|---|---|
| The split view is cramped on a laptop | Real-width validation; one visible pane when two cannot be useful |
| Back or X loses the user's place | Test X, Back, Forward and reload; list state preserved |
| Grey history reads as disabled | Readable text, explicit context, accessible corrections; disablement explained separately |
| Creating a many-band or dynamic tariff does not fit a pane | Go/no-go in §6; page for that task only |
| A late save lands in the wrong scope | `useWriteScope`; clear on scope change |

## 11. Implementation record

Values and decisions the pilot produced (reference spec §13, open question 3).

| Item | Outcome |
|---|---|
| Pane breakpoint | The list and the pane sit side by side when the **tariff content area is at least 62rem (992px) wide** (`SPLIT_MIN_REM` in `TariffsPage.tsx`, measured on the area itself by `useMinWidth`, not the viewport). Below it the pane takes the whole area. Checked with the shell's sidebar open at viewports 1440 (content 1152px: list about 640px, pane 28–34rem), 1280 (content 992px: two panes, list in card mode at about 424px), 1200 (one pane) and 400. |
| Pane width | `minmax(28rem, 34rem)` beside a flexible list. |
| Dialog sizes | Not confirmed here: the pilot removed three tariff dialogs (create/edit, version, band) rather than sizing them. The provisional `FormModal` sizes stay provisional until phase 4. |
| Table treatment | `.table-card.invoice-rows.tariff-list`: the shared sheet, header band and container behaviour. A tariff row has several bands, which the invoice row's areas do not fit, so the card reflow stays the tariff's own (below 56rem), and the shared hiding of the header is overridden so the category band stays on cards. |
| Pane navigation | Opening from the list pushes one entry marked `state.tariffPane`; X takes it back with `navigate(-1)`. A direct link has no such entry, so X removes the parameters in place. Switching tariff or version replaces the entry and keeps the marker. A link to a tariff that no longer exists clears the parameters. A renamed tariff is found by the version in the URL, which the page then rewrites to the new name. |
| Escape | In the pane, Escape cancels an open form (guarded) and otherwise closes the pane. An event already handled by a menu or picker (`defaultPrevented`) is left alone. X always closes the pane. |
| Dirty guard | `useDraftGuard`: pane actions (`run`), the router blocker for Back/Forward and links, `beforeunload` for reload. A save in flight counts as unsaved and the prompt says it may still complete. Scope, permission and account changes clear the selection and every draft without asking. Phase 2 moved the pane-independent part into `components/useDraftGuard.ts` (`useDraftConfirm`, `useRouterDraftBlock`), which `FormModal` also uses; `useDraftGuard` stays the pane's combination of both. |
| Saving | Each form is a `<form>` seeded once on mount; a refetch behind it does not overwrite the draft. While saving the fields are in a disabled `fieldset` (`display: contents`), the form is `aria-busy` and the button says "Saving…". A failure stays in the form as a `Notice` (the toast is no longer used for it); validation problems show next to the field in the user's language. A completion applies only to its scope **and** editing session (`session` counter in `useTariffCrud` / `useTariffVersions`); the result is selected only after the series refetch has landed (`invalidateTariffQueries` now resolves when it has). |
| After a save | Create and duplicate select the new tariff (a history step when no tariff was open), schedule price change and rename keep the pane on the saved version, an edit stays on its version; focus moves to the pane title. Cancel returns focus to the control that opened the form (`data-action-key`). |
| Go/no-go for creation | **Go, with one case not exercised.** A simple fixed fee was created, renamed and deleted in the pane on the dev stack; the dynamic source form opened and was dirty-guarded as an inline section of the tariff form (`DynamicSourceForm`, the body of the former dialog, shared with the admin page), outside the tariff `<form>` so forms do not nest; a many-band tariff was created as one tariff and its bands added through the band form in the pane, which was opened but not run with many bands. Since #1113 the create form takes the bands of an energy tariff itself (see tariffs-and-billing-engine §3.2e). No task moved to a page. |
| Duplicate | The spec did not name it; it follows rule A and is a pane form like rename and schedule price change. |
| Pane content | The tariff price history chart sits in a lazily mounted disclosure (the shared `Disclosure`, `lazy`, since phase 2). A dynamic source's price chart is visible by default (only its statistics and interval table are in a lazy disclosure), see the dynamic-tariffs spec §10.4. Counts and validity pills are gone from the pane. |
| Pane layout | The pane has two levels. Header actions are tariff-level and visible: Schedule price change, Rename, Duplicate. Under them every version in force or scheduled has its own card (`versionCard`, `.tariff-version-card`), the one in force first, nearest scheduled next. A card leads with its status badge (Current / Upcoming, replacing the "Viewing an …" banner) and the validity window in muted text, then its own labelled **Edit**. The body holds the price of a tariff without bands, the dynamic source or the bands (a pencil per band, a quiet **Add Period** under them), and the band coverage notice. Notes appear only when they differ from the notes of the version the overview row shows (`listedVersion`). The version the list pointed at (`version` parameter) gets an outline when there are several cards. |
| Scheduled cards | A scheduled version is **folded** to a line by default: a toggle button (`aria-expanded`, `aria-controls`) over status and window, then its price summary, the relative change against the version before it (`deltaSummary`) and an **Hours without a band** issue text when `bandCoverage` finds uncovered hours, so a problem is not hidden by the fold. It is open by default when it is the shown version; opening or folding is remembered per version id for the life of the pane. The current version is never folded. |
| History | `History` (no count) is a disclosure under the cards, present only when versions have ended. It holds the price-history chart (when the series has more than one version) and a list of the ended versions (window and price, `aria-pressed`); picking one shows its card, marked Ended, below the list. It opens by itself when an ended version is the shown one or nothing is in force or scheduled. |
| Change against the previous version | `priceDelta.ts`: `versionDeltas` compares each band of a scheduled version with the band of the version before it that applies to the same type, label, hours, weekdays and months (a band with no counterpart gets none), or the fixed fee of a flat-fee tariff; percentage tariffs compare points; a dynamic version has none. `formatDelta` renders `+0.020 (+6.8 %)` (the amount, then the relative change; percentage points for a percentage tariff) and `deltaSummary` the relative figures only, in band order, `±0` for an unchanged band, `null` when nothing moved. Shown beside the band price in the card and, as a summary, in the folded card and in the overview row. A visually hidden prefix names it for screen readers. |
| Deleting | Version and band **delete** are not on the cards. `TariffForm` (editing a version) and `TariffPeriodForm` (editing a band) take an `onDelete` and show a danger button below the fields, which asks through the shared confirmation; `useTariffCrud` closes the form when the deleted record is the one being edited. The earlier per-row `ActionMenu` and icon-only band delete are gone; `ActionMenu`'s optional `actionKey` stays. |
| Dynamic source | `DynamicSourceSummary` shows the label, status badges, the admin link (admins only) and the last successful fetch up front; URL, protocol/type/product, stored coverage and platform-wide usage are in a "Source details" disclosure. A failed fetch's error stays visible, and so does a notice naming past dates without a price. |
| Overview rows | One row per series. `tariffOverview` puts a series in **Current** when a version is in force (the row carries `upcomingVersion`, the nearest scheduled one), else in **Upcoming** (nearest scheduled), else in **History** (most recently ended). The row's validity cell links to the next version: `nextChange` compares the two versions' rate lines; the same bands (same `applies` text and unit) give `From {date}: {prices} {unit}`, different bands give "Prices and schedule change from {date}", and a next version with no prices to show gives "New version from {date}". When the prices are comparable the line adds the relative change per price in brackets (`From 01.11.2026: 0.290 / 0.220 per kWh (−1.7 % / −2.2 %)`, `deltaSummary`), left out when nothing moved. The row is highlighted for either version. |
| Band coverage | `bandCoverage` (`bandCoverage.ts`) mirrors `tariffs.periods.resolve_band` for the hours of a version's bands: month first, flat prices its months outright, a windowed band needs both ends and its weekday, windows are `[start, end)` and wrap past midnight (equal ends are the whole day), a non-flat band without a window is the catch-all that prices every hour on its weekdays no windowed band matches (not counted as an overlap with them; two on one month and day count as one), and hours still unmatched are priced by the first band of the season in model order (type, start, id). It reports uncovered stretches (months, weekdays, hours), the fallback band and overlaps, and for a version with an end date only checks the month/weekday pairs inside it. Shown as **Hours without a band** issue text (`IssueText`) on current and upcoming rows, as a warning under the bands in the pane, and as a live preview in the band form (`showCovered`; hidden while exactly one of the two times is set; both empty means "all other hours"). No API change. |
| Energy type icon | The second line under a tariff name (its energy type as text) is replaced by `TariffTypeIcon` before the name: a plug for grid, a solar panel for local, an arrow out of a box for feed-in, with the type name as `aria-label` and tooltip (`role="img"`). A tariff without an energy type (fees) has no icon. The detail pane's meta line still says it in words. |
| Header | The page actions (import, overview PDF, New tariff) moved from a toolbar card into the page header, since the toolbar only held the tabs besides them. |

Browser checks of the acceptance table (laptop and phone widths, navigation,
dirty guard, create/rename/delete round trip) were run by hand against the dev
stack. The draft guard, pane, overview, write scope, price change and band
coverage logic are covered by `tariff-draft-guard.test.ts`,
`tariff-detail-pane.test.ts`, `tariff-overview-list.test.ts`,
`tariff-write-scope.test.ts`, `tariff-price-delta.test.ts` and
`tariff-band-coverage.test.ts` (jsdom). The Playwright specs
`tariff-presentation.spec.ts` and `hub-workflow-links.spec.ts` run in a real
browser; `tariff-presentation.spec.ts` asserts, against mocked data:

- at 400px the list is `hidden` while the pane is open, no Tab stop lands in it,
  it is not in the accessibility tree, and X brings it back and clears the URL;
- the pane is not modal: nothing is `inert`, `<body>` is not scroll-locked,
  there is no `aria-modal`, and Tab leaves the pane;
- Escape on an untouched form and Cancel return to viewing with focus back on
  the control that opened the form; on a dirty form Escape asks, Keep editing
  keeps the draft, Discard returns to viewing, and a further Escape closes the
  pane.

Not yet verified: a screen-reader pass, forced-colours mode and long translated
labels beyond the existing German and French narrow-band checks.
