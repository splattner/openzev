# Feature Spec: Dynamic tariffs

- Spec ID: SPEC-2026-dynamic-tariffs
- Status: Completed
- Scope: Major
- Type: Feature
- Owners: Core maintainers
- Created: 2026-09-11
- Target Release: Ongoing
- Related Issues: #530 (parent gap #507, importer #520)
- Related ADRs: [0018](../adr/0018-dynamic-tariff-price-series.md)
- Impacted Areas: backend, frontend, async jobs, docs

---

## 1. Problem and outcome

Swiss operators are moving from published price bands to **dynamic tariffs**: the
price is published per quarter-hour on an HTTP endpoint, not in the tariff
document. A community whose operator has gone dynamic cannot bill grid energy at
all — the VSE/AES importer reads `prices.dynamic.url` and refuses the entry, and
there is no way to enter a quarter-hourly price by hand.

**Outcome:** a tariff can be priced from a fetched time series instead of from
recurring bands; the series is retained as billing evidence; and an incomplete
series refuses to bill rather than silently billing zero.

### Delivery status

This spec describes the whole feature. It lands in three parts:

| Part | Covers | Sections | Status |
|---|---|---|---|
| 1 | Data model, parser, adapters, fetching, scheduling, transfer | 3 – 8 | Shipped |
| 2 | Engine price resolution, refusal, readiness coverage | 9 | Shipped |
| 3 | Importer unblock, API and frontend | 10 | Shipped |

All three parts are shipped.

## 2. Scope

### In scope

- Fetching and storing a VSE-compatible dynamic price series (schema v1)
- Groupe E and BKW as concrete operator adapters
- Pricing an energy tariff from a stored series, including negative prices
- Refusing to bill a period the series does not fully cover
- Retaining prices for as long as the invoices derived from them

### Out of scope

- Schema **v2** (final 2026-09-01, targeting 2027). Detected and refused by name,
  not parsed — see §4.4.
