# Feature Spec: Dynamic tariffs

- Spec ID: SPEC-2026-dynamic-tariffs
- Status: Completed
- Scope: Major
- Type: Feature
- Owners: Core maintainers
- Created: 2026-09-11
- Target Release: Ongoing
- Related Issues: #530 (parent gap #507, importer #520), #702, #703
- Related ADRs: [0018](../adr/0018-dynamic-tariff-price-series.md), [0019](../adr/0019-frozen-dynamic-price-evidence.md)
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

## 2. Scope

### In scope

- Fetching and storing VSE-compatible dynamic price series (v1.0.5 and v2.0.0)
- Provider-neutral endpoint discovery and capability probing
- Pricing an energy tariff from a stored series, including negative prices
- Refusing to bill a period the series does not fully cover
- Retaining prices for as long as the invoices derived from them, with a
  guarded administrator cleanup for data that has not contributed to an invoice

### Out of scope

- Demand (`CHF_kW_*`) and reactive-energy (`CHF_kVarh`) charges — #529.
- Per-customer authenticated endpoints (v2's `/customerTariffs`, OIDC, EMS link).
- Forecasting or optimisation against future prices.

## 3. The standard

SmartGridready publishes a VSE-compatible JSON Schema and OpenAPI template,
derived from the VSE document
[*Dynamische Netznutzungstarife im Verteilnetz (HDN-CH 2025)*](https://www.strom.ch/de/shop/dynamische-netznutzungstarife-im-verteilnetz-hdn-ch-2025):

- Repository: <https://github.com/SmartGridready/SGrSpecifications/tree/master/DynamicTariff>
- **v1.0.5** (2026-05-28) — array-based price components using `CHF_kWh`
- **v2.0.0** (2026-09-01) — object-based tariff types using `CHF/kWh`

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

`publication_timestamp` may be the empty string: the v1 schema declares
`anyOf: [date-time, empty]` for a response with no published data.

### 3.3 Tariff types

| v1 `tariff_type` | Meaning | OpenZEV `energy_type` |
|---|---|---|
| `electricity` | Supply to end consumers | `grid` — bought through the connection, not from the roof |
| `grid` | Grid usage, incl. Art. 35 EnG surcharge, reserve, socialised transmission costs | `grid` |
| `integrated` | **`electricity` + `grid` combined** | `grid` |
| `regional_fees` | Local/regional surcharges (concession fees) | `grid` |
| `feed_in` | Compensation for export (positive = paid to the customer) | `feed_in` |

v2 additionally defines `metering`, `national_fees`, `dso`, `dso_complete`,
`integrated_complete`, and `refund`. OpenZEV offers any returned type carrying
an `energy` value in `CHF/kWh`, except `refund`; consumption-oriented types map to
`grid`. Storage refunds require storage-qualified metering and are excluded from
billable discovery, tariff linking, and import. Only `feed_in` prices ordinary exports. Components containing only base,
power, or reactive-energy prices are not offered because the billing engine
cannot apply them per metered kWh.

⚠️ **Double counting.** What an aggregate bundles depends on the endpoint's
API version (sources: `SGrSpecifications/DynamicTariff/OpenAPI/`
`dynamic_tariff_vse_openapi_v1.yaml`, valid 2026, and
`..._v2.yaml`, in effect 2027-01-01):

| Aggregate | v1 | v2 |
|---|---|---|
| `integrated` | `electricity` + `grid` | `electricity` + `dso` (i.e. electricity, grid, metering, national_fees) |
| `dso` | n/a (v2 only) | `grid` + `metering` + `national_fees` |
| `dso_complete` | n/a (v2 only) | `dso` + `regional_fees` |
| `integrated_complete` | n/a (v2 only) | `electricity` + `dso_complete` |

(v2 moves the Art. 35 surcharge/reserve/socialised costs out of `grid` into
`national_fees`, which is why `dso` adds it back. A DSO does not sell energy,
so `dso` never contains `electricity`.)

Billing one of these beside a community's existing tariff for a type it
already contains charges the same money twice. OpenZEV does not block the
combination — a community's tariffs are configured independently and nothing
enumerates "what else prices this ZEV" — but §10 warns at both configuration
points (picking the component, and linking a tariff to it) naming exactly
which types the choice already contains. The warning is version-aware:
the import preview (no version known yet) names the components bundled on
*every* version plus the possible extras; the pickers read the exact
expansion (`aggregated_tariff_types`) off the source/discovery object, and
the applied import upgrades to the probed version's exact list. The
canonical composition lives in `tariffs/dynamic/components.py`; there is no
frontend copy.

The mapping above is enforced for `energy_type` (a `feed_in` series must not
price consumption). `category` is deliberately *not* constrained: whether an
operator's grid series is filed under grid fees or levies changes no number.

## 4. Data model

`backend/tariffs/dynamic/models.py`, migrations `tariffs/0012`–`0015`;
invoice provenance in `invoices/models.py`, migration `invoices/0017`.

### 4.1 `DynamicTariffSource`

Global, **not** ZEV-scoped — see ADR 0018.

| Field | Type | Note |
|---|---|---|
| `id` | UUID pk | |
| `label` | `CharField(200)` | Shown when picking a source |
| `url` | `URLField(500)` | |
| `api_version` | `CharField(20)` | `v1_0_5` \| `v2_0_0` |
| `request_mode` | `CharField(20)` | discovered `standard` \| `exact_url` |
| `query_tariff_type` | `CharField(20)` | discovered wire spelling, not user-entered |
| `supports_range` | `BooleanField` | discovered endpoint capability |
| `empty_on_not_found` | `BooleanField` | administrator-configured opt-in for successful empty HTTP 404; default false |
| `tariff_type` | `CharField(20)` | §3.3 |
| `tariff_name` | `CharField(120)`, blank | Operator product |
| `enabled` | `BooleanField` | disabled sources retain evidence but are skipped by scheduled refreshes |
| `last_fetch_status` | `CharField(10)` | `pending` \| `ok` \| `failed` |
| `last_fetch_at` / `last_success_at` | `DateTimeField`, null | |
| `last_fetch_error` | `CharField(500)`, blank | **User-safe text only** |
| `covers_from` / `covers_to` | `DateTimeField`, null | Denormalised series extent |
| `recovery_from` | `DateTimeField`, null | Earliest unresolved fetch window; retained until a successful refresh attempts it |

`UniqueConstraint(url, api_version, tariff_type, tariff_name)` defines immutable
identity. Model saves and the API refuse identity edits; Django admin makes
those fields read-only after creation. `CheckConstraint(dynamic_exact_url_no_range)`
rejects `request_mode=exact_url` with `supports_range=true`.

### 4.2 `DynamicPricePoint`

| Field | Type | Note |
|---|---|---|
| `source` | FK, CASCADE | |
| `valid_from` / `valid_to` | `DateTimeField` | UTC, half-open interval |
| `price_chf_per_kwh` | `DecimalField(8, 5)` | **Signed** |

`UniqueConstraint(source, valid_from)` (whose backing index also serves ordered
source lookups) plus `CheckConstraint(valid_to > valid_from)`.
`ordering = ["source", "valid_from", "id"]` (total, for paginated walks).

`valid_to` is stored rather than derived from a resolution setting — see §6.

### 4.3 `Tariff.dynamic_source`

Nullable FK, `on_delete=PROTECT`. A dynamic tariff keeps
`billing_mode=energy`; there is no new billing mode. `dynamic_source` is **not**
one of `SERIES_FIELDS`, so a tariff series may go static → dynamic at a version
boundary.

`Tariff.clean()` rejects a source on a tariff that is not billed by energy, and
a source whose `tariff_type` disagrees with `energy_type` per §3.3.

A dynamic tariff has no `TariffPeriod` price bands. This is enforced by the
model, API serializers, tariff version and duplication paths, the VSE importer,
and the admin forms. Linking a source to an existing static tariff therefore
requires its existing bands to be removed first; copied dynamic versions keep
the source link and receive no bands.

### 4.4 InvoiceDynamicSourceEvidence

| Field | Type | Constraint |
|---|---|---|
| `id` | BigAutoField PK | |
| `invoice` | FK → Invoice, CASCADE | related_name `dynamic_evidence` |
| `source` | FK → DynamicTariffSource, PROTECT | related_name `invoice_evidence` |
| `tariff_id_snapshot` | UUIDField | copied value, not a mutable tariff FK |
| `evidence_from` / `evidence_to` | DateTimeField | half-open UTC interval; end strictly after start |

Unique on `(invoice, tariff_id_snapshot)`; ordered by invoice_id, source_id, id.
Generation records each applicable dynamic tariff's intersection with the invoice
period, conservatively including tariffs with no priced quantity. Drafts protect
points. Cancelled invoices cease protecting points but retain source provenance
until the invoice is deleted. Migration 0017 snapshots existing relationships;
relationships removed before migration cannot be recovered from current rows.

### 4.5 Version detection and parsing

v1 holds `prices[].grid` as a **list**; v2 holds an **object** with
`base`/`energy`/`power`/`reactive_energy` sub-components plus metadata. This
shape detects the version from any non-empty response. An empty response cannot
be detected, so the creation wizard lets the operator select v1.0.5 or v2.0.0
and then choose the expected component/product explicitly. Each version has its
own parser; both normalize the
billable energy value to signed CHF/kWh points.

## 5. Generic protocol and endpoint discovery

No provider/VNB is a format choice. `backend/tariffs/dynamic/protocol.py`
detects `v1_0_5` versus `v2_0_0` from the response shape and discovers every
component that carries a billable CHF/kWh energy value. For v2, the response's
embedded `tariff_name` is included in the choice. V1 responses contain no
product catalogue, so the wizard offers an optional manual product-name field.

`backend/tariffs/dynamic/discovery.py` then probes the selected series to learn
request capabilities rather than matching the hostname:

1. Try the standard `tariff_type`/optional `tariff_name` query.
2. For underscore names, also tolerate a hyphenated query enum when that is the
   spelling the endpoint accepts; the response key remains canonical.
3. If query parameters are rejected but the bare URL carries the selected
   component, persist `request_mode=exact_url` and disable history backfill.
4. If standard filtering works, probe a returned interval using
   `start_timestamp`/`end_timestamp` and persist whether ranges are supported.

These are stored capabilities, not visible provider adapters. A URL may already
contain a query; standard request construction preserves unrelated parameters
and lets the selected source identity win.

## 6. Coverage and gaps

`fetch.coverage_gaps(source, start, end)` returns the uncovered spans. A SQL
window computes only boundaries that begin after every preceding interval has
ended, so readiness does not transfer an entire year of quarter-hour points
into Python merely to locate a few gaps.

Coverage is **never** derived from a count. An operator-local quarter-hour day
can contain 92, 96, or 100 intervals around DST transitions. Billing and
readiness use UTC civil-day windows under ADR 0007. Interval coverage handles
both publication offsets and hourly prices without a resolution assumption.

Holes are ordinary: an endpoint may omit an interval when its upstream source
has no value for it.

## 7. Fetching

`backend/tariffs/dynamic/fetch.py`, reusing
`tariffs/importers/remote.py::fetch_tariff_document` (extended with HTTP status codes) — the SSRF guard,
per-hop redirect revalidation, 5 MB cap and the user-safe/log-only error split
all apply, because the URL is operator-supplied.

Backfills use 31-day chunks to remain below the HTTP size and timeout limits.

| Mode | Window |
|---|---|
| Scheduled | Resume `recovery_from`, clamped to the last 14 days; otherwise resume stored extent/last success, no later than yesterday; end at UTC today + 2 days |
| Backfill | UTC today − 400 days → UTC today + 2 days, chunked |
| No range support | One request, without a requested time window |

Starting no later than yesterday retains the first hours of operator-local days
that begin before UTC midnight. Failed/refused windows retain the earliest
recovery cursor, including failures in old backfill chunks. Only requests are
clamped: a later success or failure cannot erase an older, unattempted cursor,
even when that cursor predates the 400-day backfill window.

`dynamic/storage.py::store_points` acquires a source row lock before reading
prices or invoice evidence. It sorts old and incoming intervals into connected
overlap groups. Each group's proposed replacement must be non-overlapping and
cover every displaced old interval in full. Complete unbilled resolution changes
are accepted atomically; partial replacements and overlapping incoming intervals
are refused without clipping. An old interval overlapping non-cancelled frozen
invoice evidence cannot change price or extent, and a replacement cannot extend
into protected evidence. Identical intervals are idempotent. Independent valid
groups commit before `PriceSeriesConflict` is raised, unless an enclosing
transaction (such as import) rolls the whole operation back.

`BilledPriceChanged` identifies protected replacements;
`PriceIntervalConflict` identifies ambiguous/incomplete interval replacements.
Refusals mark the source failed and are not retried by Celery. See the
[user-guide recovery procedure](../user-guide/07-tariff-configuration.md#recovering-a-refused-price-series).
Migration 0014 refuses invalid or overlapping existing intervals and names the
rows to reconcile before continuing; it does not repair billing evidence.

An empty response is successful but adds no coverage. HTTP 404 remains a failure
unless an administrator explicitly enables `empty_on_not_found` in Django admin
after verifying the endpoint's convention. Discovery and migrations never infer
that flag from `feed_in` or `exact_url`; rechecking capabilities preserves it.
An opted-in source treats every 404 as empty; it cannot distinguish a removed
product from no publication. HTTP 410 remains a failure. Schema/version/product
errors are deterministic refusals and do not consume Celery's transport retries.

## 8. Scheduling

`backend/tariffs/tasks.py`:

| Task | Role |
|---|---|
| `refresh_dynamic_tariff_sources` | Beat entry; fans out one task per enabled source so one unreachable operator cannot delay the others |
| `fetch_dynamic_prices(source_id, backfill=False)` | Refreshes one source; retries twice only on transport failures, never schema/version/product errors, price conflicts, or unexpected program/database errors |
| `fetch_dynamic_prices_impl` | The logic, callable directly from tests |

`CELERY_BEAT_SCHEDULE["refresh-dynamic-tariff-sources"]` runs every **4 hours**,
not daily: endpoints can publish day-ahead data or republish the current day at
different times, so no single moment has final prices.
`publication_timestamp` says when the operator last wrote, not what it covers.

When the importer creates a new source, it queues
`fetch_dynamic_prices(source_id, backfill=True)` with `transaction.on_commit()`
after the tariff write succeeds. Reusing an existing global source does not
queue another initial backfill; that source already has stored history and is
included in the four-hour fan-out.

Outcomes are recorded on the source (`last_fetch_*` and `recovery_from`) and as an audit event
(`AuditActionCategory.TARIFF`, `action_type="tariff.dynamic_fetch"`,
`source=CELERY`), written best-effort so an audit failure cannot change the
outcome.

Fetch and destructive maintenance share a cache-backed, per-source 30-minute
lease (`dynamic/locking.py::dynamic_source_lock`). A second fetch skips an
already-busy source; clearing returns HTTP 409 instead of racing an in-flight
upsert. The lock token is checked before release so an expired lease cannot
delete a successor's lock.

### 8.1 Operator command

```
python manage.py fetch_dynamic_prices --list
python manage.py fetch_dynamic_prices <source-id> [--backfill]
python manage.py fetch_dynamic_prices --probe <url> --api-version v1_0_5 --tariff-type grid [--tariff-name <name>]
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

`_DynamicSeries` loads only intervals overlapping the invoice period, once per
source per participant transaction. Before pricing, `generate_invoice` locks
all applicable dynamic source rows in primary-key order. Storage, clearing, and
deletion use the same row locks; the cache lease remains fetch/maintenance
coordination only. Frozen evidence is written before the invoice commits.
`InvoiceGenerationContext` retains shared allocation denominators across the
batch but clears its price cache after acquiring each invoice's source locks.

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
gap surfaces as one failure entry carrying stable `code=dynamic_price_gap`, the
tariff/source ids, and the first missing timestamp. The single-invoice API
returns the same structured 409 response, allowing the frontend to direct the
operator to refresh the named source instead of claiming an invoice collision.

### 9.3 Readiness coverage

`backend/invoices/readiness.py`. The predicate that decides whether a tariff
is "priced" on a given day now branches on `tariff.dynamic_source_id`:

- **Static** (unchanged): `len(tariff.periods.all()) > 0`.
- **Dynamic**: the day is not inside a gap returned by
  `tariffs.dynamic.fetch.coverage_gaps` for that tariff's source.

`_dynamic_uncovered_days_by_source` computes this **once per source for the
whole span** inside `_load_bulk` (one bounded gap calculation per source, not
per day and not per period), stored on `BulkData.dynamic_uncovered` so
`compute_readiness_many` — which reuses one `BulkData` across many periods —
does not recompute it. Reported through the existing `tariffs` step
(`_tariffs_step_from_list`); no new `ReadinessStepKey`, so no frontend or
locale changes were needed for this part.

Coverage uses stored intervals over UTC civil-day windows, never a fixed
number of readings. The existing continuous-interval test demonstrates coverage
across a DST date; parser fixtures separately verify offset normalization.

`_load_energy_tariffs` still restricts a **static** tariff to
`category=TariffCategory.ENERGY` — a static grid-fee or levy tariff is priced
by the engine but not coverage-checked by readiness, a pre-existing limitation
this work did not extend the scope of. A **dynamic** tariff is included
regardless of category: #530's own mapping table files a dynamic *grid*
series under `grid_fees`, not `energy`, and `TariffResolver` (the engine's one
resolution funnel, §9.1) buckets purely on `billing_mode`/`energy_type` with
no category filter, so that is the common case, not the exception. Excluding
it here would let readiness report "ok" for a period the engine then refuses
to generate — a gap in a dynamic series is `DynamicPriceGapError`, not a
silent zero, so readiness reporting "ok" ahead of that would be worse than
the pre-existing static gap it deliberately leaves alone.

### 9.4 Printed documents (tariff overview PDF, participation contract)

`backend/tariffs/dynamic/pricing.py`, `invoices/tariff_pricing.py`, and
`tariff_overview.py`. Documents and management screens have no consumption
profile from which to select a live price, so they share one display policy:

- intersect the tariff's validity with the trailing `DYNAMIC_DISPLAY_DAYS = 30` window ending on
  the document/reference date;
- compute a duration-weighted average of the stored intervals in that bounded
  window, so hourly and quarter-hour intervals carry their actual time weight;
- return `complete`, `partial`, or `unavailable` coverage alongside the number
  and reference dates.

The tariff overview always prints the dynamic tariff. Complete and partial
averages carry distinct localized explanations; an unfetched source prints an
explicit unavailable placeholder instead of silently dropping the tariff. A
percentage tariff gets no numeric effective price when any dynamic grid-base
component is unavailable, because summing only the static remainder would
understate its base. The participation contract shares the same grid-base
summary and prints the matching dynamic-average/partial/unavailable note. The
tariff API exposes direct source averages as `dynamic_price_summary`.
Static display fallback is flat → HT → NT → first band.

Percentage tariffs additionally expose `percentage_base_summary`: decimal-string
or null `price_chf_per_kwh`, `dynamic_status` (complete/partial/unavailable or
null for an entirely static base), and ISO `reference_date`; other tariff modes
return null. Today is clamped to the percentage version's validity. Both grid
version selection and every component's average use that date, matching the
document helper's calculation. No grid tariffs yields a zero static base;
unavailable dynamic input yields null. The frontend consumes this result
directly from each tariff version, without an additional client-side map,
recalculating temporal selection, or adding differently dated averages.

`prepare_tariff_display_summaries` batches direct summaries and percentage bases.
`summarize_requests` uses stable caller keys, here `(tariff id, reference date)`.
Disjoint windows are merged per
source and sliced by bisection, with one source query even for multiple
percentage reference dates; intervening years are not loaded.

Invoices still use exact interval prices. A month's dynamic readings accumulate
into one line, whose derived `unit_price_chf` is the consumption-weighted
effective rate; its localized description identifies it as such rather than as
a published static tariff rate.

## 10. Import and UI

### 10.1 VSE importer

`backend/tariffs/importers/vse_json.py`. A `tariffForm: dynamic` entry no
longer returns a single blocked candidate; `_dynamic_candidate()` builds an
*importable* one carrying `dynamic_url` and `dynamic_tariff_type`. Dynamic
headers use the combined v1/v2 parser vocabulary from §3.3 rather than the
smaller static tariff-document category table, so `feed_in` and the
aggregate forms reach the dynamic branch. `refund` is blocked because its
storage-qualified quantity cannot be represented. It stays blocked only when this
importer genuinely cannot represent the entry:

- **No URL** — `prices.dynamic.url` is empty.
- **No billable energy component at the fetched endpoint** — discovery refuses
  a component whose response contains no CHF/kWh energy value.

A dynamic candidate warns that the document names no product. Each selected
dynamic row must supply `dynamic_tariff_name`: a product string or an explicit
empty string confirming the endpoint default. Omission yields a per-candidate
error. The UI shows a product input and the default's meaning before import.
V2's discovered product name is persisted when present, and later responses for
a different product are refused.

`is_free` (governs pre-selection, §4's `recommended`) is checked explicitly
for a dynamic candidate rather than falling through to the static formula:
`all(price == 0 for price in [])` is vacuously `True`, which would have
marked every dynamic candidate "free" and never pre-selected.

### 10.2 Linking the source

`backend/tariffs/importers/planner.py`. `apply_import` probes every selected
dynamic component **before** opening its per-candidate `transaction.atomic()`
block. Source reuse/creation and tariff writes happen inside that transaction;
a slow or failing network fetch holds no database savepoint open.

The prepare/write source path:

1. Require an explicit product choice, then probe before opening a transaction
   to determine the protocol version and capabilities.
2. Match `(url, api_version, tariff_type, tariff_name)`; a matching source is
   reused after probing. Keep the probe's dropped-unit and aggregate-component
   warnings, adding warnings for disabled/failed/unfetched state.
3. Create a new source and tariff in the same per-candidate transaction. Store
   probe prices, mark the source successful, and queue one post-commit backfill.
   Reused sources receive no duplicate initial backfill.
4. Report transport, validation, integrity, and price conflicts per candidate.
   A failed candidate rolls back its source and predecessor-version edits.

Units the probe found but cannot bill (a demand charge, a fixed fee riding
beside the requested energy component — the same vocabulary the parsers
already warn about, §3.3) travel with the created tariff as
`dynamic_source_warnings` in the apply result, rather than being visible only
in a Celery audit event after the next scheduled fetch. The manual creation
endpoint (§10.3) surfaces the same probe warnings in its response for the
same reason: the point a dropped unit is most useful to know about is right
when the source is being configured, not after an invoice already used it.

`_create` links the resolved source via `Tariff(..., dynamic_source=...)`
before `.save()`, so `Tariff.clean()`'s existing energy-type check runs for
free — `_dynamic_candidate` already computed `energy_type` from the same
`ENERGY_TYPE_BY_DYNAMIC_TARIFF_TYPE` mapping the model checks against, so
the two never disagree. It does not create price bands for a dynamic candidate.

### 10.3 API

- `VseTariffCandidateSerializer` / `_candidate_payload` gain `dynamic_url`
  (blank for a static candidate).
- `VseTariffImportCreatedSerializer` gains `dynamic: bool`, so the apply
  result can say which created tariffs were linked to a source.
- **`GET /tariffs/dynamic-sources/`** (`DynamicTariffSourceViewSet`, paginated):
  every configured source, for the tariff form and admin console. It includes
  fetch state/coverage plus annotated `point_count`, `linked_tariff_count`,
  `linked_zev_count`, and `supports_backfill`. `IsZevOwnerOrAdmin`, **not
  ZEV-scoped** — a source is global (ADR 0018).
- **`POST /tariffs/dynamic-sources/discover/`**: owner/admin wizard endpoint.
  It fetches through the SSRF-safe client, auto-detects v1.0.5/v2.0.0 unless a
  fallback version was supplied, returns the billable component/product pairs,
  and writes nothing.
- **`POST /tariffs/dynamic-sources/`**: owner or admin creation. The server
  re-probes the chosen version/component/product, discovers generic request and
  range capabilities, stores the probe response, and post-commit queues an
  initial backfill. A
  natural-key match returns the existing shared source with HTTP 200 without
  probing; a new source returns 201. The response carries `warnings`: units
  the probe found but cannot bill, empty when an existing source was reused.
- **`PATCH /tariffs/dynamic-sources/{id}/`**: admin only. Label and `enabled`
  changes are allowed and audited. A disabled source retains every stored point
  but leaves the four-hour refresh fan-out. Identity changes remain guarded;
  the UI directs operators to create a replacement source rather than mixing
  two series.
- **`POST /tariffs/dynamic-sources/{id}/recheck/`**: admin only; re-probes the
  source's own endpoint with its existing identity to correct
  `request_mode`/`query_tariff_type`/`supports_range`, without touching
  identity fields or stored points. The initial probe's range check asks
  around one sample interval, and a transient blip or an endpoint with
  nothing published at that exact moment reads as "no range support"; since
  identity is immutable afterwards, this was otherwise a one-way door short
  of deleting and recreating the source. Refused while a fetch holds the
  lock, and writes a `tariff.dynamic_source_recheck` audit event recording
  the resulting capabilities.
- **`GET /tariffs/dynamic-sources/{id}/prices/?date_from=&date_to=`**: imported
  point history, aggregate min/max/average/count/negative-count, and interval
  gaps. Defaults to seven days and permits at most 31 inclusive days. Admins
  may read any source; an owner may read it only when one of their ZEV's tariffs
  links to it.
- **`POST /tariffs/dynamic-sources/{id}/fetch/`**: admin-only queueing of a
  normal refresh or `backfill=true`, returning a task/correlation id and writing
  a queued audit event which pairs with the Celery outcome.
- Tariff responses include `dynamic_price_summary` (`complete`/`partial`/
  `unavailable`, average, and reference dates) for a linked dynamic source.
  Percentage tariffs carry the shared `percentage_base_summary` described in §9.4.
- **`DELETE /tariffs/dynamic-sources/{id}/prices/`**: admin only; requires exact
  source-label confirmation. Under the cache lease and database source lock,
  refuse with 409 when any non-cancelled invoice retains source evidence.
  Otherwise delete points, reset coverage/fetch state, and audit the count.
- **`DELETE /tariffs/dynamic-sources/{id}/`**: admin only; same confirmation
  and locks. Tariff and invoice-evidence PROTECT relations refuse deletion
  with 409, including sources whose tariffs have since moved or disappeared.
  Return 204 and audit the source label and deleted point count on success.

Destructive actions require exact source-label confirmation; an optional reason
is audited. Existing API guards on billed tariff deletion/repointing remain
conservative workflow checks. Retention itself uses frozen invoice evidence,
so validity/ZEV changes, importer predecessor truncation, and Django admin
cannot remove that provenance. Django admin cannot delete sources or edit
price points; source identity fields are read-only after creation.

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
  A new tariff can open `DynamicSourceFormModal` directly from this picker;
  after the probed source is created or reused it is selected automatically and
  its implied energy type is applied. Selecting a source whose `tariff_type`
  is an aggregate (`integrated` and v2's `dso`/`dso_complete`/
  `integrated_complete`) shows a warning naming exactly which other types it
  already contains (the `aggregated_tariff_types` field served per API
  version) — the
  double-counting trap from §3.3, surfaced at the point a community decides
  whether to keep its separate grid-fee/levy tariffs beside it.
- **`DynamicSourceFormModal`** — creation is a two-step discovery flow. Step 1
  asks for a display name and URL, with API version set to automatic by default
  and v1.0.5/v2.0.0 as fallbacks. Step 2 shows only billable series returned by
  the endpoint. V2 product names are shown directly; v1 offers an optional
  product-name input because the v1 response cannot enumerate products. The
  same aggregate-type warning as the tariff form's picker appears here too,
  since a source is just as often created from this wizard directly. A
  successful save also toasts any `warnings` the create response carries
  (units the endpoint publishes but this source cannot bill), rather than
  leaving them visible only in the audit trail.
- **`TariffCategorySections`** — `usesPeriods`/`priceSummary`/`pricingLabel`
  are branched on the *shown version's* `dynamic_source`, not the series:
  because `dynamic_source` is deliberately not a series-coherence field
  (§3.1.2 of the billing-engine spec), one series can hold both a static and
  a dynamic version across a static→dynamic switchover, and the two versions
  must render differently. A "Dynamic" badge appears next to the energy-type
  badge; it turns into a danger badge with the fetch error as its tooltip
  when the source's `last_fetch_status` is `failed`.
  Its representative number and percentage-of-grid display use the API's
  bounded summary; partial and unavailable data are labelled instead of shown
  as complete or zero.
  `TariffVersionModal` also hides both the band editor and the fixed-price editor
  for a dynamic energy version; the dynamic source is the complete price input.
- **`VseTariffImportModal`** — a dynamic candidate's price cell shows a
  "Dynamic" badge, URL and explicit product input instead of a period list; the result view shows "Dynamic" in place of a billing-mode label for
  a tariff the apply step linked to a source.
- **`dynamicSources.ts`** — the two pure functions above, tested directly
  (`tests/dynamic-sources.test.ts`).
- **`types/api.ts`** — `DynamicTariffSource`, `DynamicTariffType`,
  `Tariff.dynamic_source` / `TariffInput.dynamic_source`,
  `VseTariffCandidate.dynamic_url`, `VseTariffImportResult.created[].dynamic`.
- **`DynamicPriceHistoryModal`** — linked from the expanded dynamic tariff and
  from the platform admin table. It exposes a seven-day default/31-day maximum
  date window, summary statistics, a step chart, explicit coverage gaps, and a
  paginated interval table.
- **`AdminDynamicSourcesPanel`** — routed as `/admin/dynamic-sources` in the
  Admin Overview hub. It displays global source/point/reuse/failure KPIs and a
  `DataTable` with current fetch state, last error/time and reuse counts. Its
  `ActionMenu` opens history or source-filtered audit activity, queues refresh
  or supported backfill, re-checks discovered capabilities (§10.3's
  `recheck`, for correcting a wrongly-negative `supports_backfill`), edits
  configuration (including enabling/disabling scheduled refreshes), and opens
  the guarded typed confirmation form for either
  destructive action — clearing the fetched prices, or deleting the source
  outright. Delete is disabled in the menu while `linked_tariff_count > 0`,
  so the 409 the server would return is visible before the round trip. The
  source list refreshes every 30 seconds.

## 11. Transfer archive

`Tariff.dynamic_source` travels as a nested **natural key**
(`DYNAMIC_SOURCE_FIELDS`: label, url, api_version, request_mode,
query_tariff_type, supports_range, empty_on_not_found, enabled, tariff_type,
tariff_name), not as
its surrogate id, which means nothing on another instance. The importer
get-or-creates the matching global source. A disabled source stays disabled
on import (no backfill is queued for it); price points and the
`recovery_from` retry cursor never travel.

The price **points do not travel**: they are a global series of tens of thousands
of rows per year, not one community's data, and the importing instance fetches
its own. Invoices already issued are unaffected — an `InvoiceItem` records what
was charged as values, not as a live reference to the price that produced it.
Each invoice also carries `dynamic_evidence` entries with embedded source
descriptors, tariff UUID snapshots, and evidence bounds, independently of tariff
selection. Older archives infer provenance once from imported tariffs when
available. Version 2 adds `enabled`, `empty_on_not_found`, and this invoice
provenance to the archive contract; current code still
accepts version 1 static archives and legacy adapter-based dynamic descriptors.

## 12. Test plan

### 12.1 Backend

| Module | Tests | Coverage |
|---|---|---|
| `tariffs/test_dynamic_parsing.py` | 26 | v1/v2 detection and parsing; unit selection (including a missing-unit warning); empty/malformed responses; DST; generic request construction |
| `tariffs/test_dynamic_discovery.py` | 9 | Version/product discovery; named exact-v2 verification; override and empty-response fallback; standard, exact-URL, range, and query-spelling capability detection |
| `tariffs/test_dynamic_fetch.py` | 53 | Chunking, UTC storage, upsert idempotency, half-open invoice evidence, partial conflict writes, resulting-set overlap checks, recovery cursors including old failed/unattempted windows, coverage gaps, windows, failure recording, tasks, source identity |
| `tariffs/test_dynamic_tariff_link.py` | 13 | `Tariff.clean()` rules, capability validation, static→dynamic series versioning, PROTECT retention, no dynamic price bands |
| `zev/test_transfer.py::DynamicTariffTransferTests` | 4 | Natural-key match, recreation on a fresh instance, static tariffs unaffected |
| `invoices/test_dynamic_evidence.py` | 6 | Frozen provenance after tariff mutation/deletion; legacy-refund refusal; migration backfill and overlap preflight; PostgreSQL barriers verify concurrent clear/overwrite waits for invoice evidence |
| `invoices/test_dynamic_pricing.py` | 18 | `_DynamicSeries` bisection, `TariffResolver.price_at` (static and dynamic), the gap refusal, end-to-end `generate_invoice` (consumption, negative prices, percentage base, feed-in) |
| `invoices/test_readiness.py::DynamicTariffPricingCoverageTests` | 8 | Full/partial/no coverage, type-masking, percentage-tariff coupling, DST, static→dynamic series versioning, and coverage checked regardless of category (a dynamic tariff filed under `grid_fees`) |
| `invoices/test_dynamic_tariff_pricing.py` | 19 | Duration weighting, bounded/persistent-key batch summaries, historical percentage dates with one source query, flat/HT/NT/band fallback, unavailable-wins ordering, and static multi-band flags |
| `invoices/test_tariff_overview.py::TariffOverviewDynamicTariffTests` | 4 | Unfetched tariff prints an unavailable row, fetched average with its footnote, percentage-tariff footnote and amount |
| `tariffs/test_dynamic_components.py` | 6 | Per-version aggregate composition, recursive v2 expansion, `dso` excludes electricity, `integrated` certain/possible split, plain/unknown types empty |
| `tariffs/test_vse_import.py` | 102 | Dynamic grid candidate is importable, no-URL and storage-refund blocks, the missing-product warning, version-aware aggregate warnings (preview names certain + possible-extra, apply upgrades to the probed version's exact list), `is_free` correctness, source get-or-create + probe + version-aware reuse after probing, real probe-point initialization with successful status/timestamps, unreachable-URL error, post-commit initial-backfill enqueueing only after a successful new-source tariff write, auto-detection of the probed API version (not hardcoded v1.0.5), and a new source's dropped-unit warnings reaching the apply result |
| `tariffs/test_dynamic_source_api.py` | 6 | Authenticated role access, global list and picker fields |
| `tariffs/test_dynamic_source_management_api.py` | 32 | Discovery (components carry the versioned expansion), served `aggregated_tariff_types` on the source list, probed creation/reuse (and the probe's dropped-unit warnings reaching the response and audit metadata), API-version validation, admin editing, scoped history/stats/limits, queue audit, permissions, guarded clear (label only, mistyped label refused), guarded delete (unused source removed with its points and audited, still-linked source refused with 409, mistyped/absent label refused, owner refused, refused while the fetch lock is held), and capability re-checking (corrects a wrongly-detected `supports_range`, reports dropped units, admin-only, refused while the fetch lock is held, a fetch failure leaves identity untouched) |
| `tariffs/test_dynamic_source_link_api.py` | 12 | Historical percentage-base parity on detail/series; linking through the ordinary tariff API: create with a source, mismatched-energy-type 400, fee-tariff-cannot-link 400, existing-band refusal, dynamic source on duplicated/new versions, `dynamic_source` on the series endpoint, and the evidence-preservation guard (deleting/repointing/clearing a billed dynamic tariff's source refused; unbilled ones unaffected; setting a source for the first time unaffected) |

### 12.2 Fixtures

`backend/tariffs/dynamic/testdata/` — see its `README.md`. Two are **real
captures** taken on 2026-09-11; the BKW one **cannot be re-taken**, because that
endpoint serves only the current day and keeps no history.

### 12.3 Frontend

| Module | Tests | Coverage |
|---|---|---|
| `tests/dynamic-sources.test.ts` | 12 | Source/energy-type helpers; discovery; paginated list; manual create; bounded history query; fetch queueing; typed clear request; typed source delete (the aggregate expansion is served by the backend — see `test_dynamic_components.py`) |
| `tests/dynamic-source-form-modal.test.ts` | 1 | Two-step rendering, version-only choices, absence of provider choices, and discovered component/product selection |
| `tests/vse-tariff-import.test.ts` (extended) | +3 | A dynamic candidate is selectable, offers no billing-mode choice, can be the pre-selected recommendation |
| `tests/tariff-form-mapping.test.ts` (extended) | +4 | `dynamic_source` round-trips through the form, is dropped when billing mode is not energy, defaults to blank |

## 13. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Operator drops history before we fetch it | High — the period becomes unbillable forever | Backfill on creation; 4-hourly schedule; prices retained as evidence (ADR 0018) |
| A gap bills as zero | High — silently wrong invoice | Engine refuses (§9); readiness flags the day first |
| Endpoint URL rots | Medium | Failures recorded per source in user-safe text; `--probe` before trusting |
| An aggregate component (`integrated`, `dso*`) billed beside a tariff for a type it contains | High — double charge | §3.3 documented; version-aware warning by name at both configuration points (preview names certain + possible-extra, pickers and apply result name the exact versioned expansion), not blocked |
| A billed dynamic tariff changes or disappears | High — provenance loss | Frozen invoice/source/window rows survive tariff changes; shared source locks serialize billing and maintenance |
| A wrongly-detected `supports_range` traps a source with no way back | Low — history stays unfetchable, not a correctness bug | §10.3's `recheck` re-probes the endpoint without touching identity or stored points |
| A response parsed as the wrong version | High — bills nothing or the wrong component | Shape detection plus explicit version validation (§4.5) |
| Shared source edited by one community affects others | Medium | Owners may create/reuse but only admins may edit; identity fields remain locked after creation |

## 14. Acceptance criteria

- [x] A VSE v1 response is parsed by unit, not by array position
- [x] Unbillable units are reported rather than silently ignored
- [x] Provider-neutral request capability discovery, verified against recorded fixtures
- [x] Component and product are explicit configuration, never an implicit default
- [x] Fetching is scheduled, chunked below the fetch cap, and reuses the SSRF guards
- [x] Empty 200 responses are successful; 404 needs explicit administrator opt-in; 410 fails
- [x] Coverage is computed on intervals, correct across both DST transitions
- [x] Billed prices remain protected independently of later tariff edits
- [x] V1.0.5 and v2.0.0 payloads are detected and parsed by their versioned contracts
- [x] The transfer archive carries the source link by natural key
- [x] The engine prices from the series and refuses an uncovered period
- [x] Readiness flags an uncovered day before generation is attempted
- [x] Printed documents (tariff overview, participation contract) show a dynamic tariff's fetched average rather than skipping it or printing zero
- [x] The importer creates dynamic tariffs instead of blocking them, and refuses (per-candidate) rather than creating a dead tariff when the named URL cannot be fetched
- [x] The UI shows that a tariff is dynamic, which source it uses, and when that source's last fetch failed
- [x] An owner can discover, create, and select a dynamic source in a two-step wizard
- [x] Linked tariffs expose bounded interval-price history, statistics, and explicit gaps
- [x] Admins can inspect every shared source and its fetch activity, queue refresh/backfill, safely clear unbilled points, delete a source once no tariff uses it, and re-check discovered capabilities without touching identity or stored points
- [x] Readiness flags an uncovered day for a dynamic tariff regardless of its `category`, matching the engine's own category-agnostic resolution
- [x] Choosing an aggregate component (`integrated`, v2's `dso`/`dso_complete`/`integrated_complete`) surfaces a warning naming what it already contains, at both the source wizard and the tariff form's picker
- [x] Deleting or repointing a tariff's `dynamic_source` is refused once that tariff has priced a non-cancelled invoice, mirroring the source-side clear/delete guard
