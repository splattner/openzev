# ADR 0013: Extract shared local-pool allocation service

- Status: Accepted
- Date: 2026-08-03
- Relates to: ADR 0002

## Context

### Duplicated allocation logic

The per-timestamp local-pool allocation formulas (how ZEV production is split between participants) are copy-pasted across ten locations in the codebase:

| Location | File |
|----------|------|
| Invoice PDF (period stats) | `invoices/pdf_stats.py` |
| Invoice engine (consumer allocation) | `invoices/engine.py` |
| Invoice engine (producer allocation) | `invoices/engine.py` |
| Annual statement (monthly data) | `invoices/annual_statement.py` |
| Owner dashboard | `metering/analytics.py` |
| Participant dashboard (own timeline) | `metering/analytics.py` |
| Participant dashboard (all-participants breakdown) | `metering/analytics.py` |
| Hourly profile (PDF) | `invoices/pdf_charts.py` |
| Hourly profile (analytics) | `metering/analytics.py` |
| Feasibility calculator (annual-aggregate variant) | `feasibility/calculator.py` |

Two formula families exist.

**Consumer split** — a participant's draw is divided into community energy and grid energy:

```python
local_pool = min(total_produced, total_consumed)
if total_consumed > 0 and local_pool > 0:
    from_zev = min(consumed, local_pool * (consumed / total_consumed))
else:
    from_zev = Decimal("0")
from_grid = max(consumed - from_zev, Decimal("0"))
```

**Producer split** — a producer's output is divided into community-used and exported energy:

```python
local_pool = min(zev_produced, zev_consumed)
export_pool = max(zev_produced - zev_consumed, Decimal("0"))
producer_share = produced / zev_produced
from_zev = local_pool * producer_share
exported = export_pool * producer_share
```

The feasibility calculator is a third, annual-aggregate variant: it distributes a precomputed self-consumed total by each participant's share of annual consumption/production (`feasibility/calculator.py`) instead of building per-timestamp pools. It is expected to stay proportional to the same shares.

### Period-level assignment overlap

Assignment filtering uses a **period-level overlap** (`valid_from <= period_end AND valid_to >= period_start`) rather than per-timestamp filtering. The mechanism is the same in every consumer: metering points are selected when *any* assignment overlaps the period (e.g. `_assigned_metering_points` in `invoices/engine.py`), then **all** of that metering point's readings in the period are attributed to the participant who holds the current assignment. A metering point whose assignment started mid-period therefore has its earlier readings misattributed to the new participant.

This creates two problems:
1. **Maintenance risk**: any formula change must be replicated across 10 sites, and the variants above already diverge in guard conditions and rounding (float vs `Decimal`).
2. **Correctness risk**: mid-period assignment transfers misattribute readings, and nothing forces billed totals and charted data to agree.

## Decision

Extract a shared allocation service.

1. Own both split formulas as pure, `Decimal`-only functions in a single app-agnostic module (no imports from `invoices`, `metering`, or `feasibility`). The reference implementations already exist in `invoices/engine.py` (`split_consumption` / `split_production`); the service is their canonical lifted copy.
2. The functions are per-timestamp ready: they take one participant's reading plus the community totals for that timestamp and return the split.
3. All ten consumers migrate to the service. The feasibility calculator keeps its annual-aggregate pipeline but routes the per-participant share through the same proportionality code so the shares match the per-timestamp semantics.
4. Per-timestamp assignment filtering is implemented in the same effort: each consumer attributes a reading only to the assignment active at that reading's timestamp, instead of the period-level overlap. With no live customers yet, there is no re-billing concern; the change is verified with golden-value tests and a reconciliation check between billed totals and charted data.

Confirmed implementation choices:

