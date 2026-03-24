# ADR 0002: Timestamp-level billing allocation model

- Status: Accepted
- Date: 2026-03-24

## Context

OpenZEV invoices need to allocate energy and fees fairly across participants while supporting changing assignments and multiple tariff types. Monthly and period-based invoicing requires deterministic, auditable calculations that align with metering data completeness and assignment validity.

## Decision

Adopt timestamp-level allocation as the core billing model.

- Compute participant allocations from metering data at fine-grained timestamps.
- Apply tariff logic on top of allocated energy according to tariff category and billing mode.
- For per-metering-point recurring fees, count only assignment-backed metering points active in the billing period.

## Consequences

Positive:
- Accurate pro-rating when assignments change during a period.
- Improved transparency for invoice explanations and dispute handling.
- Consistent behavior across monthly, quarterly, semi-annual, and annual billing intervals.

Trade-offs:
- More computation and query complexity than coarse monthly-only approaches.
- Requires robust metering completeness checks and assignment validation.

## Alternatives considered

1. Period-level aggregate split without timestamp allocation.
   - Rejected due to reduced fairness/accuracy for mid-period changes.
2. Manual allocation factors per participant.
   - Rejected because it is error-prone and hard to audit at scale.
