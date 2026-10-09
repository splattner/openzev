# ADR 0031: Third-party integration credentials are encrypted under a dedicated, rotatable key

- Status: Accepted
- Date: 2026-10-08

## Context

[SPEC-2026-supplementary-energy-data](../specs/2026-10-supplementary-energy-data.md) lets a
participant connect their own Solar Manager account. OpenZEV then holds a credential for a
system outside its control: a Solar Manager API key, which the vendor treats as a **refresh
token**. Per the vendor's API (`POST /v3/auth/refresh`), exchanging it yields a one-hour bearer
token, and with key rotation enabled each exchange issues a **new** refresh token, valid 30
days, and invalidates the previous one. So the credential is not static: it is rewritten by
the platform after every refresh, and the stored value must always be the latest.

Like a TOTP secret, it cannot be hashed; the server must read it back to use it. The platform
already has two Fernet key lists with `MultiFernet` rotation:

- `MFA_ENCRYPTION_KEYS` ([ADR 0021](0021-mfa-secret-encryption-key.md)) protects TOTP secrets.
- `BACKUP_ENCRYPTION_KEYS` ([ADR 0024](0024-backup-encryption-key.md)) protects backup
  artifacts and destination secrets, and is deliberately a key that travels to backup hosts.

Reusing either would couple unrelated blast radii. A connector credential is rewritten every
few days or hours; a backup key is copied to laptops and buckets; an MFA key must stay inside
the live instance. ADR 0024 already rejected sharing a key across those two for that reason.

## Decision

Connector credentials are encrypted under a third dedicated setting,
**`INTEGRATION_ENCRYPTION_KEYS`**: a list of Fernet keys consumed through
`cryptography.fernet.MultiFernet` (first key encrypts, every key decrypts).

- **Independent of `SECRET_KEY`, `MFA_ENCRYPTION_KEYS` and `BACKUP_ENCRYPTION_KEYS`**, and never
  derived from any of them.
- **The crypto lives in `metering/supplementary/crypto.py`**, mirroring `accounts/mfa_crypto.py`
  (`encrypt_secret`, `decrypt_secret`, `NotConfigured`, `KeyError`), and
  `manage.py rotate_integration_key` re-encrypts every stored credential with the first key,
  idempotently, in one transaction.
- **Optional, and it only disables what needs it.** When unset, pull sources (Solar Manager)
  cannot be created: the API answers `503` naming the setting, and a system check and the
  system-health view report it. The push endpoint and file import store no reversible secret
  (the push token is hashed one-way, like `ApiKey`) and keep working. There is no fallback to
  another key and no plaintext path.
- **The key is never in a backup or an export.** Backups carry the ciphertext, as they do for
  TOTP secrets; the manifest records the key's fingerprint
  (`secret_fingerprints.integration_encryption_keys`) so a restore can say *"these sources were
  encrypted under a key this instance does not have"* before anyone finds out the hard way. A
  source whose credential cannot be decrypted becomes `reconnect_required`; the participant
  enters the key again. Transfer archives carry no credentials at all.
- **Credential writes are serialised.** A refresh that rotates the token is performed under a
  row lock (`select_for_update`) on the source, and the new token is persisted before the
  bearer token is used. A refresh response that cannot be saved is treated as a failed
  refresh, not a success, because the old token is already dead.
- **The credential is write-only through the API.** It is never serialized, logged, audited
  (the audit metadata records `credential_changed`, not the value) or echoed in an error.

## Consequences

Positive:
- Rotating or leaking any of the other keys does not touch connector credentials, and the
  reverse.
- A missing key is loud and early: at connection time, naming the setting.
- A lost key costs one re-connect per participant, not an outage of the feature.

Trade-offs:
- A third secret to provision and back up, on top of two existing ones. Documented in
  `.env.example`, `.env.production.example` and the Helm values.
- A deployment that never sets it cannot offer the Solar Manager source.
- Token rotation makes the credential row hot. The lock and the per-source Celery lease
  (spec §6.3) mean at most one refresh runs per source at a time, at the cost of a skipped tick
  when one is already in flight.

## Alternatives considered

1. **Reuse `MFA_ENCRYPTION_KEYS`.**
   Rejected. A key that must stay in the live instance would also unlock credentials that
   change on a different schedule, and rotating one would force rotating the other.
2. **Reuse `BACKUP_ENCRYPTION_KEYS`** (as backup destination secrets do).
   Rejected. That key is designed to leave the instance; the destination secrets can accept
   that because they are the backup system's own concern. Participant credentials are not.
3. **Store nothing and ask for the key on each sync.**
   Rejected: background sync is the point, and a participant would have to be present every
   15 minutes.
4. **Encrypt under `SECRET_KEY`.**
   Rejected for the reasons in ADR 0021.
