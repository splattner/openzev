# Architecture Decision Records (ADR)

This directory captures key architectural decisions for OpenZEV.

## Index

- [0001: Assignment-only validity model](0001-assignment-only-validity.md)
- [0002: Timestamp-level billing allocation model](0002-invoice-allocation-model.md)
- [0003: Role and ZEV-scope enforcement model](0003-role-and-zev-scope-enforcement.md) (superseded by 0027)
- [0004: Asynchronous invoice email delivery with audit logs](0004-async-invoice-email-delivery.md)
- [0005: Metering import with preview-first validation and safe write modes](0005-metering-import-preview-and-safe-write.md)
- [0006: Invoice lifecycle state machine and regeneration locking](0006-invoice-lifecycle-and-locking.md)
- [0007: Timezone policy for storage, queries, and display](0007-timezone-policy.md) (superseded by 0026)
- [0008: Security model and audit logging scope](0008-security-and-audit-logging.md)
- [0009: Remove direct MeteringPoint participant FK](0009-remove-direct-meteringpoint-participant-fk.md)
- [0010: Centralized audit event stream for high-risk operational workflows](0010-centralized-audit-event-stream.md)
- [0011: Asynchronous bulk invoice and PDF generation](0011-async-bulk-invoice-generation.md)
- [0012: Participant address geocoding via public Nominatim, cached not persisted](0012-participant-geocoding-via-nominatim.md)
- [0013: Extract shared local-pool allocation service](0013-shared-allocation-service.md)
- [0014: Print parity via shared tokens and real-PDF previews](0014-print-parity-and-ui-tokens.md)
- [0015: Retire MUI — TanStack Table and full Mantine consolidation](0015-retire-mui-tanstack-table.md)
- [0016: Explicit VAT mode, with an "inclusive" treatment for non-registered ZEVs](0016-vat-mode-inclusive.md)
- [0017: Async export jobs for whole-ZEV annual statements](0017-async-export-jobs.md) (supersedes the unmerged subprocess-pool experiment, recorded in its alternatives)
- [0018: Dynamic tariff prices are stored evidence, in globally shared series](0018-dynamic-tariff-price-series.md)
- [0019: Frozen invoice source provenance and serialized price mutations](0019-frozen-dynamic-price-evidence.md)
- [0020: A user-verified passkey replaces the password, rather than supplementing it](0020-passkeys-replace-the-password.md)
- [0021: MFA secrets are encrypted under a dedicated, rotatable key, not `SECRET_KEY`](0021-mfa-secret-encryption-key.md)
- [0022: Sessions are revoked with a per-account version counter, not a token blacklist](0022-session-revocation-by-version-counter.md)
- [0023: Backup archives preserve primary keys and restore in place, unlike transfer archives](0023-backup-archives-preserve-keys.md)
- [0024: Backup artifacts are encrypted under a dedicated, optional key](0024-backup-encryption-key.md)
- [0025: The MCP server runs inside Django and answers through the REST views](0025-mcp-server-in-process-over-rest.md)
- [0026: Readings are UTC instants; every calendar question is answered in Swiss civil time](0026-swiss-civil-time-for-billing.md) (supersedes 0007)
- [0027: Access is granted per ZEV; the platform role only says "admin or not"](0027-per-zev-access-grants.md) (supersedes 0003)
- [0028: Every person or organisation of a ZEV is a party; issuer, representative and landowner are dated roles](0028-zev-parties-and-dated-roles.md) (amends 0027)
- [0029: Buildings sit between a ZEV and its metering points](0029-buildings-between-zev-and-metering-points.md)
- [0030: Supplementary energy data lives in its own table and never reaches billing](0030-supplementary-energy-data-is-not-billing-input.md)
- [0031: Third-party integration credentials are encrypted under a dedicated, rotatable key](0031-integration-credentials-encrypted-under-a-dedicated-key.md)
- [0032: One visual language for screen and documents](0032-one-visual-language-for-screen-and-documents.md) (amends 0014)

## Conventions

- IDs are incremental (`0001`, `0002`, ...).
- Keep one decision per ADR.
- New ADRs should include: context, decision, consequences, and alternatives considered.
- Use [TEMPLATE.md](TEMPLATE.md) when creating a new ADR.
