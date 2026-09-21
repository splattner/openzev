# ADR 0024: Backup artifacts are encrypted under a dedicated, optional key

- Status: Accepted
- Date: 2026-09-21

## Context

A backup archive ([ADR 0023](0023-backup-archives-preserve-keys.md)) is the most
sensitive artifact the platform produces. It contains, in one file:

- `OAuthProvider.client_secret` — stored as a plain `CharField`, in clear
- Every `User` password hash, `ApiKey` hash and `MfaRecoveryCode` hash
- Every `TotpDevice.secret_encrypted` — Fernet ciphertext, safe only while
  `MFA_ENCRYPTION_KEYS` stays out of the archive ([ADR 0021](0021-mfa-secret-encryption-key.md))
- Full participant PII: names, postal addresses, email addresses, consumption
  profiles at 15-minute resolution
- Every generated invoice PDF and every issued participation contract

Unlike the artifacts the platform already writes, a backup is *designed to leave
the instance*: copied to an operator's laptop, pushed to an S3 bucket, retained
for months. Media-storage access control stops protecting it the moment it is
uploaded.

Two existing key mechanisms could plausibly be reused. `SECRET_KEY` is Django's
signing key, used for sessions and tokens; ADR 0021 already rejected overloading
it for encryption at rest, because rotating it signs everyone out and cannot be
staged. `MFA_ENCRYPTION_KEYS` is a purpose-built Fernet key list with
`MultiFernet` rotation — but it protects TOTP secrets *inside* the database, and
its ciphertext is one of the things a backup carries.

## Decision

Backup artifacts are encrypted under **`BACKUP_ENCRYPTION_KEYS`**: a dedicated,
optional, rotatable key list, separate from both `SECRET_KEY` and
`MFA_ENCRYPTION_KEYS`.

- **Separate from `MFA_ENCRYPTION_KEYS`.** Different blast radius and different
  lifetime. A key that has been copied to a backup host, a CI runner and an
  operator's password manager must not also be the key that decrypts every TOTP
  secret in the live database. Rotating one must not force re-encrypting the
  other.
- **A list, like the MFA keys.** The first entry encrypts; every entry can
  decrypt. This gives the same staged rotation `accounts/mfa_crypto.py` already
  implements — add the new key, take fresh backups, retire the old key once no
  retained archive needs it.
- **Optional.** With no key configured, archives are written in clear and backup
  still runs. An instance whose operator has not yet provisioned a key is better
  served by an unencrypted backup than by no backup.
- **The unencrypted path is loud, not quiet.** The management command prints a
  warning, the admin UI marks the destination as unencrypted, `BackupJob.encrypted`
  records it per artifact, and the user guide leads with what an unencrypted
  archive contains. "Optional" must never read as "fine by default".
- **The key is never in the archive, and neither is any other instance secret.**
  The manifest records **fingerprints** — the first 16 hex characters of the
  SHA-256 of each configured `MFA_ENCRYPTION_KEYS` entry and of `SECRET_KEY` — so
  a restore can tell the operator *"this backup's TOTP secrets were encrypted
  under a key this instance does not have"* before anyone is locked out. A
  fingerprint identifies a key; it does not help recover one.
- **Chunked AES-256-GCM, not Fernet.** Fernet requires the entire message in
  memory to encrypt or decrypt, which is unusable for a multi-gigabyte archive.
  The archive is encrypted as a whole stream after ZIP assembly: a `OZBK1` magic,
  a JSON header naming the algorithm, key fingerprint, chunk size and nonce
  prefix, then a sequence of independently authenticated chunks. Manifest
  checksums therefore describe the plaintext members, and verification is
  decrypt-then-check.

## Consequences

Positive:

- An archive that leaks from a bucket, a laptop or a retired disk is ciphertext,
  provided a key was configured.
- Rotation is staged and independent: a compromised backup key is replaced without
  touching logins, sessions or TOTP enrolment.
- The fingerprint turns the worst failure mode — restoring onto an instance with a
  different `MFA_ENCRYPTION_KEYS`, discovering it when users cannot log in — into a
  preflight error with an actionable message.
- Chunked GCM means encryption costs bounded memory regardless of archive size,
  and a corrupted chunk is detected at that chunk rather than after streaming the
  whole file.

Trade-offs:

- **One more backup-critical secret.** Losing `BACKUP_ENCRYPTION_KEYS` makes every
  encrypted archive unrecoverable — a worse outcome than losing
  `MFA_ENCRYPTION_KEYS`, which costs TOTP enrolment but not the data. The user
  guide must treat it as a key to escrow, not a key to generate and forget.
- **Optional means the insecure path exists.** A hurried operator gets plaintext
  PII in a bucket. Mitigated by loud warnings rather than by removing the choice,
  because forcing key provisioning before any backup can run is how instances end
  up with no backups at all.
- **Hand-rolled chunk framing.** Small, but it is envelope code that must be got
  right: nonce uniqueness per chunk, authenticated chunk ordering, and a final
  chunk marker so truncation cannot pass verification.
- **Verification requires the key.** An operator cannot check an encrypted
  archive's integrity without being able to decrypt it.

## Alternatives considered

1. **Reuse `MFA_ENCRYPTION_KEYS`.**
   - No new secret to provision, and the `MultiFernet` plumbing already exists.
   - Rejected: it puts the key that protects live TOTP secrets onto every host
     that handles backups, and couples two rotation schedules that have nothing to
     do with each other. ADR 0021's reasoning against overloading `SECRET_KEY`
     applies again here.

2. **Mandatory encryption.**
   - Removes the insecure path entirely.
   - Rejected: a backup that refuses to run is not safer than an unencrypted one.
     The realistic outcome is an operator who postpones backups until "later",
     which is the failure this feature exists to prevent. Loud warnings, and a
     spec-level question about whether *remote* destinations should require a key,
     carry the risk instead.

3. **Delegate to storage-side encryption only (S3 SSE, encrypted volumes).**
   - Zero application code, and operators running on managed object storage get it
     free.
   - Rejected as the only mechanism: it protects the bytes at rest in *that* store
     and nowhere else — not the copy downloaded through the admin UI, not the file
     on the operator's laptop, not the artifact staged in `MEDIA_ROOT` before
     upload. SSE is still required for S3 destinations, as defence in depth.

4. **age or GPG as an external tool.**
   - Well-reviewed formats, streaming, standard key management and no envelope
     code to write.
   - Rejected for the default path: it adds a runtime binary to the backend and
     worker images and to every deployment shape, for an envelope this codebase
     can express in a few dozen lines against `cryptography`, which is already a
     direct dependency. Worth revisiting if key management grows beyond a key
     list — an `age` recipient per operator is a better story than a shared
     symmetric key.

## Notes

- Key generation for the docs: `python -c "import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"`.
- `BACKUP_ENCRYPTION_KEYS` is read with `env.list(...)`, matching
  `MFA_ENCRYPTION_KEYS` in `backend/config/settings.py`.
- Destination credentials (S3 access keys) are a different secret with a different
  lifetime and are not covered here; their storage rules are in
  [SPEC-2026-09-backup-and-restore](../specs/2026-09-backup-and-restore.md) §4.2.
- A Django system check warns when a scheduled backup is configured with no
  encryption key (`backups.W001`, in `backups/checks.py`). It is tagged `database`,
  since the schedule lives in the database, so it runs under `manage.py check
  --database default` and not in an ordinary `check`.
- Whether a *remote* destination should refuse to run without a key is still open;
  encryption remains optional and loud.
