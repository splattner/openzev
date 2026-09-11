# Feature Spec: Dynamic tariffs

- Spec ID: SPEC-2026-dynamic-tariffs
- Status: In Progress
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

| Part | Covers | Sections |
|---|---|---|
| 1 | Data model, parser, adapters, fetching, scheduling, transfer | 3 – 8 |
| 2 | Engine price resolution, refusal, readiness coverage | 9 |
| 3 | Importer unblock, API and frontend | 10 |

Sections 9 and 10 describe intended behaviour that is **not yet implemented**.

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

## 9. Billing (part 2 — not yet implemented)

Price resolution funnels through `TariffResolver.price_at(tariff, ts)`, which
returns `(price, period)`; a dynamic tariff resolves from the series and returns
`period=None`. All four engine resolution points use it: energy pricing, the
percentage-tariff grid base, and both feed-in credit blocks. The series is
loaded once per `InvoiceGenerationContext`, not per participant.

A dynamic tariff with **no price at a reading's timestamp raises** rather than
billing `Decimal("0")`, which is what a missing static band does today. The check
is against reading timestamps, not a synthetic grid, so DST needs no case.

Readiness treats a dynamic tariff as priceable on a day iff its source covers
that day, replacing the `len(t.periods.all()) > 0` predicate. Reported through
the existing `tariffs` step — no new step key.

## 10. Import and UI (part 3 — not yet implemented)

The VSE importer stops blocking `tariffForm: dynamic`, creating the tariff and
getting-or-creating its source from `prices.dynamic.url`. The URL is validated
with one live probe first: the URL named as the example in the standard's own
OpenAPI (`api.tariffs.groupe-e.ch/v1/tariffs`) now returns **410 Gone**, so a URL
in a document is a starting point, not a contract.

The tariff card shows that a tariff is dynamic, which component and product it
bills, when it was last fetched and what the series covers; choosing `integrated`
warns about §3.3's double counting.

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

### 12.2 Fixtures

`backend/tariffs/dynamic/testdata/` — see its `README.md`. Two are **real
captures** taken on 2026-09-11; the BKW one **cannot be re-taken**, because that
endpoint serves only the current day and keeps no history.

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
- [ ] The engine prices from the series and refuses an uncovered period (part 2)
- [ ] Readiness flags an uncovered day before generation (part 2)
- [ ] The importer creates dynamic tariffs instead of blocking them (part 3)
- [ ] The UI shows that a tariff is dynamic and how current its data is (part 3)
