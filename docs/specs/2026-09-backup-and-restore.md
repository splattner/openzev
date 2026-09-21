# Feature Spec: Integrated Backup and Restore

- Spec ID: SPEC-2026-09-backup-and-restore
- Status: Draft
- Scope: Major
- Type: Feature
- Owners: splattner
- Created: 2026-09-21
- Target Release: —
- Related Issues: #767
- Related ADRs: [0023](../adr/0023-backup-archives-preserve-keys.md), [0024](../adr/0024-backup-encryption-key.md); builds on [0017](../adr/0017-async-export-jobs.md), [0010](../adr/0010-centralized-audit-event-stream.md), [0021](../adr/0021-mfa-secret-encryption-key.md)
- Impacted Areas: backend | frontend | async jobs | docs | infra

---

> **This spec describes work that has not been implemented.** Field lists,
> endpoints and test names are the design to build against, not a record of
> what exists. Test counts are planned counts. Once shipped, this becomes the
> baseline spec for the `backups` app and is maintained under the rules in
> [`README.md`](README.md).

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
| `retention_count` | `PositiveIntegerField` | `7` | artifacts kept at this destination; `0` = keep all |
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
`access_key_id`, `server_side_encryption`, `retention_count`, `credential_mode`,
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
| `file_expires_at` | `DateTimeField` | `null` | set at completion, so later retention changes do not expire existing artifacts |

`Meta.ordering = ["-created_at", "-id"]`; indexes on `("status", "started_at")`
and `("scope", "created_at")`. `expired` is a computed property, as on
`ExportJob`.

**Serializer:** `BackupJobSerializer` — all fields above plus `expired` and
`destination_name`, all read-only.

### 4.3 `RestoreJob`

**Model:** `backups.models.RestoreJob`

| Field | Type | Default | Constraints / Notes |
|---|---|---|---|
| `id` | `UUIDField` | `uuid4` | primary key |
| `mode` | `CharField(10)` | `zev` | choices: `instance`, `zev`. `instance` rows are only created by the CLI |
| `target_zev_id` | `UUIDField` | `null` | **not** a foreign key: a restore may recreate a ZEV that was deleted, so the target need not exist when the job is created |
| `target_zev_name` | `CharField(200)` | `""` | snapshot, for a readable log after deletion |
| `source_backup` | `FK(BackupJob, SET_NULL)` | `null` | |
| `source_description` | `CharField(500)` | `""` | for a CLI-supplied path or URI with no `BackupJob` row |
| `dry_run` | `BooleanField` | `True` | defaults to the safe value |
| `force` | `BooleanField` | `False` | override for the destructive-content refusals in §6.6 |
| `status` | `CharField(20)` | `queued` | as `BackupJob` |
| `plan_json` | `JSONField` | `dict` | the preflight plan (§6.5) |
| `safety_backup` | `FK(BackupJob, SET_NULL, related_name="+")` | `null` | the pre-restore backup |
| `requester` | `FK(User, SET_NULL)` | `null` | |
| `created_at` / `started_at` / `completed_at` | `DateTimeField` | | |
| `error_message` | `CharField(500)` | `""` | |

**Serializer:** `RestoreJobSerializer` — all fields read-only except on create,
where `source_backup`, `target_zev_id`, `dry_run` and `force` are writable.

### 4.4 Settings

Added to `backend/config/settings.py`:

| Setting | Env | Default | Purpose |
|---|---|---|---|
| `BACKUP_ENCRYPTION_KEYS` | `env.list` | `[]` | Artifact encryption and destination-secret encryption (ADR 0024) |
| `BACKUP_S3_ACCESS_KEY_ID` | `env` | `""` | Overrides every stored S3 credential |
| `BACKUP_S3_SECRET_ACCESS_KEY` | `env` | `""` | Overrides every stored S3 credential |
| `BACKUP_WORK_DIR` | `env` | `tempfile.gettempdir()` | Where archives are assembled. Must have room for a full archive |
| `BACKUP_RUNNER_TIMEOUT_S` | `env.int` | `10800` | Soft limit; hard limit a grace above, as `EXPORT_RUNNER_TIMEOUT_S` |
| `BACKUP_LOCAL_RETENTION_DAYS` | `env.int` | `30` | Retention for artifacts staged in `MEDIA_ROOT` awaiting upload |

