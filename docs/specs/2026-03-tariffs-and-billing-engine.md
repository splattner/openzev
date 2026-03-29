# Feature Spec: Tariffs and billing engine

- Spec ID: SPEC-2026-tariffs-billing
- Status: Approved
- Scope: Major
- Type: Feature
- Owners: Core maintainers
- Created: 2026-03-24
- Target Release: Ongoing baseline
- Related Issues: n/a (baseline)
- Related ADRs: 0002, 0006, 0007
- Impacted Areas: backend, frontend, docs

## 1. Problem and outcome

A ZEV community must allocate locally produced energy fairly among participants
and bill them deterministically.  The billing engine is the core of OpenZEV: it
takes metering data and tariff configuration as input and produces invoice
documents (with line items, totals, and VAT) as output.

**Outcome:** given identical metering data and tariff configuration, the engine
always produces byte-identical invoice totals.  The spec below is sufficient to
re-implement the engine from scratch.

---

## 2. Scope

### In scope

| Area | Details |
|---|---|
| Tariff data model | `Tariff`, `TariffPeriod`, categories, billing modes, energy types |
| Timestamp-level allocation | Local vs. grid energy split per 15-min / hourly reading |
| Consumer pricing | Energy tariffs, percentage-of-energy tariffs |
| Producer credits | Local-energy revenue credit and feed-in compensation |
| Fixed-fee billing | Monthly, yearly, per-metering-point monthly, per-metering-point yearly |
| Rounding | kWh precision, CHF precision, unit-price precision |
| VAT | Conditional application, rate resolution |
| Invoice construction | Line items, sort order, description templates, subtotals |
| Tariff preset export/import | JSON export of all ZEV tariffs, JSON import into a ZEV |
| Guard rails | Draft/locked handling, regeneration rules |

### Out of scope

- Dynamic market pricing feeds
- Country-specific tariff engines beyond Swiss model
- Invoice lifecycle transitions (see `SPEC-2026-invoice-lifecycle-comms`)
- PDF rendering and email delivery

---

## 3. Data model reference

### 3.1 Tariff

| Field | Type | Description |
|---|---|---|
| `zev` | FK → `Zev` | Owning community |
| `name` | `CharField(200)` | Human-readable label, used in invoice line descriptions |
| `category` | `TariffCategory` | One of: `energy`, `grid_fees`, `levies`, `metering` |
| `billing_mode` | `BillingMode` | Determines how quantity and price are computed (see §5) |
| `energy_type` | `EnergyType` (nullable) | `local`, `grid`, or `feed_in`; required when `billing_mode ∈ {energy, percentage_of_energy}` |
| `fixed_price_chf` | `Decimal(10,2)` (nullable) | Unit price for fixed-fee modes; may be negative for credits |
| `percentage` | `Decimal(5,2)` (nullable) | Used only with `percentage_of_energy` mode |
| `valid_from` | `DateField` | First day this tariff is active (inclusive) |
| `valid_to` | `DateField` (nullable) | Last day this tariff is active (inclusive); `NULL` = open-ended |
| `notes` | `TextField` | Free text |

A tariff is **active on day `d`** iff `valid_from ≤ d` and (`valid_to IS NULL` or `valid_to ≥ d`).

### 3.2 TariffPeriod (price bands within a tariff)

| Field | Type | Description |
|---|---|---|
| `tariff` | FK → `Tariff` | Parent tariff |
| `period_type` | `PeriodType` | `flat`, `high` (HT), or `low` (NT) |
| `price_chf_per_kwh` | `Decimal(8,5)` | Price in CHF per kWh |
| `time_from` | `TimeField` (nullable) | Start of HT/NT window (required for `high`/`low`) |
| `time_to` | `TimeField` (nullable) | End of HT/NT window (exclusive) |
| `weekdays` | `CharField(20)` | Comma-separated weekday numbers `0`–`6` (Mon–Sun); blank = all days |

**Period matching rules** (evaluated per-timestamp):

1. If a `flat` period exists → use its price; ignore time/weekday.
2. For `high` / `low` periods: extract the timestamp's **time** and **weekday**.
   Match periods where `time_from ≤ time < time_to` and weekday ∈ allowed weekdays.
3. **Fallback:** if no period matches, use the first period's price (ordered by `period_type`).

### 3.3 Energy types

