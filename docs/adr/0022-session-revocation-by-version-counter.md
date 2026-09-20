# ADR 0022: Sessions are revoked with a per-account version counter, not a token blacklist

- Status: Accepted
- Date: 2026-09-20

## Context

Browser sessions are a pair of stateless JWTs in httpOnly cookies: a 60-minute access token and a
7-day refresh token (rotating). "Stateless" means nothing on the server lists them, so nothing
could end them. A password change, an administrator resetting someone's second factor, or
deactivating an account left every already-issued token working for up to a week — and
reactivating a deactivated account would have brought the unexpired ones back to life.

That matters most in exactly the situations where an account may be compromised: the person
changes their password *because* someone else is in, and the intruder's session survives it.

Two ways to make tokens revocable:

1. **A token blacklist** (`rest_framework_simplejwt.token_blacklist`): a table of every issued
   refresh token and every revoked one, checked on refresh.
2. **A per-account counter**, stamped into each token and compared on use.

## Decision

Add `User.session_version` (integer, default `0`). Every token carries it as the `sv` claim,
stamped in one place (`accounts.jwt_utils.add_custom_claims`, which every issuing path shares).
`CookieJWTAuthentication.get_user` refuses an access token whose `sv` differs from the account's,
and `CookieTokenRefreshView` refuses a refresh token likewise (and one for an inactive account).
Revoking is `revoke_sessions(user)`: an atomic `UPDATE … +1`. Tokens issued before the claim
existed carry none, which reads as `0` — the value every account starts at — so the change ships
without signing anyone out, and they stop working at the account's first revocation.

`User.save()` never writes the column. A plain full-row save from an instance loaded before a
revocation would otherwise write the old value back and silently un-revoke every session that was
just signed out, so the only writer is the atomic update.

Revoked on: password change or initial set (the caller keeps their session — they are handed a
fresh pair), a confirmed email change, an administrator's two-factor reset, deactivation, and two
explicit actions ("Sign out other devices" for oneself, "Sign out everywhere" for an
administrator acting on someone else).

## Consequences

Positive:
- One integer per account and no new table: no per-token writes on login or refresh, nothing to
  prune, and the check reuses the user row `get_user` already loads — no extra query per request.
- Revocation is instantaneous and total, which is the property the triggers above want: "whoever
  was in before now is out".
- Reactivating an account cannot resurrect old sessions.

Trade-offs:
- **All-or-nothing.** A counter can say "everything issued before now is dead", never "this one
  device". There is no per-device session list and no "sign out that laptop". The Security tab is
  honest about this ("Sign out other devices").
- Logout still only clears *this* browser's cookies: a copied refresh cookie survives a plain
  logout until the next revocation. Bumping on every logout would sign out the user's other
  devices, which is the wrong behaviour for a routine action.
- The custom claims (`role`, `email`, `must_change_password`) still go stale within a token's
  lifetime; this decision is about ending sessions, not refreshing them.
- API keys are separate credentials with their own revocation and are deliberately unaffected.

## Alternatives considered

1. **Token blacklist (`token_blacklist` app).**
   Rejected for now. It gives what the counter cannot — per-token revocation and therefore a
   session list — but at the cost of an `OutstandingToken` row written on every login and every
   refresh rotation, a table that must be pruned, and a database lookup on each refresh. For the
   problem at hand (end everything after a credential change) that is machinery for a capability
   nobody asked for. If a device list is wanted later, it can be added on top: a `Session` table
   keyed by refresh-token `jti`, with the counter kept as the bulk "everything" switch.
2. **Compare the token's `iat` with a `sessions_valid_after` timestamp.**
   Rejected. It needs no claim, but `iat` has one-second resolution: a token issued in the same
   second as the revocation — the caller's own fresh pair after a password change — would be
   ambiguous. A counter is exact.
3. **Shorten the refresh lifetime instead.**
   Rejected: it narrows the window without closing it, and costs everyone a more frequent
   sign-in to mitigate an event most sessions never see.