## 5. API contracts

Registered as `path("api/v1/backups/", include("backups.urls"))` in
`config/urls.py`. Every endpoint is `[IsAuthenticated, IsAdmin]`.

| Endpoint | Method | Behaviour |
|---|---|---|
| `/api/v1/backups/destinations/` | GET | List destinations, `name` ascending |
| `/api/v1/backups/destinations/` | POST | Create. 400 on `clean()` failure — including "a secret cannot be stored without `BACKUP_ENCRYPTION_KEYS`" and "path resolves inside MEDIA_ROOT" |
| `/api/v1/backups/destinations/{id}/` | PATCH | Update. An absent `secret_access_key` leaves the stored one intact; `""` clears it |
| `/api/v1/backups/destinations/{id}/` | DELETE | 409 when a `BackupJob` still references it and its artifact has not expired |
| `/api/v1/backups/destinations/{id}/test/` | POST | Writes and deletes a small probe object. `{"ok": true}` or 400 `{"detail"}` with a safe message. Never echoes credentials |
| `/api/v1/backups/jobs/` | GET | Newest first. Filters: `?scope=`, `?status=`, `?limit=` (≤100) |
| `/api/v1/backups/jobs/` | POST | `{scope, zev_id?, destination_id}` → 202 with the job. Persist, then enqueue after commit. A failed enqueue marks the job `failed` and returns 503 — never a 202 for a job that will not run (ADR 0017) |
| `/api/v1/backups/jobs/{id}/` | GET | Status, for polling |
| `/api/v1/backups/jobs/{id}/download/` | GET | `FileResponse` for a `local` destination whose artifact has not expired; 409 for `s3` (fetch it from the bucket) and 410 when expired |
| `/api/v1/backups/jobs/{id}/verify/` | POST | Streams the artifact, decrypts if needed, checks every manifest checksum and count. 200 `{"ok": true, "members": n}` or 400 `{"detail", "failures": [...]}`. Creates nothing |
| `/api/v1/backups/restores/` | POST | `{source_backup_id, target_zev_id, dry_run, force}` → 202. `mode` is forced to `zev`; a request naming `instance` is 400 with "Whole-instance restore is only available as a management command." |
| `/api/v1/backups/restores/{id}/` | GET | Status and `plan_json` |
| `/api/v1/backups/status/` | GET | `{last_successful: BackupJob \| null, last_failed: BackupJob \| null, age_hours: number \| null, stale: boolean, encrypted: boolean, destinations_enabled: number}` — feeds the health card |

`stale` is `age_hours > 2 × the configured schedule interval`, or `true` when a
schedule exists and no backup has ever succeeded.

## 6. Async and integration behavior

### 6.1 Archive format

`kind: "backup"`, `format_version: 1`, independent of the transfer archive's
version sequence (ADR 0023). ZIP container:

```
manifest.json
instance/
  accounts.json            User, ApiKey, TotpDevice, MfaRecoveryCode,
                           WebAuthnCredential, SocialAccount
  app_settings.json        AppSettings (singleton), FeatureFlag, VatRate
  oauth_providers.json     OAuthProvider
  templates.json           PdfTemplate, EmailTemplate
  dynamic_sources.json     DynamicTariffSource
  dynamic_prices/<source_id>.csv    DynamicPricePoint, streamed
  periodic_tasks.json      django_celery_beat schedules
zevs/<zev_uuid>/
  zev.json                 Zev (single object)
  participants.json        Participant + ParticipantOnboardingToken
  metering_points.json     MeteringPoint with nested assignments
  tariffs.json             Tariff with nested TariffPeriod
  invoices.json            Invoice + items + dynamic evidence
  contract_issues.json     ContractIssue, pdf base64-encoded
  email_logs.json          EmailLog
  import_logs.json         ImportLog
  invoice_access_tokens.json
  audit_events.json        AuditEvent for this ZEV
  readings/<meter>-<digest>.csv     MeterReading, streamed, one file per meter
  media/invoices/pdf/<filename>     the actual PDF bytes
```

