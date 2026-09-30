# Feature Spec: Annual ZEV report

- Spec ID: SPEC-2026-annual-zev-report
- Status: Completed
- Scope: Minor
- Type: Feature
- Owners: Sebastian Plattner
- Created: 2026-09-30
- Target Release: 1.21.0
- Related Issues: —
- Related ADRs: [0013](../adr/0013-shared-allocation-service.md) (readings attributed at their timestamp), [0017](../adr/0017-async-export-jobs.md) (async exports), [0026](../adr/0026-swiss-civil-time-for-billing.md) (Swiss civil time)
- Impacted Areas: backend | frontend | docs

---

## 1. Problem and outcome

The owner/admin Reports page (`/reports`) offered one download (the tax
overview) and a "Reports are coming soon" placeholder promising
self-consumption over time, energy balance, and participant benefit. The
whole-ZEV annual-statement ZIP, the other yearly document, sat on a separate
Billing tab (`/billing/statements`) that repeated the Reports page's year
selector and empty states.

The pieces existed but were scattered. **Energy balance** (`/dashboard`) shows
rates for one billing period at a time, never a year or a trend. Each
participant's annual statement PDF computes their savings, but nobody sees the
ZEV-wide picture.

**Outcome:** for the selected ZEV and year, `/reports` shows

1. the year's key figures: self-consumption rate, self-sufficiency rate,
   production, consumption, and total participant savings, with the previous
   year's rates for comparison;
2. both rates month by month, with the previous year as dashed lines;
3. a table of each participant's consumption, ZEV coverage, and savings;

followed by **Annual documents**: the tax overview PDF and the
annual-statement ZIP, which moved here from Billing.

Nothing is computed a new way. Energy figures come from the Energy balance
analytics, and savings from the annual statement's calculation, so the report
agrees with both.

## 2. Scope

### In scope

| Area | Details |
|---|---|
| Backend — analytics | `metering/analytics.py`: ZEV-wide balance extracted from `owner_dashboard_summary` into `_zev_balance(base)`; new public `zev_balance_timeline(qs, trunc_fn)` |
| Backend — report | New `invoices/annual_report.py` with `build_annual_report(zev, year)` |
| Backend — savings | `invoices/annual_statement.py`: `_compute_savings` renamed to public `compute_savings` (behaviour unchanged) |
| Backend — API | `AnnualReportView` in `invoices/views_reports.py`, `GET /api/v1/invoices/invoices/annual-report/` |
| Frontend — report | New `features/reports/AnnualReportSection.tsx` on the owner/admin branch of `ReportsPage` |
| Frontend — move | `AnnualStatementsExportCard` moved from the Billing hub to `ReportsPage`; `BillingStatementsPage.tsx` deleted; `/billing/statements` → alias to `/reports` |
| Docs | User guide chapter 09 and 01; route tables in the community-and-access, invoice-lifecycle, and UI-redesign specs |

### Out of scope

- A PDF version of the report (possible follow-up; would reuse the shared PDF design base).
- A participant-facing version. Participants already get their own savings on their annual statement.
- Caching the report. It is computed on request (see §8).
- Exposing the report through the MCP server.

## 3. Actors, permissions, and ZEV scope

| Actor | Capability |
|---|---|
| `admin` | Any ZEV |
| `zev_owner` | ZEVs they own (`zev.owner == request.user`) |
| `participant` | None (`403`). Their `/reports` branch is unchanged |
| anonymous | `401` |

- Backend: `permission_classes = [IsAuthenticated, IsZevOwnerOrAdmin]`, then
  `_get_authorised_zev(request, zev_id)` (shared with the other report views):
  unknown or malformed id → `404 {"error": "ZEV not found."}`, a ZEV owned by
  someone else → `403 {"error": "Permission denied."}`.
- Frontend: `/reports` stays open to any authenticated user. The report and
  both document cards render only on the `admin`/`zev_owner` branch with a
  valid selected ZEV (`hasValidZev`). Otherwise `ReportsEmptyState` shows, as
  before.
- `/billing/statements` is now `<AliasNavigate to="/reports" />` without a
  `ProtectedRoute`. A participant following an old link lands on their own
  Reports branch.

## 4. Data model

No model or migration changes.

## 5. API contracts

| Endpoint | Method | Permission | Behaviour |
|---|---|---|---|
| `/api/v1/invoices/invoices/annual-report/` | GET | `IsAuthenticated`, `IsZevOwnerOrAdmin` + `_get_authorised_zev` | JSON annual report for `zev_id` and `year` |