| Value | Meaning |
|---|---|
| `local` | Energy produced and consumed within the ZEV (solar/battery) |
| `grid` | Energy drawn from the public grid |
| `feed_in` | Surplus energy exported to the grid |

### 3.4 Billing modes

| Mode | Quantity source | Unit price source | Unit |
|---|---|---|---|
| `energy` | kWh from timestamp allocation | `TariffPeriod.price_chf_per_kwh` (HT/NT aware) | `kWh` |
| `percentage_of_energy` | kWh from timestamp allocation | `sum(grid ENERGY tariff prices at ts) × (percentage / 100)` | `kWh` |
| `monthly_fee` | Number of billable months | `fixed_price_chf` | `month` |
| `yearly_fee` | Number of billable months | `fixed_price_chf / 12` | `month` |
| `per_metering_point_monthly_fee` | Sum of metering-point-months | `fixed_price_chf` | `month` |
| `per_metering_point_yearly_fee` | Sum of metering-point-months | `fixed_price_chf / 12` | `month` |

### 3.5 Invoice and InvoiceItem

See `SPEC-2026-invoice-lifecycle-comms` for lifecycle details.  Relevant fields
produced by the engine:

**Invoice** (created per participant per period):

| Field | Description |
|---|---|
| `total_local_kwh` | Sum of local energy allocated to this participant |
| `total_grid_kwh` | Sum of grid energy allocated to this participant |
| `total_feed_in_kwh` | Sum of exported energy allocated to this producer |
| `subtotal_chf` | Sum of all line-item totals |
| `vat_rate` | Resolved VAT rate (decimal fraction, e.g. `0.0810`) |
| `vat_chf` | `subtotal_chf × vat_rate`, rounded to 0.01 |
| `total_chf` | `subtotal_chf + vat_chf` |

**InvoiceItem** (one per tariff per bucket):

| Field | Description |
|---|---|
| `item_type` | `local_energy`, `grid_energy`, `feed_in`, `fee`, or `credit` |
| `tariff_category` | Copied from the tariff's `category` |
| `description` | Generated from tariff name + billing-mode suffix (see §8) |
| `quantity_kwh` | Accumulated quantity (kWh or months) |
| `unit` | `kWh` or `month` |
| `unit_price_chf` | Effective price per unit |
| `total_chf` | `quantity × unit_price`, rounded to 0.01 |
| `sort_order` | Deterministic integer for display ordering (see §8.3) |

---

## 4. Algorithm: `generate_invoice(participant, period_start, period_end)`

The engine runs **inside a single database transaction**.

### 4.0 Guard rails

1. If a non-draft, non-cancelled invoice exists for the same participant + period → **raise `ValueError`** (do not overwrite).
2. Delete any existing `draft` or `cancelled` invoice for the same participant + period.

### 4.1 Collect metering points

Metering points are resolved through **`MeteringPointAssignment`** (not a direct FK).

- **Consumption MPs:** `meter_type ∈ {consumption, bidirectional}`, assigned to participant, assignment window overlaps `[period_start, period_end]`.
- **Production MPs:** `meter_type ∈ {production, bidirectional}`, same assignment-overlap filter.
- **ZEV-wide consumption MPs:** all active consumption/bidirectional meters in the ZEV with an assignment overlapping the period.
- **ZEV-wide production MPs:** all active production/bidirectional meters in the ZEV with an assignment overlapping the period.

Assignment overlap condition:
```
assignment.valid_from ≤ period_end
AND (assignment.valid_to IS NULL OR assignment.valid_to ≥ period_start)
```

### 4.2 Collect readings

| Reading set | Metering points | Direction | Time window |
|---|---|---|---|
| `participant_readings` | Participant's consumption MPs | `IN` | `[period_start 00:00 UTC, period_end+1 00:00 UTC)` |
| `feedin_readings` | Participant's production MPs | `OUT` | same |
| `zev_production_by_ts` | ZEV-wide production MPs | `OUT` | same, grouped by timestamp |
| `zev_consumption_by_ts` | ZEV-wide consumption MPs | `IN` | same, grouped by timestamp |

The time window uses **exclusive upper bound**: readings at midnight on the day after `period_end` are excluded.

### 4.3 Timestamp-level energy allocation (consumers)

For **each** consumption reading (ordered by timestamp):

