# ADR 0034: Participant links never sign in an account with independent access

- Status: Accepted
- Date: 2026-10-12

## Context

Participants sign in through bearer links: the onboarding link a manager copies or sends, the
magic sign-in link, and the invoice QR flow
([SPEC-2026-09-participant-onboarding-link](../specs/2026-09-participant-onboarding-link.md)).
Whoever holds such a link can sign in as that participant's account. A manager handling a
participant's link is the normal case, so this is acceptable as long as the account can do no more
than see that participant's own data.

The same account can also hold independent access: a manager or viewer grant, an issuer or
representative role through its party, admin rights, or `may_create_zev`. A participant link for
such an account let the person holding it act as a manager or admin. Saving the participant row
also copied its email onto the account, which another manager could use to take over the login
through a password reset (#761).

The old check `has_its_own_login` was computed from relationships alone. Ending the last grant,
deleting a same-day grant or ending a role silently made the account eligible for participant
links again, and in-flight sessions, API keys and tokens issued while it was participant-only
carried over into the new access.

## Decision

- **One gate.** `zev.services.link_account_for` decides whether a participant link may
  authenticate an account. Copy, send, onboarding consumption and magic-link requests (including
  the invoice QR flow) go through it. Magic-link consumption re-checks the account and spends the
  token even when it refuses. Refusals return a code (`own_login_required`,
  `login_setup_required`) to managers. Public endpoints answer the same way as for an unknown
  link, so nothing reveals which accounts are protected.
- **Protection is sticky.** `User.independent_login_required` (not editable, excluded from plain
  `save()`) records that an account was promoted. It is never cleared by the application, so
  demotion, revocation or a deleted grant does not reopen participant links. Live relationship
  checks still apply while the flag is false, which covers pending invitations before acceptance
  sets permanent protection.
- **Promotion retires participant credentials.** `protect_account_login` runs at every promotion
  point: grant creation, managing-role assignment, linking an account to a managing party, admin
  or self-setup privileges, and ZEV restore. Under the user lock it revokes sessions (through
  `session_version`), API keys, onboarding links and magic tokens, and requires the account to
  have a login (password, enabled social login, passkey) or a pending invitation. MFA challenges
  carry the session version and therefore expire too. An account that is already protected passes
  through unchanged.
- **Guards live on the models.** `User`, `Party`, `Participant`, `ZevAccessGrant` and
  `ZevPartyRole` call the shared helper from `save()`, so the Django admin, `createsuperuser`, the
  shell and service code are covered, not only the REST endpoints. Raw restore writes bypass
  `save()`, so `restore_zev` calls the helper explicitly and reports missing logins in its plan.
- **Stale requests cannot renew a retired session.** Credential writes (passwords, API keys,
  TOTP, recovery codes, passkeys, signing out other devices) re-check the session under the user
  lock with `lock_current_session` before writing.

## Consequences

Positive:
- A participant link can only ever reach participant-scoped data.
- Protection survives later changes to grants and roles, so it never depends on remembering to
  re-check.
- Every write path is guarded, including those that bypass the API.

Trade-offs:
- Passwords and second factors set up through a participant link before promotion stay valid. The
  link holder could have set them. Follow-up: require fresh credentials on promotion (tracked
  separately).
- A ZEV restore that would give a managing role to an account without a login is refused; the
  account needs an invitation first.
- Participant-row saves, grant and role saves take row locks in a fixed order
  (parties by id → users by id → participant → token/grant), which every new write path must follow.

## Alternatives considered

1. Keep the computed check only
   - Revoking or deleting a grant reopened participant links, which was the original hole.
2. Enforce in the services and views only
   - Simpler, but the Django admin, management commands and the shell would bypass it.
3. Clear the flag on demotion
   - Credentials issued while the account was privileged would become reachable through
     participant links again. Re-enabling links is a deliberate operator action, not something
     the application does on its own.

## Notes

Spec: [SPEC-2026-09-participant-onboarding-link](../specs/2026-09-participant-onboarding-link.md)
("No link signs in an account with its own login", promotion retirement, lock order);
[SPEC-2026-10-zev-access-grants](../specs/2026-10-zev-access-grants.md) §7–8.
