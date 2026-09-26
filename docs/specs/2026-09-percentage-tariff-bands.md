# Feature Spec: Time-of-use bands for percentage-of-energy tariffs

- Spec ID: SPEC-2026-percentage-tariff-bands
- Status: Completed
- Scope: Minor
- Type: Feature
- Owners: Sebastian Plattner
- Created: 2026-09-25
- Target Release: next minor
- Related Issues: #834 (this feature), #690 (Art. 16 EnV ceiling, out of scope here)
- Related ADRs: none
- Impacted Areas: backend | frontend | docs

---

## 1. Problem and outcome

A `percentage_of_energy` tariff stores one `Tariff.percentage`, and the engine
applies it at every timestamp:

```
effective_price(ts) = grid_base_price_sum(ts) × (Tariff.percentage / 100)
```

The percentage cannot vary over the day, the week or the year. A ZEV that wants
local solar energy to be cheap at midday and dearer in the morning and evening
has to fall back to a `by energy` tariff with fixed CHF/kWh bands. That loses
the link to the grid price and has to be re-entered whenever the grid tariff
changes.

**Outcome:** a percentage-of-energy tariff is priced by **percentage bands**.
They are the same `TariffPeriod` rows, with the same recurrence model (period
type, label, time window, weekdays, months) that `by energy` tariffs use. At
every timestamp the engine resolves the band exactly as it does for an energy
tariff and applies that band's percentage to the grid base price at that same
timestamp. The old single percentage becomes one flat band, so existing
tariffs bill exactly as before.

## 2. Scope

### In scope

| Area | Details |
|---|---|
| Data model | `TariffPeriod.percentage` (new). `TariffPeriod.price_chf_per_kwh` becomes nullable. Exactly one of the two is set, depending on the tariff's billing mode. `Tariff.percentage` is **removed** after a data migration turns each value into one flat band. |
| API | `TariffPeriodSerializer` accepts bands on percentage tariffs. `TariffSerializer` drops `percentage` and gains the write-only, create-only `initial_percentage`. new-version / duplicate copy and override band percentages. |
| Engine | Percentage tariffs resolve a band per timestamp. Consumer charges and producer credits both use the band. Band itemisation (`Zev.itemize_tariff_bands`) now also splits percentage tariffs. |
| Dynamic preflight / readiness | Coverage uses "has bands" and "band percentage at ts" instead of `Tariff.percentage`. |
| Documents | Contract PDF and tariff overview PDF show one row per percentage band (label, window, %, effective Rp./kWh). A single flat band renders exactly as today. |
| Feasibility prefill | Uses a time-weighted average percentage per tariff. |
| ZEV transfer archive | Format version 4 carries `percentage` on periods. Versions 1–3 are converted on import. |
| Frontend | Band editor for percentage tariffs, drawer band list, series summary, price-history chart, version modal, create form, types, i18n (de/fr/it/en). |
| Seed data | Demo percentage tariffs are created as flat bands. |
| Docs | Baseline specs and user guide chapter 07. |

### Out of scope

