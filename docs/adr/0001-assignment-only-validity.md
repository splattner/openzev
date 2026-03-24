# ADR 0001: Assignment-only validity model

- Status: Accepted
- Date: 2026-03-24

## Context

Historically, validity windows were tracked both on metering points and on metering-point assignments. In practice, business workflows depend on participant-to-meter assignment windows for billing, metering completeness checks, and operational ownership over time. Maintaining an additional validity window on metering points introduced duplicate semantics and increased risk of inconsistent interpretation.

## Decision

Use assignment windows as the single source of truth for temporal ownership/usage of a metering point.

- Remove metering-point-level `valid_from` and `valid_to` fields.
- Keep validity fields on `MeteringPointAssignment`.
- Enforce at most one active assignment per metering point at any time by rejecting overlapping assignment date ranges.

## Consequences

Positive:
- One temporal model for billing and completeness logic.
- Fewer conflicting states and simpler API/UI contracts.
- Clearer operational workflows when participant ownership changes over time.

Trade-offs:
- Historical hardware lifecycle dates are no longer represented directly on metering points.
- Any hardware-level temporal needs must be modeled separately if required in the future.

## Alternatives considered

1. Keep both metering-point and assignment validity windows.
   - Rejected due to duplicated meaning and validation complexity.
2. Keep only metering-point validity and infer assignment windows.
   - Rejected because participant-level billing requires explicit assignment periods.
