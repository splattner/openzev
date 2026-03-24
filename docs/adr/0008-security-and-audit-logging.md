# ADR 0008: Security model and audit logging scope

- Status: Accepted
- Date: 2026-03-24

## Context

OpenZEV handles sensitive operational and billing data (participants, metering readings, invoices, account actions). The platform already enforces role-based access and tenant scoping, and it stores workflow-specific operational logs (for example invoice email attempts and import logs). However, security-sensitive behavior should be documented as a coherent policy to guide future changes.

## Decision

Use a layered security model and explicit audit logging for high-risk operational workflows.

- Enforce authorization server-side with role and ownership checks on querysets/actions.
- Keep frontend route guards as UX support only; backend remains source of truth.
- Restrict invoice lifecycle transitions and destructive operations by role and status.
- Record operational audit trails where actions are asynchronous or failure-prone:
  - invoice email attempts via `EmailLog` (status, recipient, failure message, timestamps),
  - metering import runs via `ImportLog` (counts, errors, actor, source file).
- Emit structured application logs for exceptional security-relevant failures (permission denials, task failures, missing entities during protected operations).

## Consequences

Positive:
- Clear separation between authorization enforcement and UI convenience checks.
- Better traceability for invoicing and import operations.
- Safer evolution of privileged workflows.

Trade-offs:
- Audit visibility is currently domain-specific, not a single central audit stream.
- Cross-cutting security investigations may require correlating multiple logs/models.

## Alternatives considered

1. Frontend-only security gating.
   - Rejected because client-side checks are insufficient for data protection.
2. No persistent audit records, only runtime logs.
   - Rejected due to weak operational traceability.
3. Full centralized immutable audit ledger for every action.
   - Deferred; valuable but higher implementation/operational complexity than current needs.
