# Phase 5 (TEMP placeholder) — Dashboard extraction + slim-down

> TEMP doc. Delete when phase-5 implementation lands. Tracks
> `spalinger/nav-phase5-dashboard-extraction` on `upstream/main`
> `24b77c11` (phase 4 landed as #737 — Swiss number formatting at display
> boundaries).

## Baseline (upstream/main 2026-09-18)

- `frontend/src/pages/DashboardPage.tsx` — 502 LOC on `24b77c11`; owns both
  roles in one file (ZEV-owner + participant), imports `recharts` directly.
  Uses `formatKwh`/`formatPercent` at display boundaries (`frontend/src/lib/numbers.ts`),
  `dashboardFormatting`/`dashboardTooltips` for tick/tooltip helpers, and
  `chartTokens`/`chartTheme` for colours/ticks (landed in #737).
- `frontend/src/components/dashboard/OpenInvoicesCard.tsx` — already extracted
  (manager exception list, queried via `queryKeys.invoices.list(zevId, status)`),
  not yet wired into `DashboardPage` owner variant.
- `frontend/src/components/EnergyFlowChart.tsx` — Sankey; props
  `{ totals, participantStats, highlightParticipantId }`, consumed by both
  roles.
- Routes: owner dashboard at `/` (when `admin`/`zev_owner`, with `useManagedZev`);
  participant dashboard also at `/`; metering drill-down lives at
  `/metering/chart`; billing list at `/billing/invoices`.

## Goal

Slim `DashboardPage` to ≤ ~300 LOC and remove duplicated analytics blocks
without changing KPI, flow or period semantics.

## Scope

- New shared subcomponents in `frontend/src/components/dashboard/`:
  - `EnergyFlowCard.tsx` — thin wrapper around `EnergyFlowChart` with heading
    (`pages.dashboard.energyFlow.title` + optional `— <ZEV name>`), empty
    guard (`pages.dashboard.noData`), and `highlightParticipantId` pass-through.
    Used by **both** variants; renders `null` when `participant_stats` is empty
    (matches current owner `length > 0` guard and participant
    `zev_participant_stats.length > 0` guard).
  - `BalanceChart.tsx` — owner-only balance chart. Props:
    `{ data: OwnerChartRow[], formatBucketLabel, formatBucketTooltipLabel }`
    where `OwnerChartRow` is `timeline` enriched with
    `locally_consumed / locally_produced / self_consumption_rate`.
    Renders the paired consumption (`BarChart` stacked `locally_consumed` +
    `imported_kwh`) and production (`ComposedChart` stacked
    `locally_produced` + `exported_kwh` + `Line self_consumption_rate`) that
    currently sit in `DashboardPage.tsx:261–360` (approx). Owns its own
    `CHART_*` imports; no data-fetching inside.
- `DashboardPage.tsx` changes (owner variant):
  - Keep: KPI row (5 `StatCard`s, always ZEV-wide), `EnergyFlowCard`,
    `BalanceChart`, scope eyebrows (`selectedZevName` / `participantScopeName`),
    shared period/resolution selects (`PeriodSelector` + bucket `day|hour|month`),
    `PageSkeleton`/`error-banner` guards, ZEV scoping (`isZevScopedRole`,
    `selectedZevId`, `selectedParticipantId` in `queryKeys.metering.dashboardSummary`).
  - Drop: per-participant table (`pages.dashboard.perParticipant`, ~392–439)
    and owner hourly drill-down (`hourlyProfile` when `selectedParticipantId`,
    BarChart `from_zev_kwh`/`from_grid_kwh`). Replace each with a link to
    `/metering/chart` (existing metering drill-down), preserving the
    participant filter via query param where trivial.
  - No new data-fetching topology: the one `dashboardSummary` + conditional
    `hourlyProfile` (owner only when a participant is selected; always for
    participant when `hourly_profile` present) stays in the page.
- Participant variant: untouched except for consuming `EnergyFlowCard`
  (replacing the inline `EnergyFlowChart` block). Keeps its own
  consumption-split chart (`participantTimeline`), hourly profile
  (`hourlyProfileData`), and invoices table (`/me/invoices` role-scoped
  `fetchInvoices` filtered to `approved|sent|paid` with `pdf_url`).

## Out of scope

- `StatCard`, `PeriodSelector`, `PageSkeleton`, `EnergyFlowChart` internals,
  API shapes (`fetchMeteringDashboardSummary`, `fetchHourlyProfile`),
  `queryKeys`, billing/period helpers, or i18n keys.
- Wiring `OpenInvoicesCard` into the owner dashboard (exception list stays in
  `/billing` for this slice; follow-up can compose it in `DashboardPage` once
  `≤ 300` is proven).
- Any backend or spec change beyond the follow-up note below.

## Acceptance

- `DashboardPage.tsx ≤ ~300 LOC` post-extract; no recharts duplication across
  owner/participant variants.
- `npm run test:unit` + `npm run build` green (`frontend/`). Existing
  dashboard helpers (`lib/numbers`, `lib/dashboardFormatting`,
  `lib/dashboardTooltips`) covered by `numbers.test.ts` /
  `dashboard-formatting.test.ts` / `dashboard-tooltips.test.ts`; no new unit
  tests required unless a helper is added.
- `02-dashboard*.png` screenshots re-captured via `frontend/screenshots.config.ts`
  (`SCREENSHOT_BASE_URL=http://localhost:5173 SCREENSHOT_API_URL=http://localhost:8001/api/v1`),
  folded with `--fixup` + autosquash (established pattern).
- On merge, record the decision to keep the pushed nav stack (reject review
  §3 IA) in `docs/specs/2026-03-community-and-access.md` (navigation-regroup
  history lives there; there is no `2026-09-navigation-regroup.md`).

## Follow-up note

Phase-3 nav regroup is `shipped` in `ROADMAP.md`. Phase-5 does not reopen
its IA; this TEMP only covers dashboard slim-down.