URL name `invoice-annual-report`. It is registered in `invoices/urls.py`'s
`extracted_urlpatterns` ahead of the router, like the other report endpoints.

**Query parameters** (both required):

| Param | Validation | Error |
|---|---|---|
| `year` | `_parse_year`: present, integer, `MINYEAR..MAXYEAR-1`; additionally `!= MINYEAR` because `year - 1` is read | `400 {"error": "year is required."}` / `"year must be a number."` / `"year must be between …"` |
| `zev_id` | present | `400 {"error": "zev_id is required."}` |

Validation order: year, then zev_id, then ZEV lookup and authorisation.

**Response `200`** (`build_annual_report(zev, year)`):

```json
{
  "zev_id": "uuid",
  "year": 2025,
  "has_data": true,
  "totals": { /* Balance */ },
  "previous_totals": { /* Balance */ } | null,
  "months": [ /* 12 × Month, January first */ ],
  "participants": [ /* Participant, sorted by name (case-insensitive) */ ],
  "savings_total_chf": "504.30" | null
}
```

`Balance`: `produced_kwh`, `consumed_kwh`, `imported_kwh`, `exported_kwh`,
`self_consumed_kwh` (floats, kWh), `self_consumption_rate`,
`self_sufficiency_rate` (float percent rounded to one decimal, or `null` when
the denominator is `<= 0`).

`Month`: `Balance` + `month` (1–12) + `previous_self_consumption_rate`,
`previous_self_sufficiency_rate` (`null` when the previous year has no data for
that month). A month without readings has zero kWh and `null` rates.

`Participant`: `participant_id`, `participant_name`, `consumed_kwh`,
`produced_kwh`, `from_zev_kwh`, `from_grid_kwh` (floats),
`self_sufficiency_rate` (`from_zev_kwh / consumed_kwh`, percent, or `null`),
`savings` (object or `null`, see below).

### Definitions

- `self_consumed_kwh = max(produced_kwh − exported_kwh, 0)`
- `self_consumption_rate = self_consumed / produced × 100`: the share of the
  ZEV's production used inside the ZEV.
- `self_sufficiency_rate = self_consumed / consumed × 100`: the share of the
  ZEV's consumption covered by the ZEV.

These are the Energy balance page's definitions (`DashboardPage`
`ownerSelfConsumption` / `fromZevRate`). Import and export are netted per
timestamp, then summed (`_zev_balance`).

### How the figures are computed

- **Readings**: `MeterReading` of the ZEV's metering points with
  `period_start_dt(Jan 1) <= timestamp < period_end_exclusive_dt(Dec 31)`, the
  civil year in `Europe/Zurich` (ADR 0026). A reading at local midnight on
  1 January belongs to the new year.
- **Current year**: `owner_dashboard_summary(readings, TruncMonth(tz=business_tz()), None)`.
  `zev_totals` → `totals`, `timeline` → months (bucket ISO string, month =
  characters 5–6), `participant_stats` → participant energy columns. Readings
  are attributed at their timestamp, and community metering points by
  allocation weight (ADR 0013), exactly as on the dashboard.
- **Previous year**: `zev_balance_timeline(previous_readings, trunc)`, the
  ZEV-wide half only, and only if `previous_readings.exists()`. Otherwise
  `previous_totals` is `null`.
- **`has_data`**: `readings.exists()` for the selected year.
- **Savings**: invoices of the ZEV with `period_start >= Jan 1`,
  `period_end <= Dec 31`, excluding `CANCELLED`, grouped by participant, each
  group passed to `compute_savings` (the annual statement's function, same
  invoice filter). That function returns `null` unless local and grid kWh and
  CHF are all positive and the average local rate is below the average grid
  rate. Otherwise it returns strings:
  `{local_kwh, local_chf, local_rp, grid_rp, hypothetical_chf, saved_chf}`,
  where `hypothetical_chf = local_kwh × grid_rp / 100` and
  `saved_chf = hypothetical_chf − local_chf`.
- **Participants**: everyone in `participant_stats`, plus anyone with savings
  but no readings that year (still a participant of the ZEV), with zero energy
  and `null` rate.
- **`savings_total_chf`**: sum of `saved_chf` over rows with savings, two
  decimals, or `null` when no row has savings.

## 6. Async and integration behavior

None. The report is synchronous. The annual-statement ZIP keeps its async
export-job flow (ADR 0017); only its location in the UI changed.

## 7. Frontend

