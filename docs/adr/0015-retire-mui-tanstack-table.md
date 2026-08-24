# ADR 0015: Retire MUI — TanStack Table and full Mantine consolidation

- Status: Accepted
- Date: 2026-08-23
- Related specs: `2026-08-ui-redesign-pdf-style` (Phase 5), `2026-04-frontend-management-page-design`
- Related ADRs: 0014, 0007

## Context

ADR 0014 committed the redesign to ending with **one styling system**. After
Phases 1–4 the frontend still carried four MUI surfaces:

* `@mui/x-data-grid` on `ImportsPage` (read-only import log) and
  `AdminInvoicesPage` (sortable/filterable invoice list),
* `Menu`/`MenuItem` inside `ActionMenu` (the app-wide overflow-actions control),
* `Drawer` inside `AuditEventDrawer`,
* `Switch` in `MeteringPointFormModal` and `AdminSystemSettingsPage`, plus
  `Tabs` on the latter,
* `@mui/x-date-pickers` had already been removed in Phase 2.

MUI brought its own emotion runtime (`@emotion/react`, `@emotion/styled`),
a second theming model, `sx` prop styling that bypassed the token layer, and a
~394 KB vendor chunk (`vendor-mui`). Every remaining MUI widget duplicated an
equivalent Mantine primitive already shipped and themed by the generated brand
theme.

## Decision

1. **TanStack Table replaces MUI DataGrid.** A small shared
   `frontend/src/components/DataTable.tsx` (TanStack Table v8) implements the
   operational table contract from SPEC §7.4: sticky token-styled header,
   36px row rhythm, hover, right-aligned tabular numerics via `td.numeric`,
   sortable headers, column filters, client-side pagination with page-size
   options, loading/empty states.
   * *ImportsPage*: sorting/filters stay disabled (as before); custom protocol/delete
     action cells ported 1:1; pagination parity (25 default, 10/25/50/100).
   * *AdminInvoicesPage*: header-click sorting replaces the column menus; the
     DataGrid quick filter becomes an explicit search input (number/ZEV/participant)
     plus a status dropdown feeding TanStack's `equalsString` column filter —
     same capabilities, visible controls instead of hidden menus. Initial
     sort `period_sort desc`, row identity, and empty/loading states preserved.
2. **Mantine replaces the last MUI widgets.** `ActionMenu` → Mantine `Menu`
   (`Menu.Label`/`Menu.Divider`/danger coloring; trigger stays the shared
   `.button` classes). `AuditEventDrawer` → Mantine `Drawer` (right position,
   non-blocking root preserving the click-through behaviour of the old
   `hideBackdrop` + `pointerEvents` arrangement). `Switch` and `Tabs` →
   Mantine equivalents; the settings page keeps its URL-driven tab state
   (`?tab=`) by mapping Mantine's `onChange` through the existing validator.
3. **Dependencies removed:** `@mui/material`, `@mui/x-data-grid`,
   `@emotion/react`, `@emotion/styled`; bridge files `lib/dataGridLocale.ts`
   and `lib/dataGridTheme.ts` deleted (dataGridTheme never shipped beyond the
   Phase 1 plan — the token sweep made it unnecessary). Sole new dependency:
   `@tanstack/react-table` v8 (pinned to ^8; v9 is a different API).
4. **No data-contract changes.** All ports are presentation-only: same query
   keys, same mutations, same submitted fields. The date contract of ADR 0007 is
   untouched (Phase 2 already moved pickers to civil-date strings).

## Alternatives considered

* **Keep MUI DataGrid, retire only the widgets.** Smallest diff, but it keeps
  the emotion runtime, the second theming model and the `sx` escape hatch alive
  for two pages — the "one styling system" goal of ADR 0014 would remain
  unmet, and every future table would face the same two-system choice again.
* **Mantine's own table ecosystem (`@mantine/react-table`).** One vendor for
  everything, but it is a community wrapper (Mantine v7 era, not part of core)
  bundling TanStack Table underneath anyway — an extra dependency layer with
  its own release cadence, for styling we already express in the shared
  `.data-table` CSS contract.
* **AG Grid community.** Batteries-included (grouping, pivoting, SSR modes),
  but far heavier than the two operational lists need, MIT-licensed core with
  commercial-flavoured ergonomics (theme system separate from ours), and its
  theming would reintroduce a second design surface — the exact problem being
  retired.
* **Hand-rolled table on plain `<table>` markup.** No new dependency at all,
  but re-implements sorting/filter/pagination state machines that TanStack
  Table already provides tested and headless.

TanStack Table v8 won on being headless (styling stays 100% in the token /
`.data-table` contract), unopinionated about markup, already TypeScript-first,
and the only addition to the dependency tree — the port cost is bounded by the
two consuming pages.

## Consequences

**Positive**

* Zero `@mui/*`/`@emotion/*` packages; one date system (Mantine), one overlay/
  menu system (Mantine), one styling system (tokens + hand-rolled contracts).
* The MUI vendor chunk disappears from the bundle; emotion's runtime CSS-in-JS
  overhead is gone from render paths that used `sx`.
* Tables now share one CSS contract (`.data-table`) with plain tables, so a
  design change lands once in `index.css`.

**Negative / risks**

* Column-filter menus are replaced by explicit toolbar controls — power users
  lose per-column menu filtering on AdminInvoices but gain discoverable inputs;
  accepted for an internal admin surface.
* TanStack Table is headless: accessibility semantics (aria-sort etc.) must be
  maintained by us rather than inherited from MUI. Follow-up hardening may add
  `aria-sort` to sortable headers.

## Verification

* `npm run build`, `npm run test:unit`, `npm run lint` green.
* Backend suite unaffected (no API change): full pytest run green.
* Parity checklist per ported page: sorting (AdminInvoices), filtering
  (AdminInvoices search + status), pagination + page-size (both), row identity,
  locale via i18n keys (both), loading/empty states (both), custom cell actions
  (both).