- The Art. 16 EnV price ceiling and how it interacts with a higher evening percentage (#690).
- New overlap or gap validation between timed bands. Percentage bands follow the energy-band rules exactly, including the "first band of the season" fallback for unpriced hours (§5.1). A stricter coverage check would apply to both tariff kinds and belongs in its own change.
- Aligning grid bands and percentage bands in time for the *representative* (document/display) price. The representative grid base stays a single value (`display_grid_base_summary`), and each percentage band is multiplied by it.
- VSE/AES import (it never creates percentage tariffs).
- Changing already issued invoices. `InvoiceItem` stores values, not references.

## 3. Actors, permissions, and ZEV scope

Unchanged. Tariffs and bands are edited through `TariffViewSet` /
`TariffPeriodViewSet` with `IsAuthenticated, IsZevOwnerOrAdmin` and ZEV-scoped
querysets, and in the frontend on the tariffs page (roles `admin`, `zev_owner`).
Participants see only what documents and invoices print.

## 4. Data model

### 4.1 TariffPeriod (`tariffs.models.TariffPeriod`)

| Field | Type | Default | Constraints / Notes |
|---|---|---|---|
| `price_chf_per_kwh` | `DecimalField(8,5)` | — | **now `null=True, blank=True`**. Required on a band of an `energy` tariff, and must be null on a percentage tariff. |
| `percentage` | `DecimalField(5,2)` | — | **new**, `null=True, blank=True`, `validators=[MinValueValidator(0)]`, help text "Percentage of all grid energy tariffs used as the effective price. Only for percentage-of-energy tariffs." Required on a band of a `percentage_of_energy` tariff, and must be null on an energy tariff. |

All other fields (`period_type`, `label`, `time_from`, `time_to`, `weekdays`,
`months`) and `Meta.ordering` are unchanged.

**DB constraint** (`Meta.constraints`):
`CheckConstraint(name="tariffperiod_exactly_one_price", condition=Q(price_chf_per_kwh__isnull=False, percentage__isnull=True) | Q(price_chf_per_kwh__isnull=True, percentage__isnull=False))`.

**`TariffPeriod.clean()`**: in addition to the existing checks, and when `tariff_id` is set:
- `tariff.billing_mode == ENERGY` → `price_chf_per_kwh` required (`{"price_chf_per_kwh": "A price band needs a price."}`) and `percentage` must be null (`{"percentage": "Only percentage-of-energy tariffs take a percentage."}`).
- `tariff.billing_mode == PERCENTAGE_OF_ENERGY` → `percentage` required (`{"percentage": "A percentage band needs a percentage."}`) and `price_chf_per_kwh` must be null (`{"price_chf_per_kwh": "A percentage band takes a percentage, not a price."}`).

**`__str__`**: `"{tariff.name} / {period type} @ {percentage}%"` for a percentage band, otherwise unchanged.

### 4.2 Tariff (`tariffs.models.Tariff`)

- `percentage` is **removed** (migration §4.3).
- `Tariff.clean()`: when the instance already exists and has bands, changing `billing_mode` is rejected: `{"billing_mode": "Remove this tariff's bands before changing its billing mode."}`. Bands are priced per mode, so a band of one mode is meaningless under the other. Fee modes never carry bands.

### 4.3 Migration `tariffs/0018_percentage_bands`

One migration file, in this order of operations:

1. `AddField TariffPeriod.percentage`. `AlterField TariffPeriod.price_chf_per_kwh` to nullable.
2. `RunPython(forwards, backwards)`:
   - forwards: for every `Tariff` with `billing_mode="percentage_of_energy"` and `percentage IS NOT NULL`, create a `TariffPeriod(period_type="flat", percentage=tariff.percentage, price_chf_per_kwh=None)`. The serializer rejected bands on percentage tariffs, so none have any. If a row does have some (e.g. created through the admin), delete them first, because they were never billed (the engine ignored them). A tariff with `percentage IS NULL` gets no band. A tariff with `percentage = 0` gets a 0 % flat band, which bills nothing, exactly as today (§5.2).
   - backwards: for every percentage tariff, set `Tariff.percentage` to the representative band's percentage (flat, else high, else first by `Meta.ordering`), then delete its bands. This loses data when there are several bands, which is acceptable for a rollback.
3. `AddConstraint tariffperiod_exactly_one_price`.
4. `RemoveField Tariff.percentage`.

Data and schema operations run in the same migration, so the backwards
`RunPython` runs after `percentage` has been re-added (Django reverses the
operations in order).

## 5. Behaviour

### 5.1 Band resolution

Percentage bands are resolved by the **same** function as energy bands,
`invoices.engine._resolve_tariff_band(tariff, ts)`, with no special case:

- Month first, then a flat band short-circuits. Otherwise the timed band whose
  weekdays contain `ts.weekday()` and whose `time_from <= ts.time() < time_to`.
- If nothing matched: the first in-season band (by `Meta.ordering`), else the
  first band.
- A flat band may not share months with a timed band (existing
  `_reject_flat_beside_timed_bands`, now also applied to percentage tariffs).

### 5.2 Engine (`invoices/engine.py`)

**`TariffResolver.__init__`**: a `PERCENTAGE_OF_ENERGY` tariff is bucketed
into `_percentage` when it has at least one band (`len(tariff.periods.all()) > 0`,
with periods prefetched as today). This replaces `and tariff.percentage`.

**New `TariffResolver.percentage_at(tariff, ts) -> tuple[Decimal, TariffPeriod | None]`**:
`period = _resolve_tariff_band(tariff, ts)`. It returns `(period.percentage, period)`,
or `(Decimal("0"), None)` when the tariff has no band.

**`_price_energy`** (the energy part is unchanged):

```
pct_prices = []
for tariff in tariffs.percentage(energy_type, day):
    pct, period = tariffs.percentage_at(tariff, ts)
    if pct:                       # a 0 % band at ts produces nothing and does not
        pct_prices.append(...)    # resolve the grid base, as a 0 % tariff did before
if not pct_prices: return
grid_base = sum(price_at(t, ts)[0] for t in tariffs.energy(GRID, day))
for tariff, pct, period in pct_prices:
    acc.add(tariff=..., quantity=..., total=sign*quantity*grid_base*pct/100,
            unit="kWh", base_total=quantity*grid_base, bucket=bucket, period=period)
```

Because `period` is now passed, `ItemAccumulator` splits a percentage
tariff's line per band exactly as for energy tariffs when
`Zev.itemize_tariff_bands` is on and the tariff has more than one band. Producer
credits (§4.5.1 of the baseline) go through `_price_energy` with `sign=-1`, so
they use the band that matches the timestamp without further changes.

**`preflight_dynamic_prices`**: `percentage_tariffs` keeps the percentage tariffs
of energy type local or grid that have at least one band (prefetch periods on
the queryset). A timestamp needs the grid base when some such tariff is active
on that day, applies to an energy type billed at that timestamp, **and**
resolves a non-zero percentage at that timestamp (`_resolve_tariff_band`). This
matches the engine exactly.

**`_build_item_payloads`**: each payload gains `effective_percentage`, computed
as `abs(raw entry total, before grossing) / base_total × 100`, quantised to
0.01. It is `None` when `base_total` is 0 or the tariff is not a percentage
tariff.

**`_build_description`** for `PERCENTAGE_OF_ENERGY`:

| Line | Percentage printed | Format |
|---|---|---|
| itemised by band (`period` set) | `period.percentage` | `"{name} – {band} ({pct}% {pct_of} {base}/kWh{suffix})"`, where `band` comes from `band_description` and the dash follows the energy-line convention |
| not itemised, all non-zero bands of the tariff share one percentage (0 % bands bill nothing and add no quantity, so they are ignored) | that percentage | unchanged: `"{name} ({pct}% {pct_of} {base}/kWh{suffix})"` |
| not itemised, non-zero bands differ | `effective_percentage` | `"{name} (Ø {pct}% {pct_of} {base}/kWh{suffix})"` |

Without a known base rate the same three rows drop the ` {pct_of} {base}/kWh`
part, as today. Percentages are formatted as today, with trailing zeros stripped.
`_build_description` receives `effective_percentage` as a new keyword argument.

### 5.3 Readiness (`invoices/readiness.py`)

`_uncovered_tariff_days`: `pct_active` = percentage tariffs active on the day
**that have at least one band** (replaces `t.percentage and ...`). A 0 % band
counts as a price, just as a CHF 0 energy band does. A percentage tariff with
no band leaves its energy type uncovered. That is the same outcome as a
missing `percentage` today.

### 5.4 Documents

Shared helper **`invoices.tariff_pricing.percentage_band_rows(tariff, grid_base, band_tr)`**
returns one dict per band of the tariff, in `Meta.ordering`:
`{"period": period, "label": band_description(period, band_tr), "recurrence": band_recurrence(period, band_tr), "pct": Decimal, "effective_chf": Decimal | None}`.
`effective_chf = grid_base.price_chf_per_kwh × pct / 100` when
`grid_base.has_effective_price`, otherwise `None`.

- **Tariff overview PDF** (`invoices/tariff_overview.py`, `_price_row_for_percentage_tariff` → returns a list of rows, like the energy-band path does): one row per band. `label` = `"{band label} · {pct} % × {grid} Rp./kWh"`, `recurrence` = band recurrence, and `amount`, `unit` and `footnote` follow today's three cases per band. For a tariff with a **single flat band** the row is identical to today's output.
- **Contract PDF** (`invoices/contract_pdf.py`): one row per band, using the same row shape energy-band rows already have (band label and recurrence in the row), plus today's `rate_rp`, `rate_description`, `pct`, `rate_note`. A single flat band gives exactly today's row. Template changes in `templates/.../contract` are only needed if the percentage row does not yet render the band label.
- **Feasibility prefill** (`feasibility/prefill.py::_percentage_of_energy_sum`): sums `average_percentage(tariff)` per active tariff. **New `tariffs.periods.average_percentage(tariff) -> Decimal`**: a time-weighted mean of the band percentages over one reference non-leap year (2025) in 15-minute steps, resolving each step with the same rules as §5.1. The resolver itself moves to `tariffs/periods.py` as `resolve_band(periods, ts)`, and `invoices.engine._resolve_tariff_band` delegates to it, so there is still exactly one resolution rule. The result is `Decimal("0")` without bands, quantised to 0.01. The value is an estimate by time, not by energy, and the feasibility calculator already works on estimates.

### 5.5 API contracts

**`TariffPeriodSerializer`** (`fields="__all__"`, so `percentage` appears automatically):
- `validate`: rejects dynamic tariffs (unchanged). It rejects tariffs whose `billing_mode` is not in `{ENERGY, PERCENTAGE_OF_ENERGY}` with "Tariff periods are only supported for energy-based tariffs." It enforces the §4.1 mode rules as field errors (it may call `TariffPeriod.clean()`) and applies `_reject_flat_beside_timed_bands` to both modes.
- Response: each period now carries `percentage: "60.00" | null` and `price_chf_per_kwh: "0.25000" | null`.

**`TariffSerializer`**:
- `percentage` is gone from requests and responses.
- New `initial_percentage = DecimalField(max_digits=5, decimal_places=2, min_value=0, write_only=True, required=False)`. It is accepted **only on create** of a `percentage_of_energy` tariff, and there it creates one flat band in the same transaction as the tariff. It is rejected (`{"initial_percentage": "..."}`) on update or on other modes. The field is optional: a percentage tariff without bands is valid and readiness flags it, the same as an energy tariff without bands.
- `validate` for `PERCENTAGE_OF_ENERGY` no longer requires `percentage`. The rest is unchanged (energy type required, `fixed_price_chf`/`minimum_price_chf_per_kwh` cleared).
- `percentage_base_summary` is unchanged.

**`POST /tariffs/{id}/new-version/`, `POST /tariffs/{id}/duplicate/`** (`tariffs/views.py`):
- `_apply_price_overrides` no longer handles `percentage` (only `fixed_price_chf`, `minimum_price_chf_per_kwh`).
- `_copy_or_replace_periods` copies `percentage` along with `price_chf_per_kwh`. A supplied `periods` array may carry `percentage` per band and is validated by `TariffPeriodSerializer` as today.
- A request that still sends a top-level `percentage` is ignored (DRF drops unknown keys; the views read `request.data` explicitly and must not read it).

### 5.6 ZEV transfer archive (`zev/transfer/`)

- `FORMAT_VERSION = 4`, `SUPPORTED_FORMAT_VERSIONS = {1, 2, 3, 4}`, with the version comment extended: "Version 4 moves the percentage of a percentage-of-energy tariff onto its periods."
- `TARIFF_FIELDS` drops `percentage`. `TARIFF_PERIOD_FIELDS` gains `percentage`.
- `_import_tariffs`: for an archive with `format_version < 4`, a percentage tariff whose raw entry has a non-null `percentage` gets one flat band `TariffPeriod(period_type="flat", percentage=raw["percentage"])`. Any archived periods on it are ignored, with a warning through `collector.warn`, because they were never billed. The importer needs the manifest's format version passed in. `_pick` reads only the listed fields, so the legacy top-level key must be read from `raw` explicitly.

### 5.7 Frontend

**Types (`frontend/src/types/api.ts`)**:
- `TariffPeriod.price_chf_per_kwh: string | null`, and new `percentage?: string | null`.
- `TariffPeriodInput`: `price_chf_per_kwh?: string | null`, `percentage?: string | null`.
- `Tariff.percentage` and `TariffVersionInput.percentage` removed. `TariffInput.percentage` is replaced by `initial_percentage?: string | null`.

**Tariff form (`TariffFormModal.tsx`, `useTariffForms.ts`)**: in percentage mode
the percentage input is shown **only when creating**, labelled "Initial
percentage" with a hint that more bands can be added afterwards. It maps to
`initial_percentage`. When editing, the field is hidden and the bands are
managed in the drawer. The zod schema requires it on create in percentage mode,
as today.

**Band modal (`TariffPeriodFormModal.tsx` + its form helpers)**: takes the
tariff's billing mode. Percentage mode shows a `%` input (`step=0.01`, `min=0`)
instead of CHF/kWh and maps it to `percentage` (with `price_chf_per_kwh: null`).
Energy mode does the reverse. Everything else (period type, label, window,
weekday/month chips) is shared.

**Drawer (`TariffDetailDrawer.tsx`)**: the band section is shown when
`billing_mode === 'energy' && !isDynamic` **or** `billing_mode === 'percentage_of_energy'`.
A percentage band row shows `"{pct} %"`, plus `"≈ CHF {pct × base}/kWh"` when
`percentage_base_summary.price_chf_per_kwh` is known. The existing single
percentage summary is replaced by this list.

**Series summary (`useTariffDisplay.ts`)**: the percentage label is the single
percentage when all bands share one, otherwise `"{min}–{max} %"`. The effective
price tooltip uses the same min/max logic. Without bands it shows the existing
`noPeriods` text.

**Price-history chart (`priceHistory.ts`)**: `percentagePoints` plots one line
per band, using the same band keys and the same seasonal segmentation as
energy tariffs. Each value is `base × band.percentage / 100`, and the note is
`"{pct}% × {base}"`.

**Version modal (`TariffVersionModal.tsx`)**: percentage tariffs use the same
per-band rows as energy tariffs (`usesPeriods` true for both), editing
`percentage` instead of `price_chf_per_kwh`. The single percentage input and
`payload.percentage` are removed.

**i18n**: new keys for the initial-percentage label and hint, the band %
label, and the "≈ CHF …/kWh" effective hint, in `de`, `fr`, `it` and `en`.

## 6. Test plan

### Backend

`tariffs/test_percentage_bands.py` (new):
- model: an energy band without a price is rejected, and so is an energy band with a percentage; a percentage band without a percentage is rejected, and so is a percentage band with a price; the DB constraint rejects both-null (bypassing `clean`)
- a percentage band with a negative percentage is rejected
- `billing_mode` cannot change while bands exist
- serializer: create a band on a percentage tariff; the flat-beside-timed rule applies to percentage tariffs
- `initial_percentage` creates exactly one flat band; it is rejected on update and on energy/fee modes
- new-version copies band percentages; new-version with `periods` overrides them; duplicate copies them
- migration: a percentage tariff with 18.00 becomes one flat 18.00 band; a null percentage produces no band; `Tariff.percentage` is gone (`MigratorTestCase` or the project's existing migration-test pattern, if there is one)
- `average_percentage`: a flat band gives its value; 60 % for 10:00–16:00 and 90 % otherwise gives 82.50 (6 h × 60 + 18 h × 90) / 24

`invoices/` (extend `test_engine.py` or a new `test_percentage_bands_engine.py`):
- consumer readings at 12:00 and 20:00 are priced at 60 % and 90 % of the grid base respectively
- producer local credit at 12:00 uses 60 %
- a 0 % band at ts produces no line and does not require the grid base (dynamic grid gap at that ts → no error)
- itemisation on: two lines named after their bands, and each line's rounded totals add up to the group total
- itemisation off, bands differ: one line with `Ø` and the blended percentage
- itemisation off, bands 0 % and 90 %: one line at `90%`, without `Ø`
- single flat band: description identical to today's format
- `preflight_dynamic_prices` does not require the grid base at timestamps where every percentage band is 0 %

`invoices/test_readiness*.py`: a percentage tariff without bands leaves its type uncovered; one with bands covers it when the grid is priced.

Documents: the tariff overview and contract context contain one row per band for a two-band tariff, and a single flat band gives the pre-change row.

`zev/transfer/`: v4 round-trips band percentages; a v3 archive with a top-level `percentage` imports as a flat band.

Existing tests that set `Tariff.percentage` (engine, readiness, documents, feasibility, versioning, transfer, seed) are migrated to flat bands. No assertion about billed amounts may change.

### Frontend

Unit tests (`npm run test:unit`):
- `useTariffForms` sends `initial_percentage` only on create
- the period form maps percentage vs. price by mode
- the `priceHistory` percentage lines per band
- the series summary range label

## 7. Rollout and rollback

- Rollout: the migration converts data in place, so issued invoices are unchanged and draft invoices bill identically (every tariff becomes one flat band). The archive format moves to v4; an older instance rejects v4 archives outright (by design).
- Rollback: the backwards migration restores `Tariff.percentage` from the representative band (lossy for multi-band tariffs).

## 8. Implementation plan

Order matters: each step leaves the backend test suite green.

1. **Model + migration** (§4): add the field, the constraint and the clean rules, then write the data migration and remove `Tariff.percentage`. Fix `tariffs/admin.py` if it lists `percentage`.
2. **Band resolver move** (§5.4 feasibility note): add `tariffs.periods.resolve_band`, and make `_resolve_tariff_band` delegate to it. No behaviour change.
3. **Serializers + views** (§5.5): `TariffPeriodSerializer`, `TariffSerializer.initial_percentage`, `_apply_price_overrides`, `_copy_or_replace_periods`.
4. **Engine** (§5.2): resolver bucket, `percentage_at`, `_price_energy`, preflight, `effective_percentage`, description.
5. **Readiness** (§5.3).
6. **Documents + feasibility** (§5.4): `percentage_band_rows`, tariff overview, contract PDF, `average_percentage`.
7. **Transfer archive** (§5.6).
8. **Seed data**: `seed_demo` creates flat bands for its percentage tariffs, and its versioned percentages become band overrides.
9. **Backend tests** (§6), including migrating every existing test fixture that sets `Tariff.percentage`. Run `ruff check .`, `python manage.py check`, `python -m pytest -q`.
10. **Frontend** (§5.7): types, form, band modal, drawer, summary, chart, version modal, i18n, unit tests. Run `npm run lint`, `npm run lint:style`, `node ../scripts/check-frontend-hex.mjs`, `npm run test:unit`, `npm run build`.
11. **Docs**: update the baseline `2026-03-tariffs-and-billing-engine.md` (§3.1 field table, §3.2 TariffPeriod, §4.4.2, §4.7a — which currently says percentage tariffs "are not split" — §7.2 description table, §8.5, test plan), `2026-08-contract-pdf-redesign.md`, `2026-09-tariff-overview-pdf.md` and `2026-08-zev-transfer-archive.md` (v4). Update user guide chapter `07-tariff-configuration.md` (and `13-feasibility-calculator.md` if it names the percentage). Set this spec's status to Completed.
12. **Manual check** on the dev stack: create a local percentage tariff with 60 % for 10:00–16:00 and 90 % otherwise, and generate an invoice with itemisation on and off. Screenshot the drawer and the band modal at desktop width and at ~400px, and check the console for errors.

## 9. Acceptance criteria

- [x] A percentage-of-energy tariff can hold several bands, each with its own percentage, time window, weekdays and months.
- [x] The engine applies the matching band's percentage at each timestamp, for consumer charges and producer credits.
- [x] Existing single-percentage tariffs bill exactly as before (migration to one flat band), and issued invoices are untouched.
- [x] Band itemisation splits percentage tariffs per band. Unitemised multi-band lines show the blended `Ø` percentage.
- [x] Contract PDF, tariff overview PDF, drawer and chart show one entry per band, and a single flat band looks exactly as before.
- [x] The transfer archive round-trips bands (v4) and still imports v1–v3.
- [x] Baseline specs and the user guide are updated.
