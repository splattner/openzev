# ADR 0005: Metering import with preview-first validation and safe write modes

- Status: Accepted
- Date: 2026-03-24

## Context

Metering data arrives in heterogeneous files (CSV/Excel, including daily 15-minute profiles). Import mistakes can corrupt billing inputs and are costly to detect late. Operators need an opportunity to validate mapping and meter accessibility before writing readings.

## Decision

Adopt a preview-first import workflow with explicit write behavior and audit logging.

- Support file profile variants (`standard`, `daily_15min`) and configurable column mapping.
- Provide a preview step that reports row-level mapping/availability issues before import.
- Enforce meter visibility by user role and optional ZEV scope.
- Write imports through explicit modes (skip existing by default, optional overwrite mode).
- Persist import outcomes in `ImportLog` with counts and row-level errors.

## Consequences

Positive:
- Lower risk of accidental bad imports.
- Better operator confidence and transparency before commit.
- Auditable import history for troubleshooting.

Trade-offs:
- More complexity than single-step blind import.
- Additional validation logic must be maintained for each supported profile.

## Alternatives considered

1. Direct one-step import with no preview.
   - Rejected due to high operational risk.
2. Strict schema-only ingestion with no mapping flexibility.
   - Rejected because field layouts vary across utilities/vendors.
