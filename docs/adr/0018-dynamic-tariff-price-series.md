# ADR 0018: Dynamic tariff prices are stored evidence, in globally shared series

- Status: Accepted
- Date: 2026-09-11

## Context

Swiss operators are moving to dynamic tariffs: instead of publishing a price per
time band, they publish a price per quarter-hour on an HTTP endpoint. A ZEV whose
operator has gone dynamic could not bill grid energy at all — not by import, not
by hand (#530).

When #530 was first written the blocker was that the standard defined the dynamic
price as a bare URL with no response schema. That is no longer true:
SmartGridready publishes a VSE-compatible JSON Schema and OpenAPI template
(v1.0.5, 2026-05-28; v2.0.0 final 2026-09-01 for 2027) derived from the VSE
document *HDN-CH 2025*, and both operators we probed implement the v1 envelope.

Two facts measured against those live endpoints on 2026-09-11 shaped this
decision more than the schema did:

- **Groupe E** (`api.tariffs.groupe-e.ch/v2/tariffs`) serves quarter-hourly
  `grid` and `integrated` prices with range queries, and retains roughly nine
  months of history. Its `grid` series ran −0.0543 … 0.1443 CHF/kWh that day,
  with 22 of 96 intervals negative.
- **BKW** (`api.bkw.ch/api/dyntariffs/v1/Tariffs/energyreturn`) serves
  quarter-hourly `feed_in` prices for the current day only. It **accepts no
  query parameters at all** — any parameter is a 400 — so it has no history to
  ask for, ever.

A third fact shaped the design of the link: the URL named as the example in the
VSE/AES tariff-document OpenAPI, `api.tariffs.groupe-e.ch/v1/tariffs`, now
returns **410 Gone**. A URL carried in a published document is a starting point,
not a contract.

## Decision

**1. The fetched price series is billing evidence, not a cache.**

Prices are stored permanently in `DynamicPricePoint`, and a source still
referenced by a tariff cannot be deleted (`on_delete=PROTECT`). We do not treat
the operator as the system of record and re-fetch on demand.

The reason is retention, not performance. Groupe E drops history after about
nine months and BKW keeps none at all, so an interval nobody stored on the day is
gone from every source including the operator. An invoice issued last March has
to stay re-derivable for as long as the invoice exists, and nothing outside
OpenZEV can supply those numbers again.

**2. Sources are shared globally, not scoped per ZEV.**

`DynamicTariffSource` is unique on `(url, tariff_type, tariff_name)` and carries
no ZEV foreign key. Any number of tariffs, in any number of communities, link to
the same row.

The price of Groupe E's `vario` grid product at a given instant is one fact, not
one fact per community. Scoping it per ZEV would refetch and restore the same
35 040 rows per year for each one, and — worse — two communities adding BKW on
different days would end up with different history for the same public series.

The triple is the identity because all three parts change the number: the
endpoint obviously, the component because `integrated` is a different price from
`grid`, and the product because Groupe E quoted 0.1398 for `vario` and 0.1267 for
`double` at the same instant.

**3. `Tariff` gains a nullable FK, not a new billing mode.**

A dynamic tariff keeps `billing_mode=energy` and simply carries
`dynamic_source`. It therefore flows through the existing `TariffResolver`
buckets, energy pricing, percentage-tariff base and feed-in credits without any
of them learning a new mode.

This also leaves `SERIES_FIELDS` untouched, which means a tariff *series* can go
static → dynamic at a version boundary — exactly what happens when an operator
switches on 1 January — instead of forking into two unrelated series.

**4. Coverage is measured in intervals, never in counts.**

`valid_to` is stored per point rather than derived from a resolution setting, and
gap detection walks the stored intervals. A quarter-hourly day is 96 intervals on
most days, 92 when the clocks go forward and 100 when they go back; anything that
counted to 96 would declare a complete day incomplete twice a year and refuse to
bill it.

## Consequences

Positive:

- Past invoices stay re-derivable from stored prices, independent of operator
  retention.
- One fetch serves every community on the same product; BKW's unrecoverable
  history is captured once for everyone.
- The billing engine needs one resolution branch rather than a new mode threaded
  through item types, sort order, descriptions and the frontend enums.
- DST and hourly-resolution sources need no special cases.

Negative, and accepted:

- A ZEV owner configuring a source writes a row that other communities can also
  use. The row holds a public URL and public prices, so the exposure is a
  configuration label rather than tenant data — but it is a genuine break from
  the strict per-ZEV scoping everywhere else in this codebase.
- Storage grows by ~35 000 rows per source-year and is never pruned. At Swiss
  ZEV scale that is small; it is still unbounded growth by design.
- The transfer archive carries the *link* (by natural key) but not the series, so
  an imported community starts with an empty source and refills on the next
  fetch — and for an operator that serves no history, only forward from then.

## Alternatives considered

- **Fetch on demand during invoice generation.** Rejected: it makes billing
  depend on an operator's uptime, and it cannot work at all for a period older
  than the operator's retention.
- **Per-ZEV sources.** Rejected for the duplication and divergence above.
- **A `DYNAMIC_ENERGY` billing mode.** Rejected: it would fork every switch on
  `billing_mode` in the engine, serializers, zod schema and TypeScript unions,
  and would prevent a series from spanning the static→dynamic switchover.
- **Deriving `valid_to` from a per-source resolution.** Rejected: it cannot
  express a source that changes resolution, and it turns DST into a special case.
