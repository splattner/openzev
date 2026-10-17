# ADR 0036: Explicit participant-link password recovery

- Status: Accepted
- Date: 2026-10-14

## Context

Participant edits and sign-in link generation used to erase chosen passwords.
Preserving them requires an explicit way to replace a forgotten password after
link sign-in. The standard emailed reset now covers accounts with a password;
link recovery also lets a participant who has just authenticated finish the
operation in Account → Security.

## Decision

Preserve existing passwords and pending-change flags during participant
synchronization. A completed onboarding or invoice sign-in, after any required
MFA, grants explicit password replacement for 15 minutes. The signed permission
has an absolute deadline; refresh never extends it. Ordinary password, OAuth,
passkey, API-key and impersonation sessions do not grant this permission.

Replacement validates the locked account and current session, retires other
sessions and all onboarding/magic links, and keeps the caller signed in without
recovery permission. The emailed reset retires the same links but mints no
session. Credential provenance for promotion is a separate concern: a credential
originating from a participant link does not itself prove a fresh link login or
grant recovery permission.

## Consequences

Participants can retain a chosen password and recover it without a manager
destroying it during routine edits. A leaked eligible participant link can also
establish a durable password after any required MFA. The 15-minute deadline
limits the permission after authentication, not the link's own lifetime.
Revocation and notifications limit persistence and expose changes; they do not
eliminate mailbox or link compromise. Accounts with independent access remain
outside this recovery door (ADR 0034).

## Alternatives considered

- Use only the standard emailed reset: it covers established passwords, but
  requires another mail round trip after a participant has completed link authentication.
- Treat every participant-derived session as recovery authority: rejected because
  ordinary password/passkey logins and session renewal must not grant or extend it.
- Clear passwords at every link login: rejected because sign-in itself must preserve
  an established, unflagged password; replacement is an explicit action.
