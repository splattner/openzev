# Feature Spec: Integrated Backup and Restore

- Spec ID: SPEC-2026-09-backup-and-restore
- Status: In Progress (phase 1 implemented)
- Scope: Major
- Type: Feature
- Owners: splattner
- Created: 2026-09-21
- Target Release: —
- Related Issues: #767
- Related ADRs: [0023](../adr/0023-backup-archives-preserve-keys.md), [0024](../adr/0024-backup-encryption-key.md); builds on [0017](../adr/0017-async-export-jobs.md), [0010](../adr/0010-centralized-audit-event-stream.md), [0021](../adr/0021-mfa-secret-encryption-key.md)
- Impacted Areas: backend | frontend | async jobs | docs | infra

---

## Implementation status

| Phase | Status | Notes |
|---|---|---|
| 1 — back up | **Implemented** | Archive writer, encryption, checksums, destinations, `BackupJob`, `openzev_backup`, `openzev_backup_verify`, admin API and `backup` tab. Sections 4.1, 4.2, 5, 6.1–6.3, 7 and 9 describe what shipped. |
| 2 — restore the instance | **Implemented** | `restore.py`, `openzev_restore --mode instance`, `storage.fetch_archive`. §6.5 describes what shipped; deviations 10–15 below. CLI only, as designed. |
| 3 — restore one ZEV | **Implemented** | `RestoreJob`, `restore_zev.py`, `execute_restore_job`, `/api/v1/backups/restores/`, `openzev_restore --mode zev`, the *Restore a community* section. §4.3, §5 and §6.6 describe what shipped; deviations 16–23 below. |
| 4 — operate | Planned | §6.4, retention fields, verify endpoint, staleness. |