Reading member names reuse the transfer archive's collision-safe scheme:
`<sanitised meter id>-<sha1(meter_id)[:8]>.csv`, with anything outside
`[A-Za-z0-9_.-]` replaced by `_`. The digest is what keeps `A/B` and `A_B` in
separate members.

**Key preservation.** Every JSON row carries its real primary key under `"id"`,
and every foreign key is written as the referenced row's real key. This is the
central difference from the transfer schema, which omits ids precisely so the
importer can mint new ones.

**`manifest.json`:**

```json
{
  "kind": "backup",
  "format_version": 1,
  "created_at": "2026-09-21T04:12:00+02:00",
  "instance_name": "openzev-prod",
  "openzev_version": "1.16.0",
  "scope": "instance",
  "migrations": {"zev": ["0001_initial", "..."], "invoices": ["..."]},
  "sections": ["instance/accounts", "zevs/<uuid>/invoices", "..."],
  "counts": {"instance/accounts": 42, "zevs/<uuid>/readings": 1051200},
  "members": {"instance/accounts.json": {"sha256": "…", "bytes": 18422}},
  "zevs": [{"id": "…", "name": "Sonnenhof", "counts": {"invoices": 96}}],
  "encryption": {"algorithm": "AES-256-GCM", "key_fingerprint": "a1b2c3d4e5f60718"},
  "secret_fingerprints": {
    "mfa_encryption_keys": ["9f8e7d6c5b4a3928"],
    "secret_key": "1122334455667788"
  }
}
```

`migrations` is the authoritative compatibility signal — `openzev_version` is
informational and may be empty, since the release version is not currently
available to the backend at runtime.

**Excluded by design** (short-lived; restoring them is worse than not):
`EmailVerificationToken`, `MagicLinkToken`, `OAuthState`, `OAuthExchangeCode`,
Django sessions, Celery broker state, and `ExportJob` artifacts (the rows travel,
the files do not).

**Schema parity.** `BackupSchemaParityTests` asserts each section's field list
equals its model's concrete fields minus an explicit
`FIELDS_EXCLUDED_FROM_BACKUP` set, the same guard
`SchemaParityTests` provides for the transfer archive. Without it, a new model
field silently stops being backed up.

### 6.2 Encryption envelope

Applied to the assembled ZIP as a whole stream, so manifest checksums describe
plaintext members (ADR 0024).

```
"OZBK1"                       5-byte magic
<uint32 header length><header JSON>
  {"algorithm": "AES-256-GCM", "key_fingerprint": "...",
   "chunk_size": 1048576, "nonce_prefix": "<8 hex bytes>"}
<chunk>*                      each: <uint32 length><ciphertext><16-byte tag>
```

- The AES key is `HKDF-SHA256(raw_key, info=b"openzev-backup-archive-v1")`, giving
  domain separation from the same key's Fernet use for destination secrets.
- Nonce per chunk = 4-byte random prefix ‖ 8-byte big-endian counter, so nonces
  are unique within an archive.
- Each chunk's AAD includes its counter and a final-chunk flag, so reordering or
  truncation fails authentication rather than yielding a short archive.
- Decryption tries each configured key whose fingerprint matches, then fails with
  a message naming the fingerprint the archive needs.

### 6.3 Backup runner — `backups.tasks.run_backup_job`

Soft time limit `BACKUP_RUNNER_TIMEOUT_S`, hard limit a 900 s grace above, matching
`exports.tasks.run_export_job`.