```
ts                    = reading.timestamp
participant_kwh       = reading.energy_kwh
zev_consumption_at_ts = sum of all IN readings at ts across ZEV
zev_production_at_ts  = sum of all OUT readings at ts across ZEV
local_pool_at_ts      = min(zev_production_at_ts, zev_consumption_at_ts)

IF zev_consumption_at_ts > 0 AND local_pool_at_ts > 0:
    participant_share  = participant_kwh / zev_consumption_at_ts
    r_local            = min(participant_kwh, local_pool_at_ts × participant_share)
ELSE:
    r_local = 0

r_grid = max(participant_kwh − r_local, 0)
```

**Key invariant:** at every timestamp, each participant's consumption is split into a **local** portion (energy sourced from ZEV production) and a **grid** portion (energy from the public grid).  The local pool is capped at the lesser of total production and total consumption.

### 4.4 Consumer energy pricing (per timestamp)

After computing `r_local` and `r_grid` for a reading at timestamp `ts`:

#### 4.4.1 Standard energy tariffs (`billing_mode = energy`)

For each `(energy_type, quantity)` in `{(local, r_local), (grid, r_grid)}` where `quantity > 0`:

1. Find all tariffs where `billing_mode = energy`, `energy_type` matches, and tariff is active on `ts.date()`.
2. For each matching tariff, resolve the price via period matching (§3.2).
3. Accumulate: `quantity` kWh at `quantity × price` CHF.

#### 4.4.2 Percentage-of-energy tariffs (`billing_mode = percentage_of_energy`)

These tariffs price energy as a percentage of the **grid base price sum**.

1. **Grid base price sum** = sum of `price_chf_per_kwh` at `ts` for all tariffs where `billing_mode = energy` AND `energy_type = grid` AND active at `ts.date()`.
2. For each percentage tariff active at `ts.date()` whose `energy_type` matches:
   - `effective_price = grid_base_price_sum × (tariff.percentage / 100)`
   - Accumulate: `quantity` kWh at `quantity × effective_price` CHF.
   - Also track `base_total = quantity × grid_base_price_sum` (used for description rendering).

### 4.5 Producer credit allocation (per timestamp)

For **each** production (feed-in) reading:

```
ts                    = reading.timestamp
produced_kwh          = reading.energy_kwh
zev_production_at_ts  = sum of all OUT readings at ts
zev_consumption_at_ts = sum of all IN readings at ts
local_pool_at_ts      = min(zev_production_at_ts, zev_consumption_at_ts)
export_pool_at_ts     = max(zev_production_at_ts − zev_consumption_at_ts, 0)

IF zev_production_at_ts > 0:
    producer_share   = produced_kwh / zev_production_at_ts
    local_sold_kwh   = local_pool_at_ts × producer_share
    exported_kwh     = export_pool_at_ts × producer_share
ELSE:
    local_sold_kwh = 0
    exported_kwh   = 0
```

#### 4.5.1 Local energy credit

For `local_sold_kwh > 0`: apply all `energy`-mode tariffs with `energy_type = local` **as negative amounts** (credits).  Also apply matching `percentage_of_energy` tariffs as negative.

These are accumulated in a separate **`producer_credit`** bucket so the line item is distinct from the consumer's local-energy charge.

#### 4.5.2 Feed-in compensation

For `exported_kwh > 0`: apply all `energy`-mode tariffs with `energy_type = feed_in` **as negative amounts** (credits).

### 4.6 Fixed-fee tariffs

Fixed fees are computed **after** all timestamp-level processing.  They apply to every tariff whose `billing_mode ∉ {energy, percentage_of_energy}`.

#### 4.6.1 Billable months

A **billable month** is any calendar month whose first-to-last day range intersects the overlap of `[period_start, period_end]` and `[tariff.valid_from, tariff.valid_to]`.

```
overlap_start = max(period_start, tariff.valid_from)
overlap_end   = min(period_end, tariff.valid_to or period_end)
billable_months = count of calendar months touched by [overlap_start, overlap_end]
```

Example: `period_start = Jan 15`, `period_end = Feb 14`, `tariff valid_from = Jan 1` → touches January and February → `billable_months = 2`.

Months are **not prorated**: touching any day in a month counts the full month.

#### 4.6.2 Per-mode computation

| Mode | quantity | unit_price |
|---|---|---|
| `monthly_fee` | `billable_months` | `fixed_price_chf` |
| `yearly_fee` | `billable_months` | `fixed_price_chf / 12` |
| `per_metering_point_monthly_fee` | `metering_point_months` (see below) | `fixed_price_chf` |
| `per_metering_point_yearly_fee` | `metering_point_months` (see below) | `fixed_price_chf / 12` |

