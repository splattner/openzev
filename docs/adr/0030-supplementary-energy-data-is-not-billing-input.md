# ADR 0030: Supplementary energy data lives in its own table and never reaches billing

- Status: Proposed
- Date: 2026-10-08

## Context

In a vZEV a producer's PV system often sits behind their grid connection meter. The metering
point records only what crosses the connection point: the surplus fed in (`out`) and the
residual grid draw (`in`). The household's own PV use never appears.
[SPEC-2026-behind-the-meter-generation](../specs/2026-09-behind-the-meter-generation.md)
made the statistics honest about that by suppressing the self-sufficiency rate for such
participants, and named importing gross production and consumption data as the follow-up.

[SPEC-2026-supplementary-energy-data](../specs/2026-10-supplementary-energy-data.md) delivers
it: gross production, gross consumption and grid import/export per 15-minute interval, from
an external source the participant connects (Solar Manager first; Home Assistant, n8n and
files through a push endpoint).

That data differs from `MeterReading` in the ways that matter:

- **It is not evidence.** A `MeterReading` is the grid operator's measurement of energy that
  crossed the connection point. Supplementary data is a household device's own measurement,
  delivered by a third-party cloud or an automation the participant controls. It can be wrong,
  late, revised, shifted by an interval, or absent.
- **Billing reads `MeterReading` everywhere.** Allocation (`split_consumption` /
  `split_production`, [ADR 0013](0013-shared-allocation-service.md)), the invoice engine,
  invoice PDFs, the dashboards and the data-quality checks all query that table. Any rows added
  to it, or any new `direction` or `import_source` value, reach those paths unless every one of
  them is audited and filtered.
- **Legally it is outside the community.** Behind-the-meter self-consumption is not energy the
  ZEV shares, so it has no place in what is allocated and billed.
- **It is more personal.** A 15-minute household consumption profile from a participant's own
  account, connected under their consent, is a different privacy class from metering data the
  ZEV owner already administers.

## Decision

Supplementary energy data is stored in its own models and is **never an input to billing**.

- **Separate tables.** `metering.SupplementaryReading` holds the interval values;
  `metering.SupplementarySource` holds the connection. `MeterReading`, `ReadingDirection`,
  `ImportSource` and `ImportLog` are not extended for it.
- **Structural, not conventional, isolation.** Nothing under `allocation/` or `tariffs/`, and
  none of `invoices/engine.py`, `invoices/financial_summary.py`, `invoices/tariff_pricing.py`,
  `invoices/pdf*.py` or `invoices/template_context.py` (the invoice engine and invoice
  documents), imports from the supplementary package. A test
  (`SupplementaryIsolationTests`) fails if any of them does, and another asserts that the
  invoices generated for a ZEV are identical in every amount and line item with and without
  supplementary data present.
- **Read only by statistics.** The only consumers are the statistics surfaces named in the
  spec: participant and owner dashboards, the annual report, the annual statement, and MCP's
  `consumption_summary`. They read it through one selector module, `metering/supplementary/stats.py`,
  never the model directly.
- **The official meter stays authoritative.** Supplementary values never overwrite, fill or
  correct a `MeterReading`. Where both describe the same flow (the source's export against the
  meter's `out`), the pair is *compared* and any deviation is surfaced; the meter wins.
- **Rates are computed from the supplementary data alone.** Self-sufficiency and the
  self-consumption rate use the source's own `consumption`, `production`, `import` and
  `export`, so the numerator and denominator come from one consistent measurement. The official
  meter is used for reconciliation only.
- **A rate needs coverage.** When fewer than the minimum share of intervals in the window carry
  data, the rate is withheld (`null`) and the coverage is reported instead, so a gap never
  reads as a low self-sufficiency.
- **The consenting participant owns the connection.** A source is created by the participant
  who personally holds the metering point (or an admin), and ingestion is clipped to the
  interval during which that participant held it.

## Consequences

Positive:
- A bug, a bad mapping or a revoked key in an external source cannot change an invoice. The
  worst case is a wrong or missing statistic, which is visible and reversible.
- The blast radius of the feature is the statistics surfaces; billing needs no re-audit.
- The consent boundary is modelled: data from a former tenant's account stops flowing when
  their assignment ends.

Trade-offs:
- A second reading table and a parallel ingestion path (storage, upsert, gap detection,
  retention, backup, transfer) that partly mirror `MeterReading`'s.
- The statistics surfaces gain a second source to consult, so each one must say which figures
  are metered and which are reported by the participant's own system.
- Self-consumption is derived from a device the ZEV does not control; it can never be as
  authoritative as a metered figure and must be labelled so.

## Alternatives considered

1. **Store it as `MeterReading` rows with a new `import_source`.**
   Rejected. It reuses the importers and the data-quality tooling, but every billing path then
   reads rows that are not grid-operator evidence, and "just filter by `import_source`" has to
   be right in every query, forever. A single miss changes an invoice.
2. **Add a `gross` flag or direction to `MeterReading`.**
   Rejected for the same reason, and because it would mix two different units of account in one
   column that the allocation service sums by metering point and timestamp.
3. **Compute self-consumption from the official meter plus a production reading only.**
   Rejected as the primary path. It would be the more authoritative number, but it needs a
   second meter or an inverter export per site, which is the case this feature exists to avoid.
   It stays possible as a future source, since a source only has to deliver the four columns.
4. **Let the ZEV owner enter the participant's credentials.**
   Rejected for v1. The account belongs to the participant. See
   [ADR 0031](0031-integration-credentials-encrypted-under-a-dedicated-key.md) for how the
   credential is held.
