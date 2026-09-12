# Feature Spec: Participant onboarding link (phase 1)

- Spec ID: SPEC-2026-participant-onboarding-link
- Status: Draft — implemented, not yet reviewed/merged
- Scope: Major
- Type: Feature
- Owners: Sebastian Plattner
- Created: 2026-09-12
- Related Issues: [#712](https://github.com/splattner/openzev/issues/712)
- Related ADRs: —
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
lazily if needed. The link is reusable and revocable rather than one-shot, so
it doubles as the participant's ordinary way back in, not just their first one.

## 2. Scope

### In scope

| Area | Details |
|---|---|
| Backend — model | `zev.ParticipantOnboardingToken`: per-participant, reusable, revocable bearer link |
| Backend — service | `zev.onboarding`: generate/resolve/revoke, mirrors `invoices.access_tokens` |
| Backend — service | `zev.services.ensure_participant_account` rewritten to never mint a usable password for a participant-role account |
| Backend — service | `send_participant_onboarding_link` (emails), `get_participant_onboarding_link` (does not) |
| Backend — API | `POST /zev/participants/<id>/send-onboarding-link/`, `.../onboarding-link/`, `.../revoke-onboarding-link/` |
| Backend — API | `POST /api/v1/public/onboarding/consume/` — unauthenticated, signs in |
| Backend — removed | `send-invitation` and `create-account`'s password-minting behaviour; the `participant_invitation` email template |
| Backend — audit | `AuditEventSource.ONBOARDING_LINK`; `participant.send_onboarding_link`, `participant.onboarding_link_created`, `participant.revoke_onboarding_link`, `participant_onboarding.consumed` |
| Frontend | `ParticipantOnboardingPage` at `/join/:prefix`, outside `ProtectedRoute` |
| Frontend | Participants page: send/copy/revoke actions, an onboarding-status badge |
| Frontend | Admin Accounts page: "Create account" now creates a passwordless account and shows a copyable link |
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
- **Migrating existing participant accounts.** An account issued before this
  change keeps whatever password it has until it is next touched by
  `ensure_participant_account` (any participant save, or an onboarding/magic
  link), at which point it is neutralized. There is no bulk sweep.

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
- `POST .../create-account/`'s password-minting body — **gone**; the action
  stays but returns a link instead of a password, and no longer requires
  `participant.user is None` to be reachable (see §5).
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
```

Shaped after `invoices.InvoiceAccessToken`, not `accounts.MagicLinkToken`:
**reusable and no expiry**, rather than one-shot and 15 minutes. A one-shot
token solves "get the participant in once" and reopens "get them in the
second time" a step later — on their next visit they have no password and no
invoice to scan, exactly where they started. A reusable link, killed only by
explicit revocation, is what lets the same emailed link double as the
participant's ordinary way back in. `prefix`/`secret` are stored in clear for
the same reason `InvoiceAccessToken.secret` is (see that model's docstring):
whoever can already read this row can already read the participant it
protects, and `accounts.MagicLinkToken` — which grants a full session, not
just this — already sets the clear-text precedent.

### `ensure_participant_account` (rewritten)

The single function every account-creating path now goes through
(`ParticipantSerializer`, the onboarding actions, `accounts.magic_links`).
Behavioural change: for a **participant-role** account, it always ends with
`set_unusable_password()` and `must_change_password=False` — on creation, and
on every touch of an already-linked account that still carries a usable
password (the upgrade safety net).

**Deliberately does not touch the password of an owner or admin account that
also happens to be linked as a participant** — `sync_participant_user_fields`
already carves this case out for role, for the same reason: that password is
their real login for everything else they manage, and it must survive their
own participant row being saved or invited. Checked by role *after*
`sync_participant_user_fields` has run, so an owner/admin keeps their
password while a genuine participant (including one just promoted from
`GUEST`) is neutralized.

## 5. API contracts

| Endpoint | Method | Auth | Requires email | Effect |
|---|---|---|---|---|
| `/zev/participants/<id>/send-onboarding-link/` | POST | owner/admin, zev-scoped | Yes (400 otherwise) | Ensure account + token, email the link |
| `/zev/participants/<id>/onboarding-link/` | POST | owner/admin, zev-scoped | No | Ensure account + token, return the link |
| `/zev/participants/<id>/revoke-onboarding-link/` | POST | owner/admin, zev-scoped | — | Revoke the active token; account untouched |
| `/zev/participants/<id>/unlink-account/` | POST | **admin only** (unchanged) | — | Detach the account **and** revoke the active token |
| `/api/v1/public/onboarding/consume/` | POST | none | — | Resolve `{prefix, s}`, ensure account, sign in |

`onboarding-link` is intentionally **not** admin-gated the way the old
`create-account` was: creating a harmless, passwordless link is not the
sensitive operation linking an *existing* arbitrary account is (`link-account`
stays admin-only). This is what lets the Participants page's "copy onboarding
link" and the Admin Accounts page's "create account" button call the same
action.

`unlink-account` revoking the active token is new behaviour, not carried over
from the old action: without it, detaching the account would not actually cut
access — whoever holds the emailed link could click it again and land in a
freshly recreated account.

`ParticipantSerializer` gains a computed `onboarding_status` field —
`not_sent` / `sent` / `active` / `revoked` — read from the participant's most
recent token, not from whether an account exists (one is created eagerly by
every save regardless of whether anyone has been invited yet, so its mere
existence says nothing about progress).

## 6. Frontend

- `ParticipantOnboardingPage` (`/join/:prefix?s=`) mirrors `MagicSignInPage`'s
  shape but is not one-shot: visiting it again after a successful sign-in is
  not an error, so there is no "link already used" state, only "link is
  invalid or revoked."
- Participants page: the single "Send Invitation" action is replaced by three
  — send (disabled without an email), copy, and revoke (shown only once a
  link has been sent). A badge shows `onboarding_status` on every card.
- `ParticipantOnboardingNotice` replaces `ParticipantCredentialsNotice`
  (deleted): shows the link with a copy button instead of a
  username/password pair, used identically from both the Participants page
  and the Admin Accounts page.
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

## 8. Security model

Unauthenticated by design, for the same reason `invoices.views_public` is:
the link **is** the credential, sent only to the address already on the
participant's record — the caller never supplies one, which is what removes
account-enumeration risk rather than merely mitigating it (same property
`docs/specs/2026-09-participant-invoice-access.md` §9 relies on for tier 2).

The reusability trade-off is deliberate and stated plainly rather than
glossed over: unlike a magic link, this credential does not expire and is not
spent by use. Its only kill switch is explicit revocation
(`revoke-onboarding-link`, or implicitly via `unlink-account`). This is judged
acceptable because:

- it is scoped to exactly one participant's data, same ceiling an ordinary
  participant session already has;
- the account behind it can never authenticate with a password unless the
  participant sets one themselves; and
- an operator who suspects a link has leaked has an explicit, one-click way
  to kill it, discoverable from the same row that shows its status.

## 9. Deferred / open

- **Returning without the link.** Phase 1 does not yet add "set a password"
  as an offered action after sign-in, nor a "view online" link in the
  ordinary invoice email — both listed in #712 as the real fix for
  "onboarding and returning are different problems." The reusable link
  covers the immediate gap; those are the more complete answer and are left
  for a follow-up.
- **Empty landing state.** A participant onboarded at founding, before any
  invoice exists, lands on `/me/invoices` with nothing in it. Not addressed
  here.
- **Readiness integration.** "N participants have no email on file" is not
  yet surfaced in the attention cockpit, though the data (`onboarding_status`
  plus `Participant.email`) is now available to compute it from.
- Phase 2 (self-service `/join` with an email field) is a separate issue,
  deliberately not started here — see §2.

## 10. Test plan

Backend: `zev/test_onboarding.py` (token service get-or-create/resolve/revoke,
the public consume endpoint including reusability and audit source, revoke
and unlink interaction, `onboarding_status` transitions) plus updated
coverage in `zev/tests.py` for the create/send/link actions, including the
owner-vs-admin password-preservation case in
`test_onboarding_link_preserves_privileged_roles_and_promotes_guests`
(regression test for the bug found and fixed in `ensure_participant_account`
during this implementation — see §4).

Frontend: `tests/participant-onboarding.test.ts` for the three API client
functions; existing suite (`dead-i18n-keys`, `email-template-parity`) guards
the locale and template-key changes.
