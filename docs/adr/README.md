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
- [0009: Remove direct MeteringPoint participant FK](0009-remove-direct-meteringpoint-participant-fk.md)
- [0010: Centralized audit event stream for high-risk operational workflows](0010-centralized-audit-event-stream.md)
- [0011: Asynchronous bulk invoice and PDF generation](0011-async-bulk-invoice-generation.md)
- [0012: Participant address geocoding via public Nominatim, cached not persisted](0012-participant-geocoding-via-nominatim.md)
- [0013: Extract shared local-pool allocation service](0013-shared-allocation-service.md)
- [0014: Print parity via shared tokens and real-PDF previews](0014-print-parity-and-ui-tokens.md)
- [0015: Retire MUI — TanStack Table and full Mantine consolidation](0015-retire-mui-tanstack-table.md)

## Conventions

- IDs are incremental (`0001`, `0002`, ...).
- Keep one decision per ADR.
- New ADRs should include: context, decision, consequences, and alternatives considered.
- Use [TEMPLATE.md](TEMPLATE.md) when creating a new ADR.