- Demand (`CHF_kW_*`) and reactive-energy (`CHF_kVarh`) charges — #529.
- Per-customer authenticated endpoints (v2's `/customerTariffs`, OIDC, EMS link).
- Forecasting or optimisation against future prices.

## 3. The standard

SmartGridready publishes a VSE-compatible JSON Schema and OpenAPI template,
derived from the VSE document
[*Dynamische Netznutzungstarife im Verteilnetz (HDN-CH 2025)*](https://www.strom.ch/de/shop/dynamische-netznutzungstarife-im-verteilnetz-hdn-ch-2025):

- Repository: <https://github.com/SmartGridready/SGrSpecifications/tree/master/DynamicTariff>
- **v1.0.5** (2026-05-28) — what is live in the field, and what OpenZEV reads
- **v2.0.0** (2026-09-01) — targets 2027, structurally breaking

> Note for anyone reading older documents: the VSE/AES *tariff document* OpenAPI
> models `prices.dynamic` as a bare URL with no response schema, and OpenZEV's
> own notes said this feature was therefore blocked on something outside the
> repo. That has not been true since the SmartGridready schema was published.

### 3.1 Request contract (v1)

```
GET {url}?tariff_type=&tariff_name=&start_timestamp=&end_timestamp=
```

| Parameter | Meaning |
|---|---|
| `tariff_type` | Which component. Omitted → all available. |
| `tariff_name` | Operator's product. Omitted → the operator's default. |
| `start_timestamp` / `end_timestamp` | ISO-8601 **with offset**. Omitted → the current day. |

### 3.2 Response contract (v1)

```jsonc
{
  "publication_timestamp": "2026-01-31T18:00:00+01:00",
  "prices": [
    {
      "start_timestamp": "2026-02-01T00:00:00+01:00",
      "end_timestamp":   "2026-02-01T00:15:00+01:00",
      "grid":        [{"unit": "CHF_kWh", "value": 0.113}, {"unit": "CHF_m", "value": 5}],
      "electricity": [{"unit": "CHF_kWh", "value": 0.121}]
    }
  ]
}
```

A tariff type holds an **array** because it can carry several units at once — an
energy price and a monthly base fee in the same interval. The billable value is
selected **by unit**, never by position.

`publication_timestamp` may be the empty string: the schema declares
`anyOf: [date-time, empty]`, and Groupe E returns `""` when it has no data.

### 3.3 Tariff types

| v1 `tariff_type` | Meaning | OpenZEV `energy_type` |
|---|---|---|
| `electricity` | Supply to end consumers | `grid` — bought through the connection, not from the roof |
| `grid` | Grid usage, incl. Art. 35 EnG surcharge, reserve, socialised transmission costs | `grid` |
| `integrated` | **`electricity` + `grid` combined** | `grid` |
| `regional_fees` | Local/regional surcharges (concession fees) | `grid` |
| `feed_in` | Compensation for export (positive = paid to the customer) | `feed_in` |

⚠️ **Double counting.** `integrated` already contains `electricity` and `grid`.
Billing it beside a community's existing grid-fee or levy tariffs charges the
same money twice. OpenZEV does not currently prevent this; §10 adds a warning at
configuration time.

The mapping above is enforced for `energy_type` (a `feed_in` series must not
price consumption). `category` is deliberately *not* constrained: whether an
operator's grid series is filed under grid fees or levies changes no number.

## 4. Data model

`backend/tariffs/dynamic/models.py`, migration `tariffs/0012_dynamic_tariff_source`.

### 4.1 `DynamicTariffSource`

Global, **not** ZEV-scoped — see ADR 0018.

| Field | Type | Note |
|---|---|---|
| `id` | UUID pk | |
| `label` | `CharField(200)` | Shown when picking a source |
| `url` | `URLField(500)` | |
| `adapter` | `CharField(20)` | `vse_v1` \| `groupe_e` \| `bkw` |
| `tariff_type` | `CharField(20)` | §3.3 |
| `tariff_name` | `CharField(120)`, blank | Operator product |
| `last_fetch_status` | `CharField(10)` | `pending` \| `ok` \| `failed` |
| `last_fetch_at` / `last_success_at` | `DateTimeField`, null | |
| `last_fetch_error` | `CharField(500)`, blank | **User-safe text only** |
| `covers_from` / `covers_to` | `DateTimeField`, null | Denormalised series extent |

`UniqueConstraint(url, tariff_type, tariff_name)` — all three change the number,
so all three are the identity.

### 4.2 `DynamicPricePoint`

| Field | Type | Note |
|---|---|---|
| `source` | FK, CASCADE | |
| `valid_from` / `valid_to` | `DateTimeField` | UTC, half-open interval |
| `price_chf_per_kwh` | `DecimalField(8, 5)` | **Signed** |

`UniqueConstraint(source, valid_from)` + `Index(source, valid_from)`.
`ordering = ["source", "valid_from", "id"]` (total, for paginated walks).

`valid_to` is stored rather than derived from a resolution setting — see §6.

### 4.3 `Tariff.dynamic_source`

Nullable FK, `on_delete=PROTECT`. A dynamic tariff keeps
`billing_mode=energy`; there is no new billing mode. `dynamic_source` is **not**
one of `SERIES_FIELDS`, so a tariff series may go static → dynamic at a version
boundary.

`Tariff.clean()` rejects a source on a tariff that is not billed by energy, and
a source whose `tariff_type` disagrees with `energy_type` per §3.3.

### 4.4 Version detection

v1 holds `prices[].grid` as a **list**; v2 holds an **object** with
`base`/`energy`/`power`/`reactive_energy` sub-components plus metadata. A `dict`
where a list is expected raises, naming v2. Read as v1, a v2 payload would look
like an absent component and bill nothing at all.

## 5. Operator adapters

`backend/tariffs/dynamic/adapters.py`. All deviations below were measured
against the live endpoints on 2026-09-11.

| | `vse_v1` | `groupe_e` | `bkw` |
|---|---|---|---|
| Components | as configured | `grid`, `integrated`, `feed-in` | `feed_in` |
| Range queries | yes | yes | **no — any parameter is a 400** |
| History | — | ~9 months | **none** |
| Timestamps | ISO-8601 | local + offset | UTC |
| Empty answer | — | `200 {"publication_timestamp": "", "prices": []}` | `404` problem+json |
| Products | — | `vario` (default), `double`, `project_1`, `project_3` | — |

Groupe E spells the query value **`feed-in`**, where the standard and its own
response keys use `feed_in`.

A URL may arrive from `prices.dynamic.url` with a query already on it; existing
parameters are preserved, ours win.

## 6. Coverage and gaps

`fetch.coverage_gaps(source, start, end)` walks stored intervals and returns the
uncovered spans.

Coverage is **never** derived from a count. A quarter-hourly day is 96 intervals
on most days, **92** when the clocks go forward and **100** when they go back;
counting to 96 would call a complete day incomplete twice a year. Walking
intervals also handles an operator publishing hourly.

Holes are ordinary: BKW's own documentation says an interval is omitted entirely
when its source has no value for it.

## 7. Fetching

`backend/tariffs/dynamic/fetch.py`, reusing
`tariffs/importers/remote.py::fetch_tariff_document` unchanged — the SSRF guard,
per-hop redirect revalidation, 5 MB cap and the user-safe/log-only error split
all apply, because the URL is operator-supplied.

**Chunking is mandatory.** One Groupe E request for its full retained history
returned **5 016 921 bytes — 95.7 % of `MAX_DOCUMENT_BYTES`** and strained the
20-second timeout. Backfill walks ≤31 days per request (~590 KB).

| Mode | Window |
|---|---|
| Scheduled | yesterday → day after tomorrow |
| Backfill | 400 days back → day after tomorrow, chunked |
| No range support | one bare request |

The window starts *yesterday* because it is expressed in UTC while operators
publish in local time; starting at UTC midnight clips the first hours of the
Swiss day. Re-asking is free: writes are upserts on `(source, valid_from)`.

An empty response is a **successful fetch of nothing**, not a failure — Groupe E
answers that way for any range it holds nothing for, including tomorrow before
the day-ahead auction publishes.

## 8. Scheduling

`backend/tariffs/tasks.py`:

| Task | Role |
|---|---|
| `refresh_dynamic_tariff_sources` | Beat entry; fans out one task per source so one unreachable operator cannot delay the others |
| `fetch_dynamic_prices(source_id, backfill=False)` | Refreshes one source; retries twice on a transport error |
| `fetch_dynamic_prices_impl` | The logic, callable directly from tests |

`CELERY_BEAT_SCHEDULE["refresh-dynamic-tariff-sources"]` runs every **4 hours**,
not daily: Groupe E publishes day-ahead in the afternoon and BKW republishes the
current day while it runs, so no single moment has final prices.
`publication_timestamp` says when the operator last wrote, not what it covers.

Outcomes are recorded on the source (`last_fetch_*`) and as an audit event
(`AuditActionCategory.TARIFF`, `action_type="tariff.dynamic_fetch"`,
`source=CELERY`), written best-effort so an audit failure cannot change the
outcome.

### 8.1 Operator command

```
python manage.py fetch_dynamic_prices --list
python manage.py fetch_dynamic_prices <source-id> [--backfill]
python manage.py fetch_dynamic_prices --probe <url> --adapter groupe_e --tariff-type grid --tariff-name vario
```

`--probe` fetches and parses **without storing**, which is how a URL from a
published document is checked before it is trusted.

## 9. Billing

### 9.1 Engine price resolution

`backend/invoices/engine.py`. Price resolution funnels through
`TariffResolver.price_at(tariff, ts) -> (price, period)`, the *only* place a
tariff's price is read — static or dynamic. A dynamic tariff resolves via
`_DynamicSeries` (a sorted, bisected view of one source's stored points) and
always returns `period=None`: a 15-minute series must never itemise per
reading, or a month's invoice would run to thousands of lines.

All four of the engine's price-resolution points read from `price_at`:

| Site | What it prices |
|---|---|
| `_price_energy`'s energy loop | Direct consumption/production at a reading |
| `_price_energy`'s percentage base | `sum(price_at(t, ts) for t in grid tariffs)` — a levy charged as a % of a dynamic grid rate follows the series automatically |
| Personal feed-in credit | Export compensation |
| Community feed-in credit | Export compensation, shared allocation |

`_DynamicSeries` is loaded once per `DynamicTariffSource` and cached on
`InvoiceGenerationContext` (`dynamic_series(source_id)`), not on
`TariffResolver` — the resolver itself is rebuilt per participant even inside
one batch, while the context is shared across the whole ZEV-period run. This is
what makes a 20-participant batch load a series once instead of twenty times.

### 9.2 The refusal

`price_at` raises `DynamicPriceGapError` (a `ValueError` subclass) when a
dynamic tariff has no stored point covering a reading's timestamp. This is
deliberately different from a static tariff, which bills `Decimal("0")` for an
unpriced hour — existing, unrelated behaviour, left untouched. The two cases
mean different things: a static tariff's bands are configured by a human and
may legitimately leave an hour unpriced; a gap in a fetched series is missing
information, not a choice.

The check is against each reading's real timestamp, never a synthetic
quarter-hour grid, so DST needs no special case — there simply are no readings
in an hour that does not exist.

`generate_invoice` runs inside `@transaction.atomic`, so a raised gap rolls the
whole invoice back — nothing partial is written. `generate_invoices_for_zev`
(ADR 0011) already catches per-participant exceptions into `failures`, so a
gap surfaces as one failure entry with the gap's tariff name and timestamp in
`error`, not a crashed batch.

### 9.3 Readiness coverage

`backend/invoices/readiness.py`. The predicate that decides whether a tariff
is "priced" on a given day now branches on `tariff.dynamic_source_id`:

- **Static** (unchanged): `len(tariff.periods.all()) > 0`.
- **Dynamic**: the day is not inside a gap returned by
  `tariffs.dynamic.fetch.coverage_gaps` for that tariff's source.

`_dynamic_uncovered_days_by_source` computes this **once per source for the
whole span** inside `_load_bulk` (one `coverage_gaps` query per source, not
per day and not per period), stored on `BulkData.dynamic_uncovered` so
`compute_readiness_many` — which reuses one `BulkData` across many periods —
does not recompute it. Reported through the existing `tariffs` step
(`_tariffs_step_from_list`); no new `ReadinessStepKey`, so no frontend or
locale changes were needed for this part.

Coverage is measured over stored intervals, exactly like `coverage_gaps`
itself — never by counting, so a DST day with 92 or 100 intervals reads as
fully covered rather than "broken."

`_load_energy_tariffs` (unchanged, pre-existing) only considers
`category=TariffCategory.ENERGY` tariffs — a grid-fee or levy tariff, static or
dynamic, is priced by the engine but not coverage-checked by readiness today.
This is an existing limitation this work did not extend the scope of.

### 9.4 Printed documents (tariff overview PDF, participation contract)

`backend/invoices/tariff_pricing.py` and `tariff_overview.py`. Neither
document has a reading timestamp to resolve a live price against (see
`tariff_pricing.py`'s module docstring), so a dynamic tariff prints the
**average of its fetched series** instead of a per-band figure:

- `dynamic_average_chf_per_kwh(tariff)` — `Avg("price_chf_per_kwh")` over the
  tariff's source, or `None` if nothing has been fetched yet.
- An energy tariff's own row: one row, the average, footnoted
  `dynamic_average`. `None` (nothing fetched) means no row at all — the same
  "nothing to print" outcome a static tariff with zero bands already gets,
  not a misleading zero.
- The percentage-tariff grid base (`display_grid_base_chf_per_kwh`,
  `grid_base_is_dynamic`/`grid_base_is_multiband`): a dynamic grid tariff
  contributes its average to the sum. `grid_base_is_multiband` and
  `grid_base_is_dynamic` are two distinct flags — a fluctuating fetched price
  and a static multi-band tariff are both "approximate," but for different
  reasons, worded differently in `footnote_dynamic_average` vs
  `footnote_multiband_base` (all four locales). When a base is both, dynamic
  wins the footnote, as the more surprising fact for the reader.

The participation contract (`contract_pdf.py`) shares
`display_grid_base_chf_per_kwh` and so picks up a dynamic tariff's average
automatically; it does not currently print the multiband/dynamic footnote at
all (pre-existing — it never explained the multi-band approximation either).

## 10. Import and UI

### 10.1 VSE importer

`backend/tariffs/importers/vse_json.py`. A `tariffForm: dynamic` entry no
longer returns a single blocked candidate; `_dynamic_candidate()` builds an
*importable* one carrying `dynamic_url` and `dynamic_tariff_type` (the VSE
`tariffType`, one of `electricity | grid | metering | regional_fees` — the
same vocabulary `_read_header` already validates entries against). It stays
blocked only when this importer genuinely cannot represent the entry:

- **No URL** — `prices.dynamic.url` is empty.
- **`tariffType: metering`** — the dynamic-tariff schema (§3.3) has no
  `metering` type to fetch at all; the *static* importer supports metering
  tariffs, but nothing published on a metering connection is ever dynamic.

A dynamic candidate always warns that **the document names no product**
(`tariff_name`) — that concept does not exist in the VSE tariff-document
schema, only in the fetched-series API. An operator serving a single product
is unaffected; Groupe E (`vario`/`double`/`project_1`/`project_3`, materially
different prices) needs its source's `tariff_name` corrected after import.

`is_free` (governs pre-selection, §4's `recommended`) is checked explicitly
for a dynamic candidate rather than falling through to the static formula:
`all(price == 0 for price in [])` is vacuously `True`, which would have
marked every dynamic candidate "free" and never pre-selected.

### 10.2 Linking the source

`backend/tariffs/importers/planner.py`. `apply_import` resolves (and, for a
new source, probes) the `DynamicTariffSource` **before** opening the
per-candidate `transaction.atomic()` block — a slow or failing network fetch
must not hold a database savepoint open while it happens.

`_get_or_create_dynamic_source`:

1. Looks up an existing source by natural key (`url`, `tariff_type`,
   `tariff_name=""` — the document never supplies a product). Found → reused
   without a fresh probe; it is already on the fetch schedule (§8).
2. Not found → probes the URL once
   (`tariffs.dynamic.fetch.fetch_window(probe, window=None)`, an unsaved
   `DynamicTariffSource` instance) before creating anything. **A URL in a
   document is a starting point, not a contract** — the URL named as the
   example in the standard's own OpenAPI
   (`api.tariffs.groupe-e.ch/v1/tariffs`) now returns **410 Gone**. A failed
   probe reports the fetch error against that candidate (`report.errors`)
   and creates nothing; other candidates in the same import are unaffected.
3. Creates the source (`adapter=vse_v1`, since the document names a
   standard-contract URL, not an operator-specific one) via `get_or_create`
   on the same natural key, race-safe against a concurrent import of the
   same endpoint.

`_create` links the resolved source via `Tariff(..., dynamic_source=...)`
before `.save()`, so `Tariff.clean()`'s existing energy-type check runs for
free — `_dynamic_candidate` already computed `energy_type` from the same
`ENERGY_TYPE_BY_DYNAMIC_TARIFF_TYPE` mapping the model checks against, so
the two never disagree.

### 10.3 API

- `VseTariffCandidateSerializer` / `_candidate_payload` gain `dynamic_url`
  (blank for a static candidate).
- `VseTariffImportCreatedSerializer` gains `dynamic: bool`, so the apply
  result can say which created tariffs were linked to a source.
- **`GET /tariffs/dynamic-sources/`** (`DynamicTariffSourceViewSet`,
  read-only, paginated): every configured source, for the tariff form's
  picker. `IsZevOwnerOrAdmin`, **not ZEV-scoped** — a source is global
  (ADR 0018) and carries nothing more sensitive than a public operator URL
  and public prices. Creation happens only through §10.2's get-or-create or
  Django admin; there is no write endpoint.
- `TariffSerializer` needed no change: it already declares `fields =
  "__all__"`, so `dynamic_source` is exposed and writable exactly like
  `energy_type`, and `create`/`update` already call `full_clean()` — the
  model's own validation (`Tariff.clean()`, added alongside the source model)
  surfaces as an ordinary DRF 400 with no extra serializer code.

### 10.4 Frontend

`frontend/src/features/tariffs/`:

- **`TariffFormModal`** — an energy tariff (`billing_mode = 'energy'`) gets a
  "Dynamic price source" picker alongside its bands. Picking a source sets
  `energy_type` to match it (`dynamicSources.impliedEnergyType`, mirroring
  `ENERGY_TYPE_BY_DYNAMIC_TARIFF_TYPE`) for a brand-new tariff; editing an
  existing version — whose `energy_type` is already locked — instead filters
  the picker to sources that would still validate
  (`dynamicSources.dynamicSourceOptions`), so nothing offered could fail on
  save.
- **`TariffCategorySections`** — `usesPeriods`/`priceSummary`/`pricingLabel`
  are branched on the *shown version's* `dynamic_source`, not the series:
  because `dynamic_source` is deliberately not a series-coherence field
  (§3.1.2 of the billing-engine spec), one series can hold both a static and
  a dynamic version across a static→dynamic switchover, and the two versions
  must render differently. A "Dynamic" badge appears next to the energy-type
  badge; it turns into a danger badge with the fetch error as its tooltip
  when the source's `last_fetch_status` is `failed`.
- **`VseTariffImportModal`** — a dynamic candidate's price cell shows a
  "Dynamic" badge and its URL instead of a period list (it has no periods to
  list); the result view shows "Dynamic" in place of a billing-mode label for
  a tariff the apply step linked to a source.
- **`dynamicSources.ts`** — the two pure functions above, tested directly
  (`tests/dynamic-sources.test.ts`).
- **`types/api.ts`** — `DynamicTariffSource`, `DynamicTariffType`,
  `Tariff.dynamic_source` / `TariffInput.dynamic_source`,
  `VseTariffCandidate.dynamic_url`, `VseTariffImportResult.created[].dynamic`.

Not built in this iteration, deliberately: a price chart drawing the raw
fetched series (the tariff card shows the *average* and last-fetch status,
not a quarter-hourly chart), and a UI to create a source from scratch without
going through an import (creation is import-only or Django admin, §10.2).

## 11. Transfer archive

`Tariff.dynamic_source` travels as a nested **natural key**
(`DYNAMIC_SOURCE_FIELDS`: label, url, adapter, tariff_type, tariff_name), not as
its surrogate id, which means nothing on another instance. The importer
get-or-creates the matching global source.

The price **points do not travel**: they are a global series of tens of thousands
of rows per year, not one community's data, and the importing instance fetches
its own. Invoices already issued are unaffected — an `InvoiceItem` records what
was charged as values, not as a live reference to the price that produced it.

## 12. Test plan

### 12.1 Backend

| Module | Tests | Coverage |
|---|---|---|
| `tariffs/test_dynamic_parsing.py` | 21 | v1 parsing against both real captures; unit selection; empty/malformed/v2 refusal; DST; adapter deviations |
| `tariffs/test_dynamic_fetch.py` | 24 | Chunking, UTC storage, upsert idempotency, negative prices, coverage gaps, windows, failure recording, tasks, source identity |
| `tariffs/test_dynamic_tariff_link.py` | 9 | `Tariff.clean()` rules, static→dynamic series versioning, PROTECT retention |
| `zev/test_transfer.py::DynamicTariffTransferTests` | 3 | Natural-key match, recreation on a fresh instance, static tariffs unaffected |
| `invoices/test_dynamic_pricing.py` | 17 | `_DynamicSeries` bisection, `TariffResolver.price_at` (static and dynamic), the gap refusal, end-to-end `generate_invoice` (consumption, negative prices, percentage base, feed-in) |
| `invoices/test_readiness.py::DynamicTariffPricingCoverageTests` | 7 | Full/partial/no coverage, type-masking, percentage-tariff coupling, DST, static→dynamic series versioning |
| `invoices/test_dynamic_tariff_pricing.py` | 9 | `dynamic_average_chf_per_kwh`, `display_grid_base_chf_per_kwh`, `grid_base_is_dynamic` vs `grid_base_is_multiband` |
| `invoices/test_tariff_overview.py::TariffOverviewDynamicTariffTests` | 4 | Unfetched tariff prints nothing, fetched average with its footnote, percentage-tariff footnote and amount |
| `tariffs/test_vse_import.py` (extended) | +9 | Dynamic grid candidate is importable, no-URL and `metering` blocks, the missing-product warning, `is_free` correctness, source get-or-create + probe + reuse-without-reprobing, unreachable-URL error |
| `tariffs/test_dynamic_source_api.py` | 7 | `GET /tariffs/dynamic-sources/` access (owner/admin allowed, participant/anonymous refused), payload shape, not ZEV-scoped, read-only |
| `tariffs/test_dynamic_source_link_api.py` | 4 | Linking through the ordinary tariff API: create with a source, mismatched-energy-type 400, fee-tariff-cannot-link 400, `dynamic_source` on the series endpoint |

### 12.2 Fixtures

`backend/tariffs/dynamic/testdata/` — see its `README.md`. Two are **real
captures** taken on 2026-09-11; the BKW one **cannot be re-taken**, because that
endpoint serves only the current day and keeps no history.

### 12.3 Frontend

| Module | Tests | Coverage |
|---|---|---|
| `tests/dynamic-sources.test.ts` | 9 | `impliedEnergyType`, `dynamicSourceOptions` (unlocked / locked / no match), `fetchDynamicTariffSources` pagination |
| `tests/vse-tariff-import.test.ts` (extended) | +3 | A dynamic candidate is selectable, offers no billing-mode choice, can be the pre-selected recommendation |
| `tests/tariff-form-mapping.test.ts` (extended) | +4 | `dynamic_source` round-trips through the form, is dropped when billing mode is not energy, defaults to blank |

## 13. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Operator drops history before we fetch it | High — the period becomes unbillable forever | Backfill on creation; 4-hourly schedule; prices stored permanently (ADR 0018) |
| A gap bills as zero | High — silently wrong invoice | Engine refuses (§9); readiness flags the day first |
| Endpoint URL rots | Medium | Failures recorded per source in user-safe text; `--probe` before trusting |
| `integrated` billed beside levy tariffs | High — double charge | §3.3 documented; §10 warns at configuration time |
| A v2 endpoint read as v1 | High — bills nothing | Refused by name (§4.4) |
| Shared source edited by one community affects others | Medium | Natural key is immutable in practice; only `label` is cosmetic |

## 14. Acceptance criteria

- [x] A VSE v1 response is parsed by unit, not by array position
- [x] Unbillable units are reported rather than silently ignored
- [x] Groupe E and BKW adapters, each with a recorded fixture
- [x] Component and product are explicit configuration, never an implicit default
- [x] Fetching is scheduled, chunked below the fetch cap, and reuses the SSRF guards
- [x] `200`-with-empty, `404` and `410` are each handled distinctly
- [x] Coverage is computed on intervals, correct across both DST transitions
- [x] Prices are retained for as long as the tariff referencing them exists
- [x] A v2 payload is refused by name
- [x] The transfer archive carries the source link by natural key
- [x] The engine prices from the series and refuses an uncovered period
- [x] Readiness flags an uncovered day before generation is attempted
- [x] Printed documents (tariff overview, participation contract) show a dynamic tariff's fetched average rather than skipping it or printing zero
- [x] The importer creates dynamic tariffs instead of blocking them, and refuses (per-candidate) rather than creating a dead tariff when the named URL cannot be fetched
- [x] The UI shows that a tariff is dynamic, which source it uses, and when that source's last fetch failed