- **Module location**: a new `allocation` Django app (`backend/allocation/`), registered in `INSTALLED_APPS`. `split.py` is pure arithmetic — no models, no ORM, no app-code imports. `windows.py` provides the `AssignmentWindows` in-memory index; its constructor is pure (takes plain tuples), but it offers ORM convenience classmethods (`for_zev`, `for_participant`) that query `MeteringPointAssignment` directly.
- **Gap readings**: a reading whose timestamp falls in an assignment gap (no assignment active) is excluded from *every* bill and every per-participant statistic. It is not charged to the new holder, the previous holder, or the community. ZEV-wide physical totals (dashboard/community pool) still include it.
- **Community pool totals**: per-timestamp pool totals are *physical* — they cover every metering point of the ZEV regardless of assignment, so the pool (and the physical dashboard totals) reflect everything the ZEV actually metered. Only the *attribution* of a reading to a participant is filtered per timestamp. A metering point with no assignment overlapping a period therefore still counts in the pool but is billed to nobody. That is a data-quality condition, not a valid steady state: every metering point should have a holder for each period in which it has readings — a common-area (*Allgemein*) meter is assigned to a community / Verwaltung participant. Holder-less readings are surfaced by the metering data-quality status check (`unassigned_days` / `unassigned_readings`), not silently absorbed into the pool. (The engine and PDF pool queries originally required an assignment overlapping the period, which excluded never-assigned meters from the pool while the dashboards included them; the reconciliation hardening aligned all consumers on the physical pool.)
- **Precision residual policy**: splits use the full 28-digit `Decimal` context; any rounding shortfall (~1e-28 kWh) stays on the grid side by construction and is orders of magnitude below the 0.0001 kWh settlement quantum. Exact conservation at an arbitrary quantum would require a batch allocator with explicit residual assignment (see follow-ups).
- **Decimal-only contract**: `split.py` is `Decimal` end to end. Non-`Decimal` inputs raise `TypeError` (programming errors); negative inputs and inconsistent totals (a participant's reading exceeding the community total) raise `InvalidAllocationInputError`. All allocation failures — including `OverlappingAssignmentWindowsError` — derive from `AllocationError` (a `ValueError`), so the billing API can report them distinctly from the engine's "invoice already exists" error. Chart paths accumulate in `Decimal` and convert to float only at serialization.
- **Overlapping assignment windows fail fast**: `AssignmentWindows` raises `OverlappingAssignmentWindowsError` on overlapping windows per metering point. This is defense-in-depth: overlaps are forbidden by `MeteringPointAssignment.clean()` (full validation on the API/admin paths) and by `save()` itself, which enforces the non-overlap rule on single-object ORM writes, so the runtime check protects the allocation path against direct database edits. The metering data-quality status check catches the error *per metering point* (surfacing it as an `assignment_overlap` row warning) so one corrupt meter degrades to one bad row instead of failing the whole triage page.
- **Explicit holder checks**: every allocation point checks `participant_at(metering_point_id, ts) != participant.id`, which is correct regardless of how the index was built.
- **UTC-date matching**: assignment validity is matched on the UTC civil date of the reading's timestamp (`ts.date()`), consistent with periods, tariff validity, and daily completeness (ADR 0007). Moving to Zurich-local dates would be a separate, cross-cutting decision.

## Consequences

Positive:
- Single source of truth for allocation logic; formula drift becomes impossible by construction
- Mid-period assignment transfers are attributed correctly everywhere (billing, PDFs, dashboards)
- Golden-value tests become possible (one implementation to check instead of ten)

Trade-offs:
- Requires updating 10 call sites across 4 apps
- Behavior must stay byte-identical for unchanged data during the transition, or invoices, PDFs, and dashboards will not reconcile
- Per-timestamp filtering changes billed amounts for periods with mid-period assignment changes — safe pre-launch, but must be revisited with customer communication if introduced after go-live
- The fetch-and-filter orchestration (query readings → build windows → loop → resolve holder → call split) is still duplicated per consumer; only the formulas are centralized (see follow-ups)

## Acceptance criteria

- Extracted service reproduces the current `engine.py`, `pdf_stats.py`, and `analytics.py` outputs for identical inputs (golden-value tests)
- Existing unit tests keep passing across all four apps (engine, PDF, analytics, feasibility)
- Feasibility proportional shares are unchanged
- A mid-period assignment transfer attributes each reading to the assignment active at that timestamp in the engine, PDF stats, and analytics
- Billed totals and dashboard charts reconcile for periods containing mid-period assignment changes

## Alternatives considered

1. **Fix only in PDF**: rejected — creates reconciliation gap between charts and billed totals
2. **Fix only in billing engine**: rejected — PDF charts would diverge from billed amounts
3. **Shared helper without per-timestamp-ready API**: rejected — the API would have to change again when per-timestamp filtering lands
4. **Leave as-is**: rejected — maintenance burden grows with each new consumer

## Notes

- Per-timestamp assignment filtering replaces the period-overlap queries in the five consumers: `invoices/engine.py`, `invoices/pdf_stats.py`, `invoices/pdf_charts.py`, `invoices/annual_statement.py`, `metering/analytics.py`
- Module location is an implementation detail; `split.py` must not depend on app code so that all four apps can import it
- Reconcile billed totals against dashboard charts before and after the migration

Verification (at time of implementation):

- Engine, PDF stats, PDF charts, annual statement, both dashboards, and the hourly profile attribute readings per timestamp
- Feasibility calculator and prefill use the shared functions
- Cross-consumer reconciliation: `invoices/test_allocation_reconciliation.py` proves engine, PDF stats, and owner dashboard agree on a mid-period transfer plus an assignment-gap reading
- Producer conservation: the negative local-energy CHF lines on producer invoices reconstruct exactly to the per-timestamp `split_production` local shares, and feed-in lines to the exported shares (`invoices/test_allocation_reconciliation.py`)
- Golden-value franc assertions pin the billed amount on the mid-period transfer fixture (`invoices/test_engine_allocation.py`), so a regression to period-overlap attribution fails the suite
- Fail-fast contracts covered in `allocation/tests.py`: non-`Decimal` input, negative inputs, inconsistent totals, overlapping assignment windows, UTC-date boundary, conservation invariants
- The billing engine logs a warning when readings fall outside assignment windows (gap visibility), with counts and kWh for consumption and production
- Reconciliation tests compare at the settlement quantum (0.0001 kWh) with `Decimal` rather than float tolerance; a multi-meter fixture covers two consumption meters per participant, two producers, a bidirectional meter, a producer-meter transfer, two transfers of one meter, and a never-assigned meter
- `AssignmentWindows` windows are immutable (tuple) after construction
- The generate endpoint reports allocation failures (`AllocationError`) as 400 with the underlying error instead of the 409 reserved for existing invoices (`invoices/tests.py`); the celery bulk task's audit event already carries the exact exception message
- `generate_invoices_for_zev` isolates failures per participant and reports generated/failed counts with per-participant errors (`invoices/test_batch_actions.py`)
- The metering data-quality status reports holder-less readings (`unassigned_days` / `unassigned_readings`) and flags per-meter overlapping assignment windows (`assignment_overlap`), so one corrupt meter degrades to one bad row (`metering/tests.py`)
- Query-count guards pin the single-fetch invariant and upper-bound per-consumer query counts across the billing path (`invoices/test_allocation_query_counts.py`)
- Full backend suite passes (`python -m pytest -q`)

Follow-ups from review (not this change):

- **Batch per-timestamp allocator**: an `allocate_consumption`/`allocate_production` API taking all readings of a timestamp would own quantization and residual assignment (largest remainder, deterministic tie-break), making conservation exact at the settlement quantum. The current scalar functions cannot allocate a residual deterministically — they do not know the participant set.
- **Allocation read-model**: an `iter_allocated_readings()` iterator yielding an `AllocatedReading` dataclass would remove the duplicated fetch-and-filter orchestration across consumers. The ADR centralizes the formulas; the orchestration is still per-consumer.
- **Naming vocabulary**: `from_zev` vs `local` map to public API fields (`from_zev_kwh`, `from_grid_kwh`) consumed by the frontend; renaming is a breaking API change and would need frontend updates in the same PR.
- **Gap-report feature**: surface excluded readings in the invoice document (not just the engine log) — product decision.
- **DB exclusion constraint**: application `save()` enforcement is single-object only — two concurrent transactions can both pass `_validate_no_overlap()` and both `INSERT` overlapping windows, and `QuerySet.update()` / `bulk_create()` / raw SQL bypass `save()` entirely. A Postgres `ExclusionConstraint` on a `daterange` of `(metering_point, valid_from, valid_to)` would close that race at the DB layer if concurrent admin/script writers become a real risk; the runtime `AssignmentWindows` guard remains the backstop until then.
- **System-wide local-civil-date semantics**: if business wants assignment validity, periods, and tariffs on Zurich civil dates, it must be decided for the whole system together (ADR 0001/0007 territory), not per-feature.