Sections describing later phases are the design to build against. **Where phase 1
differs from the design first written here, this document has been corrected to
match the code**; the differences and their reasons are listed in
[Deviations from the first design](#deviations-from-the-first-design).

### Deviations from the first design

Made while implementing phases 1 to 3; each is reflected in the sections below.

1. **Sections are JSON Lines written by Django's serializer, not hand-written field
   lists, and readings are JSON Lines too, not per-meter CSV.** Every concrete
   column is serialized (`{"model", "pk", "fields"}`), so a new field is backed up the
   moment it exists and cannot be forgotten, and restore is Django's own
   `deserialize` — including `Decimal`, UUID, timestamp and binary columns. The
   guard that mattered moved up a level: a model can still be forgotten, so a
   coverage test fails when an installed model is neither in a section nor in
   `EXCLUDED_MODELS` with a reason (and another when a `FileField` is not copied).
   This replaces `BackupSchemaParityTests` and `FIELDS_EXCLUDED_FROM_BACKUP`.
2. **`ExportJob` is not backed up** (the first design said its rows travel). Its
   artifact is deleted after 24 h, so a restored row would point at nothing.
3. **`django_celery_beat` schedules are not backed up yet.** Settings-defined
   schedules are recreated by beat itself; the one admin-editable schedule arrives
   with the scheduler in phase 4, and its restore will be designed then.
4. **Retention (`retention_count`), expiry (`file_expires_at`, `expired`), the
   sweep, and the `409` when deleting a used destination are phase 4.** Nothing in
   phase 1 deletes an archive, so there is nothing to retain or expire, and
   deleting a destination never touches archives already written.
5. **Destination changes are audited as `GOVERNANCE`**, not `SYSTEM`, matching
   OAuth provider changes: repointing a destination decides where the instance's
   data goes. Backup runs remain `SYSTEM`.
6. **Every archive carries `zevs/<id>/account_refs.json`.** A ZEV-scoped archive —
   which is what a pre-restore safety backup is — otherwise has no way to say who
   a referenced user id was, and per-ZEV restore relinks accounts by natural key.
7. **Rows with a null ZEV are written to `instance/unscoped_*.jsonl`.**
   `ContractIssue`, `AuditEvent` and `ImportLog` survive their ZEV's deletion on
   purpose; without these sections an instance backup would drop them.
8. **`GET /status/` ships in phase 1**, in the shape of §5, because the admin UI
   needs to know whether a key is configured before anyone has run a backup.
9. **The manifest's `members` carry `records` and per-model counts** for JSON Lines
   members, so verification can check counts without the manifest having to be
   cross-referenced.
10. **Instance restore requires the database schema to equal the archive's, and does
    not migrate for you.** The first design said the restore would `migrate` to the
    archive's state. Rows are loaded through the *current* models, so a code-newer
    schema would silently drop or default columns the archive does not have. The
    restore instead compares the applied migrations of the apps that own backed-up
    tables (`accounts`, `audit`, `invoices`, `metering`, `tariffs`, `zev`) with the
    manifest and refuses on any difference, in words that say which way it differs and
    the `migrate <app> <migration>` steps that fix it. Other apps (a library
    upgrading its own tables) do not block a restore. Restoring across a schema
    change is therefore "restore into the old schema, then `migrate`".
11. **`RestoreJob` is phase 3.** Instance restore is a CLI action with no row; it
    reports on stdout and records one audit event. The model exists for the API-driven
    per-ZEV restore.
12. **Verification also requires every section a backup of that scope must carry**
    (`archive.expected_sections`). Per-member checksums prove an archive is what its
    manifest says; they cannot notice a manifest that omits `instance/accounts.jsonl`
    together with the member. A new registry section must therefore bump
    `FORMAT_VERSION` or be read as optional.
13. **`--from` accepts `s3://bucket/key`** with `--endpoint-url` and `--region`,
    authenticated from `BACKUP_S3_*` or the environment's own credentials. A fresh
    installation has no saved destinations to name (they are not backed up).
14. **`--dry-run` refuses exactly when the real run would**, including on a non-empty
    instance; `--dry-run --force` reports what would be replaced. It reads and
    deserializes every record, so a schema mismatch is found before any write.
15. **Datetimes are serialized with full microsecond precision**
    (`archive._ExactJSONEncoder`). Django's own JSON encoder trims to milliseconds,
    which a round-trip test against the stored rows caught: a restored row must equal
    the stored one. Found by the phase 2 tests, fixed in the phase 1 writer.
16. **`RestoreJob` has no `mode` and gains `safety_destination`.** Every row is a
    per-ZEV restore (whole-instance restore leaves an audit event, not a row —
    deviation 11), so a discriminator would only ever hold one value. Where the
    safety backup is written is a real input, so it is a field: it defaults to the
    source backup's destination and is required when the community exists and the
    job is not a dry run.
17. **The plan reports `{backup, current}` counts per section, not
    create/replace/delete.** Meter readings run to millions of rows; holding their
    keys in memory to classify each one buys nothing over "the backup has 63,264,
    there are 0 now". What the operator needs to *decide* — which issued records
    would be lost — is reported exactly, as conflicts.
18. **The audit trail is not restored at all in per-ZEV mode**, rather than "restored
    but never deleted". It is append-only, already holds everything the backup's
    copy does, and inserting archive events into a live trail would collide with
    them (or, for a deleted community, with the orphaned copies that survive with
    a null community). The plan shows the section as *kept*.
19. **The community's own row is updated in place, never deleted and recreated.**
    Deleting it runs `SET NULL` on every audit event that names it and on every
    account whose `preferred_zev` it is — rewriting exactly what §6.6 promises not
    to touch. A community that does not exist is inserted.
20. **Orphaned issued contracts are replaced by the backup's copy.** When a community
    is deleted its `ContractIssue` rows survive with a null community; recreating it
    would collide with them on primary key, so those the backup also holds are
    deleted and reloaded, which relinks them. Nothing the backup lacks is touched.
21. **Conflicts are *overridable* or *hard*.** `force` covers what the design named
    (a sent/paid invoice or an issued contract the restore would delete) plus a
    sent/paid invoice it would **roll back** to an earlier status
    (`sent_invoice_reverted`). A meter id now owned by another community is **not**
    forceable, contrary to the first design: there is no way to honour it without
    stealing or duplicating another community's metering point. The same holds for
    a referenced price source that no longer exists, an owner with no matching
    account when the community must be recreated, and an export or another restore
    in flight. **A bulk invoice generation is not detected** — it has no job row to
    look for — and is called out in the user guide instead.
22. **Conflicts are evaluated twice**: for the plan, and again inside the transaction
    under `select_for_update()` on the community row, after the safety backup. The
    safety backup can take minutes, and the world can change in them. SQLite ignores
    row locks, so the test asserts that the lock is taken on the community row (and
    not for a dry run).
23. **API additions.** `GET /restores/` (a list, filterable by `zev_id`), an optional
    `safety_destination_id`, `409` when the community already has a queued or running
    restore, and a refused restore is a `failed` job that carries its `plan_json`, so
    the UI can show *why*. A failed verification stores its failures in `plan_json`
    the same way. Storage rollback is also stronger than designed: a file the restore
    overwrites is copied aside and put back on failure (`MediaUndo`), for instance
    restore too.

## 1. Problem and outcome

The platform has no backup or restore capability. The only documented procedure
is a two-line snippet in
[`docs/user-guide/12-troubleshooting.md`](../user-guide/12-troubleshooting.md):

```bash
docker compose exec db pg_dump -U openzev openzev > backup_$(date +%Y%m%d).sql
```

That snippet loses data. Every generated invoice PDF lives in
`Invoice.pdf_file` (`upload_to="invoices/pdf/"`) on the filesystem — the
`backend_media` volume in compose, the media PVC in Helm. A restore from that
dump produces an instance where every invoice row claims a document that is not
there. There is also no schedule, no off-site destination, no integrity check,
no restore tooling, and no way to answer *"when did this instance last back up?"*.

Two outcomes are wanted:

1. **Whole-instance recovery.** A fresh installation is pointed at a backup and
   comes up as the instance that was backed up: accounts, settings, templates,
   dynamic price series, invoice PDFs, issued contracts, audit trail.
2. **Per-ZEV rollback.** A live installation returns one community to the state
   it was in when the backup was taken, without touching the other communities
   or any account credential.

[ADR 0023](../adr/0023-backup-archives-preserve-keys.md) records why this is a
new key-preserving archive rather than the existing transfer archive or a
`pg_dump`; [ADR 0024](../adr/0024-backup-encryption-key.md) records the
encryption key decision.

## 2. Scope

### In scope

| Area | Details |
|---|---|
| Backend — new `backups` app | `BackupDestination`, `BackupJob`, `RestoreJob` models; archive writer and reader; instance and per-ZEV restore runners; chunked AES-256-GCM envelope; Celery tasks; retention sweep; audit events |
| Backend — destinations | Local filesystem and S3-compatible (`endpoint_url`, so MinIO/Garage/Wasabi/B2 work), via `boto3` |
| Backend — CLI | `manage.py openzev_backup`, `manage.py openzev_restore`, `manage.py openzev_backup_verify` |
| Backend — scheduling | `django_celery_beat` periodic task, admin-configurable |
| API | `/api/v1/backups/…` — destinations CRUD, jobs, verify, download, per-ZEV restore, status summary |
| Frontend | `backup` tab on the System Settings hub: destinations, schedule, job list, per-ZEV restore dialog; `AdminSystemHealthPanel` staleness card |
| Docs | New user-guide chapter; `12-troubleshooting.md` snippet replaced; `ROADMAP.md` line updated |

### Out of scope

- **Point-in-time recovery.** A restore returns state as of the backup instant;
  recovery granularity equals the backup interval. PostgreSQL WAL archiving
  (pgBackRest, wal-g) is the complement and is named as such in the user guide.
- **Whole-instance restore through the API or UI** — CLI only
  ([ADR 0023](../adr/0023-backup-archives-preserve-keys.md), *Why instance
  restore is CLI-only*).
- **Cross-version restore onto older code.** A backup restores onto its own
  migration state or a newer one, never an older one.
- **Moving `MEDIA_ROOT` to object storage.** Orthogonal; this spec copies media
  into the archive and does not change how the app stores files.
- **Backing up the Celery broker, Redis cache, or in-flight tasks.**
- **Per-participant or per-invoice restore granularity.** The unit is the ZEV.

### Phasing

| Phase | Delivers |
|---|---|
| 1 | Archive writer, destinations, `BackupJob`, `manage.py openzev_backup`, encryption, checksums, admin UI for destinations + job list |
| 2 | `manage.py openzev_restore --mode instance`, preflight, media restore, sequence reconciliation, fresh-install bootstrap docs |
| 3 | Per-ZEV restore: preflight plan, safety backup, locking, API + UI |
| 4 | Scheduling, retention/rotation, health staleness, verify action |

## 3. Actors, permissions, and ZEV scope

| Actor | Capability |
|---|---|
| `admin` | Everything: destinations CRUD, run/list/verify/download backups, per-ZEV restore |
| `zev_owner` | Nothing. A backup spans the instance; an owner restoring "their" ZEV would act on rows from a snapshot containing every other community |
| `participant` | Nothing |
| `guest` | Nothing |
| Operator at the shell | Whole-instance restore, via management command; authenticated by host access, not by a session |

Backend: every view uses `permission_classes = [IsAuthenticated, IsAdmin]`
(`accounts.permissions.IsAdmin`). There is **no** `ZevScopedQuerySetMixin` usage
— these are not ZEV-scoped resources, and the per-ZEV restore endpoint takes the
ZEV as a parameter after an explicit admin check rather than through scoping.

Frontend: the `backup` tab lives inside `AdminSystemSettingsPage`, already behind
`<ProtectedRoute allowedRoles={['admin']}>`.

Audit: every operation records an event with
`action_category = AuditActionCategory.SYSTEM`, `source = AuditEventSource.API`
for HTTP-triggered work and `AuditEventSource.MANAGEMENT_COMMAND` for CLI work.

## 4. Data model

New app `backups`, added to `INSTALLED_APPS` after `exports`.

### 4.1 `BackupDestination`

**Model:** `backups.models.BackupDestination`

| Field | Type | Default | Constraints / Notes |
|---|---|---|---|
| `id` | `UUIDField` | `uuid4` | primary key |
| `name` | `CharField(100)` | — | `unique=True`; shown in the UI and accepted by `--destination` |
| `kind` | `CharField(10)` | `local` | choices `BackupDestinationKind`: `local`, `s3` |
| `enabled` | `BooleanField` | `True` | a disabled destination is skipped by the schedule and rejected on manual run |
| `path` | `CharField(500)` | `""` | `local` only; absolute |
| `bucket` | `CharField(255)` | `""` | `s3` only |
| `prefix` | `CharField(255)` | `""` | `s3`; key prefix, no leading slash |
| `region` | `CharField(64)` | `""` | `s3` |
| `endpoint_url` | `URLField(500)` | `""` | `s3`; empty = AWS. Set for MinIO/Garage/Wasabi/B2 |
| `access_key_id` | `CharField(128)` | `""` | `s3`; not a secret, stored in clear |
| `secret_access_key_encrypted` | `BinaryField` | `b""` | `s3`; Fernet ciphertext under `BACKUP_ENCRYPTION_KEYS`. Never serialized |
| `server_side_encryption` | `CharField(20)` | `AES256` | `s3`; `""` disables, `aws:kms` supported |
| `created_at` / `updated_at` | `DateTimeField` | auto | |

**Properties and methods**

- `credential_mode` → `"environment" | "stored" | "instance_role"`.
  `environment` when `settings.BACKUP_S3_ACCESS_KEY_ID` and
  `BACKUP_S3_SECRET_ACCESS_KEY` are both set — those win over anything stored, so
  a hardened deployment keeps credentials out of the database entirely.
  `stored` when the row carries an encrypted secret. `instance_role` when
  neither, deferring to boto3's default chain (IRSA, instance profile).
- `secret_access_key` (property) — decrypts on access, never cached on the
  instance; mirrors `TotpDevice.secret`.
- `set_secret_access_key(value)` — encrypts; raises `ValidationError` when
  `BACKUP_ENCRYPTION_KEYS` is unset, because a secret that cannot be encrypted
  must not be storable.
- `clean()` enforces:
  - `local` requires `path`; every `s3` field must be empty.
  - `s3` requires `bucket`; `path` must be empty.
  - `path` must be absolute, must exist or be creatable, and **must not resolve
    inside `MEDIA_ROOT`** — media is web-reachable in several deployment shapes,
    and an archive is the one artifact that must never be.

**Serializer:** `BackupDestinationSerializer` — fields: `id`, `name`, `kind`,
`enabled`, `path`, `bucket`, `prefix`, `region`, `endpoint_url`,
`access_key_id`, `server_side_encryption`, `credential_mode`,
`has_secret_access_key`, `created_at`, `updated_at`
(read-only: `id`, `credential_mode`, `has_secret_access_key`, `created_at`,
`updated_at`). `secret_access_key` is **write-only** and absent from responses;
`has_secret_access_key` is a `SerializerMethodField`. This mirrors
`accounts.serializers.OAuthProviderSerializer`, which already exposes
`has_client_secret` instead of the secret.

### 4.2 `BackupJob`

**Model:** `backups.models.BackupJob`

| Field | Type | Default | Constraints / Notes |
|---|---|---|---|
| `id` | `UUIDField` | `uuid4` | primary key |
| `scope` | `CharField(10)` | `instance` | choices: `instance`, `zev` |
| `zev` | `FK(zev.Zev, SET_NULL)` | `null` | set only when `scope="zev"`; `SET_NULL` so a safety backup outlives the ZEV it protected |
| `trigger` | `CharField(12)` | `manual` | choices: `manual`, `scheduled`, `pre_restore` |
| `destination` | `FK(BackupDestination, SET_NULL)` | `null` | |
| `requester` | `FK(User, SET_NULL)` | `null` | `null` for scheduled runs |
| `status` | `CharField(20)` | `queued` | `queued`, `running`, `completed`, `failed` — same vocabulary as `ExportJob` |
| `created_at` | `DateTimeField` | `auto_now_add` | `db_index=True` |
| `started_at` / `completed_at` | `DateTimeField` | `null` | |
| `archive_name` | `CharField(255)` | `""` | `openzev-backup-<instance>-<YYYYMMDD-HHMMSS>.zip[.enc]` |
| `archive_location` | `CharField(1000)` | `""` | absolute path, or `s3://bucket/key` |
| `archive_bytes` | `BigIntegerField` | `null` | size as stored |
| `archive_sha256` | `CharField(64)` | `""` | of the stored bytes, encrypted or not |
| `encrypted` | `BooleanField` | `False` | |
| `encryption_key_fingerprint` | `CharField(16)` | `""` | first 16 hex of SHA-256 of the active key |
| `manifest_json` | `JSONField` | `dict` | the manifest, so the UI reports contents without fetching the archive |
| `error_message` | `CharField(500)` | `""` | user-safe summary only |

`Meta.ordering = ["-created_at", "-id"]`; indexes on `("status", "started_at")`
and `("scope", "created_at")`. `file_expires_at` and an `expired` property arrive
with retention in phase 4.

**Serializer:** `BackupJobSerializer` — all fields above except `destination`,
`requester` and `trigger`'s display, plus `zev_id`, `zev_name` and
`destination_name`, all read-only. `requester` is deliberately not exposed.

### 4.3 `RestoreJob`

**Model:** `backups.models.RestoreJob` (migration `0002_restorejob`; listed in
`EXCLUDED_MODELS`: it describes archives, it is not part of one).

| Field | Type | Default | Constraints / Notes |
|---|---|---|---|
| `id` | `UUIDField` | `uuid4` | primary key |
| `target_zev_id` | `UUIDField` | | indexed. **Not** a foreign key: a restore may recreate a community that was deleted, so the target need not exist when the job is created |
| `target_zev_name` | `CharField(200)` | `""` | snapshot, for a readable log after deletion |
| `source_backup` | `FK(BackupJob, SET_NULL)` | `null` | |
| `source_description` | `CharField(500)` | `""` | for a CLI-supplied path or URI with no `BackupJob` row |
| `dry_run` | `BooleanField` | `True` | defaults to the safe value |
| `force` | `BooleanField` | `False` | override for the *overridable* conflicts of §6.6 |
| `status` | `CharField(20)` | `queued` | `BackupJobStatus` |
| `plan_json` | `JSONField` | `dict` | the plan (§6.6); on a refusal, the plan that refused; on a damaged archive, `{"verification_failures": [...]}` |
| `safety_backup` | `FK(BackupJob, SET_NULL, related_name="+")` | `null` | the pre-restore backup |
| `safety_destination` | `FK(BackupDestination, SET_NULL, related_name="+")` | `null` | where it is written |
| `requester` | `FK(User, SET_NULL)` | `null` | `null` for the command line |
| `created_at` / `started_at` / `completed_at` | `DateTimeField` | | |
| `error_message` | `CharField(500)` | `""` | user-safe |

**Serializer:** `RestoreJobSerializer`, read-only: the fields above plus
`source_archive_name` and `source_created_at` (from the source backup's manifest).
`RestoreJobCreateSerializer` validates the input (§5).

### 4.4 Settings

Added to `backend/config/settings.py`:

| Setting | Env | Default | Purpose |
|---|---|---|---|
| `BACKUP_ENCRYPTION_KEYS` | `env.list` | `[]` | Artifact encryption and destination-secret encryption (ADR 0024) |
| `BACKUP_S3_ACCESS_KEY_ID` | `env` | `""` | Overrides every stored S3 credential |
| `BACKUP_S3_SECRET_ACCESS_KEY` | `env` | `""` | Overrides every stored S3 credential |
| `BACKUP_WORK_DIR` | `env` | `""` (the system temp directory) | Where archives are assembled. Must have room for one full archive, and for a second copy while encrypting (the plaintext is deleted before the upload) |
| `BACKUP_RUNNER_TIMEOUT_S` | `env.int` | `10800` | Soft limit; hard limit a grace above, as `EXPORT_RUNNER_TIMEOUT_S` |
| `OPENZEV_VERSION` | `env` | `""` | Release version recorded in manifests for humans; compatibility is decided by the migration state, so leaving it unset is fine |

## 5. API contracts

Registered as `path("api/v1/backups/", include("backups.urls"))` in
`config/urls.py`. Every endpoint is `[IsAdmin]` (`accounts.permissions.IsAdmin`).

Phase 1:

| Endpoint | Method | Behaviour |
|---|---|---|
| `/api/v1/backups/destinations/` | GET | Destinations by `name`, in the project's standard `PageNumberPagination` envelope (the frontend reads it with `fetchAllPages`) |
| `/api/v1/backups/destinations/` | POST | Create. 400 with per-field errors from `clean()` — including "a secret cannot be stored without `BACKUP_ENCRYPTION_KEYS`" and "path resolves inside MEDIA_ROOT". Audited `backup_destination.create` (GOVERNANCE) |
| `/api/v1/backups/destinations/{id}/` | GET, PATCH | An absent `secret_access_key` leaves the stored one intact; `""` clears it. Audited `backup_destination.update` with a diff over the tracked fields (never the secret) and `secret_changed` in metadata |
| `/api/v1/backups/destinations/{id}/` | DELETE | 204. Existing archives are not touched and jobs keep their recorded location. Audited `backup_destination.delete` |
| `/api/v1/backups/destinations/{id}/test/` | POST | Writes and deletes a small probe object. `{"ok": true}` or 400 `{"detail"}` with a safe message; never echoes credentials or a raw provider response |
| `/api/v1/backups/jobs/` | GET | Newest first, a plain list. Filters `?scope=`, `?status=`, `?limit=` (1–100, default 25) |
| `/api/v1/backups/jobs/` | POST | `{scope, zev_id?, destination_id}` → 202 with the job. Persist, then enqueue on commit; a failed enqueue marks the job `failed` and returns 503 — never a 202 for a job that will not run (ADR 0017). 400 for an unknown or disabled destination, a `zev` scope without a ZEV, an `instance` scope with one, or an unknown ZEV |
| `/api/v1/backups/jobs/{id}/` | GET | Status, for polling |
| `/api/v1/backups/jobs/{id}/download/` | GET | `FileResponse` for a completed job in a **local** destination. 409 when there is no artifact or the archive is in S3 (fetch it from the bucket); 410 when the file, or its destination, no longer exists, or when the recorded location does not resolve inside the destination's directory |
| `/api/v1/backups/status/` | GET | `{encrypted, encryption_key_fingerprint, encryption_key_problem, environment_credentials, destinations_enabled, last_successful, last_failed, age_hours}`. `encrypted` is whether a *usable key is configured*; a configured-but-unusable key sets `encryption_key_problem` instead, so it is not read as "no key". Key value never appears |

Phase 3:

| Endpoint | Method | Behaviour |
|---|---|---|
| `/api/v1/backups/restores/` | GET | Newest first, a plain list. Filters `?zev_id=`, `?limit=` (1–100, default 25) |
| `/api/v1/backups/restores/` | POST | `{source_backup_id, target_zev_id, dry_run (default true), force (default false), safety_destination_id?}` → 202. Persist, then enqueue on commit; a failed enqueue marks the job `failed` and returns 503. **400** for: `mode: "instance"` ("Whole-instance restore is only available as a management command."), an unknown or unfinished backup, a community the backup's manifest does not hold, an unknown or disabled safety destination, and a real restore of an existing community with nowhere to write the safety backup (the source backup's destination is the default). **409** when that community already has a queued or running restore. Audited `restore.created` on the community |
| `/api/v1/backups/restores/{id}/` | GET | Status and `plan_json`, for polling |

Later phases:

| Endpoint | Method | Phase | Behaviour |
|---|---|---|---|
| `/api/v1/backups/jobs/{id}/verify/` | POST | 4 | Streams the artifact, decrypts if needed, checks every manifest checksum and count. 200 `{"ok": true, "members": n}` or 400 `{"detail", "failures": [...]}`. Creates nothing (the CLI `openzev_backup_verify` ships in phase 1) |

`status` gains `stale` in phase 4: `age_hours > 2 × the configured schedule
interval`, or `true` when a schedule exists and no backup has ever succeeded.

## 6. Async and integration behavior

### 6.1 Archive format

`kind: "backup"`, `format_version: 1`, independent of the transfer archive's
version sequence (ADR 0023). A ZIP of JSON Lines sections
(`backend/backups/archive.py`):

```
manifest.json
instance/<section>.jsonl           app_settings, oauth_providers, templates,
                                   dynamic_sources, dynamic_prices, accounts
instance/unscoped_*.jsonl          audit_events, contract_issues, import_logs
                                   whose ZEV is null
zevs/<zev id>/<section>.jsonl      zev, participants, metering_points, tariffs,
                                   readings, import_logs, invoices,
                                   contract_issues, audit_events
zevs/<zev id>/account_refs.json    {"users": [{"id", "username", "email"}]}
zevs/<zev id>/media/<name>         that community's invoice PDFs
```

The section → model mapping is `backend/backups/registry.py` (`INSTANCE_SECTIONS`,
`UNSCOPED_SECTIONS`, `ZEV_SECTIONS`, each `ZevPart` naming its ORM lookup to the
ZEV and its write order). Section order is a correctness constraint for restore:
parents before the rows that point at them.

**Every line is Django's own serialization of one row** —
`{"model": "zev.participant", "pk": "<uuid>", "fields": {...}}` — written with
`serializers.serialize("jsonl", ...)` and an explicit `fields=` list of every
concrete column (`_serialized_fields`). Primary keys and foreign keys are the real
values. This is the property that separates a backup from a transfer archive. Many
to many fields (`User.groups`, `User.user_permissions`) are deliberately not
serialized: nothing in the application uses them and their target ids are not
stable across instances. `BinaryField`s (`ContractIssue.pdf`,
`TotpDevice.secret_encrypted`) travel base64-encoded inside the row.

Sections stream through `QuerySet.iterator(chunk_size=2000)` into a compressing
zip member (`force_zip64=True`, since the size is unknown when the header is
written); a `_HashingWriter` digests and counts bytes as they pass. Nothing holds a
whole section in memory.

**Media.** For each `MEDIA_FIELDS` entry — today `invoices.Invoice.pdf_file` — the
file is copied from `default_storage` into the ZEV's `media/` directory under its
storage name. A name that is absolute or contains `..` is refused (it is read from
the database, and an archive member must not be able to name a place outside its
own directory); a file the database references but storage no longer has is
recorded, not fatal — refusing to back up because an old PDF is already gone would
make the instance's other data less safe. A file named by two rows is stored once.
Both cases appear in the ZEV's `media` summary in the manifest.

**`manifest.json`:**

```json
{
  "kind": "backup",
  "format_version": 1,
  "created_at": "2026-09-21T14:24:49+02:00",
  "instance_name": "openzev-prod",
  "openzev_version": "1.16.0",
  "scope": "instance",
  "zev_id": null,
  "migrations": {"zev": ["0001_initial", "..."], "invoices": ["..."]},
  "counts": {"instance/accounts": 42, "zevs/<id>/readings": 1051200},
  "members": {
    "instance/accounts.jsonl": {"sha256": "…", "bytes": 18422, "records": 42,
                                "models": {"accounts.User": 3, "accounts.ApiKey": 1}},
    "zevs/<id>/media/invoices/pdf/a.pdf": {"sha256": "…", "bytes": 91230}
  },
  "zevs": [{"id": "…", "name": "Sonnenhof",
            "counts": {"invoices": 96},
            "media": {"files": 96, "bytes": 8765432, "missing": [], "unsafe": []}}],
  "encryption": {"algorithm": "AES-256-GCM", "key_fingerprint": "a1b2c3d4e5f60718"},
  "secret_fingerprints": {"mfa_encryption_keys": ["9f8e7d6c5b4a3928"], "secret_key": "1122334455667788"}
}
```

`openzev_version` comes from the optional `OPENZEV_VERSION` setting and is
informational and may be empty. `migrations` is the authoritative compatibility
signal. `encryption` records the fingerprint the caller *will* encrypt under: the
envelope wraps the finished ZIP, so the manifest inside cannot learn it afterwards.
The manifest is written last so `counts` and `members` are what was actually
produced.

**Excluded by design** (`EXCLUDED_MODELS`, each with a reason): the short-lived
`EmailVerificationToken`, `MagicLinkToken`, `OAuthState`, `OAuthExchangeCode`;
`exports.ExportJob` (its artifact expires after a day) and the `backups` models
themselves; `django_celery_beat` scheduler state; and framework tables
(`admin.LogEntry`, `auth.Permission`, `auth.Group`, `contenttypes.ContentType`,
`sessions.Session`).

**Completeness is enforced by tests, not by field lists.** `CoverageTests` fail
when an installed model is neither backed up nor excluded with a reason, when a
listed model no longer exists, when a model is both, when a backed-up model gains
a `FileField` that is not in `MEDIA_FIELDS`, and when a ZEV lookup does not resolve.

**Verification (`verify_archive`).** Opens the archive (decrypting to a temporary
file first when it is encrypted), then checks that every manifest member exists
with the recorded SHA-256 and size, that every JSON Lines member holds the recorded
number of records, that `counts` agrees with the members, and that nothing is
present that the manifest does not vouch for. Failures are collected (first
`MAX_REPORTED_ERRORS` = 50, true total counted alongside) and raised as
`ArchiveError`. `read_manifest` structurally validates the manifest first and
refuses a transfer archive by `kind`, naming where transfer archives belong.

### 6.2 Encryption envelope

Implemented in `backend/backups/crypto.py`; applied to the assembled ZIP as a
stream, so manifest checksums describe plaintext members (ADR 0024).

```
b"OZBK1"                            5-byte magic
<uint32 header length><header>      JSON: algorithm, key_fingerprint,
                                    chunk_size, nonce_prefix (4 random bytes, hex)
(<uint32 length><ciphertext+tag>)*  one per chunk, 1 MiB by default
```

- A key is any string of at least 32 characters (`MIN_KEY_LENGTH`); shorter is
  `BackupKeyRejected`. The AES key is `HKDF-SHA256(key, info=b"openzev-backup-archive-v1")`.
  Destination secrets use Fernet over a key derived with a *different* HKDF `info`
  (`openzev-backup-destination-secret-v1`), so one configured string cannot produce
  the same key for both purposes.
- Nonce per chunk = 4-byte random prefix ‖ 8-byte big-endian counter.
- Each chunk's associated data is `sha256(header) ‖ counter ‖ final-flag`. Editing
  the header, reordering chunks, or dropping the last chunk therefore fails
  authentication rather than yielding a shorter archive. The encryptor reads one
  chunk ahead so the last non-empty chunk is marked final; an empty source still
  yields one empty final chunk.
- The decryptor bounds every read (`header ≤ 64 KiB`, `ciphertext ≤ chunk_size + 16`,
  `chunk_size ≤ 64 MiB`) so a hostile header cannot demand unbounded memory.
- Decryption selects the configured key whose fingerprint matches; none matching is
  `BackupKeyMissing`, whose message names the fingerprint the archive needs.

### 6.3 Backup runner — `backups.tasks`

`execute_backup_job(job_id, *, source, destination=None)` does the work and is
called by the Celery task `run_backup_job` (soft time limit
`BACKUP_RUNNER_TIMEOUT_S`, hard limit a 900 s grace above, as for exports) and
directly by `manage.py openzev_backup`, which must work with no broker.

1. **Claim** with a single `UPDATE … WHERE status='queued'`; a lost claim returns
   `None` (duplicate delivery runs the job once). Audit `backup.started`.
2. Resolve the destination (`destination` override, then the job's) and the active
   key fingerprint.
3. In a `TemporaryDirectory(dir=BACKUP_WORK_DIR)`, call
   `archive.build_archive` into a file — **never a buffer**. It runs in one
   `atomic(durable=True)` block, with `SET TRANSACTION ISOLATION LEVEL REPEATABLE
   READ` on PostgreSQL: sections are read over minutes, and READ COMMITTED would
   produce an archive of a state that never existed. `durable=True` makes it the
   outermost transaction, so called inside another it fails loudly.
4. When a key is set, encrypt to a second file and delete the plaintext (the
   peak-disk moment), then digest the stored file (SHA-256 and size).
5. `storage.store_archive` — local: copy to a `.partial` name, `chmod 0600`, atomic
   rename; S3: boto3 `upload_file` (multipart above 64 MiB) with the configured
   `ServerSideEncryption`. The archive name is
   `openzev-backup-<label>-<YYYYMMDD-HHMMSS>-<job id[:8]>.zip[.enc]`.
6. **Publish** with an `UPDATE … WHERE status='running'`: a job someone already
   failed is not resurrected by a late completion. Audit `backup.completed` with
   counts, size, destination, location and whether it was encrypted — never
   contents.
7. **Failure.** `SoftTimeLimitExceeded` → `failed` with a time-limit message, then
   re-raised. `DestinationError` and `BackupCryptoError` carry messages written to
   be shown and are stored as the row's `error_message`. Anything else stores a
   generic message and logs the traceback — the detail never reaches the row or the
   audit log. The temporary directory is removed on every path.

Audit is best-effort (`_audit_best_effort`): a failed audit write neither fails a
completed backup nor masks the exception a failed one is about to raise.

**CLI.** `openzev_backup (--destination NAME | --path DIR) [--zev ID|NAME]`
creates a `BackupJob`, runs it in-process with `source=MANAGEMENT_COMMAND`, prints
the location, size, SHA-256 and encryption status, warns on standard error before
starting when no key is set, and exits non-zero (`CommandError`) on failure with the
row's safe message. `--path` writes to an ad-hoc local directory with no saved
destination. `openzev_backup_verify FILE` runs `verify_archive`.

### 6.4 Scheduling and retention

- `backups.tasks.scheduled_backup` runs from a `django_celery_beat` `PeriodicTask`
  named `openzev-scheduled-backup`, created disabled on migration. The admin UI
  edits its crontab, so the schedule is data, not a settings constant.
- It creates one `BackupJob` per enabled destination with `trigger="scheduled"`,
  and skips a destination that already has a `queued`/`running` job.
- `backups.tasks.sweep_backup_artifacts` runs hourly on the beat schedule and
  opportunistically at the start of each backup run (as `sweep_export_jobs` does,
  so deployments without a beat process still clean up):
  - deletes artifacts past `file_expires_at`;
  - enforces `BackupDestination.retention_count`, newest kept;
  - fails a `running` job whose worker died, past the hard limit plus a grace.
  Rows are retained after their artifact is deleted, so the history stays readable.

### 6.5 Instance restore — `manage.py openzev_restore --mode instance`

```
manage.py openzev_restore --mode instance --from <path|s3://bucket/key>
                          [--endpoint-url URL] [--region R] [--dry-run] [--force]
```

`backups.restore.restore_instance(source, dry_run, force, progress)` does the work;
the command adds argument handling, the S3 download (to `BACKUP_WORK_DIR`, removed
afterwards) and the report. Everything is checked before the first write, and every
write is one transaction.

1. **Open and verify.** Decrypt once (to a temporary file) and run
   `archive.verify_open_archive` on that handle: every member's SHA-256, size and
   record count, the manifest's counts, no unvouched member, every section the scope
   requires. Any failure aborts before a write.
2. **Compatibility preflight** (`RestoreError`, `ArchiveError`):
   - `kind` must be `backup` (a transfer archive is refused by name) and
     `format_version` supported.
   - `scope` must be `instance`; a single-community backup is refused.
   - **Migrations** (`restore.check_migrations`): for the apps that own backed-up
     tables, the applied set must equal the archive's. A migration the code does not
     know → *newer version of OpenZEV* (unsafe direction, refused). One the archive
     has but the database has not applied → *run `migrate`*. One the database has and
     the archive lacks → *schema is newer than the backup*, naming the
     `migrate <app> <migration>` steps back. See deviation 10.
   - **MFA keys** (`restore.key_warnings`): when the archive holds TOTP devices and
     none of its `secret_fingerprints.mfa_encryption_keys` is configured here, a
     warning names the fingerprint and the consequence. It does not refuse: recovery
     codes and an administrator reset remain (ADR 0021).
3. **Empty-instance guard.** Refuse when any `Zev` or any non-superuser `User` exists,
   unless `--force`. A bootstrap superuser does not count and is replaced with the
   backup's accounts.
4. **Load**, in one `transaction.atomic()`:
   1. Delete every backed-up table's rows, dependants first (and `ExportJob`, whose
      `PROTECT` foreign key to a community would otherwise block it). Rows outside
      the backup that cascade from a deleted user or provider (tokens, `OAuthState`)
      go with them; `BackupJob` references are nulled by their `SET_NULL`.
   2. For each member in load order — instance sections, then each community's
      sections in registry order, then the `unscoped_*` sections — deserialize with
      Django's `jsonl` deserializer and insert with `bulk_create` in batches of 1000.
      **A section may only create the models the registry assigns to it** (the
      allow-list is the security boundary: an archive cannot write to
      `sessions.Session` or anything else outside the registry). Each member's
      per-model counts must equal the manifest's.
   3. `bulk_create` runs `pre_save`, which would overwrite every `auto_now` /
      `auto_now_add` value with the time of the restore; those flags are switched off
      per model for the insert and put back in `finally` (`_stored_timestamps`).
   4. Cross-check: each table holds exactly the number of rows loaded into it;
      `connection.check_constraints()` so a dangling reference fails here, inside the
      transaction, not at commit.
   5. **Restore media** into storage under the exact name the `Invoice` row holds
      (`_restore_media`): only names some restored `Invoice.pdf_file` references, each
      re-checked as a safe relative path, an existing file at that name deleted first
      (storage would otherwise pick a fresh name), size and SHA-256 checked while
      copying. Files written are removed again if anything later fails.
   6. **Reconcile sequences** for every integer-keyed model
      (`connection.ops.sequence_reset_sql`), so the next ordinary insert cannot reuse
      a restored id.
5. **Audit** (after commit, best effort — a failed audit write cannot undo a finished
   restore): `backup.instance_restored`, category `SYSTEM`, source
   `MANAGEMENT_COMMAND`, metadata with the backup's time, instance name and version,
   record and PDF counts, whether `--force` was used, and how many existing rows were
   replaced. The archive's own audit trail is restored first, so this entry follows
   it.
6. **Report** on stdout: per-model counts, rows replaced, PDFs restored, PDFs that
   were already missing when the backup was taken, sequences advanced; warnings on
   stderr.

Errors are user-safe: a record the schema cannot read names its section and never
quotes a field value (those are participant names and addresses); a database
rejection is one generic sentence, and the cause goes to the server log.

`--dry-run` performs steps 1–3 and reads every record of step 4.2 (allow-list, counts,
schema fit) without writing.

### 6.6 Per-ZEV restore — API and `--mode zev`

The destructive one, and the one that runs next to live data it must not disturb.
`backups.restore_zev.restore_zev(source, zev_id, dry_run, force, safety_backup,
exclude_job)` does the work; `backups.tasks.execute_restore_job` is its job runner
(claim, audit, safe messages, guarded publish — as for backups), called by the Celery
task `run_restore_job` and directly by the command. Rules, in the order enforced:

1. **Open and verify** the archive (`verify_open_archive`), find the community in the
   manifest (else "does not contain that community"), and check migrations exactly
   as §6.5 does. An instance backup and a single-community backup both work.
2. **Plan** (`plan_json`), always computed, and the whole result of a dry run. Facts
   are read from the archive without loading rows (`read_facts`: invoice statuses,
   issued-contract ids, meter ids, referenced price sources, the `account_refs`),
   then compared with the database (`evaluate`):

   ```json
   {
     "zev": {"id": "…", "name": "Sonnenhof", "exists_now": true, "current_name": "Sonnenhof (renamed)"},
     "backup": {"created_at": "…", "scope": "instance", "instance_name": "", "openzev_version": "…"},
     "sections": {"readings": {"backup": 63264, "current": 0, "kept": false},
                  "audit_events": {"backup": 8, "current": 8, "kept": true}},
     "accounts": {"relink": 3, "missing": ["neu@example.com"]},
     "media": {"files": 12, "missing": 0},
     "conflicts": [{"kind": "sent_invoice_deleted", "detail": "TRF-00041 (paid)", "overridable": true}],
     "blocked": true,
     "safety_backup_id": null,
     "restored": null
   }
   ```

3. **Refuse on conflicts.** *Overridable* (need `force`): `sent_invoice_deleted`,
   `sent_invoice_reverted` (a sent/paid invoice whose backed-up status differs),
   `contract_issue_deleted` (an issued contract the backup lacks — documented as *"an
   immutable archive"*). *Hard* (never forceable): `meter_id_owned_by_other_zev`,
   `referenced_row_missing` (a price source the backup points at that is gone),
   `owner_not_found` (the community must be recreated and its owner has no matching
   account), `export_in_progress`, `restore_in_progress`. Each kind lists up to 20
   details and then "and N more". A dry run returns the plan with `blocked: true`
   instead of failing; a real run raises `RestoreRefused` and the job fails with the
   plan attached. See deviation 21.
4. **Safety backup**, only for a real run of a community that exists: a `BackupJob`
   with `scope="zev"`, `trigger="pre_restore"`, run to completion in-process before
   any write and linked as `RestoreJob.safety_backup`, to
   `safety_destination` (default: the source backup's). If it fails, the restore
   fails with "The safety backup failed, so nothing was restored" and nothing was
   written. It is the way back: a restore from it returns the community to the moment
   before.
5. **Lock and re-check.** In one transaction: `select_for_update()` on the `Zev` row
   (serialising with contract issuance, which locks it too), then `evaluate` again
   (deviation 22).
6. **Replace**, in that transaction: delete the community's rows dependants-first —
   **not the `Zev` row, not `AuditEvent`** — plus any orphaned issued contract the
   backup also holds; update the `Zev` row in place or insert it; load every other
   section with original primary keys through the same allow-list, count check and
   timestamp handling as §6.5; `check_constraints()`; verify per-table counts; restore
   the community's invoice PDFs under their exact names (`MediaUndo`); reconcile the
   sequence of the one integer-keyed model in scope
   (`InvoiceDynamicSourceEvidence`).
7. **Relink accounts by natural key** (`resolve_accounts`, applied to every user
   foreign key of the community's rows while loading). Each backed-up user id is
   looked up through `account_refs.json` and matched to today's account by `email`
   (case-insensitive), then `username`; none, or more than one, leaves the link
   empty and is listed in `plan.accounts.missing`. The one required link, `Zev.owner`,
   falls back to the community's current owner, and blocks a recreation with
   `owner_not_found`. **No account row is created, modified or deleted.**
8. **Audit, never rewrite.** `restore.created` (API), `restore.started`, then
   `zev.restored` with metadata naming the source backup and its time, rows written
   per model, accounts relinked and missing, the kinds of conflict overridden and the
   safety backup; or `restore.failed` with the reason; a preview records
   `restore.previewed`. Category `SYSTEM`; source `API`/`CELERY` or
   `MANAGEMENT_COMMAND`. No existing event is touched (asserted by test, and by an
   audit-row checksum on real PostgreSQL).

**Command:**

```
manage.py openzev_restore --mode zev --from <path|s3://bucket/key> --zev <id|name>
                          [--destination NAME | --path DIR] [--dry-run] [--force]
```

Creates a `RestoreJob` (`requester` null, `source_description` the path or URL) and
runs it in-process. `--zev` is an id, or the exact name of an existing community
(a deleted one is named by id; `openzev_backup_verify` now lists ids). A real run of
an existing community requires `--destination` or `--path`, checked before anything
starts. A dry run that would be refused exits non-zero; `--force` marks overridden
conflicts as such in the output.

## 7. Frontend

### 7.1 System Settings — `backup` tab

**File:** `frontend/src/pages/AdminSystemSettingsPage.tsx`

`SystemSettingsTab` is
`'regional' | 'features' | 'oauth' | 'security' | 'vat' | 'backup'`, appended to
`TAB_ORDER`; `?tab=backup` selects it. The panel renders `BackupSettingsSection`,
as `vat` renders `VatSettingsSection`. The route is already behind
`ProtectedRoute allowedRoles={['admin']}`.

### 7.2 Components (phase 1)

All under `frontend/src/features/backups/`.

| Component | Contents |
|---|---|
| `BackupSettingsSection` | Composes the tab. An intro; the **encryption banner** — `error-banner` when `encryption_key_problem` is set, `warning-banner` when no key is configured, `info-banner` (with the key fingerprint) when one is; a note that restore is not available in the app yet; `StatCard`s for last successful / last failed backup and enabled destinations |
| `BackupDestinationsSection` | Destination table (name, type, target, credential mode, status) with **Test**, **Edit**, **Delete** (`ConfirmDialog`), and a `FormModal` form. The secret input is disabled, with the reason, when no encryption key is configured; blank on edit; a "remove the stored secret" switch appears only when one is stored; an info banner notes when environment credentials override the form. Kind is fixed on edit |
| `BackupJobsSection` | **Back up now** (scope, community, destination) and the job table with status and encryption badges, **Details** (completed) and **Download** (completed, local archives only). Polls every 3 s only while a job is queued or running, and refreshes the status query when work finishes |
| `BackupJobDetailsModal` | Archive name, location, size, SHA-256, encryption, timestamps, record count, per-community table, a warning when invoice PDFs were missing from storage, and a note when the archive is in object storage |
| `backupHelpers.ts` | Pure logic: `buildDestinationPayload`, `destinationTarget`, `readManifest`, `hasActiveJob`, `isDownloadable`, … |

`buildDestinationPayload` follows the API's secret contract: absent leaves a stored
secret alone, a typed value replaces it, `''` clears it (only on the explicit
switch, or when an S3 destination is switched to local). Fields belonging to the
other kind are sent empty.

Phase 3 adds `BackupRestoreSection` and `RestorePlanView` (§7.6). Phase 4 adds the
schedule editor and the health-panel card.

### 7.6 Restore a community (phase 3)

`BackupRestoreSection` is the last card of the `backup` tab.

| Part | Behaviour |
|---|---|
| Form | Backup (finished backups that hold a community) and community (those in the chosen backup's manifest). Changing either discards the current preview. **Preview restore** submits `dry_run: true` and polls the job every 3 s while it is queued or running |
| `RestorePlanView` | Backup time and version; a table of each kind of data (`backup` vs `now`, the audit trail marked *never restored, only added to*); accounts relinked; a `warning-banner` naming accounts that would be left unlinked and one for PDFs already missing; the conflicts, each a `warning-banner` (*needs your confirmation*) or `error-banner` (*cannot be overridden*) |
| Confirm | Shown only after a completed preview. With a hard conflict: a blocked message and **no** way forward. Otherwise a warning, the `force` switch **only if** overridable conflicts exist, the safety-backup destination **only if** the community exists (default: the backup's own), and the community's current name to be typed exactly. **Restore now** is enabled by `canStartRestore(plan, force)` **and** the typed name **and** a destination. Sends `dry_run: false`, `force`, `safety_destination_id` |
| Outcome | Failed job: `error-banner` with the message, the refusal's plan or the archive's verification failures. Completed restore: `success-banner` with the record count and a note that the safety backup is the undo, and **every cached query is invalidated** — the restore changed data all over the app |
| History | Recent restores: when, community, backup taken, preview or restore (*forced* badge), status and failure reason |

Pure logic in `backupHelpers.ts`: `canStartRestore`, `hardConflicts`,
`forceableConflicts`, `confirmationName`, `readPlan`, `restorableBackups`,
`communitiesIn`, `hasActiveRestore`. Types `RestoreJob`, `RestorePlan`,
`RestoreConflict`, `RestoreJobInput` in `types/api.ts`; `fetchRestoreJobs`,
`fetchRestoreJob`, `createRestoreJob` in `lib/api/backups.ts`; query keys
`backups.restores()` and `backups.restore(id)`. Strings under
`pages.backups.restore.*`, in all four locales. Restoring the whole instance is not
offered; the section says where it is done.

### 7.3 TypeScript types

**File:** `frontend/src/types/api.ts`

```typescript
export type BackupDestinationKind = 'local' | 's3'
/** Where an S3 destination's credentials come from, in order of precedence. */
export type BackupCredentialMode = 'environment' | 'stored' | 'instance_role'
export type BackupJobScope = 'instance' | 'zev'
export type BackupJobTrigger = 'manual' | 'scheduled' | 'pre_restore'
export type BackupJobStatus = 'queued' | 'running' | 'completed' | 'failed'

export interface BackupDestination {
    id: string
    name: string
    kind: BackupDestinationKind
    enabled: boolean
    path: string
    bucket: string
    prefix: string
    region: string
    endpoint_url: string
    access_key_id: string
    /** `''` disables server-side encryption for stores that lack it. */
    server_side_encryption: string
    credential_mode: BackupCredentialMode
    /** The secret is never returned; this reports whether one is stored. */
    has_secret_access_key: boolean
    created_at: string
    updated_at: string
}

export interface BackupDestinationInput {
    name: string
    kind: BackupDestinationKind
    enabled: boolean
    path: string
    bucket: string
    prefix: string
    region: string
    endpoint_url: string
    access_key_id: string
    server_side_encryption: string
    /** Absent leaves a stored secret untouched; `''` clears it. */
    secret_access_key?: string
}

export interface BackupManifestMedia {
    files: number
    bytes: number
    /** Referenced by the database but absent from storage, so not in the archive. */
    missing: string[]
    unsafe: string[]
}

export interface BackupManifestZev {
    id: string
    name: string
    counts: Record<string, number>
    media: BackupManifestMedia
}

export interface BackupManifest {
    kind: 'backup'
    format_version: number
    created_at: string
    instance_name: string
    openzev_version: string
    scope: BackupJobScope
    zev_id: string | null
    counts: Record<string, number>
    zevs: BackupManifestZev[]
    encryption: { algorithm: string; key_fingerprint: string } | null
}

export interface BackupJob {
    id: string
    scope: BackupJobScope
    zev_id: string | null
    zev_name: string
    trigger: BackupJobTrigger
    destination_id: string | null
    destination_name: string
    status: BackupJobStatus
    created_at: string
    started_at: string | null
    completed_at: string | null
    archive_name: string
    /** An absolute path, or `s3://bucket/key`. */
    archive_location: string
    archive_bytes: number | null
    archive_sha256: string
    encrypted: boolean
    encryption_key_fingerprint: string
    /** Empty until the job completes. */
    manifest_json: BackupManifest | Record<string, never>
    error_message: string
}

export interface BackupJobInput {
    scope: BackupJobScope
    zev_id?: string
    destination_id: string
}

export interface BackupStatus {
    /** Whether a usable encryption key is configured (not whether the last archive used it). */
    encrypted: boolean
    encryption_key_fingerprint: string
    /** Set when a key is configured but unusable, so it is not mistaken for "no key". */
    encryption_key_problem: string
    /** S3 credentials come from the server environment and override any stored ones. */
    environment_credentials: boolean
    destinations_enabled: number
    last_successful: BackupJob | null
    last_failed: BackupJob | null
    age_hours: number | null
}
```

Restore types (`RestoreJob`, `RestorePlan…`) arrive with phase 3.

### 7.4 API client and query keys

**File:** `frontend/src/lib/api/backups.ts`

| Function | Method | Endpoint |
|---|---|---|
| `fetchBackupDestinations()` | GET (all pages) | `/backups/destinations/` |
| `createBackupDestination(input)` | POST | `/backups/destinations/` |
| `updateBackupDestination(id, input)` | PATCH | `/backups/destinations/{id}/` |
| `deleteBackupDestination(id)` | DELETE | `/backups/destinations/{id}/` |
| `testBackupDestination(id)` | POST | `/backups/destinations/{id}/test/` |
| `fetchBackupJobs()` | GET | `/backups/jobs/` |
| `createBackupJob(input)` | POST | `/backups/jobs/` |
| `downloadBackupArtifact(id)` | GET (blob) | `/backups/jobs/{id}/download/` |
| `fetchBackupStatus()` | GET | `/backups/status/` |

**File:** `frontend/src/lib/api/queryKeys.ts`

```typescript
backups: {
    destinations: () => ['backups', 'destinations'] as const,
    jobs: () => ['backups', 'jobs'] as const,
    status: () => ['backups', 'status'] as const,
},
```

### 7.5 i18n

All strings under `pages.backups.*` (plus `adminSystemSettings.tabs.backup.label`) in
`frontend/src/i18n/locales/{de,en,fr,it}.ts`; no hardcoded user-facing text. Command
names are passed as a `{{command}}` placeholder so they are never translated.

## 8. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Archives carry plaintext secrets and full PII — `OAuthProvider.client_secret` is a clear `CharField`, plus password hashes, participant addresses, invoice PDFs | Critical | `BACKUP_ENCRYPTION_KEYS` (ADR 0024). Optional, so mitigation depends on the operator setting one: warned in CLI and UI, recorded per artifact, led with in the docs. TLS + SSE for S3. `clean()` forbids a local path inside `MEDIA_ROOT` |
| `BACKUP_ENCRYPTION_KEYS` lost | High — every encrypted archive is unrecoverable | Documented as a key to escrow; key list allows staged rotation; a system check warns when a schedule exists with no key |
| `MFA_ENCRYPTION_KEYS` mismatch on restore | High — every TOTP secret undecryptable | Fingerprints in the manifest; preflight names the required fingerprint before loading anything |
| Per-ZEV restore destroys issued documents | High — `sent`/`paid` invoices and `ContractIssue` rows have legal retention | Refused by default, `force` required, recorded on the job and in the audit event |
| Restore interleaves with an invoice run | High | `select_for_update()` on the ZEV; refusal while a generation or export job for it is active |
| A backup nobody has restored | High | `verify` action; `--dry-run` on both restore modes; documented restore drill; staleness surfaced in health |
| Scale — millions of readings, multi-GB archives | High | Temp-file assembly, `iterator()` streaming, multipart upload; never `bytes` in memory |
| A long repeatable-read snapshot pins a connection and delays vacuum | Medium | Already flagged for the transfer exporter at the 2M-row scale; the backup runs off-request on a worker, and the schedule should target quiet hours |
| Corrupt or truncated archive passes as valid | Medium | Per-member SHA-256 in the manifest — ZIP CRC32 alone is too weak for an artifact that crosses a network and sits in a bucket for months — plus authenticated chunk ordering and a final-chunk flag |
| A model is added, or a model gains a file field, and silently stops being backed up | Medium | Fields cannot be forgotten (every concrete column is serialized). Whole models and file fields can, so `CoverageTests` fail until each is backed up or excluded with a reason |
| Restoring a backup restores a credential set — an attacker who plants one gains accounts | Critical | Instance restore is CLI-only (host access required); per-ZEV restore never touches accounts; every restore is audited |
| Sequence collision after an instance restore | Medium | Explicit sequence reconciliation for every integer-keyed model (§6.5 step 6), asserted by test |

## 9. Test plan

### Backend — `backend/backups/` (381 tests, phases 1–3)

| Module | Tests | Covers |
|---|---|---|
| `test_crypto.py` | 22 | Envelope round trip (multi-chunk, exact multiple, empty); **truncation, reordered chunk, flipped bit and edited header each fail authentication**; wrong key names the required fingerprint; rotation; short-key rejection; domain separation between archive and secret keys; destination-secret round trip and rotation |
| `test_archive.py` | 54 | `ArchiveShapeTests` — manifest, every section present, **timestamps keep their microseconds**, every line a serialized row, **primary keys preserved** (UUID and integer), FKs are real keys, a ZEV holds only its own rows, PDFs travel byte-exact under their own ZEV, contract PDFs base64 in-row, **rows whose ZEV was deleted are in the instance scope**, account refs, credentials travel, M2M excluded, no row of an excluded model, counts match rows, **no key material in the archive**. `ZevScopeTests`. `MediaTests` — missing PDF recorded not fatal, `..` and absolute names refused, a shared file stored once. `CoverageTests` — the registry closure. `DurabilityTests`. `VerifyTests` — tampered member, missing member, injected member, disagreeing count, **transfer archive refused by kind**, unknown version, malformed manifest, not a zip, failure cap. `EncryptedArchiveTests`. `RoundTripTests` — deserializing the sections reproduces the rows with their keys |
| `test_destinations.py` | 45 | Local and S3 validation (**path inside `MEDIA_ROOT` refused**, `..` resolved first, half a credential pair); credential precedence; boto client construction (custom endpoint → path-style and relaxed checksums; instance role passes no keys); local storage (0600, no partial file on failure, atomic); S3 upload key/SSE/location; **provider errors become safe messages that never echo the response, and an unrecognised error code is named only if it is shaped like one**; persistence |
| `test_runner.py` | 31 | Completed job records location/size/checksum/manifest; stored archive verifies; encryption on/off; a rejected key fails the job with the reason; failures (missing destination, unwritable, **unexpected error is generic on the row and detailed only in the log**, soft time limit); **a job runs once if delivered twice; a late completion does not resurrect a failed job**; audit events; **a broken audit write does not fail a completed backup**; S3 runner; the builder is handed a file, not a buffer; the work directory is empty afterwards |
| `test_api.py` | 42 | **Every endpoint refuses anonymous, owner and participant callers**; destination CRUD; **the secret is never returned, never in the audit log**; absent/empty/new secret semantics; 202 with enqueue after commit; **broker outage → 503 and a failed job**; validation matrix; list filters and limit; download streams, 409/410 cases, **a location outside the destination is never served**; status |
| `test_commands.py` | 22 | `openzev_backup` (path, destination, zev by id or name, ambiguous name, refusal cases, warning on stderr when unencrypted, non-zero exit with a safe message on failure, needs no broker, audited as a management command) and `openzev_backup_verify` (good, encrypted, wrong key, corrupted, missing file) |
| `test_restore_instance.py` | 54 | **Round trip:** every row of every backed-up table equal field for field after a wipe and restore (primary keys and timestamps included), PDFs back under the same name and bytes, encrypted round trip, the audit trail restored and the restore appended to it, a bootstrap superuser replaced, ordinary inserts after a restore. **Dry run:** writes nothing, refuses exactly when the real run would, `--force` reports what would be replaced, schema-unreadable records found. **Refusals leave the database untouched:** populated instance without `--force`, transfer archive, single-community backup, newer-version backup, unapplied migrations, schema newer than the backup (names the `migrate` steps), unrelated apps' migrations ignored. **Integrity:** corrupted member, a manifest missing a whole section, **a section cannot create a model it does not own**, an unreadable record is named without quoting its content, dangling references roll everything back. **Rollback:** a late failure undoes rows and files (**a PDF the restore overwrote is put back**), a failed forced restore leaves existing data, timestamp flags restored, an audit failure does not undo a finished restore. **Media:** a file at that name is replaced not renamed, a PDF already missing at backup time is reported, **unreferenced and `..` media are not written**. MFA key warnings; sequence reset covers exactly the integer-keyed models; S3 source parsing and safe errors; the command (file, dry run, refusal, missing file, listed verification failures, S3 download, warnings on stderr) |
| `test_restore_zev.py` | 43 | The engine. **Replace in place:** a damaged community comes back exactly; **nothing outside it changes** (every other backed-up row identical); **no account row created, modified or deleted**; the community row is updated in place so audit events and `preferred_zev` keep pointing at it; **the audit trail is untouched and none is written**; a deleted community is recreated and its orphaned audit events stay as they were; other communities restore from the same instance backup; a single-community backup works and refuses other communities; PDFs written back; only the integer-keyed model's sequence is reset. **Accounts:** relinked by email under a new id, a missing account reported and left empty (never created), owner follows the email, a live community keeps its owner, a recreation without a findable owner refused. **Conflicts:** none on a clean restore; a sent/paid invoice deleted or rolled back and an issued contract deleted each need `force` and `force` then works; **a meter id owned by another community, a missing price source, a running export and another restore are not forceable**; a refusal changes nothing; the list is capped with "and N more". **Dry run:** plan and no writes, refusals reported not raised, missing accounts shown, no safety backup, schema misfits found without quoting content. **Safety backup:** after the plan and before the first write, a failure stops everything, not taken for a refusal or a community that does not exist, **conflicts checked again under the lock after it**. **Rollback:** late failure, overwritten PDF restored, dangling references, other communities and the trail survive. **Lock** taken on the community row, and not for a dry run |
| `test_restore_runner.py` | 28 | The job lifecycle. A restore records its plan; **a safety backup of the damaged state is taken first, linked, and can undo the restore**; a dry run writes and backs up nothing; audited started/completed with what it did; **every earlier audit event unchanged**; a broken audit write does not undo a restore. A refused restore fails with its plan and takes no safety backup; `force` recorded and lets an overridable conflict through. A failing or missing safety destination stops before any write; an explicit destination is used; **an unexpected error is generic on the row**; soft time limit; a missing file or deleted source row; **damaged-archive failures stored in the plan**; delivered twice runs once; **a late completion does not resurrect a failed job**. Sources: encrypted with and without its key, **S3 round trip through a fake client**, a local file standing in for the job. `fetch_from_destination`: **a location outside its destination is never followed** (local, traversal, other bucket or prefix), a provider error is a safe message |
| `test_restore_api.py` | 21 | **Every endpoint refuses anonymous, owner and participant callers**; dry run by default; the safety destination defaults to the backup's; audited on the community; **naming the whole instance is a 400, not a downgrade**; validation matrix; another community's backup cannot restore this one; a missing safety destination is a 400 for a real restore only; **409 while a restore of that community is active**; broker outage → 503 and a failed job; list order, filter, limit; detail carries the plan; an API-created job runs end to end |
| `test_restore_zev_command.py` | 19 | `--mode zev`: restore by id and by name with a safety backup written where told; recorded as a job and audited as a management command; a saved destination; **refused up front without a place for the safety backup**; a deleted community named by id needs none; unknown and ambiguous names; a safety path inside `MEDIA_ROOT` refused; S3 source; dry run prints the plan and changes nothing; **a dry run that would be refused exits non-zero**; each problem listed with whether `force` helps, and `--force` says it overrode; missing accounts warned; argument checks |

The mutation checks run while building this (removing the traversal guard, the
final-chunk flag, the admin permission, the `MEDIA_ROOT` guard) each turned the
suite red.

Mutation checks run while building phase 3 — each turned the suite red: the community
row deleted instead of updated, the audit trail restored too, accounts not relinked,
no re-check under the lock, hard conflicts overridable by `force`, sent invoices not
protected, orphaned contracts not replaced, the constraint check removed, the row lock
removed (caught only by the lock test, since SQLite ignores locks); on the frontend the
hard-conflict guard, the `force` requirement, the typed-name requirement, the cache
refresh after a restore and the blocked state.

Mutation checks run while building phase 2 — each turned the suite red: timestamps not
preserved, the section allow-list off, files not removed on rollback, an existing file
not replaced, unreferenced media allowed, the empty-instance guard off, the constraint
check removed.

#### Verification notes (phase 2, real PostgreSQL)

The test suite runs on SQLite, which has no sequences to reset, and PostgreSQL
refuses the archive writer's `SET TRANSACTION ISOLATION LEVEL` inside a `TestCase`
transaction. The parts that only PostgreSQL can show were verified end to end on two scratch
databases in the dev stack: `seed_demo` (2 communities, 84,000 readings, 21 invoices,
5 PDFs attached), an **encrypted** `openzev_backup` (3.0 MB), then `migrate` on an
empty database and `openzev_restore`.

- 84,271 records restored in about 11 s including decryption; a wrong key is refused
  naming the fingerprint.
- An `md5` over every row of every backed-up table matched between the two databases
  — the only difference being the audit events the two commands themselves add, and
  the non-backup events matched too. The 5 PDFs matched by SHA-256.
- **Without** the sequence reset, the first `User.objects.create_user` after the
  restore raised `duplicate key value violates unique constraint "accounts_user_pkey"`;
  with it, the new user got id 6 after a restored maximum of 5.
- A populated instance was refused without `--force`; `--dry-run --force` reported the
  84,272 rows it would replace; `--force` replaced them in about 12 s and removed a
  user the backup did not contain.
- Not verified against a real object store: the S3 source is tested with a fake client
  only (as is the S3 destination from phase 1).

#### Verification notes (phase 3, real PostgreSQL)

Two scratch databases again (dev data untouched, dropped afterwards): `seed_demo`,
an **encrypted** instance backup, then damage to one community — renamed, its
63,264 readings deleted, and a **paid** invoice added that the backup never saw.
A checksum was taken of that community's rows, of every other backed-up row, and of
the audit rows that existed before, so the comparison is exact.

- **Preview** listed the plan and the paid invoice as *needs `--force`*, and exited
  non-zero. A real run without a safety destination was refused up front; with one
  but without `--force`, refused with the same problem, and **no safety backup was
  written**.
- **`--force` restore**: 63,428 records in about 22 s including verification and the
  safety backup. The community's rows were **checksum-identical to before the
  damage**, **every other table identical**, and **the 12 audit rows that existed
  before identical** (the trail then only grew).
- **Undo**: restoring from the safety backup returned the damaged state — the paid
  invoice, the rename and the missing readings.
- **Recreation**: with the community deleted outright (22 audit events and one
  issued contract left orphaned with no community), a restore by id needed no safety
  backup, recreated it **checksum-identical**, relinked the orphaned contract, and
  left the 22 audit events as they were.
- Not verified against a real object store, as before; not measured beyond ~63k rows
  per community; the row lock itself is taken (asserted) but no *concurrent* writer
  was tried against it.

### Frontend (67 tests, phases 1 and 3)

- `tests/backup-helpers.test.ts` (17) — the payload contract: a blank edit never
  wipes a secret, a clear is explicit, switching kind clears the other kind's
  fields; target formatting; manifest reading; polling and download rules.
- `tests/backup-settings-section.test.ts` (21) — the encryption banner in each of
  its three states; the restore notice (server command for an instance, single-community restore not yet in the app); destination list and empty state;
  secret field disabled without a key; environment-credentials notice; create
  payload; server validation shown inside the form; start-backup rules; job list
  (download only for local archives, unencrypted badge, failed reason, details).
- `tests/backup-restore-helpers.test.ts` (10) — `canStartRestore` (clean, needs `force`, **never past a hard conflict**), the name to type, reading a plan, choosing a backup and community, polling.
- `tests/backup-restore-section.test.ts` (18) — no backup, communities follow the chosen backup, the whole instance never offered; **a preview is a dry run**; unlinked accounts named; a refusal shows the reason, the conflicts and no way forward; damaged-archive failures listed; **apply needs the exact name** (case matters); the request carries the safety destination, no `force` unless asked; a chosen destination; none for a community that no longer exists; **`force` required for overridable conflicts and absent for hard ones**; a finished restore reports and refreshes every cache; changing the community resets the flow; history.
- `tests/system-settings-tabs.test.ts` — six tabs, and `?tab=backup` opens the
  section.
- Checks: `npm run build`, `npm run lint`, `npm run lint:style`,
  `node ../scripts/check-frontend-hex.mjs`, and the dead-i18n-key and locale-parity
  tests.
- Verified in the running dev stack at 1280 px and 400 px against a real backup on
  PostgreSQL: no console errors, no horizontal overflow.

### Acceptance criteria

- [x] A backup runs to local and/or S3-compatible storage, with a SHA-256 manifest, encrypted whenever `BACKUP_ENCRYPTION_KEYS` is set *(manual and from cron; the built-in schedule is phase 4)*
- [x] With no key set, the backup still runs and both the CLI and the admin UI say the archive is unencrypted
- [x] A destination secret stored in the database is encrypted at rest, never serialized, and overridden by environment credentials
- [x] A fresh install restores to a working instance from a backup alone — accounts, settings, templates, dynamic price series, invoice PDFs, issued contracts and the audit trail all present and linked, with primary keys preserved
- [x] An existing install restores one ZEV to its backed-up state without touching other ZEVs, any account row, or any existing audit row — and the restore itself appears in the log
- [x] Both restore modes support `--dry-run` / `dry_run` reporting exactly what would change
- [x] Restore refuses on schema mismatch, checksum failure, wrong archive `kind`, and (without `force`) on dropping `sent`/`paid` invoices or contract issues
- [x] An MFA key fingerprint mismatch is reported at preflight, not discovered by a locked-out user
- [ ] "Last successful backup" is visible to admins and goes stale loudly
- [x] The registry coverage tests pass, so a new model or file field cannot silently stop being backed up (this replaces the field-level parity test; see *Deviations*)
- [x] User-guide chapter written, including a restore drill; the `12-troubleshooting.md` snippet is replaced 
- [ ] `ROADMAP.md` updated
