# Feature Spec: Dynamic tariffs

- Spec ID: SPEC-2026-dynamic-tariffs
- Status: Completed
- Scope: Major
- Type: Feature
- Owners: Core maintainers
- Created: 2026-09-11
- Target Release: Ongoing
- Related Issues: #530 (parent gap #507, importer #520), #702, #703
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
| 1 | Data model, versioned protocol, fetching, scheduling, transfer | 3 – 8 | Shipped |
| 2 | Engine price resolution, refusal, readiness coverage | 9 | Shipped |
| 3 | Importer unblock, API and frontend | 10 | Shipped |

All three parts are shipped.

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
an `energy` value in `CHF/kWh`; the first five consumption-oriented types map to
`grid`, while `refund` maps to `feed_in`. Components containing only base,
power, or reactive-energy prices are not offered because the billing engine
cannot apply them per metered kWh.

⚠️ **Double counting.** `integrated` already contains `electricity` and `grid`;
v2's `dso`/`dso_complete`/`integrated_complete` additionally bundle in
`metering`, `national_fees`, and (for the `_complete`/`integrated_complete`
variants) `regional_fees`. Billing one of these beside a community's existing
tariff for a type it already contains charges the same money twice. OpenZEV
does not block the combination — a community's tariffs are configured
independently and nothing enumerates "what else prices this ZEV" — but §10
warns at both configuration points (picking the component, and linking a
tariff to it) naming exactly which types the choice already contains
(`dynamicSources.aggregatedTariffTypes`).

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
| `api_version` | `CharField(20)` | `v1_0_5` \| `v2_0_0` |
| `request_mode` | `CharField(20)` | discovered `standard` \| `exact_url` |
| `query_tariff_type` | `CharField(20)` | discovered wire spelling, not user-entered |
| `supports_range` | `BooleanField` | discovered endpoint capability |
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

### 4.4 Version detection and parsing

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

`fetch.coverage_gaps(source, start, end)` walks stored intervals and returns the
uncovered spans.

Coverage is **never** derived from a count. A quarter-hourly day is 96 intervals
on most days, **92** when the clocks go forward and **100** when they go back;
counting to 96 would call a complete day incomplete twice a year. Walking
intervals also handles an operator publishing hourly.

Holes are ordinary: an endpoint may omit an interval when its upstream source
has no value for it.

## 7. Fetching

`backend/tariffs/dynamic/fetch.py`, reusing
`tariffs/importers/remote.py::fetch_tariff_document` unchanged — the SSRF guard,
per-hop redirect revalidation, 5 MB cap and the user-safe/log-only error split
all apply, because the URL is operator-supplied.

**Chunking is mandatory.** A measured full-history response reached
**5 016 921 bytes — 95.7 % of `MAX_DOCUMENT_BYTES`** and strained the
20-second timeout. Backfill therefore walks at most 31 days per request.

| Mode | Window |
|---|---|
| Scheduled | yesterday → day after tomorrow |
| Backfill | 400 days back → day after tomorrow, chunked |
| No range support | one bare request |

The window starts *yesterday* because it is expressed in UTC while operators
publish in local time; starting at UTC midnight clips the first hours of the
Swiss day. Re-asking is free: writes are upserts on `(source, valid_from)`.

An empty response is a **successful fetch of nothing**, not a failure: the
standard permits an empty publication timestamp/list when nothing is published.

## 8. Scheduling

`backend/tariffs/tasks.py`:

| Task | Role |
|---|---|
| `refresh_dynamic_tariff_sources` | Beat entry; fans out one task per source so one unreachable operator cannot delay the others |
| `fetch_dynamic_prices(source_id, backfill=False)` | Refreshes one source; retries twice on a transport error |
| `fetch_dynamic_prices_impl` | The logic, callable directly from tests |

`CELERY_BEAT_SCHEDULE["refresh-dynamic-tariff-sources"]` runs every **4 hours**,
not daily: endpoints can publish day-ahead data or republish the current day at
different times, so no single moment has final prices.
`publication_timestamp` says when the operator last wrote, not what it covers.

