# ADR 0023: Backup archives preserve primary keys and restore in place, unlike transfer archives

- Status: Accepted
- Date: 2026-09-21

## Context

OpenZEV has no backup or restore capability. The only documented procedure is a
`pg_dump` snippet in [`docs/user-guide/12-troubleshooting.md`](../user-guide/12-troubleshooting.md)
that does not mention `MEDIA_ROOT`, so a restore from it produces an instance
where every `Invoice.pdf_file` points at a document that is not there (#767).

Two capabilities are wanted, and they pull in opposite directions:

- **Whole-instance recovery.** A fresh installation points at a backup and comes
  up as the instance that was backed up — accounts, settings, templates, price
  series, invoice PDFs, audit trail.
- **Per-ZEV rollback.** A live installation returns one community to the state it
  was in when the backup was taken, without touching the other communities.

A physical `pg_dump` serves the first and cannot serve the second at all: there is
no way to extract one community's rows from a dump and splice them into a running
database. So the artifact has to be **logical** — per-entity sections, like an
export.

The platform already has a logical whole-ZEV archive:
[SPEC-2026-08-zev-transfer-archive](../specs/2026-08-zev-transfer-archive.md),
a mature ZIP format (manifest, per-section JSON, per-meter readings CSVs,
section dependency graph, manifest count verification, per-entry error
collection, schema-parity tests). Reaching for it is the obvious move, and it is
the wrong one. Its contract is stated in its own spec:

> *An import always creates a **new** ZEV with new internal identifiers; it is a
> copy, not an in-place restore.*

> *Out of scope: In-place restore; audit events / import logs do not travel.*

It also omits, deliberately: account references (`Zev.owner`, `Participant.user`),
generated invoice PDFs, `DynamicPricePoint` series and fetch cursors, and the
instance-wide PDF/email templates. And because `MeteringPoint.meter_id` is
`unique=True` instance-wide, `_preflight_meter_ids` rejects an archive whose
meters already exist — which is precisely the restore case.

The re-keying is not incidental. It is what makes transfer safe: two instances
can both hold a copy of a community without their identifiers colliding. A
restore needs the opposite guarantee.

## Decision

Backup and restore use a **separate archive kind with key-preserving
semantics**, sharing the transfer archive's substrate but not its importer.

- **The manifest declares `kind: "backup" | "transfer"`**, and the two kinds have
  independent `format_version` sequences. A reader refuses a kind it was not
  asked to handle, so neither archive can be fed to the other's runner by
  accident.
- **Backup archives preserve primary keys.** Every row is written and restored
  under the identifier it had. Most models already carry UUID primary keys
  (`Zev`, `Participant`, `MeteringPoint`, `Invoice`, `MeterReading`,
  `ContractIssue`, `AuditEvent`, …), which makes this safe across instances.
  Integer-keyed models (`User`, `VatRate`, `PdfTemplate`, `EmailTemplate`,
  `OAuthProvider`, `FeatureFlag`, `InvoiceDynamicSourceEvidence`) keep their keys
  on a whole-instance restore, and the restore reconciles database sequences
  afterwards.
- **Shared substrate, separate runners.** Backup reuses the transfer archive's
  conventions — ZIP container, `manifest.json` with per-section counts, streaming
  per-meter reading CSVs, the `MAX_REPORTED_ERRORS` collector — and implements its
  own writer and restore runners in a new `backups` app. The transfer importer is
  not extended, subclassed, or parameterised into doing restores.
- **Two restore modes, deliberately different in kind:**
  - *Instance restore* reproduces the whole instance onto an empty one. It is
    **only** available as a management command.
  - *ZEV restore* replaces one community's rows on a live instance. It is
    available through the admin API and the CLI.
- **Per-ZEV restore resolves accounts by natural key, never by primary key.**
  `Participant.user` and `Zev.owner` relink by `User.email`/`username`. Accounts
  are instance-wide and shared; a community rollback must never restore a
  credential, an MFA device or a session version.
- **Per-ZEV restore never rewrites the audit trail.** Existing `AuditEvent` rows
  survive untouched, including the restored ZEV's own; the restore appends its
  event instead. A whole-instance restore does load the audit trail, because there
  is no history to protect on an empty instance.

### Why instance restore is CLI-only

A fresh installation has no account to authenticate as, so an HTTP-only path
cannot bootstrap one. More fundamentally, an instance restore replaces the
`accounts` tables — including the row and `session_version` of whoever triggered
it. Performing that through a web session means destroying the caller's own
credentials halfway through the operation. The management command has no session
to invalidate and is the honest shape for the operation.

## Consequences

Positive:

- Per-ZEV rollback becomes expressible at all. Identifiers survive, so invoice
  links, onboarding tokens and audit `target_id` references still resolve after a
  restore.
- A restored instance *is* the instance, not a copy of it. External references
  held outside the database (a bookmarked invoice link, a QR code already printed
  on a bill) keep working.
- Transfer keeps its simple, safe contract. Nothing about restore leaks into a
  code path whose whole job is to make a copy.
- The two archive kinds can evolve independently: adding accounts to a backup
  does not widen what a transfer archive discloses.

Trade-offs:

- **Two archive writers to keep in step with the models.** The transfer archive
  already guards this with `SchemaParityTests`; the backup archive needs its own
  equivalent, or a model change will silently stop being backed up. This is the
  main ongoing cost.
- **Key preservation makes an archive instance-specific in ways transfer is not.**
  Importing a backup's ZEV section into an instance that already holds that ZEV is
  a replace, not an add — there is no "import this backup as a second copy" path.
  Operators who want that use a transfer export.
- **Restore is destructive by construction.** It is gated behind a preflight plan,
  an automatic pre-restore safety backup, a typed confirmation and an audit event
  (see [SPEC-2026-09-backup-and-restore](../specs/2026-09-backup-and-restore.md) §6).
- **Per-ZEV restore leaves the audit log describing states the data no longer
  shows.** Accepted: an audit log a restore can rewrite is not an audit log.

## Alternatives considered

1. **`pg_dump` plus a media tarball.**
   - Simplest to build, and genuinely better for whole-instance recovery — it
     captures sequences, extensions and constraint state for free.
   - Cannot do per-ZEV restore at any price, which is half the requirement. Also
     couples backups to a PostgreSQL major version, and the artifact is opaque:
     nothing can report what is inside it without restoring it somewhere.
   - Remains the right tool for point-in-time recovery, which this feature
     explicitly does not attempt (see ADR notes).

2. **Extend the transfer archive to `FORMAT_VERSION 3` with a restore mode.**
   - Tempting: one format, one set of tests, code already written.
   - Rejected because the importer's central invariant is that it mints new
     identifiers and creates a new ZEV. A "preserve keys" flag would fork
     behaviour through `_import_*` at every step, and the failure mode of getting
     it wrong is silent cross-tenant data corruption. A shared substrate with two
     runners keeps the invariants separable and separately testable.

3. **Per-ZEV restore by exporting a transfer archive and re-importing it as a new
   ZEV, then deleting the old one.**
   - Uses only shipped code.
   - Produces a *different* community with new identifiers: every invoice link,
     onboarding token and audit reference breaks, participants lose their account
     links, and the invoice PDFs are not in the archive at all. This is a copy
     wearing the old one's name, not a restore.

4. **Logical backup that re-keys, like transfer, but records an ID mapping.**
   - Would let one archive serve both purposes.
   - The mapping has to be applied to every external reference the database does
     not own — printed QR bills, emailed invoice links, third-party bookmarks —
     which is impossible. Key preservation is the only way those survive.

## Notes

- Point-in-time recovery is **out of scope**. A restore returns the instance, or
  one ZEV, to the state at the moment the backup was taken; recovery granularity
  equals the backup interval. PostgreSQL WAL archiving (pgBackRest, wal-g) is the
  complement for operators who need finer recovery, and the user guide says so
  rather than leaving it assumed.
- Artifact encryption is a separate decision: [ADR 0024](0024-backup-encryption-key.md).
- The job lifecycle (`queued → running → completed / failed`, Celery execution,
  retention sweep, artifact in shared media storage) follows
  [ADR 0017](0017-async-export-jobs.md). `ExportJob` itself is not reused:
  its `zev` foreign key is non-null, and `ExportResult.payload` is `bytes`, which
  would hold a multi-gigabyte artifact in memory.
- Implementation detail, field lists, endpoints and test plan:
  [SPEC-2026-09-backup-and-restore](../specs/2026-09-backup-and-restore.md).