1. Claim the job (`status=running`, `started_at`), audit `backup.started`.
2. Open `transaction.atomic(durable=True)` and, on PostgreSQL, `SET TRANSACTION
   ISOLATION LEVEL REPEATABLE READ` — the transfer exporter's reasoning applies
   unchanged: sections are read over minutes, and READ COMMITTED would produce an
   archive of a state that never existed.
3. Write members into a `NamedTemporaryFile` in `BACKUP_WORK_DIR`, hashing each
   member as it is written. **Never into memory** — `ExportResult.payload: bytes`
   is exactly what this must not copy.
4. Stream readings and dynamic prices with `queryset.iterator()`, chunked.
5. Write `manifest.json` last, with the counts actually produced.
6. Encrypt to a second temp file when a key is configured.
7. Upload: `shutil.move` for `local`; `boto3` `upload_file` for `s3` (multipart is
   automatic above the threshold), with `ServerSideEncryption` when configured.
8. Record `archive_*`, `manifest_json`, `encrypted`, `encryption_key_fingerprint`,
   `file_expires_at`; `status=completed`; audit `backup.completed` with counts.
9. On `SoftTimeLimitExceeded` or any exception: `status=failed`, a user-safe
   `error_message`, audit `backup.failed`, the detail to the log. Temp files are
   removed in a `finally`.