**Metering-point-months:** for each billable calendar month in the tariff overlap, count the number of **distinct active metering points** assigned to the participant during that month. A metering point counts for a month if:
- It has an active assignment to the participant overlapping that month.
- `metering_point.is_active = True`.

Sum across all months to get the total metering-point-months.

If `metering_point_months = 0`, the tariff produces no line item.

### 4.7 Item accumulation

All tariff applications use a shared **accumulator map** keyed by `"{tariff_id}:{bucket}"`.

- Default bucket: `"default"` (consumers).
- Producer-credit bucket: `"producer_credit"` (for local-energy credits on producers).

Each accumulator entry tracks:
- `quantity` (running sum of kWh or months)
- `total` (running sum of CHF, before rounding)
- `unit` (`"kWh"` or `"month"`)
- `base_total` (for percentage-of-energy tariffs: running sum of `quantity × grid_base_price_sum`)

Zero-quantity + zero-total entries are skipped.

### 4.8 VAT resolution

```
IF zev.vat_number is blank or empty:
    vat_rate = 0
ELSE:
    vat_rate = VatRate.active_for_day(period_end).rate   # or 0 if no active rate
```

`VatRate` records have non-overlapping `[valid_from, valid_to]` windows.  The rate active on `period_end` is used for the entire invoice.

---

## 5. Rounding rules

| Value | Precision | Rounding mode |
|---|---|---|
| kWh quantities (`total_local_kwh`, `total_grid_kwh`, `total_feed_in_kwh`, line-item quantities) | 4 decimal places (`0.0001`) | `ROUND_HALF_UP` |
| Line-item `total_chf` | 2 decimal places (`0.01`) | `ROUND_HALF_UP` |
| Line-item `unit_price_chf` | 5 decimal places (`0.00001`) | `ROUND_HALF_UP` |
| `subtotal_chf` | 2 decimal places | `ROUND_HALF_UP` |
| `vat_chf` | 2 decimal places | `ROUND_HALF_UP` |
| `total_chf` | exact: `subtotal_chf + vat_chf` | (already rounded) |

`unit_price` is back-calculated: `total / quantity` (rounded to 5 dp).  This avoids per-reading rounding drift.

`subtotal_chf` is the sum of already-rounded line-item totals.

---

## 6. Actors, permissions, and ZEV scope

- `admin` and `zev_owner` can trigger invoice generation and manage tariffs within their ZEVs.
- `participant` consumes resulting invoice information only (read-only).

### 6.1 Tariff preset export

**Endpoint:** `GET /api/v1/tariffs/tariffs/export/?zev_id=<uuid>`

**Permission:** `IsAuthenticated`, `IsZevOwnerOrAdmin`

**Behavior:**

1. Requires `zev_id` query parameter (400 if missing).
2. Resolves ZEV via `_get_accessible_zev` — admin can access any ZEV; owner
   can access only owned ZEVs (404 if not found or not accessible).
3. Queries all tariffs for the ZEV; returns 404 if none exist.
4. Returns a JSON array of tariff presets using `_serialize_tariff_preset`.

**Preset shape** (per tariff):

| Field | Type | Notes |
|---|---|---|
| `name` | string | |
| `category` | string | `energy`, `grid_fees`, `levies`, `metering` |
| `billing_mode` | string | One of the 6 billing modes |
| `energy_type` | string \| null | `local`, `grid`, `feed_in`, or `null` |
| `fixed_price_chf` | string \| null | Decimal as string, `null` when N/A |
| `percentage` | string \| null | Decimal as string, populated for `percentage_of_energy` |
| `valid_from` | string | ISO 8601 date |
| `valid_to` | string \| null | ISO 8601 date or `null` |
| `notes` | string | |
| `periods` | array | Nested period presets (below) |

**Period preset shape:**

| Field | Type | Notes |
|---|---|---|
| `period_type` | string | `flat`, `high`, `low` |
| `price_chf_per_kwh` | string | Decimal as string |
| `time_from` | string \| null | ISO 8601 time or `null` |
| `time_to` | string \| null | ISO 8601 time or `null` |
| `weekdays` | string | Comma-separated day codes or empty |

Stripped fields: `id`, `zev`, `created_at`, `updated_at` are excluded so the
preset is portable across ZEVs.

### 6.2 Tariff preset import