### 7.1 ReportsPage (owner/admin branch)

**File:** `frontend/src/pages/ReportsPage.tsx`, route `/reports`.

Order when `isZevScopedRole && hasValidZev`:

1. Year `<select>` (last 5 years, default last year), disabled while the tax
   overview downloads or the ZIP card reports busy (`zipBusy` via
   `onBusyChange`).
2. `<AnnualReportSection zevId={selectedZevId} year={selectedYear} />`
3. `<h3>{t('pages.reports.documentsTitle')}</h3>` and a `grid grid-2` holding
   the tax overview `YearDownloadCard` and `AnnualStatementsExportCard`.

The `pages.reports.ownerComing` placeholder card and its keys are gone.

### 7.2 AnnualReportSection

**File:** `frontend/src/features/reports/AnnualReportSection.tsx`

- Query: `useQuery({ queryKey: queryKeys.invoices.annualReport(zevId, year), queryFn: () => fetchAnnualReport({ zev_id: zevId, year }) })`
- Pending: `PageSkeleton variant="cardList"`. Error: card with
  `role="alert"` and `pages.reports.annualReport.error`. `has_data === false`:
  card with the title and `annualReport.noData` (the document cards below stay
  usable).
- `AnnualReportKpis`: a `.kpi-row` of five `StatCard`s. The accent card is
  self-consumption rate, then self-sufficiency rate, production, consumption,
  and savings (`formatChf`, hint `hints.savings`). The two rate cards take
  `hints.previousYear` (`{{year}}: {{rate}}`) when `previous_totals` has that
  rate.
- `AnnualTrendCard`: Recharts `LineChart`, x = month short name
  (`Intl.DateTimeFormat(i18n.language, {month: 'short'})`), y = 0–100 %.
  Current-year lines are `CHART_LOCAL` (self-consumption) and
  `FLOW_LOCAL_CONS` (self-sufficiency). Previous-year lines appear only when
  `previous_totals` is set: same colours, `strokeDasharray="5 4"`, opacity
  0.6, no dots. Null months leave gaps.
- `ParticipantSavingsCard`: a `table.participant-table.participant-table--static`
  inside `.table-scroll`, with columns participant, consumption, from ZEV,
  self-sufficiency, ZEV electricity cost (`savings.local_chf`), cost at grid
  rate (`savings.hypothetical_chf`), savings (`savings.saved_chf`). Missing
  values show `—`. A `tfoot` total row appears when `savings_total_chf` is
  set, followed by an explanatory note (`participants.note`).
- kWh is shown whole (`formatKwh(v, {maxDecimals: 0})` + ` kWh`), percentages
  with `formatPercent`, money with `formatChf`.

CSS (`index.css`): `.participant-table--static tbody tr { cursor: default }`
and `.participant-table tfoot td` (bold, top border).

### 7.3 Billing hub

`BillingHubPage` has two tabs, `invoices` and `emails`
(`BillingTab = 'invoices' | 'emails'`). `pages.billingHub.tabs.statements` has
been removed and `pages.billingHub.description` reworded in all four locales.

### TypeScript types

**File:** `frontend/src/types/api.ts`

```typescript
export interface AnnualReportBalance {
    produced_kwh: number
    consumed_kwh: number
    imported_kwh: number
    exported_kwh: number
    self_consumed_kwh: number
    self_consumption_rate: number | null
    self_sufficiency_rate: number | null
}

export interface AnnualReportMonth extends AnnualReportBalance {
    month: number
    previous_self_consumption_rate: number | null
    previous_self_sufficiency_rate: number | null
}

export interface AnnualReportSavings {
    local_kwh: string
    local_chf: string
    local_rp: string
    grid_rp: string
    hypothetical_chf: string
    saved_chf: string
}

export interface AnnualReportParticipant {
    participant_id: string
    participant_name: string
    consumed_kwh: number
    produced_kwh: number
    from_zev_kwh: number
    from_grid_kwh: number
    self_sufficiency_rate: number | null
    savings: AnnualReportSavings | null
}

export interface AnnualReport {
    zev_id: string
    year: number
    has_data: boolean
    totals: AnnualReportBalance
    previous_totals: AnnualReportBalance | null
    months: AnnualReportMonth[]
    participants: AnnualReportParticipant[]
    savings_total_chf: string | null
}
```

### API client functions

**File:** `frontend/src/lib/api/invoices.ts`

| Function | Method | Endpoint |
|---|---|---|
| `fetchAnnualReport({zev_id, year})` | GET | `/invoices/invoices/annual-report/` |