Audit is best-effort via the `_audit_best_effort` pattern — a failed audit write
must never turn a completed backup into an error.

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
manage.py openzev_restore --mode instance --from <path|s3://…> [--dry-run] [--force]
```

1. **Read and verify.** Decrypt if needed; verify every member checksum and count
   against the manifest. Any mismatch aborts before a write.
2. **Compatibility preflight.**
   - `kind` must be `backup`; a transfer archive is refused by name.
   - `format_version` must be supported.
   - `migrations`: every migration in the archive must exist in the code. A backup
     containing migrations this code does not know is **newer than the code** and
     is refused — that is the unsafe direction. Code newer than the backup is
     fine; migrations run forward afterwards.
   - `secret_fingerprints.mfa_encryption_keys`: if no configured key matches,
     **warn loudly** and name the fingerprint. TOTP secrets in the archive will
     not decrypt. Proceeds — recovery codes and admin reset remain as escapes
     (ADR 0021) — but the operator learns it now, not from a locked-out user.
3. **Empty-instance guard.** Refuse when any `Zev` or non-superuser `User` exists,
   unless `--force`.
4. **Load**, inside one transaction: `migrate` to the archive's state → instance
   sections → per-ZEV sections in the transfer archive's dependency order
   (`zev`, `participants`, `metering_points`, `tariffs`, `readings`, `invoices`)
   → audit events. Primary keys are preserved throughout.
5. **Restore media** into `MEDIA_ROOT`, verifying each file's checksum.
6. **Reconcile sequences.** Integer-keyed models (`User`, `VatRate`,
   `PdfTemplate`, `EmailTemplate`, `OAuthProvider`, `FeatureFlag`,
   `InvoiceDynamicSourceEvidence`, `DynamicPricePoint`) keep their keys, so each
   sequence is set past its table's maximum — otherwise the next insert collides.
7. **Report and audit** (`source=MANAGEMENT_COMMAND`), with per-section counts.

`--dry-run` performs steps 1–3 and prints what step 4 would create, touching
nothing.

### 6.6 Per-ZEV restore — API and `--mode zev`

The destructive one. Rules, in the order they are enforced:

1. **Preflight plan** (`plan_json`), always computed, and the whole result when
   `dry_run`:

   ```json
   {
     "zev": {"id": "…", "name": "Sonnenhof", "exists_now": true},
     "sections": {
       "participants": {"create": 2, "replace": 18, "delete": 1},
       "invoices": {"create": 0, "replace": 96, "delete": 4}
     },
     "accounts": {"relink": 18, "missing": ["neu@example.com"]},
     "conflicts": [
       {"kind": "sent_invoice_deleted", "detail": "INV-2026-041 (paid)"},
       {"kind": "meter_id_owned_by_other_zev", "detail": "CH99…0859 → Bergblick"}
     ],
     "safety_backup_id": "…"
   }
   ```

2. **Refuse on conflicts** unless `force`:
   - an `Invoice` in `sent`/`paid` status that the restore would delete;
   - a `ContractIssue` that the restore would delete — documented as *"an
     immutable archive"*, and the participant's signed document;
   - a `meter_id` in the archive that now belongs to a **different** ZEV
     (`MeteringPoint.meter_id` is `unique=True` instance-wide).
   `force` is recorded on the `RestoreJob` and named in the audit event.
3. **Safety backup.** A `BackupJob` with `scope="zev"`, `trigger="pre_restore"`,
   run to completion before any write, linked as `RestoreJob.safety_backup`. A
   failed safety backup aborts the restore.
4. **Lock.** `select_for_update()` on the `Zev` row for the duration, and refuse
   when a bulk invoice generation or export job for that ZEV is `queued`/`running`
   — a restore interleaved with an invoice run is corruption.
5. **Replace**, in one transaction: delete the ZEV's current rows in reverse
   dependency order (**excluding `AuditEvent`**), then create from the archive with
   original primary keys, then restore that ZEV's invoice PDFs into `MEDIA_ROOT`.
6. **Relink accounts by natural key.** `Participant.user` and `Zev.owner` resolve
   through `User.email` (falling back to `username`). A missing account is
   reported in `plan_json.accounts.missing` and left unlinked. **No account row is
   created, modified, or deleted by a per-ZEV restore** — not a password hash, not
   an MFA device, not `session_version`.
7. **Append one audit event**, never rewrite. `action_type="zev.restored"`,
   `zev=<target>`, metadata naming the source backup, its `created_at`, the
   section counts and whether `force` was used. Existing audit rows — including
   the restored ZEV's — are untouched (ADR 0023).

## 7. Frontend

### 7.1 System Settings — `backup` tab

**File:** `frontend/src/pages/AdminSystemSettingsPage.tsx`

- `SystemSettingsTab` becomes
  `'regional' | 'features' | 'oauth' | 'security' | 'vat' | 'backup'`, appended to
  `TAB_ORDER`; `?tab=backup` selects it.
- The panel delegates to three sections, as `vat` delegates to
  `VatSettingsSection`.

### 7.2 Sections

| Component | File | Contents |
|---|---|---|
| `BackupDestinationsSection` | `frontend/src/features/backups/BackupDestinationsSection.tsx` | Destination table (name, kind, target, credential mode, encrypted, retention), create/edit modal, **Test** button. The secret field is blank on edit and only sent when filled, mirroring the OAuth provider form |
| `BackupScheduleSection` | `frontend/src/features/backups/BackupScheduleSection.tsx` | Enable/disable, crontab fields, next run time, destination selection |
| `BackupJobsSection` | `frontend/src/features/backups/BackupJobsSection.tsx` | **Back up now**, `DataTable` of jobs (created, scope, destination, status, size, encrypted, expiry), per-row Download / Verify / **Restore a community** |
| `ZevRestoreModal` | `frontend/src/features/backups/ZevRestoreModal.tsx` | Two-step: (1) pick the ZEV from `manifest_json.zevs`, submit `dry_run: true`, render the returned plan as an impact table with conflicts highlighted; (2) typed confirmation of the ZEV name, then `dry_run: false`. `force` is a separate checkbox, disabled until the plan reports a conflict |

An **unencrypted** destination is rendered with a warning badge, not a neutral
label (ADR 0024).

### 7.3 Health card

**File:** `frontend/src/pages/AdminSystemHealthPanel.tsx` — a "Last successful
backup" card reading `/api/v1/backups/status/`: relative age, destination, and a
warning state when `stale` or when no backup has ever succeeded.

### 7.4 TypeScript types

**File:** `frontend/src/types/api.ts`

```typescript
export type BackupDestinationKind = 'local' | 's3'
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
    server_side_encryption: string
    retention_count: number
    credential_mode: BackupCredentialMode
    /** The secret is never returned; this reports whether one is stored. */
    has_secret_access_key: boolean
    created_at: string
    updated_at: string
}