Supported deployments run exactly one Beat scheduler: the three Compose files
declare a `beat` service, and the Helm chart declares a single-replica Beat
deployment. More than one scheduler would enqueue every periodic task more than
once at each tick.

When the importer creates a new source, it queues
`fetch_dynamic_prices(source_id, backfill=True)` with `transaction.on_commit()`
after the tariff write succeeds. Reusing an existing global source does not
queue another initial backfill; that source already has stored history and is
included in the four-hour fan-out.

Outcomes are recorded on the source (`last_fetch_*`) and as an audit event
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
schema, only in the fetched-series API. An endpoint serving a single product
is unaffected; an endpoint serving multiple products needs its source's
`tariff_name` selected explicitly.

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
2. Not found → discovers and probes the URL before creating anything. The
   probe does not pin an API version: the VSE tariff document names a
   `tariffType` (`electricity`/`grid`/`regional_fees`), never a protocol
   version, and both v1.0.5 and v2.0.0 define that vocabulary, so
   auto-detection lets a document link to either generation of endpoint —
   the same way the manual two-step wizard already does. **A URL in a
   document is a starting point, not a contract** — the URL named as the
   example in the standard's own OpenAPI
   (`api.tariffs.groupe-e.ch/v1/tariffs`) now returns **410 Gone**. A failed
   probe reports the fetch error against that candidate (`report.errors`)
   and creates nothing; other candidates in the same import are unaffected.
3. Creates the source with the discovered generic request capabilities via
   `get_or_create` on the same natural key, race-safe against a concurrent
   import of the same endpoint.
4. After the tariff has been written successfully, a newly created source gets
   one post-commit `backfill=True` task. A reused source gets no duplicate
   initial task.

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
the two never disagree.

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
- **`PATCH /tariffs/dynamic-sources/{id}/`**: admin only. Label corrections are
  always allowed. Identity changes remain guarded; the UI directs operators to
  create a replacement source rather than mixing two series.
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
- **`DELETE /tariffs/dynamic-sources/{id}/prices/`**: admin only; empties the
  source but keeps it, so the next fetch refills it. It returns 409 while the
  source is fetching or when any non-cancelled invoice overlaps any linked
  tariff. On success it deletes points, resets materialized coverage/fetch
  state, and writes an audit event with the deleted count.
- **`DELETE /tariffs/dynamic-sources/{id}/`**: admin only; removes the source
  itself and, by cascade, every price it fetched. Refused with 409 while any
  tariff still links to it — the count is read first so the response can name
  how many tariffs in how many communities still use it, and `Tariff.
  dynamic_source` being `on_delete=PROTECT` is what a `ProtectedError` raised
  by the delete itself falls back to the same 409 for, closing the window
  where a tariff gets linked between that count and the delete. An unlinked
  source cannot have *currently* contributed to an invoice, since
  `source_has_billing_evidence` reasons entirely over currently-linked
  tariffs — but a tariff could have been billed and then unlinked or deleted
  a moment before, which is exactly the case the tariff-side guard below
  closes, so it is what actually makes "unlinked" imply "no evidence" here.
  Returns 204 and writes an audit event naming the label and point count,
  which is the only record left once the row is gone.

Both destructive source endpoints take the source's own **label, typed back**
(`confirmation`), and nothing else. A `reason` is recorded when one is sent but
is never required: a free-text box in front of an irreversible action invites a
keystroke rather than a thought, while the label has to be read off the row
that is about to be destroyed, which is what actually stops the wrong source
being picked out of a list.

- `TariffSerializer.validate` gains one check: a tariff's `dynamic_source` is
  the only thing tying an issued invoice back to the fetched prices behind it
  (invoice items store rendered amounts, not a tariff FK), so repointing or
  clearing it on a tariff that already priced a non-cancelled invoice is
  refused the same way clearing a source's points is — the same evidence,
  lost through the tariff side of the link instead of the source side.
  Setting `dynamic_source` for the *first* time is unaffected: there was no
  link to lose. `TariffViewSet.perform_destroy` applies the identical check
  before deleting a tariff outright, for the same reason.

