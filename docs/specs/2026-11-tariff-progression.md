# Feature Spec: Combined tariff progression (Tarifverlauf)

- Spec ID: SPEC-2026-tariff-progression
- Status: Draft
- Scope: Minor
- Type: Feature
- Owners: Sebastian Plattner
- Created: 2026-11-03
- Target Release: next minor
- Related Issues: #1117 (this feature), #1081 (suggested there by @spalinger), #1070 (UI patterns rollout)
- Related ADRs: none
- Impacted Areas: backend | frontend | docs

---

## 1. Problem and outcome

The price history chart in the tariff pane shows the history of **one** tariff
(`features/tariffs/priceHistory.ts`). A manager or participant asking "what did
the whole electricity price per kWh do over three years?" has to add up several
tariffs by hand: the energy price, the grid fees, the levies and the metering
charge, each with its own versions, bands and VAT treatment.

This feature adds a read-only **combined progression**: for one ZEV and one
energy type (grid, local or feed-in) it shows what one kWh costs, over time, as
the sum of every per-kWh tariff that applies. It is computed on the server by
the same band-resolution and VAT rules the invoice engine uses, so the number on
the screen is the number an invoice would use.

It shows:

- **one line per band** (time-of-use slot), because the summed price depends on
  when the energy is used;
- **subtotals per category** (energy, grid fees, levies, metering) and the tariff
  components behind each, for a chosen date;
- **net and gross** values wherever the ZEV's `vat_mode` makes the two differ;
- the **fixed fees** (monthly, yearly, per metering point, shared) in a separate
  block, never added into the per-kWh total.

It answers the four acceptance points of #1117: the questions are decided in §4,
the view is §8, fixed fees are handled in §5.8, and the summing across version
boundaries is tested in §10.

## 2. Scope

### In scope

| Area | Details |
|---|---|
| Backend computation | New module `invoices/tariff_progression.py`; one read-only endpoint `GET /api/v1/tariffs/tariffs/progression/` |
| Frontend | A routed page `/tariffs/progression` reached from the tariffs page header: controls, stepped chart, composition table, fixed-fee table |
| Types, client, i18n | `TariffProgression*` types, `fetchTariffProgression`, `queryKeys.tariffs.progression`, `pages.tariffs.progression.*` in de/en/fr/it |
| Docs | User guide chapter 07, baseline spec updates (§9) |

### Out of scope

- **Dynamic tariffs** (stored price series, no bands): listed as *not included*
  per period, never summed (§5.9). A daily or monthly average is a follow-up.
- **Per-participant views**: no consumption assumption, no allocation of shared
  fees to a participant, no annual-cost estimate.
- **Moving the single-tariff chart onto this endpoint.** The existing chart keeps
  its frontend derivation (§11, risk 2).
- Tariff overview PDF, reports, the MCP server and the analytics dataset API.
- Any model, migration, audit or ZEV-transfer change: the endpoint reads existing
  rows and writes nothing.

## 3. Actors, permissions, and ZEV scope

| Actor | Capability |
|---|---|
| `admin` | Any ZEV |
| `zev_owner` / manager | ZEVs they manage |
| viewer (access grant) | ZEVs they may view; the page is read-only for everyone |
| `participant` | No access, as for the tariffs page |
| anonymous | 401 |

Backend: `TariffViewSet` action `progression` (`detail=False`, `GET`), inherited
permissions `[IsAuthenticated, HasZevAccess]`. The ZEV is resolved through the
same scope as the tariffs (`ZevScopedQuerySetMixin`); a ZEV outside the caller's
scope answers 404 (not an empty result, which would hide the difference between
"no tariffs" and "not yours"). The tariffs used are `scope_queryset(...)`, so
`?zev_id=` cannot widen visibility.

Frontend: `ProtectedRoute` with the same roles as `/tariffs`
(`components/AppRoutes.tsx`). The scope-aware shell keeps the **Tariffs**
navigation item active on `/tariffs/progression`.

## 4. Decisions

These answer the open questions of #1117.

