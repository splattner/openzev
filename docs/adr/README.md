# Architecture Decision Records (ADR)

This directory captures key architectural decisions for OpenZEV.

## Index

- [0001: Assignment-only validity model](0001-assignment-only-validity.md)
- [0002: Timestamp-level billing allocation model](0002-invoice-allocation-model.md)
- [0003: Role and ZEV-scope enforcement model](0003-role-and-zev-scope-enforcement.md)
- [0004: Asynchronous invoice email delivery with audit logs](0004-async-invoice-email-delivery.md)
- [0005: Metering import with preview-first validation and safe write modes](0005-metering-import-preview-and-safe-write.md)
- [0006: Invoice lifecycle state machine and regeneration locking](0006-invoice-lifecycle-and-locking.md)
- [0007: Timezone policy for storage, queries, and display](0007-timezone-policy.md)
- [0008: Security model and audit logging scope](0008-security-and-audit-logging.md)

## Conventions

- IDs are incremental (`0001`, `0002`, ...).
- Keep one decision per ADR.
- New ADRs should include: context, decision, consequences, and alternatives considered.
- Use [TEMPLATE.md](TEMPLATE.md) when creating a new ADR.
