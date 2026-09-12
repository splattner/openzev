# ADR 0019: Freeze invoice source provenance and serialize price mutations

- Status: Accepted
- Date: 2026-09-12
- Supersedes: ADR 0018's mutable tariff evidence lookup and three-field source identity

## Context

An invoice's price inputs must remain protected after tariff validity, community,
or source links change. Looking up invoices through current tariffs cannot
provide that guarantee. Atomic invoice generation alone also allows concurrent
price replacement or clearing before the new invoice commits.

## Decision

Store `InvoiceDynamicSourceEvidence` with the invoice, source, tariff UUID
snapshot, and half-open UTC validity intersection. Its source foreign key uses
`PROTECT`; its invoice foreign key uses `CASCADE`. Drafts protect prices;
cancelled invoices no longer prevent price changes, but their provenance still
retains the source row. Backfill existing invoice relationships in migration
`invoices/0017_dynamic_source_evidence`; past relationships already removed from
the database cannot be reconstructed.

Invoice generation locks all applicable dynamic source rows in primary-key
order before reading prices. Storage, clearing, and source deletion acquire
the same database locks. Record evidence before committing the invoice. Reset
the dynamic series cache between participant transactions so a failed invoice
cannot leave an unprotected cached price for the next participant.

Source identity is `(url, api_version, tariff_type, tariff_name)`: the API
version changes component semantics. Identity is immutable through model saves,
API writes, and Django admin. Discovery never infers successful-empty HTTP 404
handling from the component type; it requires an explicit administrator setting.

Storage validates connected overlap groups. A refused replacement leaves its
whole group intact; independent groups can commit. Complete replacements of
unbilled intervals may change resolution without clearing historical evidence.
No replacement may clip an old interval or change an interval protected by an
invoice. Enclosing transactions may roll back all groups on refusal.

Transfer archives include frozen provenance in each invoice, with embedded
source descriptors independent of the tariff section. Price points still do
not travel: retain a database backup to preserve the original fetched series.

## Consequences

Tariff maintenance cannot erase an invoice's source reference. Real PostgreSQL
concurrency tests verify that clearing and replacement wait for invoice reads
and then see their committed evidence. Global source locks can delay concurrent
billing or maintenance; invoice transactions reload each source once per
participant, instead of sharing a cache across separately committed invoices.

## Alternatives considered

- Freeze every billed tariff field: fragile across import, versioning, admin,
  and future write paths, and unnecessarily restricts tariff maintenance.
- A cache lease alone: invoices did not participate, and an expired lease
  cannot serialize database transactions.
- Remove the overlap retry loop without preserving restored intervals: a
  rejected replacement can expose an old interval that conflicts with a later
  candidate. Connected groups account for both old and incoming boundaries.