export interface BackupJob {
    id: string
    scope: BackupJobScope
    zev_id: string | null
    trigger: BackupJobTrigger
    destination_id: string | null
    destination_name: string
    status: BackupJobStatus
    created_at: string
    started_at: string | null
    completed_at: string | null
    archive_name: string
    archive_location: string
    archive_bytes: number | null
    archive_sha256: string
    encrypted: boolean
    encryption_key_fingerprint: string
    manifest_json: BackupManifest | Record<string, never>
    error_message: string
    file_expires_at: string | null
    expired: boolean
}

export interface BackupManifestZev {
    id: string
    name: string
    counts: Record<string, number>
}

export interface BackupManifest {
    kind: 'backup'
    format_version: number
    created_at: string
    instance_name: string
    openzev_version: string
    scope: BackupJobScope
    counts: Record<string, number>
    zevs: BackupManifestZev[]
    encryption: { algorithm: string; key_fingerprint: string } | null
}

export interface RestorePlanSection {
    create: number
    replace: number
    delete: number
}

export interface RestorePlanConflict {
    kind: string
    detail: string
}

export interface RestoreJob {
    id: string
    mode: BackupJobScope
    target_zev_id: string | null
    target_zev_name: string
    source_backup_id: string | null
    dry_run: boolean
    force: boolean
    status: BackupJobStatus
    plan_json: {
        zev?: { id: string; name: string; exists_now: boolean }
        sections?: Record<string, RestorePlanSection>
        accounts?: { relink: number; missing: string[] }
        conflicts?: RestorePlanConflict[]
        safety_backup_id?: string
    }
    safety_backup_id: string | null
    created_at: string
    started_at: string | null
    completed_at: string | null
    error_message: string
}