### 10.3a Both sides of the evidence link

Two independent things can each sever the tie between an issued invoice and
the `DynamicPricePoint` rows behind it, and both are guarded the same way —
by the source's own `source_has_billing_evidence` and the tariff's own
`tariff_has_dynamic_billing_evidence` (`tariffs/dynamic/services.py`), which
share one overlap check:

| Action | What it would sever | Guard |
|---|---|---|
| Clear/delete a source's points | Every tariff's link at once | `source_has_billing_evidence` — over every currently-linked tariff |
| Delete a billed dynamic tariff | That one tariff's link | `TariffViewSet.perform_destroy` |
| Repoint/clear a billed tariff's `dynamic_source` | That one tariff's link | `TariffSerializer.validate` |

Without the last two, a tariff could be deleted or repointed after billing —
nothing in the codebase prevented that generally, since invoices are
deliberately decoupled from tariffs (`Invoice` carries no tariff FK at all) —
dropping `linked_tariff_count` to zero and letting the source-level check
pass despite the source having priced an invoice moments before.

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
  already contains (`dynamicSources.aggregatedTariffTypes`) — the
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
- **`VseTariffImportModal`** — a dynamic candidate's price cell shows a
  "Dynamic" badge and its URL instead of a period list (it has no periods to
  list); the result view shows "Dynamic" in place of a billing-mode label for
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
  configuration, and opens the guarded typed confirmation form for either
  destructive action — clearing the fetched prices, or deleting the source
  outright. Delete is disabled in the menu while `linked_tariff_count > 0`,
  so the 409 the server would return is visible before the round trip. The
  source list refreshes every 30 seconds.

## 11. Transfer archive

