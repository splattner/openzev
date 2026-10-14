# Feature Spec: Participant onboarding link (phase 1)

- Spec ID: SPEC-2026-participant-onboarding-link
- Status: Completed
- Scope: Major
- Type: Feature
- Owners: Sebastian Plattner
- Created: 2026-09-12
- Related Issues: [#712](https://github.com/splattner/openzev/issues/712)
- Related ADRs: [ADR 0034](../adr/0034-participant-links-never-sign-in-independent-accounts.md)
- Impacted Areas: backend | frontend | docs

---

## 1. Problem and outcome

The roadmap carries *"Participant self-service onboarding via email auto-link"*
(PVshare model: an owner adds a participant, the participant visits a link and
is in — no admin invite flow). Issue #712 found that the mechanism for this
already existed in `accounts.magic_links` (tier 2 of the invoice-access
feature), but its only door was an invoice token — a participant could not get
in before their first bill existed, which is precisely the onboarding moment
this item is about.

It also found something #712 didn't originally scope: three separate places
minted a real, transmitted temporary password for a participant —
`send_participant_invitation` (emailed), `ParticipantSerializer.create()`
(shown once in the UI on every participant creation, unconditionally), and the
admin console's `create-account` action (shown once, admin-only). All three
have the same failure mode `docs/specs/2026-09-participant-invoice-access.md`
§1 already diagnosed for the invitation mail: a password chosen under duress,
for an account most participants activate once a year, is a password nobody
remembers by the next billing period.

**Outcome:** a participant account is never issued a real password by any of
these three paths any more. Instead, each produces (or reuses) a per-participant
bearer link — clicking it signs the participant in, creating the account
lazily if needed. The link is reusable within a 30-day lifetime
(`zev.onboarding.ONBOARDING_LINK_LIFETIME`) and revocable rather than one-shot, so
it doubles as the participant's ordinary way back in, not just their first one,
without leaving an immortal credential behind.

## 2. Scope

### In scope

| Area | Details |
|---|---|
| Backend — model | `zev.ParticipantOnboardingToken`: per-participant, reusable bearer link with a 30-day expiry |
| Backend — service | `zev.onboarding`: generate/resolve/revoke, mirrors `invoices.access_tokens` |
| Backend — service | `zev.services.ensure_participant_account` rewritten to never mint a usable password for a participant-role account |
| Backend — service | `send_participant_onboarding_link` (emails), `get_participant_onboarding_link` (does not) |
| Backend — API | `POST /zev/participants/<id>/send-onboarding-link/`, `.../onboarding-link/`, `.../revoke-onboarding-link/` |
| Backend — API | `POST /api/v1/public/onboarding/consume/` — unauthenticated, signs in |
| Backend — removed | `send-invitation` and `create-account`'s password-minting behaviour; the `participant_invitation` email template |
| Backend — audit | `AuditEventSource.ONBOARDING_LINK`; `participant.send_onboarding_link`, `participant.onboarding_link_created`, `participant.revoke_onboarding_link`, `participant_onboarding.consumed` |
| Frontend | `ParticipantOnboardingPage` at `/join/:prefix`, outside `ProtectedRoute` |
| Frontend | Participants page: send/copy/revoke actions, an Invitation status icon |
| Docs | This spec; `docs/ROADMAP.md` updated to reference it |

### Out of scope (phase 2, not built here)

- **Self-service `/join` with an email field.** Phase 1 only emails a link to
  an address the operator already put on the participant's record. A form
  where a stranger types an email and a link goes out on a match is a
  different trust model — it downgrades the invoice-access spec's "no address
  field to probe" property from *removed* to *mitigated* — and needs its own
  flag, separate from anything phase 1 touches.
- **A per-community `/join/<zev-slug>` variant.** Considered as a middle
  ground for phase 2, not needed for phase 1.
- **Custom username on account creation.** The removed `create-account`
  action accepted an operator-chosen username. `ensure_participant_account`
  always derives one from the participant's name/email now; preserving the
  override was judged not worth threading through a function used by every
  participant save. An operator who needs a specific username can still
  rename the account afterwards via the existing edit-user action.
- **Migrating existing participant accounts.** No bulk sweep or password-origin
  field is needed. Existing passwords and `must_change_password` survive account
  synchronization and link generation. A valid participant-link consumption
  retires a password after full authentication only when `must_change_password=True`; the flag describes
  a pending change, including one requested by an admin, rather than its origin.

## 3. What this replaces, and why it is a removal rather than a new door

`docs/specs/2026-09-participant-invoice-access.md` §2 lists "replacing the
password invitation" as out of scope for that spec, because tier 2 there was a
genuinely different entry point (from paper already in hand). Phase 1 here is
not that: it occupies the *same* workflow slot as `send-invitation` and
`create-account` — operator-triggered, per-participant, reachable from the
same pages. Shipping both would leave two ways to onboard a participant with
different security properties and two audit trails, with the weaker one still
wired to the default button. So this phase removes them outright rather than
adding a third option:

- `POST /zev/participants/<id>/send-invitation/` and its
  `{username, temporary_password}` response — **gone**, replaced by
  `send-onboarding-link`.
- `POST .../create-account/` — **gone**, replaced by `onboarding-link`, which
  returns a link and also works when an eligible account is already linked (see §5).
- The `participant_invitation` email template — **gone**, including any
  operator customisation of it (data migration deletes the row). The
  replacement, `participant_onboarding`, is templatable again from its own
  shipped default, with `{link_url}` instead of `{username}`/`{temporary_password}`.

This is a breaking API change and a template reset; both must be called out
explicitly as removals when this ships in a release.

## 4. Data model

### `ParticipantOnboardingToken`

```python
class ParticipantOnboardingToken(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    participant = models.ForeignKey(Participant, on_delete=models.CASCADE,
                                     related_name="onboarding_tokens")
    prefix = models.CharField(max_length=32, unique=True, db_index=True)
    secret = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField()

    class Meta:
        ordering = ["-created_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["participant"],
                condition=models.Q(revoked_at__isnull=True),
                name="one_unrevoked_onboarding_token_per_participant",
            ),
        ]
```

**Lifetime.** A freshly minted token expires 30 days out
(`zev.onboarding.ONBOARDING_LINK_LIFETIME`). Migration `0028` backfills
outstanding rows with `created_at + 30d` in one statement and then makes the
column non-nullable, so every row carries an expiry and no code path can mint
an immortal link. Migration `0029` adds a partial unique constraint (one
unrevoked link per participant) after revoking older duplicates, so rows
minted by the earlier race-prone implementation cannot fail the upgrade.

Shaped after `invoices.InvoiceAccessToken`, not `accounts.MagicLinkToken`:
**reusable within its lifetime**, rather than one-shot and 15 minutes. A one-shot
token solves "get the participant in once" and reopens "get them in the
second time" a step later — on their next visit they have no password and no
invoice to scan, exactly where they started. A reusable link, killed by
explicit revocation, by expiry, or once the participant sets their own
password (`POST /auth/me/set-initial-password/` revokes the account's links),
is what lets the same emailed link double as the participant's ordinary way
back in. `prefix`/`secret` are stored in clear for
the same reason `InvoiceAccessToken.secret` is (see that model's docstring):
whoever can already read this row can already read the participant it
protects, and `accounts.MagicLinkToken` — which grants a full session, not
just this — already sets the clear-text precedent.

### `ensure_participant_account` (rewritten)

The single function every account-creating path now goes through
(`ParticipantSerializer`, the onboarding actions, `accounts.magic_links`).
New **participant-only** accounts are passwordless with `must_change_password=False`.
Existing accounts keep their password and pending-change flag through participant
edits, onboarding copy/send and invoice sign-in-link requests.

**Leaves an account with its own login untouched** when it also happens to be
linked as a participant (eligibility below). Its password, email and name are unchanged: participant edits
must not alter its authentication identity. Only an account without its own
login follows its participant record (`sync_participant_user_fields`).

### No link signs in an account with its own login

`requires_independent_login(user)` is true for an admin, `may_create_zev`,
`independent_login_required`, any grant row, or any issuer/representative role
linked through a party or participation, including ended and future rows.
`link_account_for` raises `LinkRefused` before issuing a link for these accounts.
An unlinked managing party instead raises `login_setup_required`: it needs an
access invitation. Onboarding and invoice consumption recheck eligibility;
rejected magic tokens are spent. Public requests keep their non-enumerating
responses (invoice request 202, bad onboarding link 404, bad magic link 400).

Independent authentication remains required after accepted access is revoked,
including same-day grants that leave no history row. `User.independent_login_required`
(default false, not editable) records promotion, invitation acceptance and admin/
self-setup privileges. Demotion does not clear it. It has no application reset:
recovery establishes independent credentials rather than restoring participant links.
The relationship checks also cover pending invitations and unsupported legacy writes;
the flag preserves policy after those relationships disappear.

**Upgrade.** `accounts.0025_backfill_independent_login_required` uses historical
models to set the flag for existing admins, superusers, `may_create_zev` accounts,
all grant holders (including pending invitations), and accounts linked through
`Party.user` or `Participant.user` to an issuer/representative party. Ended and
future grants and roles count; landowner roles and participant-only accounts do
not. It depends on `accounts.0024` and `zev.0038`, uses the migration connection's
database alias, and updates only the flag without changing passwords, revoking
sessions or API keys, or consuming onboarding/magic tokens. Subsequent profile
saves also preserve existing credentials and sessions. Passwordless legacy
accounts are included without credential validation. Reversing the data migration
is a no-op, so rolling back the backfill alone does not clear protection.

| Account state | Participant links | Permanent flag |
|---|---|---|
| Participant only | Allowed | False |
| Pending access invitation | Refused through grant/role relationships | False unless already protected or backfilled on upgrade |
| Accepted access, admin or self-setup privileges | Refused | True |
| Independent access subsequently revoked | Refused | Remains true |
| Unaccepted invitation cancelled, no other protected relationship | Allowed again | Remains false |

**Credential ownership.** Participant-link possession permits password/factor
setup. Those credentials remain valid after promotion. A usable password, passkey
or enabled linked social account is a setup check, not proof of enrollment through
an independent channel. Promotion does not establish fresh account ownership;
known credential compromise requires password/factor recovery separately.

`protect_account_login` locks the user and returns it unchanged when permanent
protection is already set (for example a role change after the invitation was
accepted but before a password was chosen). Otherwise it requires a login (usable
password, enabled social login, passkey or pending invitation; else `ValidationError`
on `credential_field`) and retires sessions, API keys, onboarding links and magic tokens. Pending
invitations can repeat retirement until acceptance. MFA challenges carry the
session version, so revocation also retires them. API-key creation, initial password
setup, password changes, signing out other devices, TOTP setup/confirmation/removal,
recovery-code regeneration and passkey registration/removal use
`accounts.session_revocation.lock_current_session(request)` inside a transaction.
It reloads and locks the account, then rejects deleted/inactive accounts or a stale
session version with 401 before writing credentials or issuing fresh cookies.
The lock remains held through credential writes and JWT issuance, so a request
authenticated before promotion cannot renew its retired session.
User locks go through `User.objects.locked()`, which uses `no_key` only when
`has_select_for_no_key_update` is true;
MariaDB/MySQL use ordinary `FOR UPDATE`.
Lock order is parties ordered by id → users ordered by id → participant → token/grant.
`lock_participant_account` requires an outer transaction that holds the locks through
the writes. It locks old and new links, then rechecks them under the participant lock;
a change raises `ValidationError`; callers can refresh and retry.
Lookup reloads both related objects. With `for_save=True`, links outside `update_fields`
are refreshed, while unchanged cached objects are preserved. Empty saves do nothing;
unrelated partial saves skip link locking. `Participant.clean()` is advisory.
Full saves refuse to recreate deleted participants. Link-writing saves enforce promotion
checks under the locks. Participant updates repeat the immutable-party and protected-account
admin checks after locking. Grant creation locks an existing account before its duplicate-grant
check, so a concurrent grant for the same account is refused with 400.
Onboarding consumption locks and rechecks the token after locking the participant,
before creating an account, and holds the user and token locks through JWT issuance.
Invoice JWTs use the version read under
that lock, so concurrent promotion invalidates them. Onboarding email delivery
runs after the service transaction; delivery failure leaves the token available
for retry through the same send action.

Account-link saves accept field names and attnames (`user_id`, `party_id`).
Managing role identity and grant recipient/ZEV are immutable: end/revoke and
create instead. Saving a role or grant deleted in the meantime raises `ValidationError`. Grant creation, managing links and promotion of existing accounts to admin or
self-setup privileges require credentials or a pending invitation, with model
`clean()` validation for admin forms. Supported
writes use services or guarded `save()` paths; bulk updates, raw SQL and fixtures
bypass these hooks. Archive import leaves accounts unlinked; ZEV restore explicitly
protects newly managing accounts before committing, and its plan reports a
`login_setup_required` conflict for one without a login. Whole-instance restore restores
account policy from its schema-compatible snapshot.

## 5. API contracts

| Endpoint | Method | Auth | Requires email | Effect |
|---|---|---|---|---|
| `/zev/participants/<id>/send-onboarding-link/` | POST | manager/admin, zev-scoped | Yes (400 otherwise) | Ensure account + token, email after the service transaction; 400 refusal for protected accounts (audited `DENIED`) |
| `/zev/participants/<id>/onboarding-link/` | POST | manager/admin, zev-scoped | No | Ensure account + token, return the link; same 400 refusal as send |
| `/zev/participants/<id>/revoke-onboarding-link/` | POST | manager/admin, zev-scoped | — | Revoke the active token; account untouched |
| `/zev/participants/<id>/unlink-account/` | POST | **admin only** (unchanged) | — | Detach the account **and** revoke the active token |
| `/api/v1/public/onboarding/consume/` | POST | none | — | Resolve `{prefix, s}`, ensure account, sign in; 404 like any bad link when the account has its own login (audited `participant_onboarding.consumed`, `DENIED`) |

Send/copy return 400 `{"code": "own_login_required", "error": "This account must use its existing login."}` for protected accounts, or 400 `{"code": "login_setup_required", "error": "Give this party an access invitation before creating a participant login."}` for an unlinked managing party. Both refusals are audited `DENIED` with the code in `metadata.reason`.

If links change during locking, copy/send/link/unlink and participant edits return
a 400 validation error; a participant removed after lookup returns 404. The caller
can refresh and try again. Public onboarding
consumption keeps its generic 404, and magic-link requests keep their non-enumerating
response. Missing target parties/accounts produce field validation errors on saves.

`onboarding-link` is available to managers for participant-only accounts;
`link-account` remains admin-only. The Participants page's "copy onboarding
link" action calls `onboarding-link`.

`unlink-account` detaches the account and revokes its active token in one transaction.
A consume request that resolved the token before unlink must recheck it under lock;
it cannot recreate an account or issue a session after revocation commits.

Authenticated password writes (`set-initial-password`, `change-password`, `reset-password`)
retire the account's onboarding and outstanding magic links. Audit metadata records
`onboarding_links_revoked` and `magic_links_revoked`; the caller keeps fresh cookies
without recovery permission, and `password_changed` is scheduled after commit.
The emailed `password-reset/confirm` door also retires both kinds of link, with the
same audit counts, but signs out every session and schedules `password_reset` after
commit without issuing cookies. Its signed token is fully revalidated under the user lock.

`zev.onboarding.resolve(prefix, secret)` compares the secret first and returns
`None` for an expired token exactly as for a revoked one (same 404 on consume —
see the enumeration comment in `invoices/views_public.py`).
`get_or_create_for_participant`
revokes an expired active token and mints a fresh one (new secret, never an
extension), so "copy onboarding link" / "resend" always hands out a live link.
Concurrent copy/send requests serialize on the participant row; the loser returns
the winner's link. The partial unique constraint is the backstop.

### Password setup and explicit recovery

Decision and alternatives: [ADR 0036](../adr/0036-explicit-participant-link-password-recovery.md).

Valid onboarding consumption locks party → user → participant, then re-resolves
the token's secret, expiry, revocation and disabled-ZEV status before synchronizing
the current account. A request waiting behind password recovery cannot use a
token read before its revocation. Both onboarding and magic-link consumption
use `accounts.magic_links.retire_pending_password` to clear the password and flag
only when `must_change_password=True`, after full authentication, including MFA.
Issuing a challenge, failing it, or abandoning it leaves both unchanged.
An unflagged chosen password survives sign-in. Inactive accounts are refused by
both link doors without changing pending credentials.

After completed eligible link authentication (including any MFA), JWTs carry
`password_recovery_until`, an absolute Unix deadline from `PASSWORD_RECOVERY_WINDOW`
(15 minutes). Refresh preserves it; `/auth/me/` exposes it as
`password_recovery_expires_at: ISO datetime | null`. Sessions without a future
integer claim skip account-eligibility queries.
Ordinary password/OAuth/passkey sessions, API keys and impersonation have no recovery permission.

`POST /auth/me/reset-password/` takes `{new_password}`. Under the user lock it
checks the JWT's account id, current session version, live deadline and independent
login boundary. Missing/expired/ineligible authority returns 403 with
`code=password_recovery_required`; stale sessions return 401. Password validation
failures return 400 without changing credentials or spending permission.
Success validates and stores the password, clears `must_change_password`, bumps
the session version, revokes all unrevoked onboarding links and outstanding magic
tokens across the account's communities, and reissues caller cookies without
recovery authority. API keys keep their separate semantics. Cookie requests require
CSRF; API keys are denied; MFA-enrolment policy exempts this self-protective endpoint.
No browser throttle is added: this authenticated action does not guess a credential,
and success invalidates its permission through the session-version bump.
Audit `password.reset` records success/denial, with success counts
`onboarding_links_revoked` and `magic_links_revoked`; successful recovery schedules
the existing `password_changed` notification after commit. All three password
endpoints share `_finish_password_change` for retirement, cookies and notification.
Session revocation also discards pending OAuth exchange codes; callback issuance and
exchange serialize with it under the user lock. Profile updates save only supplied
fields, and ordinary model saves/hash upgrades cannot restore a replaced password
(community-and-access spec §5.6b).
All password audits share their credential-write transaction; a failed insert rolls
back the password, session version and retired links. No password or bearer secret
is recorded. Magic-link issuance uses the same user lock, so tokens cannot be inserted
inside an uncommitted retirement; later authorized issuance remains possible.

Account → Security offers first-time setup without an old password via
`set-initial-password` when `has_usable_password=False`. Existing passwords use
the ordinary change form, with an explicit recovery action while link authority
is live. Expiry disables recovery and asks for fresh link sign-in. Selection is tied
to the displayed deadline; a changed/removed permission returns to ordinary change
without clearing entered fields. Successful writes show success even if the subsequent
profile refresh fails; refresh errors separately ask the user to reload. Signup,
invitation and passwordless independent-account setup retain their existing gate.
Participant-only email addresses remain manager-maintained even after password setup
(`can_change_email=False`); both email-change request and confirmation enforce this.
Passwords already wiped cannot be restored; the participant chooses a new one.

`ParticipantSerializer` gains a computed `onboarding_status` field —
`not_sent` / `sent` / `active` / `revoked` / `expired` — read from the participant's most
recent token, not from whether an account exists (one is created eagerly by
every save regardless of whether anyone has been invited yet, so its mere
existence says nothing about progress).
It also carries `onboarding_link_expires_at` (ISO datetime of the latest
non-revoked link — present even when that link has already expired, so the
operator sees *when* it died — `null` only when no link was ever sent or the
latest was revoked), and the `onboarding-link` /
`send-onboarding-link` responses carry a top-level `onboarding_expires_at`
alongside `onboarding_url`, which the Participants page shows under the link
(`pages.participants.onboardingLinkExpires`).

## 6. Frontend

- `ParticipantOnboardingPage` (`/join/:prefix?s=`) mirrors `MagicSignInPage`'s
  shape but is not one-shot: visiting it again after a successful sign-in is
  not an error, so there is no "link already used" state, only "link is
  invalid or revoked."
- Participants page: the single "Send Invitation" action is replaced by three
  — send (disabled without an email), copy, and revoke (shown only for
  `sent` or `active` links). The actions live in each row's **⋯** menu. The
  **Invitation** icon in the Status column exposes `onboarding_status`
  in its tooltip and visually hidden text: `active` carries a done mark;
  other states carry no mark. The `sent` and `expired` tooltips include
  `onboarding_link_expires_at`, formatted as a short date. The icon describes
  the link's state, not portal access; setting a password revokes the link.
  Send/copy/revoke operations capture
  the submitting account/community/write-capability scope and recheck it before
  dispatch. Successful requests invalidate that community's participant query;
  obsolete completions do not display a URL or notify. Existing notices clear
  on scope changes, including manager-to-viewer transitions. Delayed success/error
  and notice-reset coverage is in `frontend/tests/participant-write-scope.test.ts`.
  Send/copy map `own_login_required` and `login_setup_required` to localized
  instructions; revoke uses its ordinary failure handler.
- `ParticipantOnboardingNotice` replaces `ParticipantCredentialsNotice`
  (deleted): shows the link with a copy button instead of a
  username/password pair on the Participants page.
- Admin console email templates: `participant_invitation` tab replaced by
  `participant_onboarding`, with `{link_url}` instead of
  `{username}`/`{temporary_password}`.

## 7. Audit

New `AuditEventSource.ONBOARDING_LINK`, mirroring `INVOICE_LINK` — the log
must say the actor was a bearer link, not a session, the same way an API key
or a printed invoice link already does.

New action types: `participant.send_onboarding_link`,
`participant.onboarding_link_created`, `participant.revoke_onboarding_link`,
`participant_onboarding.consumed`. `participant.send_invitation` and
`participant.create_account` stop being emitted; existing rows are untouched.
A link refused because the account has its own login (§4) is recorded under
the same action type with status `DENIED`.

## 8. Security model

Unauthenticated by design, for the same reason `invoices.views_public` is:
the link **is** the credential, sent only to the address already on the
participant's record — the caller never supplies one, which is what removes
account-enumeration risk rather than merely mitigating it (same property
`docs/specs/2026-09-participant-invoice-access.md` §9 relies on for tier 2).

The reusability trade-off is deliberate and stated plainly rather than
glossed over: unlike a magic link, this credential is not spent by use. Its
kill switches are explicit revocation (`revoke-onboarding-link`, or implicitly
via `unlink-account`), a 30-day expiry, and
setting a password (both password doors revoke the account's links). This is judged
acceptable because:

- it is scoped to exactly one participant's data, same ceiling an ordinary
  participant session already has — which holds only because no link signs in
  an account with its own login (§4): an account that manages a ZEV, or may set
  one up, is never reachable through a link;
- the account behind it can never authenticate with a password unless the
  participant sets one themselves; and
- an operator who suspects a link has leaked has an explicit, one-click way
  to kill it, discoverable from the same row that shows its status.

A stolen participant link can also establish a durable password during recovery,
subject to any required MFA. The 15-minute deadline limits the interval after login,
not a stolen link's own lifetime. Password writes retire old sign-in links and
sessions, and notify the account address. These limits do not eliminate mailbox or
link compromise; accounts with independent access remain unreachable through this door.

A disabled ZEV is one more kill switch, not one this spec originally
anticipated: `onboarding.resolve()` returns `None` for a disabled ZEV's
token, same as an unknown prefix or a wrong secret, so `onboarding_consume`
answers `404` indistinguishably from every other failure (ZEV lifecycle
phase 2 — see `2026-03-community-and-access.md` §7.1a).

## 9. Deferred / open

- **Invoice email entry.** A "view online" link in the ordinary invoice email
  remains deferred. Password setup and explicit link-authorized recovery are
  offered in Account → Security.
- **Empty landing state.** A participant onboarded at founding, before any
  invoice exists, lands on `/me/invoices` with nothing in it. Not addressed
  here.
- **Readiness integration.** "N participants have no email on file" is not
  yet surfaced in the attention cockpit, though the data (`onboarding_status`
  plus `Participant.email`) is now available to compute it from.
- Phase 2 (self-service `/join` with an email field) is a separate issue,
  deliberately not started here — see §2.

## 10. Test plan

`zev/test_onboarding.py` covers token creation, reuse, expiry, revocation, public
consumption, audit source, unlinking and onboarding-status transitions.
`OwnLoginLinkTests` checks that independent accounts cannot receive or consume
participant links, while participant-only accounts can still sign in.

`LinkPromotionLockTests` (6 tests, requiring database row locks; PostgreSQL lock and
statement timeouts bound blocked workers):

| Method | Assertion |
|---|---|
| `test_user_save_during_party_move_is_refused` | Reject a user-only save when a party move commits between the snapshot and locking |
| `test_lookup_during_party_move_is_refused` | Reject link lookup on the same interleaving |
| `test_lookup_during_account_relink_is_refused` | Reject a committed account relink during locking; preserve its credentials and create no token |
| `test_resolved_token_cannot_sign_in_after_unlink` | Resolve before unlink commits; refuse afterward without a replacement account or cookies |
| `test_edit_and_copy_of_the_same_participant_complete_without_deadlock` | Hold party and participant locks through copying; a concurrent edit completes |
| `test_sign_in_holds_the_user_lock_and_promotion_retires_its_session` | Hold user and token locks through JWT issuance; promotion invalidates that session |

`RevokeAndUnlinkTests.test_unlink_conflict_leaves_account_and_token_unchanged`
checks HTTP 400, preserved links and no success audit.
`test_revocation_failure_rolls_back_unlink` verifies detachment rolls back if revocation fails.

`zev/tests.py` covers create/send/link actions, including credential preservation
for independent accounts in `test_onboarding_link_leaves_roles_alone_and_keeps_privileged_logins`.

`OnboardingConstraintUpgradeTests.test_upgrade_revokes_older_duplicates_then_constrains`
checks the real constraint upgrade and restores the full migration graph in
cleanup. It then creates an invoice with the current models to catch leaked
historical schemas (including the invoice VAT-base column) regardless of test order.

Frontend: `tests/participant-onboarding.test.ts` for the three API client
functions; existing suite (`dead-i18n-keys`, `email-template-parity`) guards
the locale and template-key changes.

`zev/test_login_protection.py` — `LoginProtectionTests` (54 tests):

| Method | Assertion |
|---|---|
| `test_another_zevs_manager_cannot_deactivate_a_participant` | 403; account and session stay active |
| `test_cancelling_yesterdays_invitation_restores_login_and_only_spends_invitation_tokens` | Restore login; spend invitation, preserve signup token |
| `test_accepted_access_keeps_its_login_after_same_day_revocation` | Preserve password; refuse links after grant deletion |
| `test_raw_id_saves_cannot_link_a_passwordless_account_to_a_managing_party` | Reject all three attnames, string foreign-key IDs, and reconstructed Party saves |
| `test_user_only_save_checks_the_current_party` | Refuse linking a passwordless account after a party move hidden by the stale instance |
| `test_party_only_save_checks_the_current_account` | Refuse moving the persisted passwordless account even when the instance caches a different account with credentials |
| `test_link_lookup_refreshes_a_stale_party` | Report `login_setup_required` for the current managing party without an account |
| `test_link_lookup_refuses_a_removed_participant` | Raise `Participant.DoesNotExist` when the participant was deleted after lookup |
| `test_full_save_refuses_a_removed_participant` | Refuse to recreate a deleted participant |
| `test_empty_saves_preserve_pending_fields_and_cached_objects` | Zero queries for empty lists/tuples; preserve staged facade writes and cached objects |
| `test_unrelated_saves_do_not_query_or_reload_links` | Notes, validity and allocation saves use only their update and transaction statements |
| `test_failed_link_save_preserves_pending_party_fields` | Preserve staged party fields across a locking failure and retry |
| `test_user_only_save_does_not_write_a_staged_party` | Persist only the user; discard the staged managing-party link |
| `test_link_saves_preserve_unchanged_cached_objects` | Preserve unchanged cached party/user objects and their unsaved attributes |
| `test_missing_link_targets_return_field_errors` | Missing user/party IDs raise field validation errors |
| `test_link_lock_requires_an_outer_transaction` | Refuse calls without an existing transaction |
| `test_link_actions_return_404_after_a_participant_is_removed` | Copy/send return 404 for deletion during lookup |
| `test_link_actions_return_400_on_a_locking_conflict` | Copy/send translate concurrency validation errors to 400 |
| `test_public_links_conceal_removed_or_changed_participants` | Public consumption returns generic 404 without cookies; magic-link lookup returns no account |
| `test_participant_edit_returns_404_for_a_removed_participant` | Serializer updates return 404 after concurrent deletion |
| `test_participant_edit_rechecks_unchanged_party_after_locking` | Refuse a stale party payload accepted before a committed move |
| `test_accepted_access_remains_protected_after_an_older_grant_is_revoked` | Retain history; refuse onboarding |
| `test_raw_id_saves_linking_a_managing_party_retire_participant_credentials` | Retire session, onboarding and magic credentials |
| `test_saving_a_removed_grant_or_role_is_refused` | `ValidationError` instead of a missing-row error |
| `test_role_identity_cannot_be_changed_in_place` | Reject kind/party changes |
| `test_grant_recipient_cannot_be_changed_in_place` | Reject recipient reassignment |
| `test_managing_party_without_an_account_reports_setup_required` | Copy 400 setup code; public consume 404 without cookie |
| `test_account_sync_errors_on_participant_edit_return_400` | Convert non-dict validation safely |
| `test_admin_form_rejects_passwordless_managing_party_link` | Show form error on user |
| `test_rejected_valid_magic_token_is_spent` | Set consumed_at on refusal |
| `test_failed_existing_participant_invitation_can_be_resent` | Retain pending grant; resend succeeds |
| `test_stale_user_save_cannot_clear_independent_login_protection` | Preserve permanent flag |
| `test_a_manager_cannot_deactivate_a_participant_shared_with_another_zev` | 403; shared account stays active |
| `test_participant_api_key_is_retired_before_it_can_inherit_grants` | Retained key receives 401 after promotion |
| `test_key_creation_rechecks_a_session_authenticated_before_promotion` | Reject key creation after authenticated request loses its session |
| `test_key_creation_refuses_an_account_deleted_after_authentication` | 401; no key for a deleted account |
| `test_session_writes_refuse_a_request_authenticated_before_promotion` | Password setup/change, signing out other devices, TOTP, recovery-code and passkey writes return 401 without credential writes or fresh cookies |
| `test_participant_edit_rechecks_admin_rule_after_locking` | Manager edit refused with 400 when the account is promoted after validation |
| `test_concurrent_grant_for_the_same_account_is_refused_after_the_lock` | Grant created while waiting for the user lock gives 400, not a uniqueness error |
| `test_login_paths_use_supported_row_locks` | Copy, magic consumption, API-key creation, grant creation and revocation work without `no_key` support |
| `test_a_password_enrolled_through_a_participant_link_remains_usable` | Preserve enrolled password; require fresh sign-in |
| `test_promotion_retires_an_outstanding_mfa_challenge` | Reject challenge with an old session version |
| `test_direct_grants_and_admin_forms_require_login_setup` | Reject passwordless grant; show user form error |
| `test_foreign_manager_cannot_rotate_an_already_pending_invitation` | 403; existing invitation remains usable |
| `test_acceptance_between_cancellation_lookup_and_lock_preserves_history` | Retain ended grant after acceptance |
| `test_acceptance_between_resend_lookup_and_lock_refuses_a_new_token` | 400; no fresh invitation |
| `test_cancellation_between_resend_lookup_and_lock_refuses_a_new_token` | 404; no fresh invitation |
| `test_cancelling_a_reinvitation_restores_a_protected_accounts_active_state` | Reactivate; consume invitation; retain protection |
| `test_admin_and_self_setup_protection_survives_demotion` | Keep permanent flag after privilege removal |
| `test_passwordless_privilege_promotion_requires_login_setup` | Reject passwordless admin/superuser/self-setup promotion without retiring sessions |
| `test_passwordless_admin_promotion_returns_api_and_form_errors` | Return role error through API and Django admin form |
| `test_party_account_selection_uses_the_state_under_the_party_lock` | Grant to the refreshed party account |
| `test_onboarding_email_runs_after_the_service_transaction` | Release service transaction before delivery |
| `test_access_validation_failure_rolls_back_pending_invitation_changes` | 400 on request field; restore active state and discard invitation/grant |

`frontend/tests/participant-write-scope.test.ts` covers localized send/copy
refusals and ordinary failures for send, copy and revoke.

`LoginProtectionUpgradeTests` (3 tests) migrates real pre-0024 rows forward and
restores the full migration graph in cleanup:

- `test_upgrade_backfills_independent_accounts_only`: admin, superuser, self-setup,
  manager/viewer grants, and issuer/representative roles through both account-link
  paths, with current, ended and future windows; landowners and participant-only
  accounts remain unprotected.
- `test_upgrade_profile_save_preserves_existing_credentials`: a profile save after
  upgrade preserves the password, session version, working JWT and API key.
- `test_upgrade_passwordless_admin_can_be_edited_and_stays_protected_after_demotion`:
  a passwordless legacy admin can save its profile and remains protected after
  demotion without session revocation.
