# Feature Spec: Two-factor authentication — TOTP and passkeys

- Spec ID: SPEC-2026-09-two-factor-authentication
- Status: Implemented (all three PRs — see §10)
- Scope: Major
- Type: Feature
- Owners: @splattner
- Created: 2026-09-19
- Target Release: 1.16.0 (staged over three PRs)
- Related Issues: [#740](https://github.com/splattner/openzev/issues/740)
- Related ADRs: [ADR 0020](../adr/0020-passkeys-replace-the-password.md) (a verified passkey replaces the password), [ADR 0021](../adr/0021-mfa-secret-encryption-key.md) (the MFA encryption key is independent of `SECRET_KEY`)
- Impacted Areas: backend | frontend | docs

---

## 1. Problem and outcome

A password is currently the only thing between an attacker and a full admin session. There is
no second factor of any kind: `grep -ril "webauthn\|passkey\|totp" backend/ frontend/src`
returns nothing, and `backend/requirements.txt` carries no MFA dependency.

For an instance holding metering data, IBANs, participant addresses and the authority to issue
invoices, a single stolen or reused password is the whole attack. The roadmap carries
*"Two-factor authentication (TOTP)"* as `idea`/`medium`
([ROADMAP.md](../ROADMAP.md?plain=1#L236)).

**Outcome.** A user can protect their account with a passkey (which replaces the password
entirely) or with TOTP (which is checked after it). An administrator can require either for
privileged roles, reset a locked-out user's factor, and read the whole enrolment and challenge
history out of the audit log.

### What the roadmap line understates

The password form is not the only door. `set_auth_cookies` — the call that turns a request into
an authenticated session — is reached from **seven** places that constitute authentication.
An eighth, `CookieTokenRefreshView` ([views.py:135](../../backend/accounts/views.py#L135)),
renews an existing session rather than creating one.

| # | Call site | Endpoint | Credential presented | §2 treatment |
|---|---|---|---|---|
| 1 | [views.py:75](../../backend/accounts/views.py#L75) | `POST /token/` | password | challenged |
| 2 | [views.py:610](../../backend/accounts/views.py#L610) | `POST /verify-email/` | emailed token | unaffected |
| 3 | [views.py:664](../../backend/accounts/views.py#L664) | `POST /me/set-initial-password/` | emailed token | unaffected |
| 4 | [views_oauth.py:508](../../backend/accounts/views_oauth.py#L508) | `POST /oauth/token-exchange/` | IdP assertion | IdP owns it |
| 5 | [invoices/views_public.py:273](../../backend/invoices/views_public.py#L273) | magic-link consume | emailed magic link | challenged |
| 6 | [zev/views_public.py:80](../../backend/zev/views_public.py#L80) | onboarding-link consume | emailed onboarding link | challenged |
| 7 | [views_impersonation.py:138](../../backend/accounts/views_impersonation.py#L138) | `POST /users/<id>/impersonate/` | an existing admin session | not challenged |

A second factor bolted onto (1) alone would be close to decorative: four of the remaining six
mint a session from **possession of an email**, which is exactly the factor an attacker who has
phished a password most plausibly also has.

### Already shipped

**Part 0 — `auth.*` audit events — is done** (PR #741, released in 1.15.0).
`CustomTokenObtainPairView.post` records `auth.login` on success and `auth.login_failed` on
every failure. This spec extends that namespace rather than establishing it.

---

## 2. Scope

### In scope

| Area | Details |
|---|---|
| Data model | `TotpDevice`, `WebAuthnCredential`, `MfaRecoveryCode`; two `AppSettings` policy fields |
| Crypto | Fernet encryption of the TOTP secret under a dedicated, rotatable key set |
| Login flow | Two-step password login; passwordless passkey login |
| Enrolment | TOTP enrol/confirm/remove, passkey register/remove, recovery-code issue/regenerate |
| Policy | Per-role requirement with a grace period and a forced-enrolment interstitial |
| Admin | Reset another user's factors, audited |
| Audit | `auth.mfa.*` and `auth.passkey.*` action types; `method` metadata on `auth.login` |
| Throttling | A per-**account** budget on the challenge endpoint |
| Frontend | Enrolment UI, login challenge step, recovery-code display, admin policy control, 4 locales |
| Docs | User-guide chapter; update §5.1 of `2026-03-community-and-access.md`; flip the ROADMAP row |

### Out of scope

- **Step-up re-authentication** for high-consequence admin actions (impersonation, settings
  writes, destructive deletes). Related, and the natural follow-up, but a separate mechanism
  with its own decisions. Tracked separately.
- **SMS or email OTP as a factor.** Email is already a session-minting credential here (doors
  5 and 6); adding it as a "second" factor would be circular.
- **Per-ZEV MFA policy.** Authentication is account-scoped, not community-scoped (§3).
- **Hardware-attestation enforcement** (requiring a specific authenticator vendor).
- **Passkey autofill / conditional UI** (`mediation: "conditional"`). A deliberate v2 item.

---

## 3. Actors, permissions, and ZEV scope

MFA belongs to the **account**, not to a community. A user with memberships in three ZEVs has
one set of factors, and the audit events carry `zev = None` — so, exactly as with `auth.login`
today, they are visible only in the platform-wide log at **Platform administration → Overview →
Audit Logs**, never in a ZEV owner's community-scoped tab (`_base_queryset` filters non-admins
by `zev__owner=request.user`, [audit/views.py:33](../../backend/audit/views.py#L33)).

| Actor | Capability |
|---|---|
| `admin` | Enrol own factors; set the policy; reset **any** user's factors; read all `auth.mfa.*` events |
| `zev_owner` | Enrol and remove own factors; cannot see or reset another user's |
| `participant` | Enrol and remove own factors |
| `guest` | Enrol and remove own factors |

Backend permission classes: `IsAuthenticated` for every `/me/mfa/**` route; `IsAdmin`
([accounts/permissions.py](../../backend/accounts/permissions.py)) for the reset route and the
policy fields on `AppSettings`. The challenge and passkey-authentication routes are `AllowAny`
by necessity — the caller is not yet authenticated.

Frontend: enrolment lives on `/account` (`AccountProfilePage`, all roles); the policy control
lives on `/admin/system-settings` (`ProtectedRoute` role `admin`).

---

## 4. Data model

### 4.1 `TotpDevice`

**Model:** `accounts.models.TotpDevice`

One device per user — a second TOTP app is not a meaningfully different factor, and the
duplicate-secret handling is not worth the surface.

| Field | Type | Default | Constraints / Notes |
|---|---|---|---|
| `id` | `UUIDField` | `uuid4` | Primary key, non-editable |
| `user` | `OneToOneField(User, CASCADE)` | — | `related_name="totp_device"` |
| `secret_encrypted` | `BinaryField` | — | Fernet token over the base32 secret (§4.5) |
| `confirmed_at` | `DateTimeField` | `null` | Null until a code is verified; an unconfirmed device never gates login |
| `last_used_step` | `BigIntegerField` | `null` | Replay guard: the TOTP step counter last accepted |
| `created_at` | `DateTimeField` | `auto_now_add` | |

**Key methods**

- `secret` (property) → `str`: decrypts `secret_encrypted` via `MultiFernet.decrypt`. Raises
  `MfaKeyError` when no configured key can decrypt it.
- `set_secret(value: str)`: encrypts with the **first** configured key.
- `verify(code: str) -> bool`: `pyotp.TOTP(secret).verify(code, valid_window=MFA_TOTP_SKEW)`.
  On success, the matched step must be **strictly greater** than `last_used_step`, and
  `last_used_step` is written in the same transaction under `SELECT … FOR UPDATE` — so a code
  cannot be replayed inside its own validity window. This mirrors the row-locking approach
  taken for invoice transitions (`2026-03-invoice-lifecycle-and-communication.md` §5.3).
- `is_active` (property) → `bool`: `confirmed_at is not None`.

**Serializer:** `TotpDeviceSerializer` — fields: `id`, `confirmed_at`, `created_at`
(all read-only). **The secret is never serialized**, in any form, on any route.

### 4.2 `WebAuthnCredential`

**Model:** `accounts.models.WebAuthnCredential`

Many per user, deliberately — a lost phone must not be a lockout.

| Field | Type | Default | Constraints / Notes |
|---|---|---|---|
| `id` | `UUIDField` | `uuid4` | Primary key |
| `user` | `ForeignKey(User, CASCADE)` | — | `related_name="webauthn_credentials"` |
| `credential_id` | `BinaryField` | — | `unique=True`; the raw credential ID from the authenticator |
| `public_key` | `BinaryField` | — | COSE-encoded public key. **Public — not encrypted** |
| `sign_count` | `BigIntegerField` | `0` | Monotonic counter; a decrease signals a cloned authenticator |
| `transports` | `JSONField` | `list` | e.g. `["internal", "hybrid"]`, used to hint the browser |
| `aaguid` | `CharField(36)` | `""` | Authenticator model identifier, for display |
| `name` | `CharField(100)` | `""` | User-chosen nickname ("MacBook Touch ID") |
| `created_at` | `DateTimeField` | `auto_now_add` | |
| `last_used_at` | `DateTimeField` | `null` | |

**Validation.** On authentication, a `sign_count` that is **not greater than** the stored value,
when the stored value is non-zero, is rejected and recorded as
`auth.passkey.sign_count_regression` with status `DENIED`. Authenticators that always report `0`
(common, and permitted by the spec) skip the check.

**Meta:** `ordering = ["-created_at", "id"]`.

**Serializer:** `WebAuthnCredentialSerializer` — fields: `id`, `name`, `aaguid`, `transports`,
`created_at`, `last_used_at` (read-only except `name`). `credential_id` and `public_key` are
never exposed.

### 4.3 `MfaRecoveryCode`

**Model:** `accounts.models.MfaRecoveryCode`

| Field | Type | Default | Constraints / Notes |
|---|---|---|---|
| `id` | `UUIDField` | `uuid4` | Primary key |
| `user` | `ForeignKey(User, CASCADE)` | — | `related_name="mfa_recovery_codes"` |
| `code_hash` | `CharField(64)` | — | SHA-256 hex of the code |
| `used_at` | `DateTimeField` | `null` | Single use |
| `created_at` | `DateTimeField` | `auto_now_add` | |

**Format.** Ten codes per issue, each `secrets.token_hex(5)` → 10 hex characters, displayed
grouped as `a1b2c-3d4e5`. Shown **once**, at confirmation or regeneration.

**Hashing.** SHA-256, not a password hasher — the same argument `accounts/api_keys.py` already
documents for API keys: the code is 40 bits from `secrets`, not a human-chosen password, so
there is nothing for an attacker to guess and no iteration count changes that. Reuse
`api_keys.hash_secret` / `verify_secret` rather than adding a second hashing path.

**Regeneration** deletes all existing rows for the user and issues ten new ones, so an old
printout stops working.

### 4.4 `AppSettings` additions

**Model:** `accounts.models.AppSettings` (existing singleton, `singleton_enforcer`)

| Field | Type | Default | Constraints / Notes |
|---|---|---|---|
| `mfa_required_roles` | `JSONField` | `list` | Roles that must enrol, e.g. `["admin", "zev_owner"]`. Validated against `UserRole` values in `clean()` |
| `mfa_grace_period_days` | `PositiveIntegerField` | `14` | Days after the requirement is set, or after account creation, before enrolment is enforced |

`clean()` rejects any value in `mfa_required_roles` that is not a `UserRole` member, and rejects
a non-empty list when `MFA_ENCRYPTION_KEYS` is unset (§4.5) — a policy that cannot be honoured
must not be saveable.

**Serializer:** `AppSettingsSerializer` gains both fields, writable by `admin` only. Validation lives
in `AppSettings.validate_mfa_required_roles`, shared by `clean()` and the serializer (DRF does not run
`clean()`), and clearing the list never needs a key. Policy changes are audited through the existing
`app_settings.update` diff.

**Addition beyond the table above: `mfa_policy_changed_at`** (`DateTimeField`, null, non-editable),
set by `AppSettings.save()` whenever either policy field changes. The grace deadline is
`max(user.date_joined, mfa_policy_changed_at) + mfa_grace_period_days`. Without it "days after the
requirement is set" is not computable, and an admin account older than the grace period would be
locked out the moment the policy was switched on — the failure §7.3 exists to prevent.

### 4.5 Secret encryption — the key, and why it is not `SECRET_KEY`

**Settings**

```python
# config/settings.py
# Fernet keys for the TOTP secret at rest. The FIRST key encrypts; every key is
# tried on decrypt, so a rotation is: prepend the new key, re-encrypt, drop the old.
MFA_ENCRYPTION_KEYS = env.list("MFA_ENCRYPTION_KEYS", default=[])
```

**This is deliberately not `SECRET_KEY`, and not derived from it.** `SECRET_KEY` is *designed*
to be rotatable — Django ships `SECRET_KEY_FALLBACKS` for exactly that purpose, and rotating it
is the standard response to a suspected leak. If the TOTP secrets were encrypted under it, that
routine hygiene action would silently become *"every user with 2FA is locked out of their
second factor"*, recoverable only through recovery codes or an admin reset. The incident you
rotate the key to contain would be made worse by containing it. A dedicated key decouples the
two lifecycles: `SECRET_KEY` can rotate freely, and `MFA_ENCRYPTION_KEYS` rotates only when
someone intends to re-encrypt.

**Implementation.** `accounts/mfa_crypto.py`, kept separate from `models.py` for the same
reason `api_keys.py` is:

- `_fernet() -> MultiFernet` — builds from `MFA_ENCRYPTION_KEYS`, cached per key tuple.
  `cryptography.fernet.MultiFernet` natively encrypts with the first key and decrypts with any,
  so rotation needs no bespoke logic.
- `encrypt_secret(value: str) -> bytes` / `decrypt_secret(token: bytes) -> str`.
- Raises `MfaNotConfigured` when `MFA_ENCRYPTION_KEYS` is empty.

**When unset.** Enrolment is refused with `503` and a message naming the setting; the policy
field cannot be set (§4.4). Existing deployments therefore upgrade cleanly — nobody has a factor
yet — and the first person to try enrolling is told exactly what to configure, rather than
silently getting a weaker guarantee. A Django system check (`accounts.checks.mfa_key_configured`,
severity `Warning`) surfaces it in `manage.py check`, which CI already runs, and
`SystemHealthView` reports it as a named condition.

**Rotation** is a management command, `manage.py rotate_mfa_key`, which re-encrypts every
`TotpDevice.secret_encrypted` with the first configured key inside one transaction. It is
idempotent and safe to re-run.

**Not encrypted:** recovery codes (hashed — one-way is sufficient and correct) and WebAuthn
public keys (public by construction). Exactly one field needs reversible encryption, because
TOTP verification requires the shared secret.

**As shipped in PR 1**, two small additions beyond the above, both natural fits for "the crypto
and audit substrate" rather than separate scope: `rotate_mfa_key` records `auth.mfa.key_rotated`
(`AuditEventSource.MANAGEMENT_COMMAND`, `metadata.devices_reencrypted`) — the one PR-1-scoped
action that actually happens, so it is the one PR-1-scoped audit event — and
`SystemHealthView`'s payload gains an `mfa` probe (`{status, encryption_key_configured}`,
`"unknown"` rather than `"degraded"` when unset, matching how the existing Celery probe treats
"no broker in dev" as an expected state, not a fault), surfacing the same fact `manage.py check`
does, in the tab an admin actually looks at day to day.

---

## 5. API contracts

All paths are under `/api/v1/auth/`.

### 5.1 Login

| Endpoint | Method | Permission | Behaviour |
|---|---|---|---|
| `token/` | POST | `AllowAny` | Password step. **Unchanged** when the account has no factor. With one (TOTP or a passkey): returns `200` with `{"mfa_required": true, "mfa_token": "…", "methods": ["totp", "recovery_code"]}` (`["recovery_code"]` for a passkey-only account) and sets **no** auth cookies |
| `token/mfa/` | POST | `AllowAny` | `{mfa_token, code}` → sets auth cookies, returns `{"detail": "Login successful."}`. `code` accepts a TOTP code or a recovery code |
| `passkeys/authenticate/begin/` | POST | `AllowAny` | `{email?}` → WebAuthn `PublicKeyCredentialRequestOptions` with `userVerification: "required"`. Challenge cached 5 min |
| `passkeys/authenticate/complete/` | POST | `AllowAny` | Verifies the assertion, **refusing one whose `uv` flag is false**, → sets auth cookies. **No password involved** (D1, ADR 0020) |

**As shipped in PR 2.** `auth.login` carries `metadata.method` `password+totp` or `recovery_code`
for the second-step logins; the `oauth` value listed in §5.6 is **not** emitted — OAuth sign-ins
keep their existing `oauth.login` event, which already names the provider. `passkey` is emitted by
`passkeys/authenticate/complete/`. `token/mfa/` returns `400` for every failure (bad, replayed or expired), each audited as
`auth.mfa.challenge_failed` with the reason.

**The challenge token** is `django.core.signing.TimestampSigner(salt="accounts.mfa.challenge")`
over the user PK, with `max_age = MFA_CHALLENGE_TTL` (5 minutes). A signed token rather than a
JWT deliberately: it is structurally incapable of authenticating a request, because no
authentication class parses it, so a bug cannot promote it into a session.

It is **not** single-use, and does not need to be: within its 5-minute window it is only useful
with a valid TOTP code, and `last_used_step` (§4.1) already makes each code single-use. Adding a
server-side nonce would buy nothing and add state.

### 5.2 Self-service enrolment

| Endpoint | Method | Permission | Behaviour |
|---|---|---|---|
| `me/mfa/` | GET | `IsAuthenticated` | `{totp: {...}\|null, passkeys: [...], recovery_codes_remaining: int, required: bool, grace_until: date\|null}` |
| `me/mfa/totp/` | POST | `IsAuthenticated` | Begin enrolment. Creates an **unconfirmed** device, returns `{provisioning_uri, secret, qr_svg}`. Replaces any existing unconfirmed device |
| `me/mfa/totp/confirm/` | POST | `IsAuthenticated` | `{code}` → sets `confirmed_at`, issues ten recovery codes, returns them **once** |
| `me/mfa/totp/` | DELETE | `IsAuthenticated` | Removes the device **and its recovery codes**, audited as `auth.mfa.removed`. Refused with `409` if the policy requires a factor from this user and no other factor (a passkey) would remain |
| `me/mfa/recovery-codes/` | POST | `IsAuthenticated` | Regenerates all ten, returns them once |
| `me/passkeys/` | GET | `IsAuthenticated` | List (`WebAuthnCredentialSerializer`) |
| `me/passkeys/register/begin/` | POST | `IsAuthenticated` | `PublicKeyCredentialCreationOptions`; `residentKey: "preferred"`, `userVerification: "required"` (ADR 0020) |
| `me/passkeys/register/complete/` | POST | `IsAuthenticated` | `{credential, name}` → verifies attestation (user verification required), stores the credential, returns `{passkey, recovery_codes}`. `409` if the credential ID is already registered anywhere |
| `me/passkeys/<uuid:pk>/` | PATCH, DELETE | `IsAuthenticated` | Rename or remove own credential. Same `409` guard as TOTP removal |

**As shipped.** `me/mfa/` returns `required` (the policy names this user's role) and
`grace_until` as an ISO **datetime** (a moment the gate compares with now, not a bare date), which is
`null` once the user has any factor or when no policy applies. `me/mfa/totp/` POST returns `409`
while an *active* device exists (remove it first) and `503` naming `MFA_ENCRYPTION_KEYS` when the
key is unset. `me/mfa/recovery-codes/` POST returns `400` when the user has no factor at all.
`me/mfa/totp/confirm/` audits `auth.mfa.enrolled` (`method=totp`). None of these endpoints is on
`ACCOUNTS_API_KEY_ALLOWLIST`, so API keys are refused by default (tested).

**Recovery codes belong to the account, not to a factor** (ADR 0020: they are the escape from both).
They are issued when the user's **first** factor is enrolled — a passkey or TOTP — and confirming a
second factor does not replace them (its response carries `recovery_codes: []`). Regeneration works
with any factor. They are deleted when the last factor is removed.

**What gates a password login.** Any factor does (`mfa.requires_challenge`, i.e. `has_any_factor`:
an active TOTP device **or** at least one passkey). A passkey signs in on its own, but an account that
has one must not keep a password-only way in — otherwise enrolling protects nothing against a stolen
password (ADR 0020). The password, magic-link and onboarding-link doors therefore all return the
challenge; only the passkey route never does. What the challenge accepts is `mfa.challenge_methods`:
`["totp", "recovery_code"]` when the account has an authenticator app, `["recovery_code"]` for a
passkey-only account, which has nothing to generate a code with. The login forms follow that list
(`lib/mfaChallenge.ts`) and, for a passkey-only account, also offer "Sign in with a passkey instead".
`has_any_factor` is also what the enrolment *policy* is satisfied by.

*Earlier in this feature's delivery (PR 3 as first merged) the challenge was TOTP-only, so a
passkey-only account still accepted a password-only login and the recovery codes issued with its
first passkey had nowhere to be entered. That was a gap, not a decision, and is closed here.*

**Passkey ceremony mechanics.** Challenges live in the Django cache for 5 minutes and are taken with
an atomic `cache.delete`, so a ceremony completes once. Registration keys the challenge on the user
(`mfa:webauthn:reg:{user_pk}`); authentication is unauthenticated, so it keys on the challenge itself
(`mfa:webauthn:auth:{challenge}`), read back out of the assertion's own `clientDataJSON` — the browser
still signs it, and py_webauthn still verifies it. `authenticate/begin/` returns the same shape
whether or not the optional `email` matches an account (an unknown one yields an empty
`allowCredentials`), so it cannot enumerate accounts. Every failure on `authenticate/complete/` is
the same generic `400`; the audit reason distinguishes `expired_challenge`, `unknown_credential`,
`invalid_assertion` (which includes an authenticator that did not verify the user, a wrong origin
and a bad signature) and `inactive_user`. The library's own counter check is neutralised so a
regression can be audited as `auth.passkey.sign_count_regression` (`DENIED`) rather than as a bare
failure.

`me/mfa/totp/` POST returns the secret in plain text **once**, because the user must be able to
type it into an authenticator that cannot scan a QR code. `qr_svg` is rendered server-side with
the already-installed `qrcode` dependency, so the secret never reaches a third-party QR service.

### 5.3 Administration

| Endpoint | Method | Permission | Behaviour |
|---|---|---|---|
| `users/<int:pk>/mfa/` | DELETE | `IsAdmin` | Removes **all** factors and recovery codes for that user. Audited as `auth.mfa.reset` (D3) |
| `app-settings/` | PATCH | `IsAdmin` | Now also accepts `mfa_required_roles`, `mfa_grace_period_days` |

An admin **cannot** enrol a factor *for* another user, and cannot read any secret — the reset is
a removal, mirroring the API-key rule that an admin may revoke but not create on someone's
behalf (`2026-03-community-and-access.md`).

### 5.4 The other six doors (D2)

| Door | Behaviour | Rationale |
|---|---|---|
| OAuth token-exchange (4) | The IdP owns authentication. If the assertion carries `amr` naming an MFA method, honour it and do **not** double-challenge. A new per-provider `OAuthProvider.require_mfa_claim` (default `False`, migration `0017`, editable in the admin provider form) makes requiring that assertion opt-in. The claim is read from the **userinfo** response — the codebase does not parse ID tokens — and accepted as a list or a space-separated string against the RFC 8176 method values | Double-challenging a user who already did WebAuthn at their IdP is friction with no security gain |
| Magic link (5) | If the account has any factor (TOTP or a passkey), the consume endpoint returns an MFA challenge instead of a session | MFA must not be bypassable by requesting an email |
| Onboarding link (6) | Same as (5) | Same |
| Email verification (2) | Unaffected in practice — reached before a factor can exist — but the code must not *assume* it, so it runs the same check | Defensive; a re-verification flow later would otherwise open a hole |
| Initial password (3) | `set_initial_password` is `IsAuthenticated`, so it never mints a session from an unauthenticated request; there is no moment to challenge. Documented in the view rather than enforced | The door exists for a session the user already holds |
| Impersonation (7) | The target is **not** challenged; the admin already authenticated | The right control here is step-up on the admin's side, which is out of scope (§2) |

### 5.5 Throttling

New scope in `accounts/throttling.py` and `DEFAULT_THROTTLE_RATES`:

| Scope | Default | Keyed on | Purpose |
|---|---|---|---|
| `auth_mfa` | `10/hour` | The **user PK** from the challenge token | The per-account brake that `auth_login` (40/hour per IP) does not provide |
| `auth_passkey` | `30/hour` | Source IP | Bounds assertion-verification cost |

*Both scopes are overridable (`AUTH_MFA_THROTTLE_RATE`, `AUTH_PASSKEY_THROTTLE_RATE`). `auth_passkey` covers `begin` and `complete` together, so 30/hour is about fifteen sign-ins per IP. A challenge token that cannot be resolved falls back to per-IP keying.*

`AuthMfaThrottle` keying on the account rather than the IP is the point: credential stuffing
spread across a botnet is invisible to a per-IP budget.

### 5.6 Audit events

All `AuditActionCategory.AUTH`, `target_type = "accounts.User"`, `zev = None` (§3).

| Action type | Status | Actor | Notes |
|---|---|---|---|
| `auth.login` | SUCCESS | the user | **Existing.** Gains `metadata.method` ∈ `password` \| `password+totp` \| `passkey` \| `recovery_code` \| `oauth` |
| `auth.login_failed` | FAILED | none | **Existing**, unchanged |
| `auth.mfa.challenge_failed` | FAILED | none | Wrong TOTP or recovery code. `metadata.reason` ∈ `invalid_code` \| `replayed_code` \| `expired_challenge` |
| `auth.mfa.enrolled` | SUCCESS | the user | `metadata.method` ∈ `totp` \| `passkey` |
| `auth.mfa.removed` | SUCCESS | the user | Self-service removal |
| `auth.mfa.reset` | SUCCESS | the **admin** | Target is the affected user; `metadata.removed` counts what was deleted (D3) |
| `auth.mfa.recovery_used` | SUCCESS | the user | `metadata.remaining` — the count left |
| `auth.mfa.recovery_regenerated` | SUCCESS | the user | |
| `auth.passkey.registered` | SUCCESS | the user | `metadata.aaguid`, `metadata.name` |
| `auth.passkey.removed` | SUCCESS | the user | |
| `auth.passkey.sign_count_regression` | DENIED | none | Possible cloned authenticator (§4.2) |

---

## 6. Async and integration behavior

**No Celery work.** Every operation here is synchronous and sub-millisecond; queueing them would
add failure modes without removing latency.

**New dependencies** (`backend/requirements.txt`):

| Package | Purpose | Note |
|---|---|---|
| `pyotp` | TOTP generation and verification | Small, no transitive deps |
| `webauthn` (py_webauthn) | WebAuthn ceremonies | Brings `cryptography` transitively |
| `cryptography` | Fernet (§4.5) | Pinned explicitly rather than relied on transitively, since the encryption at rest depends on it |

`qrcode` is **already installed** and is reused for the enrolment QR — no new dependency.

**WebAuthn configuration.** Three settings, because the relying-party identity must match the
origin the browser sees:

```python
WEBAUTHN_RP_ID   = env("WEBAUTHN_RP_ID", default="localhost")        # e.g. "zev.example.ch"
WEBAUTHN_RP_NAME = env("WEBAUTHN_RP_NAME", default="OpenZEV")
WEBAUTHN_ORIGIN  = env("WEBAUTHN_ORIGIN", default="http://localhost:5173")
```

A mismatch between `WEBAUTHN_RP_ID` and the served domain makes every ceremony fail with an
opaque browser error, so the system check in §4.5 also warns when `DEBUG` is false and
`WEBAUTHN_RP_ID` is still `localhost`. The Helm chart's values gain all three plus
`MFA_ENCRYPTION_KEYS`. **As shipped (PR 2):** `mfaEncryptionKeys.{value, existingSecret}`, wired
to the backend deployment only (workers never touch a TOTP secret), following the `secretKey`
pattern — a plain `value` is accepted for parity, but an `existingSecret` reference is the
documented production route. The three WebAuthn settings ship as `webauthn.{rpId, rpName, origin}` (each optional; the backend defaults to `localhost`), and `manage.py check` gains `accounts.W002` when `DEBUG` is off and the RP ID is still `localhost`.

**Challenge storage.** WebAuthn ceremony challenges live in the Django cache (Redis in
production) under `mfa:webauthn:{user_pk|session_key}` with a 5-minute TTL — they are
single-use by construction and must not outlive the ceremony.

---

## 7. Frontend

### 7.1 `LoginPage`

**File:** `frontend/src/pages/LoginPage.tsx` · Route `/login`

- Gains a second step. `login()` now resolves to `{ mfaRequired: true, mfaToken, methods }` or a
  completed session; on the former the form swaps to a 6-digit code input with a "Use a recovery
  code instead" toggle.
- Gains a **"Sign in with a passkey"** button, shown when `PublicKeyCredential` exists in the
  browser. It calls `passkeyAuthenticateBegin()` → `navigator.credentials.get()` →
  `passkeyAuthenticateComplete()`, and **never asks for a password** (D1).
- The code input uses `inputMode="numeric"`, `autoComplete="one-time-code"`, and
  `maxLength={6}`, so platform OTP autofill works.

### 7.2 `AccountProfilePage`

**File:** `frontend/src/pages/AccountProfilePage.tsx` · Route `/account`

**As shipped:** the page is three tabs — Profile, **Security**, API keys — with the tab in `?tab=`
(`features/account/accountTabs.ts`). Security holds the password card, linked accounts and the
two-factor card (`TwoFactorSection`). Panels stay mounted while hidden, because recovery codes and a
new API key are shown once in component state and would otherwise be lost on a tab switch. The
enrolment gate links to `/account?tab=security`.

The **Security** tab's two-factor card contains:

- **Passkeys** — list with nickname, created and last-used dates, a rename and a remove action,
  and an "Add a passkey" button calling `navigator.credentials.create()`.
- **Authenticator app** — status, an "Set up" flow showing the QR (`qr_svg`) alongside the
  typed secret, and a confirm field.
- **Recovery codes** — remaining count, a regenerate action, and a one-time display in a modal
  with copy and download actions. The modal states plainly that the codes will not be shown
  again.
- Queries: `useQuery({ queryKey: queryKeys.auth.mfa(), queryFn: fetchMfaStatus })`. Every
  mutation invalidates `queryKeys.auth.mfa()`.

### 7.3 `MfaEnrolmentGate`

**File:** `frontend/src/components/MfaEnrolmentGate.tsx`

Wraps the authenticated shell. When `/me/mfa/` reports `required && !enrolled`, it renders a
full-page interstitial rather than the app. Before `grace_until` the interstitial is
dismissible ("Set this up later"); after it, it is not. A hard lockout of existing admins on
upgrade is the failure mode this exists to prevent.

**As shipped.** The decision lives in `lib/mfaGate.ts` (`pass` / `grace` / `hard`) so it is testable
without a router. `/account` always passes, so the enrolment UI stays reachable, and an impersonating
admin is never gated. **The gate is a UI control, not an API one:** a required user without a factor
who calls the API directly (a script holding their session cookie or an API key) is not stopped by
it. Server-side enforcement would have to touch every view's permission classes and every
authentication class, which is a separate, larger change; the policy today is a strong nudge with an
audit trail, not a hard wall. Say so before describing it to an operator as "enforced".

### 7.4 `AdminSystemSettingsPage`

**File:** `frontend/src/pages/AdminSystemSettingsPage.tsx` · Route `/admin/system-settings`

The existing **Security** area (or a new tab alongside `regional`, `features`, `oauth`, `vat`)
gains a multi-select for `mfa_required_roles` and a number input for `mfa_grace_period_days`.
Both are disabled, with an explanatory hint, when `/auth/system-health/` reports the encryption
key as unconfigured — mirroring the pattern PR #732 used for the dynamic-source picker.

### 7.5 `AdminAccountsPage`

**File:** `frontend/src/pages/AdminAccountsPage.tsx`

Each account row gains a **Reset two-factor** action (admin only), behind a confirmation dialog
naming the user and what will be removed. The row also shows which factors the account has (from
`AdminUserSerializer.mfa_methods`) — see `2026-03-community-and-access.md` §6.4.

### TypeScript types

**File:** `frontend/src/types/api.ts`

```typescript
export interface TotpDevice {
    id: string
    confirmed_at: string | null
    created_at: string
}

export interface Passkey {
    id: string
    name: string
    aaguid: string
    transports: string[]
    created_at: string
    last_used_at: string | null
}

export interface MfaStatus {
    totp: TotpDevice | null
    passkeys: Passkey[]
    recovery_codes_remaining: number
    required: boolean
    grace_until: string | null
}

export interface MfaChallenge {
    mfa_required: true
    mfa_token: string
    methods: ('totp' | 'recovery_code')[]
}

export interface TotpEnrolment {
    provisioning_uri: string
    secret: string
    qr_svg: string
}
```

### API client functions

**File:** `frontend/src/lib/api/auth.ts`

| Function | Method | Endpoint |
|---|---|---|
| `fetchMfaStatus()` | GET | `/auth/me/mfa/` |
| `beginTotpEnrolment()` | POST | `/auth/me/mfa/totp/` |
| `confirmTotpEnrolment(code)` | POST | `/auth/me/mfa/totp/confirm/` |
| `removeTotp()` | DELETE | `/auth/me/mfa/totp/` |
| `regenerateRecoveryCodes()` | POST | `/auth/me/mfa/recovery-codes/` |
| `fetchPasskeys()` | GET | `/auth/me/passkeys/` |
| `passkeyRegisterBegin()` | POST | `/auth/me/passkeys/register/begin/` |
| `passkeyRegisterComplete(credential, name)` | POST | `/auth/me/passkeys/register/complete/` |
| `renamePasskey(id, name)` | PATCH | `/auth/me/passkeys/<id>/` |
| `removePasskey(id)` | DELETE | `/auth/me/passkeys/<id>/` |
| `passkeyAuthenticateBegin(email?)` | POST | `/auth/passkeys/authenticate/begin/` |
| `passkeyAuthenticateComplete(credential)` | POST | `/auth/passkeys/authenticate/complete/` |
| `submitMfaChallenge(mfaToken, code)` | POST | `/auth/token/mfa/` |
| `resetUserMfa(userId)` | DELETE | `/auth/users/<id>/mfa/` |

### i18n

All strings under `auth.mfa.*` in `frontend/src/i18n/locales/{de,en,fr,it}.ts`. No hardcoded
user-facing text, per AGENTS.md.

---

## 8. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| `MFA_ENCRYPTION_KEYS` lost or not backed up | **High** — every TOTP secret becomes undecryptable | Enrolment refused when unset; system check + system-health warning; documented as a backup-critical secret; recovery codes and admin reset remain as escapes |
| Encrypting under `SECRET_KEY` instead | High — routine key rotation mass-locks users out | Rejected by design (§4.5); a dedicated, independently rotatable key set |
| Admins locked out on upgrade when policy is enabled | High | Grace period (default 14 days) plus a dismissible interstitial; enforcement only after `grace_until` |
| `WEBAUTHN_RP_ID` misconfigured | Medium — all passkey ceremonies fail opaquely | System check warns when `DEBUG=False` and RP ID is `localhost`; documented in the Helm values |
| TOTP code replayed within its window | Medium | `last_used_step` written under a row lock (§4.1) |
| Cloned authenticator | Medium | `sign_count` regression detection, audited as `DENIED` (§4.2) |
| Audit log becomes an account-enumeration oracle | Medium | Failures are undifferentiated, exactly as `auth.login_failed` already is (PR #741) |
| Recovery codes treated as a password | Low | Hashed, single-use, ten per issue, regeneration invalidates the old set |
| Users enrol then lose both factors | Medium | Admin reset (D3), audited |

---

## 9. Test plan

**As shipped in PR 1**, ahead of the API-level tests below (which need the enrolment/login
endpoints landing in PR 2): `accounts/test_mfa_crypto.py` carries the spec's own
`MfaCryptoTests` (5) plus `RotateMfaKeyCommandTests` (3) and `MfaKeyConfiguredCheckTests` (2) —
10 total. `accounts/test_mfa_models.py` (not named above; added because the replay-protection
logic in `TotpDevice.verify()` ships now) carries `TotpDeviceTests` (9) and
`MfaRecoveryCodeTests` (2) — 11 total. `accounts/test_system_health.py` gains 2 tests for the
`mfa` probe. 23 tests, all passing alongside the full existing suite unchanged.

**As shipped in PR 2**: `accounts/test_mfa.py` carries `TotpEnrolmentTests` (14), `TotpLoginTests`
(7), `MfaDoorTests` (5, the OAuth doors moved out) and `MfaThrottleTests` (2) — 28 tests. Beyond
the tables below it also covers active-device re-enrolment refusal, DELETE, recovery-code
regeneration invalidating the old set, the status endpoint, and API-key refusal. OAuth's door
lives in `accounts/test_oauth.py` as `OAuthMfaClaimTests` (5: refused without an MFA `amr` value,
refused with no claim at all, accepted with one, accepted as a space-separated string, and a
provider without the requirement unaffected). TOTP tests pin the clock
with a `totp_step` helper so replay protection never collides with a real 30-second step. The
Passkeys, the policy, the removal guard and the admin reset shipped with PR 3 (below).

**As shipped in PR 3**: `accounts/test_passkeys.py`, 62 tests, driving py_webauthn end to end
through a small software authenticator (real `none` attestations, real ES256 assertions, nothing
about the library mocked): `PasskeyRegistrationTests` (13), `PasskeyLoginTests` (14),
`PasskeyGatesThePasswordRouteTests` (7, the passkey-gated password / magic-link routes and the recovery-code second step), `PasskeyThrottleTests` (1), `MfaPolicyTests` (11), `MfaRemovalGuardTests` (6),
`MfaAdminResetTests` (7) and `WebAuthnRpCheckTests` (3). These replace the illustrative
`PasskeyTests` / `MfaAdminTests` tables below and additionally cover replay of a spent ceremony,
wrong-origin and tampered-signature assertions, the zero-counter exemption, the grace-period
arithmetic (including an account far older than the policy), and recovery codes surviving a second
factor. Frontend: `tests/mfa.test.ts` (22) covers the API client, the WebAuthn bridge and the gate's
decision table (`lib/mfaGate.ts`).

### Backend — `accounts/test_mfa.py` (new)

**`TotpEnrolmentTests`** (8 tests):

| Test | Asserts |
|---|---|
| `test_begin_enrolment_creates_unconfirmed_device` | Device exists, `confirmed_at` is null |
| `test_unconfirmed_device_does_not_gate_login` | `POST /token/` still returns a session |
| `test_confirm_with_valid_code_activates_and_issues_recovery_codes` | `confirmed_at` set, 10 `MfaRecoveryCode` rows, codes returned once |
| `test_confirm_with_invalid_code_is_refused` | 400, device stays unconfirmed |
| `test_begin_replaces_an_existing_unconfirmed_device` | Exactly one device row |
| `test_secret_is_never_serialized_after_enrolment` | No route returns `secret` once confirmed |
| `test_enrolment_refused_when_encryption_key_unset` | 503 naming `MFA_ENCRYPTION_KEYS` |
| `test_removal_refused_when_policy_requires_a_factor` | 409 when no passkey remains |

**`TotpLoginTests`** (7 tests):

| Test | Asserts |
|---|---|
| `test_password_login_returns_a_challenge_not_a_session` | `mfa_required`, no auth cookies set |
| `test_challenge_exchange_sets_cookies` | Cookies present, `auth.login` with `method=password+totp` |
| `test_expired_challenge_is_refused` | 400 after `MFA_CHALLENGE_TTL`, `auth.mfa.challenge_failed` reason `expired_challenge` |
| `test_replayed_code_is_refused` | Second use of the same code fails, reason `replayed_code` |
| `test_recovery_code_completes_the_challenge_once` | First use succeeds and marks `used_at`; second fails |
| `test_account_without_a_factor_is_unaffected` | Response byte-identical to today's |
| `test_challenge_token_cannot_authenticate_a_request` | Presented as a bearer token → 401 |

**`PasskeyTests`** (7 tests):

| Test | Asserts |
|---|---|
| `test_registration_stores_credential_and_audits` | Row created, `auth.passkey.registered` |
| `test_authentication_without_a_password_sets_cookies` | Session issued, `auth.login` with `method=passkey` (D1) |
| `test_sign_count_regression_is_refused_and_audited` | 400, `auth.passkey.sign_count_regression` with status `DENIED` |
| `test_multiple_credentials_per_user_are_allowed` | Two rows, both usable |
| `test_removing_one_leaves_the_other_usable` | Login still works |
| `test_credential_id_is_globally_unique` | `IntegrityError` on duplicate |
| `test_assertion_without_user_verification_is_refused` | An assertion with `uv=false` is rejected on the passwordless route — the guarantee ADR 0020 rests on |

**`MfaDoorTests`** (6 tests) — one per door in §5.4:

| Test | Asserts |
|---|---|
| `test_magic_link_challenges_an_account_with_a_factor` | Returns a challenge, not a session |
| `test_onboarding_link_challenges_an_account_with_a_factor` | Same |
| `test_oauth_does_not_double_challenge` | Session issued directly |
| `test_oauth_requires_amr_when_provider_demands_it` | Refused without the claim |
| `test_impersonation_does_not_challenge_the_target` | Session issued |
| `test_email_verification_is_unaffected` | Session issued |

**`MfaAdminTests`** (4 tests):

| Test | Asserts |
|---|---|
| `test_admin_reset_removes_all_factors_and_audits` | TOTP, passkeys and codes gone; `auth.mfa.reset` with the admin as actor (D3) |
| `test_non_admin_cannot_reset_another_user` | 403 |
| `test_admin_cannot_read_any_secret` | No route exposes it |
| `test_policy_cannot_be_enabled_without_an_encryption_key` | `ValidationError` from `AppSettings.clean()` |

**`MfaCryptoTests`** (5 tests) — `accounts/test_mfa_crypto.py`:

| Test | Asserts |
|---|---|
| `test_round_trip` | `decrypt(encrypt(x)) == x` |
| `test_second_key_still_decrypts_after_rotation` | A token from the old key decrypts when it is second in the list |
| `test_new_writes_use_the_first_key` | Re-encrypted token fails against the old key alone |
| `test_rotate_command_re_encrypts_every_device` | All rows decrypt under the new key alone |
| `test_missing_key_raises_mfa_not_configured` | Explicit exception, not a silent plaintext path |

**`MfaThrottleTests`** (2 tests): per-account budget on `token/mfa/`; the passkey scope is
per-IP.

Expected new backend tests: **39**. Existing `accounts` and `audit` suites must pass unchanged —
an account with no factor must behave exactly as it does today.

### Frontend — `frontend/tests/mfa.test.ts` (new)

| Test | Asserts |
|---|---|
| `challenge response switches the login form to the code step` | State transition |
| `passkey button is hidden when PublicKeyCredential is absent` | Feature detection |
| `recovery-code toggle swaps the input and its validation` | 6-digit vs 10-char |
| `enrolment gate blocks after grace, is dismissible before` | Both branches |

Plus `npm run lint`, `npm run lint:style`, the hex sweep, `npm run test:unit`, `npm run build`.

### Acceptance criteria

- [ ] A user can enrol a passkey and sign in with it **without entering a password** (D1).
- [ ] A user can enrol TOTP, and a password login then requires a code.
- [ ] A recovery code completes a challenge exactly once and is then dead.
- [ ] Each of the seven doors behaves as §5.4 specifies, with a test naming it.
- [ ] An admin can reset another user's factors, and `auth.mfa.reset` records who did it (D3).
- [ ] The TOTP secret is never returned once the device is confirmed, and never stored in plain text.
- [ ] `MFA_ENCRYPTION_KEYS` is independent of `SECRET_KEY`; rotating `SECRET_KEY` does not affect enrolled users (D4).
- [ ] With the key unset, enrolment is refused with a message naming the setting, and `manage.py check` warns.
- [ ] A required role is not locked out during the grace period.
- [ ] Every enrolment, challenge failure, removal, reset and recovery use appears in the platform audit log.
- [ ] An account with no factor sees byte-identical login behaviour to 1.15.0.
- [ ] All new user-facing strings exist in de, en, fr and it.

---

## 10. Delivery plan

Three PRs, in order. Each is independently releasable.

| PR | Contents | Why this boundary |
|---|---|---|
| 1 ✅ | `mfa_crypto.py`, `MFA_ENCRYPTION_KEYS`, system check, `TotpDevice` + `MfaRecoveryCode` models and migrations, the `auth.mfa.*` audit types | The crypto and audit substrate, with no user-visible change — reviewable on its own merits |
| 2 ✅ | TOTP enrolment and the two-step login, the six other doors, throttling, `AccountProfilePage` security section, login challenge step | The first shippable factor |
| 3 ✅ | `WebAuthnCredential`, passkey registration and passwordless authentication, policy fields, enrolment gate, admin reset | The larger surface, once the flow it plugs into is proven |

ADR 0020 should be written alongside PR 1, recording two decisions a future maintainer will
otherwise re-litigate: that a user-verified passkey **replaces** the password rather than
supplementing it, and that the MFA key is deliberately independent of `SECRET_KEY`.