Query key: `queryKeys.invoices.annualReport(zevId, year)` →
`['invoices', 'annual-report', zevId, year]`.

### i18n

All four locales, under `pages.reports`: `documentsTitle`, and
`annualReport.{title, error, noData}`,
`annualReport.stats.{selfConsumptionRate, selfSufficiencyRate, produced, consumed, savings}`,
`annualReport.hints.{previousYear, savings}`,
`annualReport.trend.{title, description, selfConsumption, selfSufficiency}`,
`annualReport.participants.{title, description, empty, total, note}`,
`annualReport.col.{participant, consumption, fromZev, selfSufficiency, localCost, gridCost, savings}`.

## 8. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Response time: a year of 15-minute readings goes through the per-timestamp dashboard pass (≈3.7 s for the demo ZEV) | Medium | Previous year uses only the ZEV-wide pass; skeleton while loading; TanStack Query caches per ZEV/year. Caching or pre-aggregation is a follow-up if real ZEVs are slower |
| Savings disagree with the statements | Medium | Same function (`compute_savings`) and invoice filter as the annual statement; test asserts equality |
| Rates disagree with Energy balance | Low | Same analytics function and rate definitions |
| Old `/billing/statements` bookmarks | Low | Alias redirect to `/reports`; route-guard matrix covers it |
| Year with no data looks broken | Low | `has_data` → explicit notice; documents stay available |

## 9. Test plan

### Backend — `backend/invoices/test_annual_report.py`

**`AnnualReportContentTests`** (11 tests):

| Test | Asserts |
|---|---|
| `test_totals_carry_the_balance_and_both_rates` | kWh totals, `self_consumed_kwh`, 40 %/40 % rates |
| `test_months_are_always_twelve_with_null_rates_where_there_is_no_data` | 12 months; June rates; January zeros and `null` rates |
| `test_previous_year_supplies_the_comparison_rates` | previous June rates, `previous_totals` |
| `test_previous_totals_are_null_without_previous_year_readings` | `previous_totals` null, all previous month rates null |
| `test_year_follows_swiss_civil_time` | local-midnight reading in January of the new year; 23:45 on 31 Dec in the previous year |
| `test_participants_carry_their_split_and_rate` | consumer split and rate; producer rate `null` |
| `test_participants_are_sorted_by_name` | name order |
| `test_savings_match_the_annual_statement` | `savings == compute_savings([invoice])`, `saved_chf`, total |
| `test_cancelled_invoices_and_other_years_do_not_count` | no savings, total `null` |
| `test_invoiced_participant_without_readings_keeps_a_row` | row present with savings |
| `test_year_without_readings_reports_no_data` | `has_data` false, null rates, no participants, 12 months |

**`AnnualReportAccessTests`** (7 tests): `test_admin_can_read_any_zev`,
`test_owner_cannot_read_another_owners_zev` (403),
`test_participant_is_forbidden` (403), `test_anonymous_is_rejected` (401),
`test_zev_id_is_required` (400), `test_year_is_required_and_bounded` (400 for
missing and for `year=1`), `test_unknown_or_malformed_zev_is_404`.

The existing metering dashboard tests cover the `_zev_balance` extraction
unchanged.

### Frontend

- `tests/reports-page.test.ts`: the owner test now asserts the report, the
  documents heading, and both document cards. The new `ReportsPage annual
  report` block (4 tests) covers the request parameters; rates, previous-year
  hint, savings, table rows, `—` for rows without savings, and the footer
  total; the no-data notice with documents still available; and the error
  alert.
- `tests/annual-statements-export.test.ts`: the page-level export tests render
  `ReportsPage` instead of the deleted `BillingStatementsPage`.
- `tests/billing-hub-order.test.ts`: two tabs.
- `tests/route-guard-matrix.test.ts`: `/billing/statements` resolves to the
  Reports page for all roles.
- `npm run build`, `npm run lint`, `npm run lint:style`, hex sweep.

### Acceptance criteria

- [x] Owners/admins see key figures, the monthly trend with the previous year, and the savings table for the selected ZEV and year on `/reports`.
- [x] Participant savings equal the annual statement's.
- [x] Rates match the Energy balance definitions.
- [x] The annual-statement ZIP is on `/reports`; `/billing/statements` redirects there; Billing has two tabs.
- [x] Participants cannot call the endpoint; owners cannot read other owners' ZEVs.
- [x] No horizontal page overflow at 400 px; no console errors.
