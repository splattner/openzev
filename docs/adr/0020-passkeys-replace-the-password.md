# ADR 0020: A user-verified passkey replaces the password, rather than supplementing it

- Status: Proposed
- Date: 2026-09-19

## Context

OpenZEV authenticates with a password (SimpleJWT over httpOnly cookies), OAuth against a
configured provider, emailed magic and onboarding links, and API keys for scripting. It has no
second factor of any kind. `docs/specs/2026-09-two-factor-authentication.md` adds TOTP and
WebAuthn for [#740](https://github.com/splattner/openzev/issues/740).

Adding WebAuthn forces a question the spec cannot leave to implementation: when a user has
registered a passkey, does the login flow still ask for their password first?

The two readings produce different products. "Password **and** passkey" treats WebAuthn as a
second factor bolted onto the existing form. "Passkey **or** password+TOTP" treats it as an
authentication method in its own right, and the password becomes one of two routes rather than
the only door.

The distinction matters more here than in a typical application, because the threat this feature
exists to address is a stolen or reused password on an instance that can issue invoices and read
IBANs and metering data.

## Decision

A WebAuthn credential authenticates on its own. `POST /api/v1/auth/passkeys/authenticate/complete/`
mints a session with no password step, and the MFA policy in `AppSettings.mfa_required_roles` is
satisfied by a passkey *or* by TOTP.

- **User verification is `required`**, at both registration and authentication — not `preferred`.
  A passkey that replaces the password is the whole authentication, so the authenticator must
  prove possession *and* verify the human (biometric or PIN). A credential that can be used by
  whoever holds the unlocked device is a single possession factor, and would not justify
  dropping the password.
- TOTP remains the second factor for password logins, and the fallback where a passkey is
  impractical — a shared workstation, an unsupported browser, a user who declines platform
  biometrics.
- Recovery codes are the escape from both, and are the only credential that bypasses a
  registered factor.
- Multiple credentials per user are supported and encouraged, so a lost device is not a lockout.

## Consequences

Positive:
- The strongest available method is also the fastest, so the incentive points the right way.
  A flow that made passkeys *slower* than passwords would suppress adoption of the method with
  the better security properties.
- Phishing resistance is real rather than partial. WebAuthn binds the assertion to the origin,
  and on the passkey route no reusable secret exists at any point in the flow — there is nothing
  for a lookalike domain to collect, and nothing to reuse from a breach elsewhere.
- The password route is unchanged for users who do not enrol, so this is additive.

Trade-offs:
- A user whose only factor is a passkey, and who loses every registered authenticator, depends on
  recovery codes or an administrator reset (`auth.mfa.reset`, ADR 0008's audit model). Encouraging
  a second credential mitigates but does not remove this.
- `userVerification: "required"` refuses authenticators that cannot verify a user. That is the
  intended trade: such a credential does not carry the guarantee this decision rests on.
- Two authentication routes to the same session means every guard added later — step-up
  re-authentication in particular — has to cover both, or it covers neither.

## Alternatives considered

1. **Passkey as a second factor after the password.**
   Rejected. A user-verified passkey is already two factors (possession of the authenticator plus
   the verification that unlocks it). Requiring a password in front of it is two factors twice
   over: it adds a phishable, reusable secret to a flow whose entire value is that it has none,
   and charges the user an extra step for the privilege. It also keeps the password as the
   account's weakest link while claiming the account is protected.

2. **Passkeys only, retiring passwords entirely.**
   Rejected as premature. Browser and platform support is good but not universal, shared and
   kiosk workstations are a real deployment for a community administrator, and this is
   self-hosted software whose operators cannot be assumed to control their users' devices.
   Revisit when the passkey route has a full release of production use.

3. **`userVerification: "preferred"` with passwordless login.**
   Rejected. "Preferred" means the ceremony silently succeeds without verification when the
   authenticator declines, so the guarantee would vary per credential while the login flow
   treated them identically. If the passkey replaces the password, the weaker variant must not
   be accepted on that route.

4. **Let the administrator choose per instance.**
   Rejected for the first release. The setting would encode a security model, not a preference,
   and the wrong choice is not visible in operation. Revisit if a deployment presents a concrete
   case the fixed model cannot serve.

## Notes

Implementation lives in `docs/specs/2026-09-two-factor-authentication.md` §5.1–5.2 (endpoints),
§7.1 (the login form's passkey route) and §9 (`PasskeyTests`). The key-management side of the
same feature is ADR 0021. This ADR extends ADR 0008's security model; it supersedes nothing.