**Endpoint:** `POST /api/v1/tariffs/tariffs/import/`

**Permission:** `IsAuthenticated`, `IsZevOwnerOrAdmin`

**Request body:**

```json
{
  "zev_id": "<uuid>",
  "tariffs": [ /* array of preset objects (§6.1 shape) */ ]
}
```

**Behavior:**

1. Validates `zev_id` (400 if missing) and `tariffs` array (400 if missing or
   empty).
2. Resolves ZEV via `_get_accessible_zev` (404 if not found or not accessible).
3. Wraps all creation in `transaction.atomic()` — any validation failure rolls
   back all tariffs.
4. For each preset:
   - Strips `id`, `zev`, `created_at`, `updated_at`; sets `zev` to target ZEV.
   - Validates via `TariffSerializer`; raises on invalid data.
   - Creates `Tariff`, then creates each nested `TariffPeriod` via
     `TariffPeriodSerializer`.
5. Returns 201 with `{ "created": <count>, "tariffs": [ ...serialized ] }`.
6. On any validation error, returns 400 with `{ "error": "<message>" }`.

### 6.3 Frontend: export/import UI

**File:** `frontend/src/pages/TariffsPage.tsx`

The tariffs page provides two toolbar buttons visible to `admin` and
`zev_owner` roles:

- **Export JSON** — opens a `FormModal` confirming the export. On confirm,
  calls `exportTariffs(selectedZevId)`, converts the response to a JSON blob,
  and triggers a browser download as `tariffs-<zevId>.json`.
- **Import JSON** — opens a `FormModal` with a file input (`accept=".json"`).
  On file selection, parses the JSON, validates it is an array, and calls
  `importMutation.mutate({ zevId, tariffs })`. On success, invalidates
  `['tariffs']` and `['tariff-periods']` query caches.

### 6.4 TypeScript types

```typescript
// frontend/src/types/api.ts
interface TariffPresetPeriod {
    period_type: 'flat' | 'high' | 'low'
    price_chf_per_kwh: string
    time_from?: string | null
    time_to?: string | null
    weekdays?: string
}

interface TariffPreset {
    name: string
    category: 'energy' | 'grid_fees' | 'levies' | 'metering'
    billing_mode: TariffBillingMode
    energy_type?: 'local' | 'grid' | 'feed_in' | null
    fixed_price_chf?: string | null
    percentage?: string | null
    valid_from: string
    valid_to?: string | null
    notes?: string
    periods: TariffPresetPeriod[]
}
```

```typescript
// frontend/src/lib/api.ts
exportTariffs(zevId: string): Promise<TariffPreset[]>
importTariffs(zevId: string, tariffs: TariffPreset[]): Promise<{ created: number; tariffs: Tariff[] }>
```

---

## 7. Invoice line-item construction

### 7.1 Item type mapping

| Condition | `item_type` |
|---|---|
| `billing_mode ∈ {energy, percentage_of_energy}` and `energy_type = feed_in` | `feed_in` |
| `billing_mode ∈ {energy, percentage_of_energy}` and `energy_type = grid` | `grid_energy` |
| `billing_mode ∈ {energy, percentage_of_energy}` and `energy_type = local` | `local_energy` |
| Fixed-fee mode with `fixed_price_chf < 0` | `credit` |
| Fixed-fee mode with `fixed_price_chf ≥ 0` | `fee` |

### 7.2 Description generation

Descriptions are **localized** using the ZEV's `invoice_language` (de/fr/it/en).

| Billing mode | Description format |
|---|---|
| `energy` | `"{tariff.name}"` |
| `percentage_of_energy` | `"{tariff.name} ({pct}%)"` or `"{tariff.name} ({pct}% of CHF {base_rate}/kWh)"` when base rate is known |
| `monthly_fee` | `"{tariff.name} ({n} Monat/Monate)"` |
| `yearly_fee` | `"{tariff.name} ({n} monatliche Rate(n) der Jahresgebühr)"` |
| `per_metering_point_monthly_fee` | `"{tariff.name} ({n} Messpunkt-Monat(e))"` |
| `per_metering_point_yearly_fee` | `"{tariff.name} ({n} monatliche Rate(n) pro Messpunkt)"` |

Singular vs. plural forms are selected based on `quantity == 1`.

### 7.3 Sort order

Line items are sorted by a deterministic integer `sort_order` to group related items:

