# ADR 0009: Remove direct MeteringPoint participant FK

- Status: Accepted
- Date: 2026-03-24
- Related: ADR 0001

## Context

After introducing temporal participant ownership via `MeteringPointAssignment`, the direct
`MeteringPoint.participant` foreign key remained in the schema as a deprecated compatibility field.

Keeping both assignment-based ownership and a direct participant link caused ongoing risk:

- duplicate ownership sources with potential drift,
- extra synchronization logic in serializers/views,
- accidental query usage of the wrong relation,
- migration and test burden whenever ownership semantics change.

At the same time, operational features (billing, data quality, participant visibility, and period
overview logic) already rely on assignment windows.

## Decision

Remove `MeteringPoint.participant` from the data model and make assignment-based ownership the only source of truth.

- Drop the `MeteringPoint.participant` field from `zev.MeteringPoint`.
- Use `MeteringPointAssignment` for all participant ownership queries.
- Remove FK synchronization code paths that copied assignment state into `MeteringPoint.participant`.
- Backfill missing assignment rows from legacy participant links during migration before removing the field.
- Update API contracts, frontend types, and tests to stop creating/updating metering points with a participant field.

## Consequences

Positive:
- Single, consistent ownership model for metering points.
- No drift between assignment windows and a mirrored FK.
- Simpler backend logic and cleaner API contracts.
- Better long-term maintainability for billing and analytics queries.

Trade-offs:
- Requires coordinated updates across backend, frontend, docs, and tests.
- Legacy clients sending `participant` on metering-point payloads must be updated.
- Historical databases must run the migration to preserve ownership continuity.

## Alternatives considered

1. Keep direct FK and continue syncing from assignments.
   - Rejected: still duplicates state and keeps drift/sync complexity.

2. Keep direct FK as read-only denormalized cache.
   - Rejected: adds maintenance overhead and can still become stale.

3. Remove assignments and revert to direct participant ownership.
   - Rejected: cannot represent temporal ownership windows needed for billing correctness.

## Notes

- Migration strategy: backfill missing assignments from legacy FK only when a metering point has no assignment records, then remove the field.
- This ADR is complementary to ADR 0001 (assignment-only validity windows).
