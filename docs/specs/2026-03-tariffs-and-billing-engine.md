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
| Fixed-fee billing | Monthly, yearly, per-metering-point monthly/yearly, shared monthly/yearly |
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
| `split_key` | `SplitKey` (`equal` \| `weight`) | Default `equal`. Read only by the two `SHARED_*` billing modes (§3.4): `equal` divides the fee by headcount (today's behaviour, byte-identical); `weight` divides it by `Participant.allocation_weight` — the same key a `COMMUNITY`-mode metering point always uses (`SPEC-2026-08-shared-metering-points` §7.2). Inert on the other six billing modes |

A tariff is **active on day `d`** iff `valid_from ≤ d` and (`valid_to IS NULL` or `valid_to ≥ d`).

### 3.1.1 Tariff series (versioning)

Every tariff in a ZEV sharing a `name` is a **version** of one **series**.  This
is not a convention layered on the data — it follows from the overlap rule
below: versions of a series form a non-overlapping timeline by construction, and
§4.4.1 already selects the right one because tariff resolution is evaluated
**per day**, not once per invoice.

There is no separate series table.  The series is derived from `(zev, name)`;
helpers live in `tariffs/series.py`.

Every version of one series must agree on `category`, `billing_mode`, and
`energy_type` (`SERIES_FIELDS`), enforced in `Tariff.clean()`.  Without that,
"the same tariff over time" would be meaningless and comparing versions could
compare a local-energy rate against a grid fee.  `split_key` is **not** in
`SERIES_FIELDS`: a series may change its split key across versions (for
example switching a shared fee from headcount to weight).  `new_version` and
`duplicate` still copy `split_key` from the source — without that copy a
weight-split shared fee silently reverts to the model default `equal` on the
new row, and every subsequent invoice under that version splits by headcount.

**Prices are not on the tariff.**  For `energy` mode they live on
`TariffPeriod`; for fixed-fee modes on `fixed_price_chf`; a
`percentage_of_energy` tariff has no own price at all.  Any operation that
copies a version must therefore copy its price bands too, or the copy prices
nothing.

#### Gaps are a billing hazard

A day covered by **no** version of a series is not an error anywhere today, and
its consequences are silent: §4.4.1 prices energy only against tariffs active on
that day, so the allocated kWh still appear on the invoice while no line item is
produced.

Measured on a 3-month invoice with a one-month gap and 500 kWh consumed inside
it:

```
grid kWh on the invoice: 500.0000
line items:              0
subtotal CHF:            0.00
```

`find_gaps()` reports interior gaps so callers can surface them.  Only interior
gaps count: the stretch before a series begins, and the stretch after an
end-dated last version, are simply periods the series does not cover.

#### Version window arithmetic

`plan_new_version(versions, valid_from)` decides how a new version slots in:

- The **predecessor** (greatest `valid_from` below the new one) is truncated to
  `valid_from − 1 day`, but **only** if it would otherwise overlap.  A
  predecessor that already ends earlier is left alone — extending a closed
  window would change what that period bills, and the gap may be deliberate.
- The new version is capped at `successor.valid_from − 1 day` when a later
  version exists, so a mid-chain insert is bounded on **both** sides.  Without
  the upper bound the new version would swallow its successor's window and be
  rejected by the overlap guard for reasons the caller cannot see.
- Two versions of one series may not share a `valid_from`.

OpenZEV rejects overlapping validity windows for two tariffs of the same
`(zev, name)` — regardless of billing mode.

The rule is deliberately keyed on **name**, not on
`(category, billing_mode, energy_type)`.  A ZEV normally carries several
simultaneous per-kWh components inside one category — grid fees are
*Netznutzung* **and** *Systemdienstleistung*; levies are the *Netzzuschlag*
**and** a cantonal charge — and §4.4.1 accumulates them into separate invoice
lines by design (see also the risk table in §12).  Keying the check on the
category tuple made that ordinary structure unrepresentable.

What the check does catch is the case that is almost always a mistake:
a new seasonal version of a tariff created without closing the previous one,
where both windows stay open and every participant is billed twice with nothing
to signal it.

The check covers fixed-fee modes too.  It previously applied only to
`energy` and `percentage_of_energy`, so a duplicated monthly fee was charged
twice unguarded.

### 3.2 TariffPeriod (price bands within a tariff)

| Field | Type | Description |
|---|---|---|
| `tariff` | FK → `Tariff` | Parent tariff |
| `period_type` | `PeriodType` | `flat`, `high` (HT), `low` (NT), or `band` (see §3.2c) |
| `label` | `CharField(60)` | Name for a `band`; blank falls back to its window. Unused by the other types |
| `price_chf_per_kwh` | `Decimal(8,5)` | Price in CHF per kWh |
| `time_from` | `TimeField` (nullable) | Start of the window (required for every type but `flat`) |
| `time_to` | `TimeField` (nullable) | End of the window (exclusive) |
| `weekdays` | `CharField(20)` | Comma-separated weekday numbers `0`–`6` (Mon–Sun); blank = all days |
| `months` | `CharField(40)` | Comma-separated month numbers `1`–`12`; blank = all months |

Both masks are validated on write (`validate_weekday_list`, `validate_month_list`
in `tariffs/models.py`): the engine parses them with a bare `int()`, so a stray
value has to be refused at entry rather than discovered at invoice time.

**Ordering** is `["period_type", F("time_from").asc(nulls_first=True), "id"]`,
so a tariff's bands read down the day. The null placement is stated rather than
inherited: `time_from` is null for flat bands, SQLite and Postgres disagree on
where nulls sort, and the engine's fallback reads `periods[0]` — that must be
the same row on every database. `id` keeps the order total, which
`testing/test_pagination_ordering.py` enforces for every model (its helper
reads through `OrderBy` expressions to the column they sort on).

The frontend sorts again for display, by season first
(`features/tariffs/recurrence.ts`, `seasonSortKey`).

**Period matching rules** (evaluated per-timestamp, `invoices/engine.py:_get_tariff_price`):

1. Restrict to periods whose `months` contain the timestamp's month. A blank
   mask matches every month, so every period predating seasonal support
   qualifies unchanged.
2. Among those, if a `flat` period exists → use its price; ignore time/weekday.
3. For every other period: extract the timestamp's **time** and **weekday**.
   Match periods where `time_from ≤ time < time_to` and weekday ∈ allowed weekdays.
   The number of such periods is irrelevant — a band is matched by its window,
   never by its name, so three or five resolve exactly as two do.
4. **Fallback:** when no period matches the hour, the day's **first band in this
   season** — `periods[0]` under the ordering above, which is the earliest
   window. Preferring an in-season band matters once seasons exist: billing a
   January night at the summer rate would be the worse guess.

The month check comes **first, before the flat short-circuit**. A winter-only
flat band that short-circuited on `period_type` would bill its winter price in
July, which is the whole hazard seasonal support introduces.

Step 2 is only safe because a flat band may not share months with a timed one —
see §3.2c.

### 3.2c Tariffs with more than two bands

`PeriodType` names the two bands a Swiss tariff traditionally has. HT and NT are
not merely labels: the contract PDF and the price-history chart both look bands
up *by name*, so a third band was previously not just unstorable but invisible
where it did exist.

A tariff with three or more prices has no such names — the VSE/AES standard
does not label its bands at all — so those bands are stored as `band` and told
apart by their windows. The mapping is by count, not by preference:

| Distinct prices in one season | Stored as |
|---|---|
| 1 | one `flat` band, no window |
| 2 | `high` and `low` — the existing shape, unchanged |
| ≥ 3 | all `band`, ordered by start time |

`TariffPeriod.display_name` is what to call a band where a name is needed: the
type's own name for `flat`/`high`/`low`, and for a `band` its `label` if one was
given, else its window (`07:00–17:00`), which is the thing that actually
distinguishes it. The frontend mirrors this in `features/tariffs/bands.ts`
(`bandName`), so a band is called the same thing on screen and on the contract.

**A flat band may not share months with a timed band.** The engine returns a
flat band's price without looking at any window (step 2 above), so where both
apply the flat price wins every hour and the timed bands are dead weight that
still print on the contract. `TariffPeriodSerializer._reject_flat_beside_timed_bands`
refuses that combination in either direction. It is checked **per season**, not
per tariff: winter-flat with summer-HT/NT is an ordinary shape, and the flat
band never gets the chance to short-circuit a month it does not apply in. The
check is serializer-level, so it governs the API; `bulk_create` paths (the
version copy, the archive importer, the tariff importer) build their rows from
already-valid data.

Consumers:

- **Contract PDF** takes timed bands *by exclusion* (`period_type != FLAT`)
  rather than by naming HIGH and LOW, so all of them print. A `band` row is
  described by `label` or window; `tariff_band` is the last-resort name for a
  band with neither.
- **Price-history chart** gives each unnamed band its own series, keyed
  `band-0…band-N` by position — meaningful because the model orders by start
  time, so one line follows the same band of the day across versions — and
  labelled from `bandLabels`. Named bands keep their fixed colours; unnamed
  ones cycle the consumer ramp.
- **New version / duplicate** copy `label` along with the rest of the band.
- The form offers `band` as a fourth period type with an optional name. The
  label is cleared when the type is switched away from `band`, so one left
  behind cannot surface on a contract under a name nothing set.

Remaining gap: nothing enforces that a tariff's bands cover the whole day. The
fallback above is deterministic and stated rather than accidental, and the
importer warns when a document leaves hours unpriced — but a hand-entered
tariff can still have a hole. Enforcing coverage would make a half-entered
tariff invalid mid-edit, the same reason month coverage is not enforced either.

### 3.2b Seasonal bands

Winter/summer pricing is ordinary in Switzerland. A seasonal tariff is several
bands over one tariff, each restricted to its months — and seasons combine with
HT/NT, so a tariff can carry four bands and four distinct prices even though
`PeriodType` offers only three slots. That works because `period_type` only has
to tell apart bands competing for the same moment, and a winter band never
competes with a summer one.

`tariffs/periods.py` holds what both the engine and the contract PDF need:
`months_of` / `weekdays_of` (parsed once and memoised on the instance, since
the engine reads them per reading), and `month_ranges`, which treats December
and January as adjacent so a winter season reads as one `Oct–Mar` range rather
than two the reader has to piece together.

Consequences elsewhere:

- **Contract PDF** (`invoices/contract_pdf.py`) renders one row per *band*, not
  one per band type, and qualifies a seasonal row with its month range
  (`_band_description`). Picking the first band of a type would print a winter
  price with nothing to say it applies for half the year.
- **New version / duplicate** copy `months` along with the rest of the band. A
  copy that dropped it would keep the winter price and apply it all year.
- **Price-history chart** (`features/tariffs/priceHistory.ts`) splits each
  version at its season boundaries and charts the result as steps, which is
  what a seasonal price actually does over time. A tariff with no seasonal band
  is passed through untouched.
- **The band form** (`features/tariffs/RecurrenceChips.tsx`) sets both axes
  with toggle groups rather than free-text number lists. Asking the user to
  know that Monday is `0` while January is `1` was tolerable for one axis and
  not for two, and a typo was only reported by the server. Blank is rendered as
  *every* chip lit, so an unrestricted band shows what it does rather than
  showing nothing, and turning one off reads as "not this one" instead of "now
  only this one". Selecting everything stores blank again; selecting nothing is
  refused, since a band applying on no day at all cannot be stored and would
  not mean anything if it could. The chips sit on a fixed grid — a selected
  chip is wider than an unselected one, so wrapping made every click reflow the
  rows below it.
- The **representative price** used for percentage-of-energy tariffs (contract
  PDF and chart) still takes one band per tariff. For a seasonal grid tariff
  that is one season's price — the same approximation the HT/NT case already
  makes by preferring HT.

More than two distinct prices within one season are stored as unnamed bands —
see §3.2c.

**Tests (§3.2c).** `backend/tariffs/test_multi_band_periods.py` (13): a
three-band tariff pricing each window and its boundaries; bands read back in
start-time order; an uncovered hour billing at the day's first band; band naming
by label, by window, and the named types keeping their own; the flat-beside-timed
refusal in both directions, allowed across seasons, several timed bands together,
and editing a band not colliding with itself; a new version carrying band labels.
`backend/invoices/test_contract_context.py::ContractPdfSeasonalTariffTests`
covers a three-band contract printing every band. Frontend:
`frontend/tests/tariff-bands.test.ts` (11) covers band naming and the chart
giving each unnamed band its own labelled series while leaving HT/NT and flat
tariffs as they were.

**Tests (§3.2b).** `backend/tariffs/test_seasonal_periods.py` (16): month-range wrapping;
the parsed masks being memoised; a winter flat band not pricing July; seasons and
time bands combining into four prices; a band with no months still pricing every
month; the unpriced-hour fallback staying inside its own season; weekday and month
restrictions applying together; and the write-time validation of both masks.
`backend/tariffs/test_versioning.py` covers a new version keeping each band in its
own season. `backend/invoices/test_contract_context.py::ContractPdfSeasonalTariffTests`
(3) covers the contract rows. Frontend: `frontend/tests/tariff-recurrence.test.ts` (19)
covers parsing, naming, display ordering, the toggle group's blank-means-all and
refuse-empty rules, and the chart stepping between seasons.

### 3.2a Importing bands from a grid operator's publication

Tariffs no longer have to be typed in from a PDF. `POST
/api/v1/tariffs/imports/vse/preview/` reads a grid operator's Art. 7b StromVV
tariff publication and reports the `Tariff` + `TariffPeriod` records it would
create; `.../apply/` creates the ones the user selects. Imported tariffs are
ordinary tariffs — nothing in this document special-cases them.

Two consequences are worth knowing here, because they follow from the shape of
`Tariff` and `TariffPeriod` rather than from the import:

- One published tariff carrying both a base fee and a per-kWh price becomes
  **two** tariffs, because `Tariff` has a single `billing_mode`, named
  `"… (Grundpreis)"` and `"… (Arbeitspreis)"`.
- Seasonal bands (`months[]`) are imported: bands are grouped by their month
  set and the band shape is decided per season. Groups whose months
  merely *overlap* are refused, because which one prices the shared months
  would be ambiguous.
- A published base price is an amount per month, but the document cannot say
  *who* pays it, so the preview asks: a fee row is imported as
  `shared_monthly_fee`, `monthly_fee` or `per_metering_point_monthly_fee` at
  the user's choice. The yearly modes are never offered — they read
  `fixed_price_chf` as a per-year amount.
- What decides the shape of a published multi-band tariff is the number of
  **distinct prices**, not the number of windows: a three-window/two-price
  document maps onto one `high` and two `low` rows, while three or more
  distinct prices become unnamed `band` rows (§3.2c).

Full mapping table, the constructs that are refused, and the fetch guards:
`2026-09-vse-tariff-import.md`.

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
| `shared_monthly_fee` | Number of charged months (see §4.6.3) | Derived: `fixed_price_chf` divided per month by that month's participant count (`split_key = equal`) or weight sum (`split_key = weight`) | `month` |
| `shared_yearly_fee` | Number of charged months (see §4.6.3) | Derived: `fixed_price_chf / 12` divided per month by that month's participant count (`split_key = equal`) or weight sum (`split_key = weight`) | `month` |

> **`fixed_price_chf` changes meaning for the two shared modes.** For every
> other fixed fee it is the amount *one participant* pays. For `shared_*` it is
> the amount the *whole community* pays, which the engine divides between its
> members. Their unit price is therefore derived rather than configured.

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
| `vat_rate` | Resolved VAT rate (decimal fraction, e.g. `0.0810`); 0 unless `vat_mode = registered` |
| `vat_chf` | `subtotal_chf × vat_rate`, rounded to 0.01 |
| `embedded_vat_chf` | Non-recoverable VAT folded into the line totals under `vat_mode = inclusive`; null otherwise (§4.8) |
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

The overlap condition only *selects* metering points and the ZEV-wide pools.
Attribution of individual readings to a participant is **per timestamp** (ADR
0013): a reading is billed to the participant whose assignment is active on
`reading.timestamp.date()`. Assignments are date-granular (ADR 0001) — a
reading at 00:30 on `valid_from` day belongs to the new holder, and a reading
on the last day `valid_to` belongs to the outgoing holder. Readings in an
assignment gap belong to nobody.

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
ts          = reading.timestamp
resolution  = assignment_at(metering_point_id, ts)   # holder + allocation_mode, or None for a gap

IF resolution is None:
    SKIP this reading, count as a gap             (no assignment covers ts)
IF resolution.allocation_mode != PERSONAL OR resolution.holder_id != participant.id:
    SKIP this reading, NOT counted as a gap        (community energy — see §4.3a — or somebody else's meter)

participant_kwh       = reading.energy_kwh
zev_consumption_at_ts = sum of all IN readings at ts across ZEV
zev_production_at_ts  = sum of all OUT readings at ts across ZEV
local_pool_at_ts      = min(zev_production_at_ts, zev_consumption_at_ts)

IF zev_consumption_at_ts > 0 AND local_pool_at_ts > 0:
    participant_share  = participant_kwh / zev_consumption_at_ts
    r_local            = local_pool_at_ts × participant_share
ELSE:
    r_local = 0

r_grid = participant_kwh − r_local
```

Before shared metering points (`SPEC-2026-08-shared-metering-points`), this gate was a plain `participant_at(...) != participant.id` check and every non-matching reading counted as a skipped gap. It is now mode-aware (`assignment_at`, which additionally reports `allocation_mode`) so a `COMMUNITY`-mode assignment's readings — priced once and split by weight in §4.3a — are neither billed to the holder personally nor miscounted as unattributed gap energy. A meter whose mode changes mid-period is billed correctly on both sides: personal readings from a `PERSONAL` window stay attributed to the holder in full, and readings from a later `COMMUNITY` window on the *same* metering point are excluded here and picked up by §4.3a instead — the gate is the only thing preventing double counting, since a community meter's readings legitimately appear in both this participant loop (gated out) and the ZEV-level community loop.

**Key invariant:** at every timestamp, each participant's consumption is split into a **local** portion (energy sourced from ZEV production) and a **grid** portion (energy from the public grid).  The local pool is capped at the lesser of total production and total consumption.  Skipped readings are **excluded from every bill** (ADR 0013): they are not charged to the previous holder, the new holder, or the community; the ZEV-wide pool totals still include them.

**Pool coverage:** the pool is physical — `zev_consumption_at_ts`/`zev_production_at_ts` sum over **every** metering point of the ZEV, with or without an assignment in the period and regardless of the `is_active` flag. A never-assigned meter feeds the pool but is billed to nobody; a deactivated meter (`is_active = False`) still feeds the pool, and its readings are still attributed to its assignment holder — deactivation does not remove a meter from allocation. This matches across the engine, dashboards, PDFs, and annual statement (ADR 0013 pool decision). `is_active` gates nothing in the billing engine at all (§4.6.5) — it is a list/admin status only. A metering point with no assignment overlapping the period still counts in the pool but is billed to nobody; that is a data-quality condition rather than a valid steady state — every metering point should have a holder for each period it has readings (a common-area *Allgemein* meter is assigned to a community / Verwaltung participant), and such holder-less readings are surfaced by the metering data-quality status check.

**Assignment matching** uses the *UTC civil date* of the reading's timestamp (`_utc_date(ts)` — `ts.astimezone(tz.utc).date()`), consistent with period, tariff, and completeness conventions (ADR 0007 — all timestamps are stored and queried in UTC). A reading at 22:30 UTC on the day an assignment ends still belongs to that day's holder even though Zurich is already on the next civil day.

**Fail-fast contracts** (implemented in `allocation/split.py`): all inputs must be `Decimal` (`TypeError` otherwise) and non-negative (`InvalidAllocationInputError`); a participant's draw above the community's total consumption, a producer's output above the community's total production, or a participant's share above the total in `proportional_share`, raises `InvalidAllocationInputError` — with consistent data these are impossible (the total includes the participant's own reading), so they indicate duplicate readings or the wrong metering-point scope. No arithmetic is clamped silently. All allocation failures (`InvalidAllocationInputError`, and `OverlappingAssignmentWindowsError` from the assignment-window index) derive from `AllocationError` (a `ValueError`), so the billing API reports them as HTTP `400` with the underlying message instead of the `409` reserved for an existing invoice (ADR 0013).

**Gap visibility:** the engine counts skipped readings and their kWh — personal consumption, personal production, community consumption, and community production separately — and logs a warning when any exist, so unattributed energy does not vanish unnoticed. Covered are readings in *intra-period* gaps of metering points assigned somewhere in the period: both reading querysets require an assignment overlapping the period, so a never-assigned meter is not covered here (it surfaces via the metering data-quality status check instead). The four counters partition the gap readings: a meter held both personally and community-wide appears in both querysets, and its gap readings are counted exactly once, on the personal side.

### 4.3a Community-allocated energy (shared metering points)

A `COMMUNITY`-mode assignment (`SPEC-2026-08-shared-metering-points`) does not change who holds the metering point — `participant` on the assignment stays the holder of record, for provenance — but it changes who pays: the meter's energy is split across every eligible participant by `Participant.allocation_weight` instead of billed to the holder alone.

**Price once, allocate second.** After the personal consumption/production loops (§4.3, §4.5), the engine iterates the ZEV's community-allocated readings once per invoice (per participant, since `generate_invoice` runs per participant):

```
FOR EACH community reading (metering points with a COMMUNITY assignment overlapping the period, direction IN):
    resolution = assignment_at(metering_point_id, ts)
    IF resolution is None OR resolution.allocation_mode != COMMUNITY:
        SKIP    (a gap, or this window is personal — billed in §4.3 instead)

    day = _utc_date(ts)
    IF NOT (participant.valid_from ≤ day ≤ participant.valid_to or open-ended):
        SKIP    (a mid-period joiner pays no share of readings before their join date;
                 a leaver's share stops at their leave date)

    weight_sum = allocation_weight_sum_by_date[day]   # sum of every eligible participant's weight on that date
    share      = participant.allocation_weight / weight_sum

    r_local, r_grid = split against the same ZEV-wide totals used in §4.3
                      (already physical — they include community meters)

    price each (energy_type, quantity) pair with the SAME tariff resolution as §4.4,
    but quantity = (r_local or r_grid) × share, and record the line under bucket="shared"
```

The date-granular weight sum (`allocation_weight_sum_by_date`, keyed by calendar date) mirrors `participant_on`'s granularity: a participant active for any part of a date is eligible for that date's full share, and a date with no eligible participant is absent from the map entirely (never zero), so a caller can never divide by it. With every participant's weight at the default `1`, the share is `1 / headcount` — the equal split that would also result from omitting the weight feature.

Community production is allocated with the **same eligibility rule and weights as consumption** — an explicit decision, not a technical necessity; a future meter-specific allocation rule could override it. The local-sold credit accumulates under `bucket="shared_producer_credit"` (kept distinct from `bucket="shared"` so a consumption charge and a production credit under the same local-energy tariff render as two separate lines, mirroring how personal energy already separates `producer_credit` from the default consumption bucket); the feed-in credit uses `bucket="shared"`.

Shared kWh accumulate into the same `total_local_kwh` / `total_grid_kwh` / `total_feed_in_kwh` invoice totals as personal energy — there is no separate "community" total on the `Invoice` model.

### 4.4 Consumer energy pricing (per timestamp)

After computing `r_local` and `r_grid` for a reading at timestamp `ts`:

#### 4.4.1 Standard energy tariffs (`billing_mode = energy`)

For each `(energy_type, quantity)` in `{(local, r_local), (grid, r_grid)}` where `quantity > 0`:

1. Find all tariffs where `billing_mode = energy`, `energy_type` matches, and tariff is active on `_utc_date(ts)`.
2. For each matching tariff, resolve the price via period matching (§3.2).
3. Accumulate: `quantity` kWh at `quantity × price` CHF.

#### 4.4.2 Percentage-of-energy tariffs (`billing_mode = percentage_of_energy`)

These tariffs price energy as a percentage of the **grid base price sum**.

1. **Grid base price sum** = sum of `price_chf_per_kwh` at `ts` for all tariffs where `billing_mode = energy` AND `energy_type = grid` AND active at `_utc_date(ts)`.
2. For each percentage tariff active at `_utc_date(ts)` whose `energy_type` matches:
   - `effective_price = grid_base_price_sum × (tariff.percentage / 100)`
   - Accumulate: `quantity` kWh at `quantity × effective_price` CHF.
   - Also track `base_total = quantity × grid_base_price_sum` (used for description rendering).

### 4.5 Producer credit allocation (per timestamp)

For **each** production (feed-in) reading:

```
ts          = reading.timestamp
resolution  = assignment_at(metering_point_id, ts)
IF resolution is None:
    SKIP this reading, count as a gap
IF resolution.allocation_mode != PERSONAL OR resolution.holder_id != participant.id:
    SKIP this reading, NOT counted as a gap   (community production — §4.3a — or somebody else's meter)
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

Same assignment matching (UTC civil date), fail-fast contracts, and gap logging as §4.3.

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
| `shared_monthly_fee` | `charged_months` (see §4.6.3) | derived — see §4.6.3 |
| `shared_yearly_fee` | `charged_months` (see §4.6.3) | derived — see §4.6.3 |

**Metering-point-months:** for each billable calendar month in the tariff overlap, count the number of **distinct metering points** assigned to the participant during that month. A metering point counts for a month if:
- It has an assignment to the participant overlapping that month.
- The window that **owns** the month (see §4.6.4) is a `PERSONAL`-mode assignment to the participant — a month owned by a `COMMUNITY`-mode window (or by another participant's window) is excluded from this personal count and billed separately in §4.6.4, with the same per-window care as the §4.3 energy gate (a meter personal in one month and community the next counts in the first and is excluded from the second). Ownership makes the counts disjoint by construction: a mid-month mode switch or holder change bills the month exactly once, on whichever side the owning window names.

Sum across all months to get the total metering-point-months.

If `metering_point_months = 0`, the tariff produces no line item — but a participant with zero personal metering points may still owe a community metering-point contribution (§4.6.4).

#### 4.6.3 Shared fees

For `shared_monthly_fee` and `shared_yearly_fee`, `fixed_price_chf` is the
amount the **community** pays, not the amount each participant pays.  The
engine divides it between the participants active in each billed month.

**The denominator depends on `tariff.split_key`** (`SPEC-2026-08-shared-metering-points`
§7.2). `split_key = equal` (the default) keeps the structure below verbatim —
the numerator is `1` and `N` is the headcount, so existing shared-fee tariffs
produce byte-identical invoices. `split_key = weight` replaces `N` with the
**sum of `Participant.allocation_weight`** active that month
(`allocation_weight_sum_by_month`) and the numerator with this participant's
own weight — the same key a `COMMUNITY`-mode metering point always uses
(§4.6.4). With every weight at the default `1`, `weight` and `equal` agree
exactly.

**Exclusion of zero-value shares:** a member whose charged months produce a
share that rounds to CHF 0.00 (half-up, like every rendered amount) gets no
line item at all — the same rule as the per-metering-point gate in §4.6.4.
This covers a zero-weight member under `split_key = weight`, who previously
received a bogus "`N Monate / CHF 0.00`" line, and equally a `SHARED_*` fee
configured at `fixed_price_chf = 0` under *either* split key — both shapes
bill nothing. The rule is scoped to the shared paths: a plain, non-shared fee
with `fixed_price_chf = 0` still renders its CHF 0.00 line, because there the
line's point is to show that the fee exists.

**Both denominators are clamped to the same months as the numerator** — the
overlap of the invoice period *and this tariff's own validity*, not the period
alone. A tariff clipped inside the period (a version starting mid-month, which
tariff versioning makes ordinary — §3.1.1) otherwise counts a participant who
is a member of the calendar month but not of the part the tariff actually
bills: they land in the denominator while the numerator loop below skips them,
and the community recovers less than the whole fee. The weight-sum helper
therefore takes the tariff, exactly as the headcount helper always has.

```
monthly_amount = fixed_price_chf / 12  if shared_yearly_fee else fixed_price_chf
IF split_key == WEIGHT:
    numerator   = participant.allocation_weight
    denominator_for(month) = allocation_weight_sum_by_month(tariff)[month]  # weights active in the BILLED window
ELSE:
    numerator   = 1
    denominator_for(month) = N   # headcount over the same billed window, as below

total = 0
charged_months = 0
for each billable month M in the tariff overlap:
    billed_from, billed_to = M clamped to [overlap_start, overlap_end]
    N = participants of the ZEV whose validity overlaps [billed_from, billed_to]
    if N == 0:                       # nobody to share it with
        continue
    if this participant's validity does not overlap [billed_from, billed_to]:
        continue                     # not a member that month
    total += monthly_amount × numerator / denominator_for(M)
    charged_months += 1

quantity   = charged_months
unit_price = total / quantity        # derived; the average monthly share
```

If `charged_months = 0`, the tariff produces no line item.

**Both sides are evaluated per month.**  The denominator `N` is community-wide;
the months summed are only those this participant was a member of.  Getting
either wrong breaks reconciliation:

- Computing `N` once over the whole period would let a member joining in
  February retroactively dilute January's share.
- Summing every month the *tariff* was live, rather than every month the
  *participant* was a member, would bill a mid-period joiner for months before
  they arrived and over-recover the fee.

**Membership is tested against the billed part of the month**, not the whole
calendar month.  A period opening on Jan 15 therefore excludes a participant
whose validity ended Jan 10 — they receive no invoice for the period, so
counting them into `N` would leave the community short.

**Participant count source.**  `N` is derived from the ZEV's participants, not
from which invoices happen to exist.  Generating a single participant's invoice
in isolation therefore yields the same share as a full ZEV run.

**Reconciliation property.**  Across a full
`generate_invoices_for_zev(zev, period_start, period_end)` run, each billed
month's `monthly_amount` is recovered exactly once, regardless of how membership
changed during the period — subject to the rounding shortfall below.

**Rounding.**  Line totals are rounded to the centime independently
(§6), so a fee that does not divide evenly leaves the community short by up to
`N - 1` centimes per month: CHF 100 across 3 participants bills 33.33 each and
recovers 99.99.  This is deliberate.  The alternative — assigning the leftover
centimes to one participant by a deterministic order — couples every invoice to
the others and reconciles only when every participant is actually invoiced.
Consistent with the treatment of an indivisible local-energy pool, where the
unallocated remainder likewise stays where it falls rather than being
force-balanced (`ADR-0002`, §4.3).

**Owner participation.**  No special-casing: `N` counts every active
`Participant` row, and a ZEV owner who holds one is counted like any other
member.

#### 4.6.4 Community metering-point fees

For `per_metering_point_monthly_fee` and `per_metering_point_yearly_fee`,
each **active** metering point whose month is *community-owned* (defined
below) contributes its own fee — split by weight, month-granular — in
addition to (not instead of) the participant's personal
metering-point-months count from §4.6.2:

**Window ownership of a month.** Every calendar month, every active metering
point is owned by exactly one assignment window: the one with the latest
`valid_from` among the windows overlapping that month. The non-overlap rule
(`MeteringPointAssignment._validate_no_overlap`) allows at most one
assignment per metering point at any date, so "last to start" is
unambiguous. Ownership is
what keeps the personal count (§4.6.2) and this community count disjoint by
construction: each meter-month is billed on exactly one side, named by the
owning window's `allocation_mode`. A meter whose mode switches mid-month
(PERSONAL→COMMUNITY or back) — or whose holder changes mid-month — bills the
transition month exactly once, on the side of the window that starts latest
in that month. §4.6.1 already commits to a tie-break of this shape: months
are never prorated, so one side always gets the full month; this rule merely
decides *which* side. When every mode switch falls on a month boundary the
ownership pick degenerates to plain per-mode window counting, so
single-mode meters are unchanged — including `PERSONAL` → gap, where the
last overlapping window is still the personal one.

The community count must see *every* window of a metering point — including
`PERSONAL` windows and windows held by other participants — so a superseding
window can take ownership; filtering the fetch by mode would bring the
double-bill back. The personal count likewise needs the full history of the
participant's own metering points, for the same reason.

```
community_counts = for each billable month M, count distinct metering points
                    of the ZEV whose month-owning window (§4.6.4) is COMMUNITY-mode
                    (metering_point.is_active is not consulted — see §4.6.5)

total = 0
shared_months = 0
for each billable month M in community_counts:
    if this participant's validity does not overlap M (clamped to the overlap):
        continue
    weight_sum = allocation_weight_sum_by_month(tariff)[M]   # clamped to this tariff's billed window
    total += unit_price × community_counts[M] × participant.allocation_weight / weight_sum
    shared_months += 1

if shared_months > 0 and round_half_up(total, 0.01) != 0:
    add a second line item: quantity = shared_months, total = total, bucket = "shared"
```

`split_key` plays no part here — it is read only by the two `SHARED_*`
billing modes. The cost being divided belongs to a community *metering
point*, which always allocates by weight (§1.1 of the feature spec). A
per-assignment split key is a documented follow-up, out of scope.

Both weight-split paths (this one and §4.6.3) resolve their denominator per
tariff but share **one** fetch of the ZEV's participant membership rows per
invoice: the billed months differ between tariffs, the membership does not, so
querying per tariff would be an N+1 over the ZEV's tariff list.

#### 4.6.5 `is_active` is not a billing input

Neither fee counter consults `MeteringPoint.is_active` (#408). It is a
present-state boolean, and reading it while pricing a past period let an
operator action taken today change what that period cost: deactivating a meter
in December silently reduced the fee already invoiced for January, and
regenerating the same period produced a different amount with no record of why.

Every other input to these counters is resolved against the billed month.
The fact the flag was standing in for — *this meter stopped being billable on
date X* — is what `MeteringPointAssignment.valid_to` already records, with a
date, per month, and without rewriting history. **Ending billing for a meter
means closing its assignment**, not unticking the flag; a meter whose
assignment still runs is still billed, deactivated or not.

Adding a separate deactivation *date* to `MeteringPoint` was considered and
rejected: it would duplicate `valid_to` one table over and create two dates
that can disagree, with no rule for which wins.

`is_active` remains an inventory status — the badge and active/inactive filter
on the metering-point list, and the Django admin filter. #406 removed it from
the energy pool for the same reason; this closes the equivalent gap in fee
counting, leaving it with no behavioural consumer in the engine.

### 4.7 Item accumulation

All tariff applications use a shared **accumulator map** keyed by `"{tariff_id}:{bucket}"`,
or by `"{tariff_id}:{bucket}:{period_id}"` when the ZEV sets `itemize_tariff_bands`
and the tariff has more than one band (§4.7a).

- Default bucket: `"default"` (consumers).
- Producer-credit bucket: `"producer_credit"` (for local-energy credits on producers).
- Community buckets (§4.3a, §4.6.4): `"shared"` (community energy, feed-in credit, and per-metering-point fee lines) and `"shared_producer_credit"` (community local-energy production credit, kept distinct from `"shared"` so a consumption charge and a production credit under the same local-energy tariff render as separate lines). Entries in a `"shared"*` bucket get a `community_marker` appended to their description (§7.2).

Each accumulator entry tracks:
- `quantity` (running sum of kWh or months)
- `total` (running sum of CHF, before rounding)
- `unit` (`"kWh"` or `"month"`)
- `base_total` (for percentage-of-energy tariffs: running sum of `quantity × grid_base_price_sum`)
- `group_key` (the `"{tariff_id}:{bucket}"` the entry rounds against, §5)
- `period` (the band that priced it, set only when the entry is band-split)

Zero-quantity + zero-total entries are skipped.

### 4.7a Band itemisation (`Zev.itemize_tariff_bands`)

Off by default. A multi-band tariff otherwise accumulates into one entry, so
its line is priced at `total / quantity` — the quantity-weighted average of
whichever bands the participant's consumption fell into. That average matches
no band's published rate, and differs between two participants on the same
tariff, so the invoice cannot be checked against the tariff.

With the setting on, the band resolved per timestamp (§3.2b) also keys the
entry, and each band that was used bills as its own line at its own rate. A
tariff with a single band is never split: there is nothing to distinguish.

The band is named by `band_labels.band_description`, which the participation
contract also uses, so both documents call a band the same thing (§7.2). The
name is written into the line's `description` rather than stored as a foreign
key, following the rule that an invoice records what was charged rather than
referencing the pricing structure that produced it.

Percentage-of-energy tariffs are not split: their price derives from the grid
base rather than from a band of their own. Fixed fees are per-month and have
no band.

Existing invoices are untouched; the setting applies to invoices generated
after it is changed.

### 4.8 VAT resolution

`zev.vat_mode` selects one of three treatments. In all three, the rate — where
one is needed — is `VatRate.active_for_day(period_end).rate` (or 0 if no rate is
active). `VatRate` records have non-overlapping `[valid_from, valid_to]`
windows, and the rate active on `period_end` applies to the whole invoice.

| `vat_mode` | `vat_rate` on invoice | `vat_chf` | line totals | `embedded_vat_chf` |
|---|---|---|---|---|
| `not_registered` | 0 | 0 | as entered | null |
| `registered` | active rate | `subtotal × rate` | net (as entered) | null |
| `inclusive` | 0 | 0 | VAT-bearing lines grossed by `1 + rate` | non-recoverable VAT folded in |

**`registered`** is the old behaviour, and the data migration moves every ZEV
that had a non-empty `vat_number` into it (the number is now required in this
mode and forbidden in the other two).

**`inclusive`** is for a ZEV that is not VAT-registered but buys in costs that
carry VAT it cannot reclaim. Tariff prices stay net in storage. At invoice
time, each line whose tariff *bears input VAT* has its raw total multiplied by
`1 + rate` before rounding, so the derived unit price is gross too. No VAT line
appears — a non-registered issuer must not show one — but the amounts billed
are gross. The VAT thus folded in is summed into `Invoice.embedded_vat_chf`
for the operator's own records (annual statement, bookkeeping); it is never
shown on the participant invoice.

A tariff **bears input VAT** when its category is `grid_fees`, `levies` or
`metering`, or its category is `energy` and its `energy_type` is `grid`. Local
(solar) energy and the feed-in credit do not: the ZEV pays no input VAT on its
own production, and the feed-in credit is money paid out, not a purchased cost.

Rationale and alternatives: ADR 0016.

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

**Lines round against their group, not individually.** A group is one
`"{tariff_id}:{bucket}"` — a single line, or that tariff's band lines when
§4.7a applies. The group's unrounded total is rounded once, and the difference
against the individually-rounded lines is handed out a centime at a time to
the lines that lost the most in their own rounding (ties broken by magnitude,
then position, so the distribution is deterministic). A tariff therefore costs
the same whether or not its bands are itemised, and the lines still sum to
`subtotal_chf`.

The centime a line gains or gives up lands on its `total_chf` only. Its
`unit_price_chf` stays derived from the unrounded total, so an itemised line
still shows its band's real rate.

---

## 6. Actors, permissions, and ZEV scope

- `admin` and `zev_owner` can trigger invoice generation and manage tariffs within their ZEVs.
- `participant` consumes resulting invoice information only (read-only).

### 6.1 Tariff transfer (superseded)

The tariff-only JSON export and import — `GET /api/v1/tariffs/tariffs/export/`,
`POST /api/v1/tariffs/tariffs/import/`, and their `TariffExportModal` /
`TariffImportModal` UI — were **removed** and replaced by whole-ZEV transfer
(issue #389). An export with only the `tariffs` section selected produces the
same tariff structure, in an archive that also has somewhere to put it.

See `backend/zev/transfer/` for the archive contract and
`docs/user-guide/17-zev-transfer.md` for the behaviour.

The all-or-nothing-with-every-failure-reported semantics the tariff import
established are preserved: `zev/transfer/importer.py` collects failures across
every section and rolls the whole import back rather than stopping at the first
one.

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
| `energy` | `"{tariff.name}"`, or `"{tariff.name} – {band}"` when the line is band-itemised (§4.7a) |
| `percentage_of_energy` | `"{tariff.name} ({pct}%)"` or `"{tariff.name} ({pct}% of CHF {base_rate}/kWh)"` when base rate is known |
| `monthly_fee` | `"{tariff.name} ({n} Monat/Monate)"` |
| `yearly_fee` | `"{tariff.name} ({n} monatliche Rate(n) der Jahresgebühr)"` |
| `per_metering_point_monthly_fee` | `"{tariff.name} ({n} Messpunkt-Monat(e))"` |
| `per_metering_point_yearly_fee` | `"{tariff.name} ({n} monatliche Rate(n) pro Messpunkt)"` |
| `shared_monthly_fee` | `"{tariff.name} ({n} Monat/Monate, Gemeinschaftskosten anteilig)"` |
| `shared_yearly_fee` | `"{tariff.name} ({n} monatliche Rate(n) der Jahresgebühr, Gemeinschaftskosten anteilig)"` |

Singular vs. plural forms are selected based on `quantity == 1`.

**Band qualifier.** A band-itemised energy line (§4.7a) names its band with
`band_labels.band_description` — the same function the participation contract
uses, so a band the contract calls "HT (Hochtarif)" or "Peak (Okt–März)" is
called that on the invoice too. The band is set off with a dash rather than parenthesised, because band
names carry their own brackets. A line carrying both a band and the community
marker keeps them apart: `"{tariff.name} – {band} ({marker})"`.

The shared modes carry **no participant count** in the description: the
denominator is per month and can differ between the months covered by a single
line, so no one figure would be truthful.  The derived `unit_price` column
carries the participant's average monthly share instead.

**Community marker.** A line item in the `"shared"` or `"shared_producer_credit"`
bucket (§4.3a, §4.6.4 — community-allocated metering points, distinct from the
`SHARED_*` billing modes above) gets a localized `community_marker` appended:
de `"Gemeinschaftsanteil"`, fr `"Part communautaire"`, it `"Quota comunitaria"`,
en `"Community share"`. For `energy`, the format becomes
`"{tariff.name} ({marker})"`; for the month-count modes it is appended inside
the existing parentheses: `"{tariff.name} ({n} {suffix}, {marker})"`.

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
| | | | | | | `shared_monthly_fee` | 6 |
| | | | | | | `shared_yearly_fee` | 7 |

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

### 8.4a Shared fee with changing membership

**Setup:**
- Period: Jan 1 – Mar 31, 2026
- Shared monthly fee: 60.00 CHF/month for the community (valid from Jan 1)
- Participants: Alice and Bob (whole period), Carol (from Feb 1), Dave (until Jan 31)

**Per-month denominators:**
```
January:  Alice, Bob, Dave    → N = 3
February: Alice, Bob, Carol   → N = 3
March:    Alice, Bob, Carol   → N = 3
```

**Per-participant computation:**
```
Alice: 60/3 + 60/3 + 60/3 = 60.00 CHF   (3 months)
Bob:   60/3 + 60/3 + 60/3 = 60.00 CHF   (3 months)
Carol:      —  + 60/3 + 60/3 = 40.00 CHF   (2 months)
Dave:  60/3 +  —  +  —     = 20.00 CHF   (1 month)
```

**Reconciliation:** 60.00 + 60.00 + 40.00 + 20.00 = 180.00 = 3 months × 60.00.

Note Dave is invoiced at all — `generate_invoices_for_zev` invoices anyone
active at *any* point in the period — and is charged only for the month he was
a member of.

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
| `fixed_price_chf` entered per-participant on a shared fee | Medium | Field label and form hint state "total for the community"; §3.4 and §4.6.3 call out the changed meaning |
| Shared fee over- or under-recovering after a membership change | Medium | Denominator and charged months both evaluated per month (§4.6.3); reconciliation asserted across a full ZEV run |

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
| Feed-in total half-up rounding | §5 rounding table — a .00005 tie quantizes `total_feed_in_kwh` with `ROUND_HALF_UP`, matching the sibling kWh totals |

### Backend (`invoices/test_engine_allocation.py`)

| Test case | Validates |
|---|---|
| Mid-period transfer splits the period's readings between both holders | §4.1 per-timestamp attribution (ADR 0013) |
| Reading on the transfer boundary date belongs to the outgoing holder | §4.1 inclusive `valid_to` (ADR 0001) |
| Gap readings are billed to nobody | §4.1 gap exclusion (ADR 0013) |
| Producer transfer attributes output per timestamp | §4.1/§4.5 producer side |

### Backend (`invoices/test_allocation_reconciliation.py`)

| Test case | Validates |
|---|---|
| Engine bills each holder exactly their readings, gap excluded | §4.1/§4.3 gap exclusion |
| PDF stats reconcile with engine invoices | PDF stats == billed totals on the same fixture |
| Owner dashboard reconciles with engine invoices | Dashboard == billed totals, gap only in physical totals |
| Analytics and PDF stats agree on participant splits | Charting consumers are mutually consistent |
| Multi-meter fixture: two consumption meters, two producers, a bidirectional meter, producer-meter transfer, two transfers of one meter, never-assigned meter | §4.3/§4.5 allocation and pool coverage on a mixed fixture; all comparisons at the 0.0001 kWh settlement quantum |
| Producer local credits and feed-in lines reconstruct exactly to the per-timestamp split shares | §4.5 producer credits are the billed image of the allocation (ADR 0013) |
| Direction/type pairing: a consumption meter's OUT reading leaves the production pool and a production meter's IN reading leaves the consumption pool; the annual statement still agrees with the engine invoices | §4.3 pool is paired by (meter type, direction); pre-read-model union pivot grouped by direction only, inflating the statement's local share on corrupt readings |

### Backend (`allocation/tests.py`)

| Test case | Validates |
|---|---|
| Split/proportional-share arithmetic | §4.3/§4.5 formulas, shared service (ADR 0013) |
| Assignment windows: overlap handling, boundary dates, gaps | §4.1 attribution index |
| Non-`Decimal` input, negative inputs, totals above the community total | §4.3 fail-fast contracts |
| Overlapping assignment windows raise; adjacent (non-overlapping) windows pass | Fail-fast on direct-DB corruption |
| UTC civil-date matching at 22:30/00:30 boundaries, incl. a Zurich-tz timestamp | §4.3 UTC-date assignment matching |
| Conservation invariants (Σ local == pool; producer sold == consumer local) | §4.3 pool conservation |
| Exact Decimal arithmetic where floats would drift | §4.3/5 Decimal end-to-end billing contract |

### Backend (`invoices/test_shared_fee.py`)

| Test case | Validates |
|---|---|
| Per-month participant counter: stable membership, joiner, leaver, member gone before the window opens, months outside tariff validity, month with nobody active | §4.6.3 denominator, including the billed-window clamp and the absent-rather-than-zero rule |
| Sole participant carries the whole fee; three carry a third each | §4.6.3 basic split |
| Shared yearly fee is a twelfth per month | §4.6.3 `monthly_amount` |
| Joiner's line spans only their own months | §4.6.3 charged-months rule (numerator) |
| Participant with no readings still charged | Fixed fees are independent of metering |
| Negative shared amount produces a credit item | §7.1 item type |
| Reconciliation across a full ZEV run, with and without membership changes | §4.6.3 reconciliation property; worked example §8.4a |
| CHF 100 across 3 participants recovers 99.99 | §4.6.3 documented rounding shortfall |
| Description text and average-share unit price | §7.2 |
| `equal` key ignores weights entirely (isolation guarantee); `weight` key splits by weight; default is `equal`; two shared tariffs can use different keys in the same invoice; default weights reproduce the equal split under `weight`; a joiner shifts the weight-sum denominator only from their own month; a negligible-weight member bills almost nothing; an indivisible weighted share leaves the documented rappen shortfall | §4.6.3 `split_key` (`SPEC-2026-08-shared-metering-points` §7.2) |
| Zero-value shares get no line: a zero-weight member, an exact half-cent share surviving the gate (ROUND_HALF_UP, not banker's rounding), and a shared fee configured at CHF 0.00 under either split key | §4.6.3 zero-value gate |
| A tariff starting mid-month: both keys agree, a full ZEV run recovers the whole fee, and a member active *inside* the billed window still dilutes it | §4.6.3 tariff-clamped denominators (regression, #465) |

### Backend (`invoices/test_shared_metering.py`)

Community-allocated metering points (`SPEC-2026-08-shared-metering-points`):
weighted consumption/production splits (incl. the holder-of-record paying no
more than their own share, and a sole participant carrying a meter alone);
kWh-total conservation within rounding; a meter personal in one month and
community the next billing correctly on both sides with no double count and no
lost readings (§4.3a); community readings tracked in their own gap/skip counters;
per-metering-point community fees, the
disjoint-by-construction month ownership tie-break — a mid-month mode switch
or holder change bills the month exactly once, on the side of the last window
to start (§4.6.4); a mid-period joiner/leaver's
date-granular energy share vs. the month-granular fee share; the description
marker in all four locales; single-participant regeneration reproducing a full
run's share.

`invoices/test_allocation_reconciliation.py` gains a community-meter fixture
class: engine, `pdf_stats`, and `analytics` all attribute the same weighted
share, including to the meter's own holder of record — no consumer attributes
community energy to a single participant.

### Backend (`tariffs/tests.py`) — export/import

| Test case | Validates |
|---|---|
| `test_owner_can_export_tariffs_as_json` | §6.1: export returns preset array, strips `id`/`zev`, includes nested periods without `tariff` FK |
| `test_owner_can_import_tariffs_from_json` | §6.2: import creates tariff + periods in target ZEV, returns 201 with created count |
| `test_import_accepts_several_simultaneous_components_in_one_category` | §3.1: multiple per-kWh components sharing category/mode/energy type import cleanly |
| `test_import_reports_every_rejected_tariff_and_saves_nothing` | §6.2: every rejected entry reported by position and name in one response; valid entries rolled back with them |
| `test_import_rejects_invalid_period_payload` | §6.2: nested period errors surface per entry |

### Backend (`tariffs/test_series.py`) — version arithmetic (no DB)

| Test case | Validates |
|---|---|
| `active_version` across both inclusive bounds, open-ended, and inside a gap | §3.1.1 day resolution |
| `find_gaps`: contiguous, one missing month, **one missing day**, several interior gaps, leading/trailing stretches ignored, input order irrelevant | §3.1.1 gap detection |
| `plan_new_version`: append onto open-ended, truncate an over-long predecessor, mid-chain insert bounding both sides, predecessor already ending earlier left alone, prepend, first version of a series, only the immediate predecessor touched | §3.1.1 window arithmetic |

### Backend (`tariffs/test_versioning.py`) — series API

| Test case | Validates |
|---|---|
| Versions collapse into one series, newest first, active version identified, retired series has none | §6.1a `GET series/` |
| Gaps reported / absent; series scoped to the caller's ZEVs; `?zev_id=` filter | §6.1a |
| New version closes the predecessor the day before and leaves no gap | §3.1.1 |
| New version copies HT/NT bands including times; can set new prices in one call; fixed-fee amount overridable | §6.1a |
| New version and duplicate preserve `split_key` (`weight` and `equal`) | §3.1.1 |
| Mid-chain insert is capped against its successor | §3.1.1 |
| Duplicate starts a separate series without touching the source; refuses a blank or identical name | §6.1a |
| Rename renames every version; refuses a name already in use; identical name is a no-op | §6.1a |
| A version cannot change the series' category/billing mode/energy type | §3.1.1 |

### Backend (`tariffs/tests.py`) — validity windows

| Test case | Validates |
|---|---|
| `test_rejects_overlapping_tariffs_with_the_same_name` | §3.1: the forgotten-`valid_to` double-billing case is blocked |
| `test_allows_overlapping_tariffs_with_different_names` | §3.1: distinct simultaneous components are permitted |
| `test_allows_the_same_name_in_consecutive_windows` | §3.1: seasonal versioning with the old window closed |
| `test_rejects_overlapping_fixed_fees_with_the_same_name` | §3.1: the check covers fixed-fee modes, not only energy modes |

### Backend (`invoices/test_engine_edge_cases.py`) — VAT modes (§4.8)

| Test case | Validates |
|---|---|
| `InvoiceVatRateSelectionTests` | `registered`: rate resolved at `period_end`, VAT line added; missing rate → 0% |
| `TariffBearsInputVatTests` | classifier: grid energy / grid fees / levies / metering bear VAT; local energy and feed-in do not |
| `InvoiceVatInclusiveModeTests` | `inclusive`: VAT-bearing lines grossed by `1 + rate`, `embedded_vat_chf` recorded, no VAT line; no active rate → prices unchanged; `not_registered` bills verbatim |

### Backend (`zev/tests.py`) — VAT-mode validation

| Test case | Validates |
|---|---|
| `ZevVatModeTests` | default `not_registered`; `clean()` requires a number for `registered` and forbids one otherwise; PATCH to `inclusive` accepted, PATCH to `registered` without a number rejected |

### Frontend

- Tariff management page behaviors and invoice detail rendering
- Build and type checks (`npm run build`)

### Manual verification

- Verify worked examples (§8) against generated invoices
- Validate VAT / no-VAT totals for same input period

---

## 14. Acceptance criteria

- [ ] Timestamp-level allocation matches the formulas in §4.3
- [ ] Mid-period assignment transfers attribute every reading to the holder active at its timestamp (§4.1), and gap readings appear on no bill
- [ ] All eight billing modes produce correct quantities and totals per §4.4–4.6
- [ ] Producer credits are symmetric with consumer charges for local energy
- [ ] Fixed fees count billable months without proration (§4.6.1)
- [ ] Shared fees divide by the participant count of each billed month, and charge only the months the participant was a member (§4.6.3)
- [ ] A full ZEV run recovers each shared-fee month exactly once, up to the documented rounding shortfall (§4.6.3)
- [ ] Rounding matches §5 for all output fields
- [ ] VAT is applied only when `zev.vat_number` is set (§4.8)
- [ ] Worked examples (§8) pass as automated tests
- [ ] Historical invoice totals remain stable across non-historical tariff changes