```
sort_order = category_rank + energy_type_rank + billing_mode_rank
```

| Category | Rank | | Energy type | Rank | | Billing mode | Rank |
|---|---|---|---|---|---|---|---|
| `energy` | 100 | | `local` | 10 | | `energy` | 0 |
| `grid_fees` | 200 | | `grid` | 20 | | `percentage_of_energy` | 1 |
| `levies` | 300 | | `feed_in` | 30 | | `monthly_fee` | 2 |
| (other) | 900 | | (none) | 40 | | `yearly_fee` | 3 |
| | | | | | | `per_mp_monthly` | 4 |
| | | | | | | `per_mp_yearly` | 5 |

Within the same sort order, items are sorted by `tariff.name` (case-insensitive).

---

## 8. Worked examples

### 8.1 Basic local + grid allocation (single consumer, single producer)

**Setup:**
- 1 participant (Alice) with 1 consumption MP and 1 production MP
- Tariffs: local = 0.15 CHF/kWh, grid = 0.25 CHF/kWh, feed-in = 0.08 CHF/kWh (all flat)
- Period: January 2026

**Readings at 2026-01-15 00:00 UTC:**
- Consumption MP: 10.0 kWh IN
- Production MP: 6.0 kWh OUT

**Allocation:**
```
zev_consumption = 10.0, zev_production = 6.0
local_pool = min(6.0, 10.0) = 6.0
Alice share = 10.0 / 10.0 = 1.0 (sole consumer)
r_local = min(10.0, 6.0 × 1.0) = 6.0
r_grid  = 10.0 − 6.0 = 4.0
```

**Producer credit (Alice is also the producer):**
```
export_pool = max(6.0 − 10.0, 0) = 0.0
local_sold  = 6.0 × (6.0 / 6.0) = 6.0
exported    = 0.0
```

**Line items:**

| Description | Qty (kWh) | Unit price | Total |
|---|---|---|---|
| Local tariff (consumer) | 6.0 | 0.15 | 0.90 |
| Grid tariff (consumer) | 4.0 | 0.25 | 1.00 |
| Local tariff (producer credit) | 6.0 | 0.15 | −0.90 |

**Invoice:** `subtotal = 0.90 + 1.00 − 0.90 = 1.00 CHF` (3 line items; zero-quantity entries are skipped per §4.7)

### 8.2 Multiple producers with export

**Setup:**
- Alice: 1 production MP (6 kWh OUT)
- Charlie: 1 production MP (4 kWh OUT)
- Bob: 1 consumption MP (5 kWh IN)
- Same tariffs as §8.1

**At timestamp ts:**
```
zev_production  = 6 + 4 = 10 kWh
zev_consumption = 5 kWh
local_pool      = min(10, 5) = 5 kWh
export_pool     = 10 − 5 = 5 kWh
```

**Bob's allocation:**
```
r_local = min(5, 5 × 1.0) = 5 kWh
r_grid  = 0 kWh
```

**Alice's producer credit:**
```
producer_share = 6 / 10 = 0.6
local_sold     = 5 × 0.6 = 3.0 kWh  → credit = −3.0 × 0.15 = −0.45
exported       = 5 × 0.6 = 3.0 kWh  → credit = −3.0 × 0.08 = −0.24
```

**Charlie's producer credit:**
```
producer_share = 4 / 10 = 0.4
local_sold     = 5 × 0.4 = 2.0 kWh  → credit = −2.0 × 0.15 = −0.30
exported       = 5 × 0.4 = 2.0 kWh  → credit = −2.0 × 0.08 = −0.16
```

### 8.3 Fixed fees across billing period boundaries

**Setup:**
- Period: Jan 15 – Feb 14, 2026
- Monthly service fee: 12.00 CHF/month (valid from Jan 1)
- Annual platform fee: 120.00 CHF/year (valid from Jan 1)

**Computation:**
```
Billable months = 2 (touches January and February)

Monthly fee:  2 × 12.00 = 24.00 CHF
Annual fee:   2 × (120.00 / 12) = 2 × 10.00 = 20.00 CHF
```

### 8.4 Per-metering-point fees

**Setup:**
- Period: Jan 15 – Feb 14, 2026
- Participant has 2 active metering points (consumption + production) assigned for full period
- Per-MP monthly fee: 3.00 CHF/MP/month
- Per-MP yearly fee: 120.00 CHF/MP/year

