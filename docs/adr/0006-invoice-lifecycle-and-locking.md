# ADR 0006: Invoice lifecycle state machine and regeneration locking

- Status: Accepted
- Date: 2026-03-24

## Context

Invoice generation can be repeated as metering/tariff data evolves, but once invoices are approved/sent/paid, uncontrolled regeneration or deletion creates audit and accounting risk.

OpenZEV currently exposes explicit invoice states and transition endpoints.

## Decision

Use an explicit invoice state machine with restricted transitions and lock behavior.

- Allowed states: `draft`, `approved`, `sent`, `paid`, `cancelled`.
- Regeneration may replace only `draft`/`cancelled` invoices for the same participant+period.
- Regeneration is blocked for locked states (`approved`, `sent`, `paid`).
- Deletion is role-gated; non-admin owners may delete only `draft`/`cancelled` invoices.
- Manual transitions (`approve`, `mark-sent`, `mark-paid`, `cancel`) enforce business constraints.

## Consequences

Positive:
- Stronger auditability and accounting integrity.
- Predictable operator workflow for invoice finalization.
- Safer re-run behavior during draft preparation.

Trade-offs:
- Requires explicit cancellation/new cycle if post-approval adjustments are needed.
- More transition checks across API and UI behavior.

## Alternatives considered

1. Free-form status edits and unrestricted regeneration.
   - Rejected due to high integrity and audit risk.
2. Immutable invoices immediately after first creation.
   - Rejected because draft iteration is needed in real operations.
