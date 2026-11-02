# Feasibility prefill aggregation

- Spec ID: SPEC-2026-feasibility-prefill-aggregation
- Status: Completed
- Scope: Minor
- Type: Refactor
- Created: 2026-10-28
- Related ADR: [0013](../adr/0013-shared-allocation-service.md)
- Impacted areas: backend, docs

## Outcome and scope

`feasibility/prefill.py` batches participant energy reads and aggregates the
physical local pool in SQL. Calculator math, tariff estimates, models and API
contracts are unchanged. No response cache or background job is added.

## API and access

`GET /api/v1/feasibility/prefill/{zev_id}/` retains `IsAuthenticated`,
`HasZevAccess` and `can_view`. A disabled feature returns 403 before ZEV lookup;
permissions can deny 403, and unknown/inaccessible ZEV lookups return 404.

The response contains `participants[]` (`name`, `annual_production_kwh`,
`annual_consumption_kwh`, `has_metering_data`), `self_consumption_rate`,
`retail_price_chf_per_kwh`, `feed_in_price_chf_per_kwh`, and
`internal_energy_price_chf_per_kwh`. Energy is serialized to four decimal
places, rate to four, and prices to five; rate and prices can be null.

For a ZEV on `vat_mode = inclusive`, `retail_price_chf_per_kwh` and the grid base a
percentage-of-energy `internal_energy_price_chf_per_kwh` is taken of are grossed:
each flat grid tariff that bears input VAT (`_tariff_bears_input_vat`) is
multiplied by `1 + rate`, the `VatRate` active today, as the invoice engine does
(#1173). Other VAT modes use the net prices.

## Participant history

For participants active today, fetch distinct participant/meter pairs, clearing
assignment ordering so repeated windows cannot duplicate a meter. Group readings
once by meter, meter type and direction, with sum and first/last timestamps.

Combine eligible summaries before extrapolating:
`annual_kwh = total * 365 / max((last - first).days, 1)`. Consumption uses `in` on
consumption/bidirectional meters; production uses `out` on production/bidirectional
meters. Zero/absent totals have no data. If neither direction has data, use
`DEFAULT_PARTICIPANT_CONSUMPTION_KWH` for consumption.

All history of each assigned meter is included once per participant, including
previous assignment windows. This planning approximation uses the combined
first-to-last span even for disjoint histories; billing ownership and community
weights do not apply.

## Physical self-consumption rate

Use every ZEV meter, including unassigned meters, and treat absent directions
as zero. Compute `Σ min(produced_ts, consumed_ts) / Σ produced_ts`, preserving
timestamp-level netting. Reject negative timestamp totals through `local_pool_kwh`,
even when period totals are positive. Empty data, zero production or zero
consumption return null; otherwise quantize to `0.0001` in Python using Decimal.

## Verification

Run the feasibility suite on SQLite and PostgreSQL. Correctness coverage in
`feasibility/test_prefill.py` includes:

- `test_combines_meter_spans_before_extrapolation`
- `test_repeated_assignments_count_meter_history_once_per_participant`
- `test_zero_and_ineligible_directions_keep_the_default`
- `test_sql_rate_matches_decimal_interval_reference`
- `test_disjoint_production_and_consumption_have_no_local_pool`
- `test_rejects_negative_timestamp_totals_even_when_period_total_is_positive` (both directions)
- `test_preserves_decimal_half_even_rounding` (fractional readings, multiple meters/timestamps)
- `test_ignores_other_zevs_and_includes_unassigned_pool_readings`
