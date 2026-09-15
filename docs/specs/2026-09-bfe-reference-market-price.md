# Feature Spec: BFE reference market price and minimum feed-in price

- Spec ID: SPEC-2026-bfe-reference-market-price
- Status: Completed
- Scope: Minor
- Type: Feature
- Owners: Sebastian Plattner
- Created: 2026-09-14
- Target Release: 1.14.0
- Related Issues: [#720](https://github.com/splattner/openzev/issues/720)
- Related ADRs: [0018](../adr/0018-dynamic-tariff-price-series.md), [0019](../adr/0019-frozen-dynamic-price-evidence.md)
- Related Specs: [2026-09-dynamic-tariffs](2026-09-dynamic-tariffs.md)
- Impacted Areas: backend, frontend, async jobs, docs

---

## 1. Problem and outcome

Some grid operators pay feed-in remuneration as **the greater of** a
contractually fixed minimum price per kWh **or** the BFE reference market
price for the settlement period. Since 2026-01-01 that mirrors the statutory
default: absent another agreement, Art. 15 EnG/EnV points at the BFE
reference market price (Art. 15 EnFV) as the baseline.

Neither half existed. A tariff was priced *either* from static bands *or*
entirely from a fetched series — there was no "whichever is higher" — and
`DynamicTariffSource` only spoke the VSE protocol: live operator endpoints
serving quarter-hourly JSON, discovered by probing. The BFE reference price
is a different shape of publication entirely: a small federal open-data CSV,
one price per quarter (or month) per technology, with no request protocol.

**Outcome:** an administrator configures the BFE publication once as a
shared price source, links a feed-in tariff to it, sets the contractual
minimum, and the engine credits exported energy at `max(minimum, reference)`.

## 2. Scope

### In scope

- `Tariff.minimum_price_chf_per_kwh`, a floor under a fetched feed-in series.
- `DynamicApiVersion.BFE_RMP`, a third publication protocol, with a CSV
  parser and a creation path that skips VSE discovery.
- Both published series (quarterly and monthly) and all four technologies.
- Display and printed-document handling for a source that publishes one
  price per period rather than continuously.

### Out of scope

- A floor on a static band-priced tariff, or on any non-feed-in tariff.
- A price *ceiling*, or any comparison other than `max`.
- Provisional invoices that re-settle once BFE publishes (see §8).
- Automatically deciding which ZEVs should use the reference price.

## 3. The publication

| | |
|---|---|
| Dataset | `BFE-DS-0020` on [i14y](https://www.i14y.admin.ch/de/catalog/datasets/BFE-DS-0020) / opendata.swiss |
| Quarterly | `https://www.bfe-ogd.ch/ogd60_rmp_quartalspreise.csv` |
| Monthly | `https://www.bfe-ogd.ch/ogd60_rmp_monatspreise.csv` |
| Columns | `Year`, `Period` (`Q1`…`Q4`) *or* `Month` (`1`…`12`), `Days`, then `Volume_<tech>_MWh` and `Price_<tech>_CHF_MWh` per technology |
| Technologies | `pv`, `wasserkraft`, `windenergie`, `biomasse` |
| Cadence | quarterly, by the 10th working day after quarter end, 12:00 |
| Retention | the full history since 2023-Q3 in every response (~1 KB) |
| Licence | `terms_by` (Opendata BY) — free use, **attribution required** |

Discovery of the current download URL, if it should ever move:
`GET https://api.i14y.admin.ch/api/public/v1/datasets?datasetIdentifier=BFE-DS-0020`
(no authentication) returns the live `distributions[].downloadUrl`.

## 4. Data model

Migrations `tariffs/0016` (the floor) and `tariffs/0017` (the widened
`api_version` choices). No new tables: the reference price reuses
`DynamicTariffSource` / `DynamicPricePoint` wholesale, so evidence retention,
`PROTECT` on billed sources, locking and the admin operations all apply
unchanged — see ADR 0018 for why this is one protocol rather than a parallel
model.

### 4.1 `Tariff.minimum_price_chf_per_kwh`

| Field | Type | Note |
|---|---|---|
| `minimum_price_chf_per_kwh` | `DecimalField(8, 5)`, null, blank | Floor under a fetched series |

Validated in `Tariff.clean()`: it requires `dynamic_source`, and requires
`energy_type = feed_in`. The second rule is deliberate — a floor on a grid
series would propagate into the percentage-of-energy base every such tariff
feeds (the Art. 16 ceiling), which is not what an "at least X" feed-in clause
means.

Deliberately **not** one of `SERIES_FIELDS`: it is a price, like
`fixed_price_chf`, so it must be free to change from one tariff version to
the next. `TariffViewSet._apply_price_overrides` therefore carries it onto a
new version, and `TARIFF_FIELDS` carries it through the transfer archive.

### 4.2 `DynamicApiVersion.BFE_RMP`

`api_version` names the publication protocol, not only an endpoint version.
`bfe_rmp` sits beside `v1_0_5` and `v2_0_0` and reuses the existing identity
tuple:

```
(url, api_version="bfe_rmp", tariff_type="feed_in", tariff_name=<technology>)
```

`url` separates the quarterly series from the monthly one; `tariff_name`
carries the technology in the slot v2 uses for an operator's product. One
globally shared row per (series, technology), which is the right scope: a
national reference price is one fact, not one per community.

Two rules in `DynamicTariffSource.clean()` guard the combination:

- `tariff_name` must be one of the four technologies.
- `tariff_type` must be `feed_in`. Without this a source could be filed as
  `grid` and would then satisfy `Tariff._dynamic_source_errors` for grid
  *consumption* — billing what a producer is paid as what a consumer owes.

Capabilities are fixed rather than discovered: `request_mode = exact_url`,
`supports_range = false`. Those are the values the existing fetch loop
already understands, so no window or scheduling logic changes.

## 5. Parsing

`backend/tariffs/dynamic/bfe_rmp.py`, pure like `vse_v1` / `vse_v2`: no
database, no network, no Django.

- `parse_tariff_response(text, *, tariff_name)` selects the technology's
  `Price_<tech>_CHF_MWh` column and returns the same `PricePoint` /
  `ParsedSeries` shapes the VSE parsers return.
- **Unit:** CHF/MWh ÷ 1000 → CHF/kWh. The source carries two decimals, so the
  result always lands on exactly the five `DynamicPricePoint` stores — no
  rounding loss (`38.96 → 0.03896`).
- **Period → interval:** `[start, end)` built from **Europe/Zurich civil**
  month boundaries and converted to UTC, so a quarter runs e.g.
  `2026-03-31T22:00Z … 2026-06-30T22:00Z`. Consecutive periods are contiguous
  by construction, so the series has no boundary gaps.
- A blank price cell is skipped, not an error: BFE leaves the current period
  blank rather than omitting the row.
- Rows are sorted and checked for overlap before storage —
  `DynamicPricePoint` has no database-level non-overlap constraint, and the
  display bisections depend on the invariant.

## 6. Fetching

`fetch_window` branches on the protocol: `bfe_rmp` downloads text
(`fetch_tariff_text`), everything else JSON (`fetch_tariff_document`). Both
sit on one shared `_download` in `importers/remote.py` so the SSRF guard,
redirect validation and size cap stay in exactly one place.

Because the source is `supports_range = false`, `refresh_source` already
issues a single unparameterised request per run, and a backfill is the same
request as a refresh. Every fetch therefore re-reads the whole published
history and `store_points` no-ops on unchanged rows.

**Known consequence:** if BFE revises a *past* period that a non-cancelled
invoice already used, `store_points` raises `BilledPriceChanged` and the
whole fetch fails — so newly published periods stop being ingested too, until
an administrator clears the source's points or cancels the affected invoice.
A VSE source never hits this, because its windows only reach back a fortnight.
This is the evidence protection working as designed (ADR 0018/0019), but it
is a support case worth recognising: the source sits in `failed` with the
conflict in `last_fetch_error`.

## 7. Creation

`create_or_reuse_source` branches for `bfe_rmp` to `probe_bfe_rmp_source`,
which fetches and parses the CSV once and returns the same
`SourceCapabilities` shape the VSE probe returns — so
`initialise_source_from_probe` stores the whole history immediately and the
source is usable the moment it is created. There is nothing to discover, so
`discover_endpoint` / `probe_source_configuration` are never called for it,
and `recheck_source_capabilities` is a no-op (its request shape is fixed, not
probed).

## 8. Billing

`TariffResolver.price_at` is the single funnel every pricing call site reads
from. For a tariff carrying a floor it returns `max(floor, fetched price)`,
which covers both feed-in credit loops without either of them learning about
it.

The floor is applied **after** the gap check, not instead of it: a period BFE
has not published yet is still a refusal, not a fall back to the minimum.
Under-crediting a producer for a quarter whose reference later turns out to
be *above* the floor would be the worse error, and readiness already reports
the uncovered days. In practice this means a ZEV can close a quarter once BFE
publishes it — roughly ten working days after it ends.

## 9. Display

A period-published source is always weeks behind: the trailing 30-day window
`summarize_dynamic_tariff` uses would sit in the unpublished stretch and
report "price unavailable" permanently, printed tariff overview included.

- `PERIOD_PUBLISHED_API_VERSIONS` marks the protocols this applies to.
  For those, the display window is anchored on the last **fully covered**
  civil day (derived from `covers_to`) instead of on today. Every other
  source still anchors on today, where an empty window is the honest answer
  and is how a stalled endpoint surfaces.
- The floor is applied **per interval before duration weighting**, never to
  the finished average — otherwise the displayed rate would disagree with
  what the invoice bills.
- The tariff overview PDF states the minimum beside the figure
  (`dynamic_minimum`, all four languages), including when the series is
  unavailable: the floor is knowable even when the reference is not.
- The Tariffs page appends `min. CHF x/kWh` to the price summary.

### 9.1 Price history

The `prices/` endpoint's 31-day cap is sized for a quarter-hourly series and
would make even a single BFE quarter (~91 days) un-viewable, so the cap is
keyed by protocol (`MAX_PRICE_HISTORY_DAYS_BY_API_VERSION`); a
period-published source gets a 20-year cap, which is free when the whole
series is a few dozen rows.

Opened from the Tariffs page, the history view is scoped to the tariff it was
opened for: the date range defaults to and is bounded by that tariff's own
validity — a shared source's series can start years before a given tariff
linked to it — and displayed points and stats are floored at the tariff's
minimum. The admin Dynamic Sources panel, which has no single tariff to scope
to, still shows the raw shared series.

## 10. API contracts

No new endpoints. Changed shapes:

- `Tariff` gains `minimum_price_chf_per_kwh` (read/write). `TariffSerializer.validate`
  nulls it for any tariff that is not a dynamic feed-in tariff, matching the
  other per-mode normalisations.
- `POST /api/v1/tariffs/dynamic-sources/` accepts `api_version="bfe_rmp"`;
  `tariff_type` must be `feed_in` and `tariff_name` a technology.
- `GET /api/v1/tariffs/dynamic-sources/<id>/prices/` applies the
  protocol-dependent range cap described in §9.1.

## 11. Frontend

- The source wizard offers a **source kind**: an operator endpoint (the
  existing two-step discovery flow) or the BFE reference market price, which
  is single-step — pick the series (quarterly/monthly) and the technology,
  and the URL follows from the series.
- The tariff form shows a **minimum price** field when a feed-in tariff has a
  dynamic source selected; the new-version and duplicate dialogs carry it.
- Zod validation mirrors the DRF rules, and the payload mapper clears the
  floor for anything that is not a dynamic feed-in tariff, so a value left
  behind by switching energy type can never reach the server.

## 12. Transfer archive

`minimum_price_chf_per_kwh` joins `TARIFF_FIELDS`; archives written before it
simply omit the key. The source travels by its natural key as before — the
key already contains `api_version`, so a BFE source round-trips with no
change, and the importing instance re-fetches the series itself.

## 13. Risks and mitigations

| Risk | Mitigation |
|---|---|
| A revised historical period blocks all further ingestion (§6) | Surfaced as a `failed` source with the conflict text; recovered by clearing points, which is already guarded by billing evidence |
| The reference price for a period is published weeks after it ends | Billing refuses rather than guessing (§8); readiness names the uncovered days; display anchors on coverage (§9) |
| A source filed under the wrong component prices the wrong energy | `tariff_type` is constrained to `feed_in` for this protocol (§4.2) |
| Attribution obligation under `terms_by` | The protocol is named in the UI wherever the source appears; ZEVs republishing the figures are told of the obligation in the user guide |

## 14. Test plan

### Backend

- `tariffs/test_bfe_rmp_parsing.py` — unit conversion lands on exactly five
  decimals; quarter and month boundaries are Europe/Zurich civil, contiguous
  across both DST switches; unknown technology, missing column, bad period
  and non-numeric price are rejected; a blank price is skipped. Asserted
  against the real captured CSVs in `tariffs/dynamic/testdata/`.
- `tariffs/test_bfe_rmp_source.py` — text rather than JSON download, one bare
  request, every period stored, technology selects the column, creation skips
  VSE discovery and reuses an existing row, recheck is a no-op, and the
  technology/component validation rules.
- `invoices/test_dynamic_pricing.py` — `price_at` floors and does not lower;
  a gap still raises with a floor set; the feed-in credit is billed at the
  floor end to end.
- `invoices/test_dynamic_tariff_pricing.py` — per-interval flooring before
  weighting; coverage anchoring for a period-published source, and that a
  stalled VSE source still reads unavailable.
- `invoices/test_tariff_overview.py` — the printed row states the minimum.
- `tariffs/test_dynamic_source_management_api.py` — the range cap by protocol.
- `zev/test_transfer.py` — the floor round-trips.

### Frontend

- `tests/dynamic-price-history-modal.test.ts` — default range by source kind
  and tariff validity, the floor applied to points, recomputed stats. Pins
  `TZ` rather than depending on the runner's.
- `tests/tariff-form-mapping.test.ts` — the floor is carried for a dynamic
  feed-in tariff and dropped otherwise.

## 15. Acceptance criteria

- [x] A feed-in tariff priced from a fetched series can carry a minimum, and
      bills `max(minimum, reference)` per interval.
- [x] The displayed average never disagrees with what the invoice bills.
- [x] A BFE source can be created from the UI in one step and stores the
      whole published history immediately.
- [x] Both the quarterly and the monthly series are supported, per technology.
- [x] A period BFE has not published yet refuses to bill and is named by
      readiness.
- [x] The printed tariff overview shows the rate and the guaranteed minimum.
- [x] Existing VSE-protocol sources are unaffected in fetching, display and
      price history.