`Tariff.dynamic_source` travels as a nested **natural key**
(`DYNAMIC_SOURCE_FIELDS`: label, url, api_version, request_mode,
query_tariff_type, supports_range, tariff_type, tariff_name), not as
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
| `tariffs/test_dynamic_parsing.py` | 23 | v1/v2 detection and parsing; unit selection (both versions report a fixed fee riding beside the requested energy component); empty/malformed responses; DST; generic request construction |
| `tariffs/test_dynamic_discovery.py` | 6 | Version/product discovery; override and empty-response fallback; standard, exact-URL, range, and query-spelling capability detection |
| `tariffs/test_dynamic_fetch.py` | 24 | Chunking, UTC storage, upsert idempotency, negative prices, coverage gaps, windows, failure recording, tasks, source identity |
| `tariffs/test_dynamic_tariff_link.py` | 9 | `Tariff.clean()` rules, static→dynamic series versioning, PROTECT retention |
| `zev/test_transfer.py::DynamicTariffTransferTests` | 3 | Natural-key match, recreation on a fresh instance, static tariffs unaffected |
| `invoices/test_dynamic_pricing.py` | 17 | `_DynamicSeries` bisection, `TariffResolver.price_at` (static and dynamic), the gap refusal, end-to-end `generate_invoice` (consumption, negative prices, percentage base, feed-in) |
| `invoices/test_readiness.py::DynamicTariffPricingCoverageTests` | 8 | Full/partial/no coverage, type-masking, percentage-tariff coupling, DST, static→dynamic series versioning, and coverage checked regardless of category (a dynamic tariff filed under `grid_fees`) |
| `invoices/test_dynamic_tariff_pricing.py` | 9 | `dynamic_average_chf_per_kwh`, `display_grid_base_chf_per_kwh`, `grid_base_is_dynamic` vs `grid_base_is_multiband` |
| `invoices/test_tariff_overview.py::TariffOverviewDynamicTariffTests` | 4 | Unfetched tariff prints nothing, fetched average with its footnote, percentage-tariff footnote and amount |
| `tariffs/test_vse_import.py` (extended) | +13 | Dynamic grid candidate is importable, no-URL and `metering` blocks, the missing-product warning, `is_free` correctness, source get-or-create + probe + reuse-without-reprobing, unreachable-URL error, post-commit initial-backfill enqueueing only after a successful new-source tariff write, auto-detection of the probed API version (not hardcoded v1.0.5), and a new source's dropped-unit warnings reaching the apply result |
| `tariffs/test_dynamic_source_api.py` | 6 | Authenticated role access, global list and picker fields |
| `tariffs/test_dynamic_source_management_api.py` | 29 | Discovery, probed creation/reuse (and the probe's dropped-unit warnings reaching the response and audit metadata), API-version validation, admin editing, scoped history/stats/limits, queue audit, permissions, guarded clear (label only, mistyped label refused), guarded delete (unused source removed with its points and audited, still-linked source refused with 409, mistyped/absent label refused, owner refused, refused while the fetch lock is held), and capability re-checking (corrects a wrongly-detected `supports_range`, reports dropped units, admin-only, refused while the fetch lock is held, a fetch failure leaves identity untouched) |
| `tariffs/test_dynamic_source_link_api.py` | 9 | Linking through the ordinary tariff API: create with a source, mismatched-energy-type 400, fee-tariff-cannot-link 400, `dynamic_source` on the series endpoint, and the evidence-preservation guard (deleting/repointing/clearing a billed dynamic tariff's source refused; unbilled ones unaffected; setting a source for the first time unaffected) |

### 12.2 Fixtures

`backend/tariffs/dynamic/testdata/` — see its `README.md`. Two are **real
captures** taken on 2026-09-11; the BKW one **cannot be re-taken**, because that
endpoint serves only the current day and keeps no history.

### 12.3 Frontend

| Module | Tests | Coverage |
|---|---|---|
| `tests/dynamic-sources.test.ts` | 15 | Source/energy-type helpers; discovery; paginated list; manual create; bounded history query; fetch queueing; typed clear request; typed source delete; `aggregatedTariffTypes` for every aggregate and non-aggregate component |
| `tests/dynamic-source-form-modal.test.ts` | 1 | Two-step rendering, version-only choices, absence of provider choices, and discovered component/product selection |
| `tests/vse-tariff-import.test.ts` (extended) | +3 | A dynamic candidate is selectable, offers no billing-mode choice, can be the pre-selected recommendation |
| `tests/tariff-form-mapping.test.ts` (extended) | +4 | `dynamic_source` round-trips through the form, is dropped when billing mode is not energy, defaults to blank |

## 13. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Operator drops history before we fetch it | High — the period becomes unbillable forever | Backfill on creation; 4-hourly schedule; prices retained as evidence (ADR 0018) |
| A gap bills as zero | High — silently wrong invoice | Engine refuses (§9); readiness flags the day first |
| Endpoint URL rots | Medium | Failures recorded per source in user-safe text; `--probe` before trusting |
| An aggregate component (`integrated`, `dso*`) billed beside a tariff for a type it contains | High — double charge | §3.3 documented; §10 warns by name at both configuration points (picking the component, linking a tariff to it), not blocked |
| A billed dynamic tariff deleted or repointed away from its source | High — the invoice's only link to its evidence disappears | §10.3a: `TariffViewSet.perform_destroy` and `TariffSerializer.validate` refuse it, mirroring the source-side clear/delete guard |
| A wrongly-detected `supports_range` traps a source with no way back | Low — history stays unfetchable, not a correctness bug | §10.3's `recheck` re-probes the endpoint without touching identity or stored points |
| A response parsed as the wrong version | High — bills nothing or the wrong component | Shape detection plus explicit version validation (§4.4) |
| Shared source edited by one community affects others | Medium | Owners may create/reuse but only admins may edit; identity fields remain locked while points exist |

## 14. Acceptance criteria

- [x] A VSE v1 response is parsed by unit, not by array position
- [x] Unbillable units are reported rather than silently ignored
- [x] Provider-neutral request capability discovery, verified against recorded fixtures
- [x] Component and product are explicit configuration, never an implicit default
- [x] Fetching is scheduled, chunked below the fetch cap, and reuses the SSRF guards
- [x] `200`-with-empty, `404` and `410` are each handled distinctly
- [x] Coverage is computed on intervals, correct across both DST transitions
- [x] Prices are retained for as long as the tariff referencing them exists
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
