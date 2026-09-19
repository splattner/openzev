# ADR 0021: MFA secrets are encrypted under a dedicated, rotatable key, not `SECRET_KEY`

- Status: Proposed
- Date: 2026-09-19

## Context

`docs/specs/2026-09-two-factor-authentication.md` introduces TOTP. Unlike every other credential
the platform stores, a TOTP secret cannot be hashed: verification recomputes the code from the
shared secret, so the server must be able to read it back. API keys
(`accounts/api_keys.py`) and the new MFA recovery codes are hashed one-way, which is both
sufficient and correct for them. Exactly one field — `TotpDevice.secret` — needs reversible
encryption at rest, because a database dump containing plaintext TOTP secrets is not meaningfully
better than having no second factor at all.

That raises a question with no obvious default: which key encrypts it?

Django already requires `SECRET_KEY`, which is present in every deployment and needs no new
configuration. Reaching for it is the path of least resistance, and it is the wrong one.

`SECRET_KEY` is designed to be **rotated**. Django ships `SECRET_KEY_FALLBACKS` specifically so
an operator can rotate it and keep existing sessions and signed tokens valid through the
changeover, and rotating it is the standard response to a suspected leak — the exact incident
where an operator is most likely to act quickly.

Everything `SECRET_KEY` currently protects in OpenZEV is *ephemeral*: session signatures, CSRF
tokens, password-reset and magic-link signatures. Rotating it costs users a re-login. A TOTP
secret is *durable state* with no other copy on the server, so encrypting it under the same key
would silently change what rotation means.

## Decision

Encrypt `TotpDevice.secret` under a dedicated setting, `MFA_ENCRYPTION_KEYS`, which is
independent of `SECRET_KEY` and never derived from it.

- The setting is a **list** of Fernet keys, consumed through
  `cryptography.fernet.MultiFernet`: the first key encrypts, every key is tried on decrypt.
  Rotation is therefore prepend-new, re-encrypt, drop-old, with no window in which stored
  secrets are unreadable.
- `manage.py rotate_mfa_key` re-encrypts every device with the first configured key in one
  transaction. It is idempotent and safe to re-run.
- The crypto lives in `accounts/mfa_crypto.py`, separate from `models.py`, for the reason
  `api_keys.py` is separate: the choices belong in one readable file rather than scattered
  across model methods.
- **When unset**, enrolment is refused with `503` naming the setting, `AppSettings.clean()`
  refuses a non-empty `mfa_required_roles`, a Django system check warns (CI already runs
  `manage.py check`), and `SystemHealthView` reports it. There is deliberately no fallback to
  `SECRET_KEY` and no plaintext path.
- Recovery codes stay hashed and WebAuthn public keys stay unencrypted. The encrypted surface is
  exactly one field.

## Consequences

Positive:
- `SECRET_KEY` rotation stays a routine, low-consequence action. An operator responding to a
  suspected leak does not also have to reason about whether they are about to lock every
  administrator out of their second factor.
- Key rotation for MFA becomes a deliberate, supported operation with a command behind it,
  rather than an accident with no recovery path.
- The failure mode when the key is missing is loud and early — at enrolment, naming the
  setting — instead of silent and late.

Trade-offs:
- One more secret to provision, and a **backup-critical** one: losing `MFA_ENCRYPTION_KEYS`
  without a backup makes every enrolled TOTP secret undecryptable. Recovery codes and
  administrator reset remain as escapes, but the blast radius is every 2FA user at once. This is
  documented in the spec's risk table and in the Helm values.
- MFA cannot be enabled on a deployment that has not configured it. This is intended: the
  alternative is a weaker guarantee that nobody notices.
- Adds `cryptography` as an explicit dependency. It arrives transitively with `py_webauthn`
  anyway, but is pinned directly because encryption at rest depends on it.

## Alternatives considered

1. **Encrypt under `SECRET_KEY`.**
   Rejected. It couples a durable secret to a key whose whole design assumes rotation, turning
   routine hygiene into a mass lockout — and doing so precisely when an operator is rotating in
   response to a compromise, so the incident is made worse by the act of containing it.
   `SECRET_KEY_FALLBACKS` does not help: it is a Django-internal mechanism for Django's own
   signers, not something a custom Fernet path participates in for free.

2. **Derive a distinct key from `SECRET_KEY` with HKDF.**
   Rejected. It avoids new configuration but keeps the coupling that is the actual problem: the
   derived key changes when `SECRET_KEY` changes, so rotation still orphans every stored secret.
   It also *looks* safer than option 1 while behaving identically, which is worse than option 1
   being obviously wrong.

3. **Store the secret in plaintext.**
   Rejected. It makes a database dump equivalent to a full 2FA bypass for every enrolled user,
   which defeats the purpose of adding the factor.

4. **Application-level envelope encryption with an external KMS.**
   Deferred. Correct for a managed multi-tenant deployment, but this is self-hosted software
   whose operators run Docker Compose or a Helm chart against their own Postgres; requiring a
   KMS would exclude most of them. The `MultiFernet` key list is the same shape a KMS-backed
   provider would slot into later.

5. **Use Django's `Signer` instead of Fernet.**
   Rejected. Signing proves integrity, not confidentiality — the secret would still be readable
   in the dump.

## Notes

Implementation: `docs/specs/2026-09-two-factor-authentication.md` §4.5 (the crypto module and
settings), §4.1 (`TotpDevice`), §8 (risk table) and §9 (`MfaCryptoTests`, including a rotation
round-trip). Delivered in that spec's PR 1, before any user-visible MFA surface exists. The
authentication-model side of the same feature is ADR 0020.