export interface BackupStatus {
    last_successful: BackupJob | null
    last_failed: BackupJob | null
    age_hours: number | null
    stale: boolean
    encrypted: boolean
    destinations_enabled: number
}
```

### 7.5 API client and query keys

**File:** `frontend/src/lib/api/backups.ts`

| Function | Method | Endpoint |
|---|---|---|
| `fetchBackupDestinations()` | GET | `/backups/destinations/` |
| `createBackupDestination(input)` | POST | `/backups/destinations/` |
| `updateBackupDestination(id, input)` | PATCH | `/backups/destinations/{id}/` |
| `deleteBackupDestination(id)` | DELETE | `/backups/destinations/{id}/` |
| `testBackupDestination(id)` | POST | `/backups/destinations/{id}/test/` |
| `fetchBackupJobs(params?)` | GET | `/backups/jobs/` |
| `createBackupJob(input)` | POST | `/backups/jobs/` |
| `fetchBackupJob(id)` | GET | `/backups/jobs/{id}/` |
| `downloadBackupArtifact(id)` | GET | `/backups/jobs/{id}/download/` (blob) |
| `verifyBackupArtifact(id)` | POST | `/backups/jobs/{id}/verify/` |
| `createRestoreJob(input)` | POST | `/backups/restores/` |
| `fetchRestoreJob(id)` | GET | `/backups/restores/{id}/` |
| `fetchBackupStatus()` | GET | `/backups/status/` |

**File:** `frontend/src/lib/api/queryKeys.ts`

```typescript
backups: {
    destinations: () => ['backups', 'destinations'] as const,
    jobs: (scope?: string, status?: string) =>
        ['backups', 'jobs', scope ?? 'all', status ?? 'all'] as const,
    job: (id: string) => ['backups', 'job', id] as const,
    restore: (id: string) => ['backups', 'restore', id] as const,
    status: () => ['backups', 'status'] as const,
},
```

Running or queued jobs poll their detail key; completing invalidates
`backups.jobs()` and `backups.status()`.

### 7.6 i18n

All strings under `pages.backups.*` in
`frontend/src/i18n/locales/{de,en,fr,it}.ts`. No hardcoded user-facing text.
The confirmation copy must name the community and state that current data will be
replaced.

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
| A model field is added and silently stops being backed up | Medium | `BackupSchemaParityTests`, mirroring the transfer archive's guard |
| Restoring a backup restores a credential set — an attacker who plants one gains accounts | Critical | Instance restore is CLI-only (host access required); per-ZEV restore never touches accounts; every restore is audited |
| Sequence collision after an instance restore | Medium | Explicit sequence reconciliation for every integer-keyed model (§6.5 step 6), asserted by test |

## 9. Test plan

### Backend — `backend/backups/`

**`test_destinations.py` — `BackupDestinationTests`** (planned, 12):

| Test | Asserts |
|---|---|
| `test_local_destination_requires_a_path` | `clean()` rejects an empty path |
| `test_local_path_inside_media_root_is_rejected` | An archive cannot be written where media is served |
| `test_s3_destination_requires_a_bucket` | `clean()` rejects an empty bucket |
| `test_kind_specific_fields_are_mutually_exclusive` | S3 fields on a `local` row are rejected, and the reverse |
| `test_storing_a_secret_without_an_encryption_key_is_rejected` | `set_secret_access_key` raises when `BACKUP_ENCRYPTION_KEYS` is empty |
| `test_secret_round_trips_through_encryption` | `secret_access_key` returns what was set; the column holds ciphertext |
| `test_environment_credentials_take_precedence_over_stored` | `credential_mode == "environment"` when both are present |
| `test_instance_role_when_no_credentials_anywhere` | `credential_mode == "instance_role"` |
| `test_serializer_never_returns_the_secret` | Response has `has_secret_access_key`, no `secret_access_key` |
| `test_patch_without_a_secret_keeps_the_stored_one` | Absent field is not a clear |
| `test_patch_with_an_empty_secret_clears_it` | `""` clears |
| `test_delete_refused_while_an_unexpired_artifact_references_it` | 409 |

**`test_archive.py` — `ArchiveShapeTests`** (planned, 14): manifest present and
well-formed; one CSV per meter; collision-safe member names; a meter id with a
path separator cannot escape `readings/`; primary keys are preserved in every
section; invoice PDFs travel as media members; `ContractIssue.pdf` travels
base64-encoded; instance sections present for a `scope="instance"` archive and
absent for `scope="zev"`; excluded models are absent; manifest counts equal the
rows written; per-member SHA-256 matches; `secret_fingerprints` present and no
key material anywhere in the archive; `kind == "backup"`.

**`test_archive.py` — `EncryptionEnvelopeTests`** (planned, 8): round-trips a
multi-chunk archive; a truncated archive fails authentication; a reordered chunk
fails; the wrong key is refused with the required fingerprint named; an archive
written with an old key still decrypts after rotation; no key configured produces
a readable ZIP; `encrypted`/`encryption_key_fingerprint` recorded on the job;
memory stays bounded for an archive larger than the chunk size.

**`test_archive.py` — `BackupSchemaParityTests`** (planned, 2):
`test_field_lists_match_their_models_exactly` over every section/model pair; and
`test_reading_csv_columns_exist_on_the_reading_model`.

**`test_backup_runner.py` — `BackupRunnerTests`** (planned, 10): a completed job
records location, size, checksum and manifest; a failed enqueue marks the job
`failed` and never leaves it `queued`; a soft time limit is recorded as a clean
failure; temp files are removed on both paths; readings stream rather than
materialise; the runner refuses to run inside an outer transaction (the
`durable=True` guard); audit events fire for started/completed/failed; an audit
failure does not fail the job; the sweep deletes expired artifacts and keeps
`retention_count`; the sweep fails a job whose worker died.

**`test_restore_instance.py` — `InstanceRestoreTests`** (planned, 12): a full
round trip reproduces every section with identical primary keys; invoice PDFs are
back on disk; the audit trail is restored; sequences are past each table's
maximum, and a subsequent insert succeeds; a transfer archive is refused by
`kind`; an unknown `format_version` is refused; a backup with unknown migrations
is refused; a backup older than the code is accepted and migrated forward; a
non-empty instance is refused without `--force`; an MFA fingerprint mismatch warns
and names the fingerprint; a checksum mismatch aborts before any write;
`--dry-run` creates nothing.

**`test_restore_zev.py` — `ZevRestoreTests`** (planned, 16): the plan reports
create/replace/delete per section; `dry_run` changes nothing; a ZEV is returned to
its archived state; other ZEVs are untouched; **no account row is created,
modified or deleted**; participants relink by email; a missing account is reported
and left unlinked; a `sent` invoice that would be deleted is refused without
`force`; a `paid` invoice likewise; a `ContractIssue` likewise; `force` proceeds
and is recorded in the audit event; a meter id owned by another ZEV is refused; a
safety backup is created before any write and linked; a failed safety backup
aborts the restore; existing audit rows survive, including the restored ZEV's; one
`zev.restored` event is appended.

**`test_api.py` — `BackupApiTests`** (planned, 14): every endpoint is admin-only
(403 for `zev_owner`, `participant`, anonymous); job creation returns 202 and
enqueues after commit; a broker failure returns 503; download serves a local
artifact and 409s an S3 one; an expired artifact returns 410; verify reports
failures without creating anything; a restore request naming `mode: "instance"`
is refused with the CLI message; `/status/` reports staleness.

Planned total: **88 backend tests** across seven modules.

### Frontend

- Unit tests (`npm run test:unit`):
  `frontend/tests/backup-destination-form.test.ts` — the secret field is blank on
  edit, omitted when untouched, and sent when filled;
  `frontend/tests/zev-restore-modal.test.ts` — the confirm button stays disabled
  until the typed name matches, `force` is disabled until the plan reports a
  conflict, and a plan with conflicts renders them.
- Build and type checks: `npm run build`, `npm run lint`, `npm run lint:style`,
  `node ../scripts/check-frontend-hex.mjs`.
- Manual: the `backup` tab at a ~400 px viewport.

### Acceptance criteria

- [ ] A scheduled backup runs unattended to local and/or S3-compatible storage, with a SHA-256 manifest, encrypted whenever `BACKUP_ENCRYPTION_KEYS` is set
- [ ] With no key set, the backup still runs and both the CLI and the admin UI say the archive is unencrypted
- [ ] A destination secret stored in the database is encrypted at rest, never serialized, and overridden by environment credentials
- [ ] A fresh install restores to a working instance from a backup alone — accounts, settings, templates, dynamic price series, invoice PDFs, issued contracts and the audit trail all present and linked, with primary keys preserved
- [ ] An existing install restores one ZEV to its backed-up state without touching other ZEVs, any account row, or any existing audit row — and the restore itself appears in the log
- [ ] Both restore modes support `--dry-run` / `dry_run` reporting exactly what would change
- [ ] Restore refuses on schema mismatch, checksum failure, wrong archive `kind`, and (without `force`) on dropping `sent`/`paid` invoices or contract issues
- [ ] An MFA key fingerprint mismatch is reported at preflight, not discovered by a locked-out user
- [ ] "Last successful backup" is visible to admins and goes stale loudly
- [ ] `BackupSchemaParityTests` passes, so a new model field cannot silently stop being backed up
- [ ] User-guide chapter written, including a restore drill; the `12-troubleshooting.md` snippet is replaced
- [ ] `ROADMAP.md` updated
