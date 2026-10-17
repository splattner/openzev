# ADR 0035: Participant-enrolled credentials cannot carry independent access

- Status: Accepted
- Date: 2026-10-13
- Amends: ADR 0034

## Context

A manager can hold a participant's onboarding or invoice sign-in link. Retiring
that link and its sessions on promotion is insufficient when the holder enrolled
a password or passkey first. Those credentials could otherwise inherit manager,
viewer, issuer/representative, admin or self-setup access. A password login, MFA
challenge or replacement session must not erase the original source.

## Decision

- Record provenance per password, TOTP device, passkey and recovery code. Signed
  participant sessions and their descendants retain `src=participant_link`.
  Access authentication and refresh reject that source whenever independent login
  is required, even if a stale profile save restores a retired credential hash.
- First promotion requires an independently established password/passkey, a trusted
  enabled social identity, or a pending access invitation. Remove participant-enrolled
  credentials in the existing promotion transaction. Independent credentials survive.
- An access invitation proves the recorded mailbox owner independently and permits
  fresh enrollment. Provider login matched by verified email does too. Explicit
  provider linking from a participant-derived session requires the provider to verify
  that same account email; otherwise a link holder could attach their own identity.
  Bind linking requests to the authorizing session version and recheck after provider I/O.
- Participant-derived passwords cannot change the account email, including through
  an older confirmation token. The invitation destination remains operator-managed.
- Conservatively mark legacy local credentials on currently linked participant-only
  accounts and end their sessions once. Expire old OAuth linking requests without
  session binding and discard outstanding exchange codes. Existing social identities
  qualify only if stored provider claims verify the account email; other identities must prove it at login
  or are retired on promotion. Leave already-promoted accounts unchanged.

## Consequences

Participant links still support participant login and credential setup, but never
bootstrap independent access. Promotion may send an invitation where it previously
reused a password. Legacy participant-only accounts need to sign in again and may
need an invitation even when an older password was independently established.
Historical credentials on already-promoted accounts are retained; recovering a
known compromise on those accounts remains a separate operator action.

## Alternatives considered

1. Delete every local credential on promotion: loses independently established logins.
2. Track only direct link sessions: password/passkey sign-in and MFA completion could
   erase provenance and enroll trusted replacements.
3. Trust every provider identity: explicit account linking accepts a different email
   from an independent session, which participant-link holders must not inherit.
4. Re-invite every existing privileged account: disruptive and unnecessary for the
   chosen scope of future promotions.

## Notes

Implementation: `zev.services.protect_account_login`, `accounts.jwt_utils`,
`accounts.mfa`, credential enrollment/login views, migrations `accounts.0028–0029`.
Contract: [Participant onboarding spec §4](../specs/2026-09-participant-onboarding-link.md).