| Question | Decision | Why |
|---|---|---|
| Fixed fees | Not part of the per-kWh total. Shown in a separate block with their own history, in their own unit (CHF per month or per year), with scope (participant / per metering point / community). Shared fees show the **community** amount and the `split_key`; no per-participant share. No assumed kWh. | A per-kWh sum plus an assumed consumption is a number nobody entered and nobody is billed. |
| Which energy and category | The user picks the **energy type**. Every `energy` and `percentage_of_energy` tariff of that type is summed, whatever its category (energy, grid fees, levies, metering), grouped into category subtotals. Types are never mixed. Feed-in is its own view with the credit's own sign. | Mirrors how the engine bills a flow (`tariffs.energy(energy_type, day)`), and a participant with local energy has a different price than one without. |
| Time of use | **One line per band.** The summed price is resolved at every time of the week and year; times with the same combination of bands are one *slot*, and each slot is a line (§5.3). | The user's choice. A flat "the price" would hide HT/NT and seasons. |
| Net and gross | Computed in the backend with the ZEV's `vat_mode` and the `VatRate` in force on each day (§5.5). `not_registered`: one series, no gross. `registered`: gross = net + active rate. `inclusive`: the *billed* price grosses only the input-VAT-bearing tariffs, exactly as the engine does. | The three modes already differ in the engine; the view must not invent a fourth treatment. |
| Percentage tariffs | Priced as `percentage × grid base` where the base is the sum of the grid tariffs' bands **at the same slot**. | The engine resolves the grid base per timestamp (`_price_energy`); the existing chart's representative-price shortcut is not repeated here. |
| Dynamic tariffs | Excluded and reported (§5.9). | They have no bands and a stored series. |
| Where | A routed page `/tariffs/progression`, opened from the tariffs page header (§8). | Own controls and query; keeps the pane's draft/scope logic untouched. Decided, §12 point 1. |

## 4a. Data model

No model, field, migration or serializer-for-a-model change. Read-only use of
`Tariff`, `TariffPeriod`, `Zev.vat_mode` and `accounts.VatRate`.

## 5. Behaviour

Everything is computed by `invoices/tariff_progression.py::build_progression(zev,
energy_type, date_from, date_to)`, next to `tariff_pricing.py`. It uses
`tariffs.periods.resolve_band` (the one band-resolution rule, shared with the
engine), `invoices.engine._tariff_bears_input_vat` (the one input-VAT classifier;
imported, not copied; open point 3) and `tariffs.series.series_key`.

### 5.1 Which tariffs

For `energy_type = X` and the ZEV:

- **Displayed set:** tariffs with `billing_mode` in `{energy, percentage_of_energy}`
  and `energy_type == X`, without `dynamic_source`.
- **Base set:** if the displayed set contains a `percentage_of_energy` tariff, the
  static `energy` tariffs of type `grid` are resolved too, even when `X != grid`.
  They shape the slots and the percentage base but are not listed as components
  unless `X == grid`.
- **Dynamic tariffs** of type X, and percentage tariffs whose active grid base
  contains a dynamic tariff, are reported under `incomplete` (§5.9).
- **Fixed fees** are collected separately (§5.8), independent of `X`.

Tariffs are not filtered by name or category: `energy_type` alone decides, as in
the engine.

### 5.2 Date range and intervals

- `from` defaults to the earliest `valid_from` of the displayed set; `to` to
  `max(today, latest valid_from of the displayed set)` (an open-ended version is
  drawn to that day, as `terminalBoundary` does in the existing chart). Both are
  inclusive; `from > to` is a 400.
- **Breakpoints:** every `valid_from` and every `valid_to + 1 day` of every tariff
  in the displayed and base sets, plus (only when `vat_mode != not_registered`)
  every `VatRate.valid_from` and `valid_to + 1 day`, clipped to `[from, to]`.
- Consecutive breakpoints delimit **elementary intervals** `[d_i, d_{i+1} - 1]`;
  the last ends at `to`. Within an interval the set of active tariffs and the VAT
  rate are constant. Intervals are not merged when their values happen to be equal
  (a new version at an unchanged price is still a version).
- A day on which no displayed tariff is active gives an interval with
  `slots: []` (a gap, drawn as such).

### 5.3 Slots: one line per band

A tariff's price depends on month, weekday and time of day
(`TariffPeriod.months`, `weekdays`, `time_from`, `time_to`). The combined price
is therefore a function of the *combination* of bands in force.

1. **Cells.** The year is cut into cells `(month 1..12, weekday 0..6, segment)`.
   Segments are the day cut at every `time_from`/`time_to` of every band in the
   request (union across intervals, plus 00:00 and 24:00). A cell is resolved at a
   naive wall-clock datetime in reference year 2025 (month `m`, the first date of
   that month with weekday `w`, time = segment start), because `resolve_band`
   reads a naive datetime as the Swiss wall clock (ADR 0026) and bands are wall
   clock rules.