**Computation:**
```
January:  2 active metering points → 2 MP-months
February: 2 active metering points → 2 MP-months
Total metering-point-months = 4

Per-MP monthly: 4 × 3.00  = 12.00 CHF
Per-MP yearly:  4 × (120.00 / 12) = 4 × 10.00 = 40.00 CHF
```

### 8.5 Percentage-of-energy tariff

**Setup (extends §8.1):**
- Additional grid-fee tariff: 0.05 CHF/kWh (energy mode, grid)
- Additional levy tariff: 0.02 CHF/kWh (energy mode, grid)
- Percentage tariff: 50%, energy_type = local

```
Grid base price sum = 0.25 + 0.05 + 0.02 = 0.32 CHF/kWh
Effective price     = 0.32 × 50/100 = 0.16 CHF/kWh

Consumer (local kWh = 6.0):  6.0 × 0.16 = +0.96 CHF
Producer credit:              6.0 × 0.16 = −0.96 CHF
Net: 0.00 CHF  (the surcharge passes through symmetrically)
```

The description renders as: `"Surcharge 50% (50% von CHF 0.32/kWh)"` (German).

---

## 9. Async and integration behavior

- Invoice generation may be triggered asynchronously for heavy periods (via Celery).
- The engine runs inside `@transaction.atomic`; partial failures roll back cleanly.
- Re-runs / regeneration must honor locking rules (§4.0).

---

## 10. Observability, auditability, and security

- Calculation provenance is inspectable through invoice line items: each item links to a tariff category, quantity, unit price, and total.
- The grid base price used for percentage-of-energy items is preserved in the item's description (e.g. `"50% von CHF 0.32/kWh"`).
- Role/scoped access ensures only authorized actors can view billing artifacts.
- Engine logs invoice number, participant name, and total CHF on successful generation.

---

## 11. Rollout and rollback

- Engine changes require regression run against the engine test fixture set.
- Rollback must not corrupt existing invoice states and totals.
- Tariff validity windows ensure historical invoices remain reproducible: changing a tariff's future `valid_from` does not affect already-generated invoices.

---

## 12. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Allocation regressions in edge timestamps | High | Golden-case regression tests and ADR alignment checks |
| Historical invoice drift after tariff changes | High | Versioned validity windows and non-mutating historical invoices |
| Rounding/VAT discrepancies | Medium | Currency rounding tests and explicit VAT selection tests |
| Zero-production timestamps causing division by zero | Medium | Guard clause: `if zev_production_at_ts > 0` before share computation |
| Overlapping tariff validity windows | Medium | Tariff matching applies **all** active tariffs (no conflict — they accumulate) |

---

## 13. Test plan

### Backend (`invoices/test_engine.py`)

| Test case | Validates |
|---|---|
| Local + grid pricing (single participant) | §4.3/4.4 allocation, 3-item invoice |
| Categories and fixed fees combined | §4.6, category segregation, monthly/yearly fee math |
| Fixed fees across month boundaries | §4.6.1 non-prorated month counting |
| Per-metering-point monthly and yearly fees | §4.6.2 MP-month accumulation |
| Percentage-of-energy billing mode | §4.4.2 base-rate computation, symmetric consumer/producer |
| Multi-producer with export | §4.5 producer share allocation, feed-in credits |

### Backend (`tariffs/tests.py`) — export/import

| Test case | Validates |
|---|---|
| `test_owner_can_export_tariffs_as_json` | §6.1: export returns preset array, strips `id`/`zev`, includes nested periods without `tariff` FK |
| `test_owner_can_import_tariffs_from_json` | §6.2: import creates tariff + periods in target ZEV, returns 201 with created count |

### Frontend

- Tariff management page behaviors and invoice detail rendering
- Build and type checks (`npm run build`)

### Manual verification

- Verify worked examples (§8) against generated invoices
- Validate VAT / no-VAT totals for same input period

---

## 14. Acceptance criteria

- [ ] Timestamp-level allocation matches the formulas in §4.3
- [ ] All six billing modes produce correct quantities and totals per §4.4–4.6
- [ ] Producer credits are symmetric with consumer charges for local energy
- [ ] Fixed fees count billable months without proration (§4.6.1)
- [ ] Rounding matches §5 for all output fields
- [ ] VAT is applied only when `zev.vat_number` is set (§4.8)
- [ ] Worked examples (§8) pass as automated tests
- [ ] Historical invoice totals remain stable across non-historical tariff changes