2. **Resolve.** For each tariff active in the interval,
   `resolve_band(tariff.periods, ts)` gives its band for the cell. Results are
   memoised per `(tariff id, cell)`, so each tariff version is resolved at most
   `12 × 7 × segments` times for the whole request.
3. **Group.** Cells whose bands are identical for every tariff of the interval
   form one *slot*.
4. **Rules.** A slot's cells are folded into `rules`: per month a map weekday →
   merged time windows; weekdays with equal windows are merged, then months with
   equal weekday groups. A window that ends at 24:00 beside one that starts at
   00:00 on the same weekday set is reported as one wrapping window
   (`from > to`, the model's convention since #837). All-day is
   `{"from": "00:00", "to": "24:00"}`.
5. **Lines.** The canonical JSON of a slot's `rules` is its *signature*.
   Slots with the same signature in different intervals are the **same line**; a
   changed window gives a new line (the old one ends, the new one begins). Lines
   get stable keys `line-1`, `line-2`, … (free of `.`, which Recharts reads as a
   property path), ordered: the all-hours line first, then by first appearance,
   then by earliest window start.
6. **Limit.** More than 24 slots in one interval (the most 12 months × 2 bands
   give) is refused with 422 `too_many_bands`; the page tells the user to narrow
   the date range.

A single-band set therefore produces one line, `rules` = every month, every
weekday, all day. The frontend names a line from its rules with the existing
helpers (`bandName`, `bandWindow`, `RecurrenceChips`); the backend returns no
display text.

### 5.4 Price of a slot

For a slot, each displayed tariff contributes its resolved band:

- `energy`: `net = band.price_chf_per_kwh`.
- `percentage_of_energy`: `net = band.percentage / 100 × base_net`, where
  `base_net` is the sum, over the **static grid `energy` tariffs active in the
  interval**, of their resolved band prices in this slot (the engine's
  `net_base`). A percentage tariff with a 0 % band contributes 0 and does not
  resolve a base, as in the engine.
- A tariff active in the interval with no bands contributes nothing and is
  reported as `incomplete` (`no_bands`), the same condition readiness flags.

`net` of the slot is the exact sum of the components' `net`.

### 5.5 VAT: net and gross

`gross` is `null` everywhere when `vat_mode = not_registered`. Otherwise `rate`
is `VatRate.active_for_day(interval.from).rate`, or 0 when none is active
(then `gross == net`). The rate is constant within an interval because VAT
boundaries are breakpoints.

| `vat_mode` | `net` means | `gross` of a component |
|---|---|---|
| `not_registered` | the price as entered, which is final | `null` |
| `registered` | the price as entered (net) | `net × (1 + rate)` for every component |
| `inclusive` | the published price | bearing tariff (`_tariff_bears_input_vat`): `net × (1 + rate)`; other: `net`. A percentage line that does **not** bear VAT uses the **gross** grid base: `pct × gross_base`; one that does bear VAT uses the net base, then `× (1 + rate)` (never both) |

where, for `inclusive`, `gross_base = Σ band price × (1 + rate)` over the grid
tariffs that bear input VAT (`+ price` for those that do not), the engine's
`gross_base`. Gross totals and subtotals are sums of exact component gross
values, then rounded (§5.10), never gross applied to a rounded net.

Differences from invoicing, stated so nobody expects them to vanish:

- The engine uses the rate in force on an invoice's **`period_end`** for the whole
  invoice; the progression uses the rate in force **on the day**. An invoice that
  spans a rate change is billed at one rate; the chart shows the step on the day.
- Under `registered`, VAT is charged on `vat_base_chf`, which excludes producer
  credits. This is a per-invoice base, not a per-kWh price, so the view shows the
  price a consumer pays and does not model it.

### 5.6 Categories and subtotals

For each slot, components are grouped by `Tariff.category` in
`TariffCategory` order (energy, grid_fees, levies, metering; `other` cannot be a
tariff). A category's subtotal is the sum of its components (`net` and `gross`);
the slot `total` is the sum of the subtotals. `expected_categories` (top level)
is the set of categories that have at least one displayed tariff anywhere in the
range; an interval's `missing_categories` is `expected_categories` minus the
categories active in it. A missing category means the total is **understated**
for that interval, so the page marks it (§8).

### 5.7 Gaps

A gap in one tariff's own timeline (a day with no active version) shows up as a
missing category, or an empty interval when nothing is active, never as a
silently lower price. The engine bills no line for a tariff with no active
version, so the figure is the truth, and the mark tells the user why it is low.

### 5.8 Fixed fees

`fixed_fees` lists every tariff series of the ZEV whose `billing_mode` is one of
`monthly_fee`, `yearly_fee`, `per_metering_point_monthly_fee`,
`per_metering_point_yearly_fee`, `shared_monthly_fee`, `shared_yearly_fee`,
regardless of `energy_type` and of the requested type. Grouped by
`series_key`; each version is a row, split at VAT-rate changes when
`vat_mode != not_registered`:

| Field | Meaning |
|---|---|
| `unit` | `month` or `year` |
| `scope` | `participant` (`monthly_fee`, `yearly_fee`), `metering_point` (`per_metering_point_*`), `community` (`shared_*`) |
| `split_key` | `equal` or `weight` for `community`, else `null` |
| `amount_net` | `fixed_price_chf` (for `community`: what the community pays, not a participant's share) |
| `amount_gross` | by §5.5 with the same classifier (`registered`: `× (1 + rate)`; `inclusive`: only if the tariff bears input VAT; else `null`/`net`) |
| `vat_rate` | the rate used for the row, `null` under `not_registered` |

Fee amounts are never added to each other or to the per-kWh total, and amounts of
different units are never combined.

### 5.9 Incomplete

`incomplete` per interval lists `{tariff_id, name, reason}` for tariffs that are
active but cannot be priced here:

| `reason` | When |
|---|---|
| `dynamic` | the tariff has a `dynamic_source` |
| `dynamic_base` | a percentage tariff whose active grid base contains a dynamic tariff |
| `no_bands` | the tariff has no bands |

Such tariffs are left out of every sum. A non-empty `incomplete` also makes the
total understated, so the page marks the interval like a missing category.

### 5.10 Rounding

All arithmetic is `Decimal`. Prices (net, gross, subtotals, totals) are quantised
to 5 decimal places, `ROUND_HALF_UP` (the precision of `price_chf_per_kwh`);
percentages are not rounded; fee amounts are quantised to 2 places. Components
and totals are each quantised from the exact value, so a displayed total can
differ from the displayed components by one unit in the last place.

## 6. API contracts

| Endpoint | Method | Permission | Behaviour |
|---|---|---|---|
| `/api/v1/tariffs/tariffs/progression/` | GET | `IsAuthenticated`, `HasZevAccess` | The combined progression for one ZEV and energy type |

The view is `TariffViewSet.progression` (`tariffs/views.py`), which validates
the query with `TariffProgressionQuerySerializer` and delegates to
`invoices.tariff_progression.build_progression` (imported inside the method, as
`list` does with `tariff_pricing`). The response is built from plain dicts; there
is no response serializer.

### Query

| Param | Type | Required | Notes |
|---|---|---|---|
| `zev_id` | UUID | yes | 400 if missing, 404 if not visible |
| `energy_type` | `grid` \| `local` \| `feed_in` | yes | 400 otherwise |
| `from`, `to` | `YYYY-MM-DD` | no | defaults per §5.2; `from > to` is 400 |

### Response

```jsonc
{
  "zev": "uuid",
  "energy_type": "grid",
  "vat_mode": "inclusive",              // not_registered | registered | inclusive
  "from": "2024-01-01",
  "to": "2026-11-03",
  "expected_categories": ["energy", "grid_fees", "levies", "metering"],
  "lines": [
    { "key": "line-1",
      "rules": [ { "months": [1,2,3,4,5,6,7,8,9,10,11,12],
                   "weekdays": [0,1,2,3,4],
                   "windows": [ { "from": "07:00", "to": "20:00" } ] } ] }
  ],
  "intervals": [
    { "from": "2024-01-01", "to": "2024-12-31",
      "vat_rate": "0.0810",              // null when not_registered
      "missing_categories": [],
      "incomplete": [ { "tariff_id": "uuid", "name": "Spot", "reason": "dynamic" } ],
      "slots": [
        { "line": "line-1",
          "net": "0.27300", "gross": "0.29511",       // gross null when not_registered
          "categories": [
            { "category": "energy", "net": "0.15000", "gross": "0.16215",
              "components": [
                { "tariff_id": "uuid", "name": "Netzstrom",
                  "billing_mode": "energy", "band_period_id": "uuid",
                  "net": "0.15000", "gross": "0.16215",
                  "percentage": null, "base_net": null } ] } ] } ] }
  ],
  "fixed_fees": [
    { "name": "Grundgebühr", "category": "metering",
      "billing_mode": "shared_monthly_fee", "unit": "month",
      "scope": "community", "split_key": "equal",
      "versions": [ { "tariff_id": "uuid", "valid_from": "2024-01-01", "valid_to": null,
                      "amount_net": "40.00", "amount_gross": "43.24", "vat_rate": "0.0810" } ] }
  ]
}
```

Percentage components carry `percentage` (e.g. `"65.00"`) and `base_net` (the
slot's net grid base); other components carry `null` for both.

### Errors

| Status | When |
|---|---|
| 400 | missing/invalid `zev_id`, `energy_type`, `from`, `to`; `from > to` |
| 401/403 | unauthenticated / no ZEV access (as for every tariffs endpoint) |
| 404 | ZEV not visible to the caller |
| 422 | `{"detail": "...", "code": "too_many_bands"}` |

Cost: at most four queries (ZEV, tariffs with `prefetch_related("periods")`,
`VatRate` rows overlapping the range, and the scope lookup); everything else is in
memory.

## 7. Async and integration behavior

None. The endpoint is synchronous and read-only; no Celery task, no audit event,
no cache. Dynamic prices are not read (§5.9).

## 8. Frontend

### 8.1 Entry and route

- Route `/tariffs/progression` (`components/AppRoutes.tsx`, lazy
  `pages/TariffProgressionPage.tsx`), same `ProtectedRoute` roles as `/tariffs`.
- The tariffs page header (`TariffsPage.tsx`) gets a secondary link **Price
  progression** to it, shown to everyone who can open the page. The new page
  header has a back link to `/tariffs`. Following rule 6 / D of the UI patterns
  spec: the page has its own filters and query and no list or pane beside it; a
  chart alone would not justify a page, the independence from the pane's draft
  and scope logic does (decided, §12 point 1).
- **No navigation item.** The page is a view of the tariffs, reached from their
  page. `SidebarLink` matches by path prefix (`Layout.tsx`), so **Tariffs** stays
  active on `/tariffs/progression` (`aria-current="true"`) without any change.

### 8.2 Page

**File:** `frontend/src/pages/TariffProgressionPage.tsx`, feature code in
`frontend/src/features/tariffs/progression/`.

- `useManagedZev` supplies `selectedZevId`; `ScopeGuard` and `useScopeNote` as on
  the tariffs page. Without a selected ZEV: the shared empty state.
- Query: `useQuery({ queryKey: queryKeys.tariffs.progression(zevId, energyType, from, to), queryFn: () => fetchTariffProgression(...) })`.
  The key lives in `lib/api/queryKeys.ts`; the existing tariff invalidation helper
  (`features/tariffs/invalidate.ts`) also invalidates it, so a tariff, band or
  VAT-rate change refetches.
- **Controls** (state in URL params so a view can be linked and survives reload:
  `energy`, `from`, `to`, `basis`, `date`, `line`):
  - Energy type: grid (default), local, feed-in.
  - Date range: two date inputs, blank = whole history.
  - **Net / gross toggle**, shown only when `vat_mode != not_registered`. Labels
    by mode: `registered` "Excl. VAT / Incl. VAT"; `inclusive` "Published price /
    Billed price". Under `not_registered` one series, titled "Price", no toggle.
- **Chart** (`TariffProgressionChart.tsx`): stepped lines, one per `lines[]`, built
  by `progressionChart.ts` (same step assembly as `priceHistory.ts`: a point at
  every interval boundary; `null` before a line's first appearance and during a
  gap so the line breaks). Intervals with `missing_categories` or `incomplete` are
  hatched, with a notice below listing what is missing and from when. Uses the
  colourblind-safe palette and tokens of `TariffPriceHistoryChart.css`; no raw
  colour literals (hex sweep). Each line is named in a direct legend from its
  rules, so colour is never the only cue. A click on the chart sets `date`.
- **Composition** (`ProgressionComposition.tsx`): for the chosen `date` (default
  today, clamped to the range) and `line` (default the first), a table with one
  block per category: the subtotal in the block header, the components below
  (tariff name, band label, price; percentage components "65 % of CHF 0.30840"),
  and a total row. It follows the net/gross toggle and is the accessible
  equivalent of the chart. Narrow viewports use the shared stacked-row treatment.
- **Fixed fees** (`ProgressionFixedFees.tsx`): grouped by unit, a table of series
  with scope, current amount, and the version history; `community` rows are
  labelled as the amount the community pays, split by headcount or weight. Not
  added up anywhere.
- States: loading skeleton; no tariffs for this energy type (message offering
  the other types); 422 `too_many_bands` (narrow the range); request error.
  Read-only: there are no write controls, so viewers see exactly the same page.

### TypeScript types

**File:** `frontend/src/types/api.ts`

```typescript
export type TariffProgressionVatMode = 'not_registered' | 'registered' | 'inclusive'
export type TariffProgressionIncompleteReason = 'dynamic' | 'dynamic_base' | 'no_bands'

export interface TariffProgressionRule {
    months: number[]
    weekdays: number[]
    windows: Array<{ from: string, to: string }>
}

export interface TariffProgressionComponent {
    tariff_id: string
    name: string
    billing_mode: 'energy' | 'percentage_of_energy'
    band_period_id: string
    net: string
    gross: string | null
    percentage: string | null
    base_net: string | null
}

export interface TariffProgressionSlot {
    line: string
    net: string
    gross: string | null
    categories: Array<{
        category: TariffCategory
        net: string
        gross: string | null
        components: TariffProgressionComponent[]
    }>
}

export interface TariffProgressionInterval {
    from: string
    to: string
    vat_rate: string | null
    missing_categories: TariffCategory[]
    incomplete: Array<{ tariff_id: string, name: string, reason: TariffProgressionIncompleteReason }>
    slots: TariffProgressionSlot[]
}

export interface TariffProgressionFixedFee {
    name: string
    category: TariffCategory
    billing_mode: BillingMode
    unit: 'month' | 'year'
    scope: 'participant' | 'metering_point' | 'community'
    split_key: 'equal' | 'weight' | null
    versions: Array<{
        tariff_id: string
        valid_from: string
        valid_to: string | null
        amount_net: string
        amount_gross: string | null
        vat_rate: string | null
    }>
}

export interface TariffProgression {
    zev: string
    energy_type: EnergyType
    vat_mode: TariffProgressionVatMode
    from: string
    to: string
    expected_categories: TariffCategory[]
    lines: Array<{ key: string, rules: TariffProgressionRule[] }>
    intervals: TariffProgressionInterval[]
    fixed_fees: TariffProgressionFixedFee[]
}
```

(`TariffCategory`, `BillingMode`, `EnergyType` already exist in `api.ts`; reuse them.)

### API client functions

**File:** `frontend/src/lib/api/tariffs.ts`

| Function | Method | Endpoint |
|---|---|---|
| `fetchTariffProgression({ zevId, energyType, from?, to? })` | GET | `/tariffs/tariffs/progression/` |

### i18n

All text under `pages.tariffs.progression.*` in `de`, `en`, `fr`, `it`
(`frontend/src/i18n/locales`): title, controls, the three net/gross label pairs,
category names (reuse the existing tariff category keys), notice texts per
`incomplete.reason`, fixed-fee scope and unit labels, empty and error states. No
hard-coded text.

## 9. Documentation to update on completion

- `docs/user-guide/07-tariff-configuration.md`: a "Price progression" section
  (what it sums, the energy-type choice, bands as lines, net vs gross per VAT
  mode, why fixed fees are separate, what "not included" means); a screenshot
  `07e-tariff-progression.png` added to the `npm run screenshots` set.
- `docs/specs/2026-03-tariffs-and-billing-engine.md`: the endpoint and its
  correspondence to `_price_energy` / §4.8.
- `docs/specs/2026-10-tariff-split-view.md`: the page-header link (§4) and that
  the progression is a separate page.
- `docs/specs/2026-09-percentage-tariff-bands.md`: a note that the single-tariff
  chart still uses the representative-price derivation (§11, risk 2).
- `AGENTS.md`: add this spec to the completed feature specs list when it ships.

## 10. Test plan

### Backend — `invoices/test_tariff_progression.py` (computation)

**`TestIntervals`** (6 tests):

| Test | Asserts |
|---|---|
| `test_sum_changes_at_each_version_boundary` | Two tariffs with offset version dates give a new interval, and a new sum, at every boundary |
| `test_valid_to_is_inclusive` | The new interval starts the day after `valid_to` |
| `test_open_ended_version_runs_to_today` | Default `to` is today, or the latest `valid_from` if later |
| `test_range_clips_intervals` | `from`/`to` cut the first and last interval |
| `test_gap_gives_empty_interval` | A day with nothing active gives `slots: []` |
| `test_unchanged_price_new_version_is_still_an_interval` | Intervals are not merged |

**`TestSlots`** (9 tests):

| Test | Asserts |
|---|---|
| `test_flat_tariffs_make_one_line` | One line, all months, weekdays, all day |
| `test_ht_nt_beside_flat_fee_gives_two_lines` | Two lines; the flat tariff's price is in both |
| `test_misaligned_windows_give_three_or_more_slots` | 06–22 beside 07–20 splits at both edges |
| `test_seasonal_band_splits_by_months` | Winter HT/NT beside summer flat gives three lines |
| `test_wrapping_window_is_one_window` | 20:00–07:00 reported as `{from: "20:00", to: "07:00"}` |
| `test_same_when_in_two_intervals_shares_a_line` | Equal signature, same `line` key |
| `test_changed_window_starts_a_new_line` | Different signature, new key, old line ends |
| `test_line_order_is_all_hours_first` | Ordering rule of §5.3 |
| `test_too_many_bands_is_refused` | More than 24 slots raises `TooManyBands` |

**`TestPricing`** (7 tests):

| Test | Asserts |
|---|---|
| `test_category_subtotals_add_up_to_total` | Σ subtotals == total, per slot |
| `test_category_order_is_tariff_category_order` | energy, grid_fees, levies, metering |
| `test_energy_type_filter_excludes_other_types` | Local view never contains grid components |
| `test_feed_in_is_a_separate_view` | Feed-in components only, never netted |
| `test_missing_category_is_reported` | `missing_categories` lists the category with no active version |
| `test_tariff_without_bands_is_incomplete` | `no_bands`, left out of the sum |
| `test_matches_engine_price_for_sample_timestamps` | For a timestamp in every slot, the slot's `net` equals what `_price_energy` bills per kWh; parametrised over the three `vat_mode`s for `gross` |

**`TestPercentage`** (6 tests):

| Test | Asserts |
|---|---|
| `test_percentage_uses_grid_band_at_same_slot` | HT percentage line = pct × HT grid base |
| `test_percentage_follows_grid_version_change` | A grid version change is a breakpoint for the local line |
| `test_percentage_zero_band_contributes_nothing` | 0 % band, no base resolved |
| `test_inclusive_percentage_uses_gross_base` | `gross = pct × gross_base` for a non-bearing line |
| `test_inclusive_bearing_percentage_is_not_grossed_twice` | Net base, then `× (1 + rate)` once |
| `test_dynamic_grid_base_marks_percentage_incomplete` | `dynamic_base` |

**`TestVat`** (6 tests):

| Test | Asserts |
|---|---|
| `test_not_registered_has_no_gross` | `gross` null, `vat_rate` null, no VAT breakpoints |
| `test_registered_grosses_every_component` | `net × (1 + rate)` |
| `test_inclusive_grosses_only_bearing_tariffs` | Local and feed-in unchanged |
| `test_vat_rate_change_is_a_breakpoint` | New interval, new gross, same net |
| `test_no_active_rate_means_gross_equals_net` | Rate 0 |
| `test_rounding_is_five_places_half_up` | §5.10 |

**`TestFixedFees`** (6 tests):

| Test | Asserts |
|---|---|
| `test_fees_are_listed_not_summed` | Not in any slot total |
| `test_scope_and_unit_per_billing_mode` | All six modes map as §5.8 |
| `test_shared_fee_reports_community_amount_and_split_key` | No per-participant division |
| `test_fee_rows_split_at_vat_change` | One row per rate |
| `test_fee_gross_follows_input_vat_classifier` | `inclusive`: only bearing categories |
| `test_fees_are_independent_of_requested_energy_type` | Same list for grid and local |

### Backend — `tariffs/test_progression_api.py` (endpoint)

**`TestProgressionApi`** (10 tests):

| Test | Asserts |
|---|---|
| `test_requires_authentication` | 401 |
| `test_zev_id_required` | 400 |
| `test_invalid_energy_type` | 400 |
| `test_from_after_to` | 400 |
| `test_out_of_scope_zev_is_404` | A manager of another ZEV |
| `test_viewer_can_read` | 200 for a read-only grant |
| `test_participant_has_no_access` | As for the tariffs list |
| `test_response_shape` | Keys and types of §6 |
| `test_too_many_bands_is_422` | Code `too_many_bands` |
| `test_query_count_is_bounded` | At most four queries, independent of the number of tariffs |

### Frontend — `frontend/tests/tariff-progression.test.ts` (unit)

**`progressionChart`** (6 tests): a point at every interval boundary; `null` for a
line before it exists and across a gap; line keys free of `.`; net/gross
selection; hatched-interval flags from `missing_categories`/`incomplete`; line
name from rules (all hours, weekday window, wrapping window). **`composition`**
(3 tests): lookup by date and line, clamping outside the range, subtotal and total
rows. **`labels`** (2 tests): net/gross label pair per `vat_mode`; no toggle for
`not_registered`.

Plus a Playwright spec `tariff-progression` (opens from the tariffs header,
switches energy type and net/gross) and the user-guide screenshot.

### Validation

Backend: `ruff check .`, `python manage.py check`, `python -m pytest -q`.
Frontend: `npm run lint`, `npm run lint:style`, `node ../scripts/check-frontend-hex.mjs`,
`npm run test:unit`, `npm run build`. Check the page in the dev stack with demo data
(`seed_demo`) in each of the three VAT modes, in the console and at ~400px.

### Acceptance criteria

- [ ] This spec decides the questions of #1117 (§4).
- [ ] The endpoint returns the combined per-kWh progression for one energy type, one line per band, with category subtotals and net/gross by `vat_mode`.
- [ ] A slot's price equals what the invoice engine bills per kWh at a timestamp in that slot, in all three VAT modes (parity test).
- [ ] Summing across version and VAT-rate boundaries is covered by unit tests (`TestIntervals`, `TestVat`).
- [ ] Fixed fees are shown separately, in their own unit, and never added into the per-kWh total.
- [ ] Dynamic tariffs and gaps are visibly reported, never silently dropped or summed.
- [ ] The page works for viewers read-only, at ~400px, with all four locales.
- [ ] User guide and the baseline specs of §9 updated.

## 11. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Computation cost: cells × tariffs × intervals | Medium | Global segment grid and memoised `(tariff, cell)` resolutions; ≤ 4 queries; sanity test with ~20 versions |
| Two derivations of a percentage tariff's price (this endpoint exact, the existing chart a representative-price estimate) can show different numbers | Medium | The chart keeps its "derived" note; the user guide says the progression is exact per band; follow-up issue to move the chart onto this endpoint |
| Drift from the engine's VAT rules | High | Reuse the engine's classifier; the parity test runs all three modes; the baseline spec §4.8 links here |
| Many lines on an irregular tariff set | Medium | Hard limit of 24 slots per interval, a 422 asking for a narrower range, direct legend |
| Understated total read as the real price when something is missing | High | Hatched intervals, a notice naming the missing category or tariff and the date from |
| Participants or viewers misread the community amount of a shared fee as their own | Medium | Scope label and split key shown; no per-participant figure |

## 12. Sign-off points

Decided:

1. **Page, not tab.** A routed `/tariffs/progression` page. A tab on the tariffs
   page would entangle the pane's draft guard, scope clearing and
   `tariff`/`version` URL state.
2. **Line identity across window changes.** A changed window (HT 07–20 becomes
   06–22) ends the old line and starts a new one (§5.3). The break is honest: the
   two lines describe different times of day. Matching lines by band type
   (HT/NT/flat) was considered and rejected, because it cannot be right once a
   tariff set mixes bands of different tariffs.

Open:

3. **`_tariff_bears_input_vat`.** Imported from the engine as is; promote it to a
   public name in the same PR if importing a private function is unwelcome.
4. **Registered feed-in.** Feed-in is grossed like every other component under
   `registered` because the credit reduces the VAT base (#969, still open there).
   If #969 changes that, this view follows.
5. **Slot limit.** 24 is the structural maximum for one tariff, not a usability
   limit; the real figure may be lower after trying realistic data.
