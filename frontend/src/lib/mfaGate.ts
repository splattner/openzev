import type { MfaStatus } from '../types/api'

/**
 * What the enrolment gate should do for a user (spec
 * 2026-09-two-factor-authentication.md §7.3):
 * - `pass`: render the app.
 * - `grace`: the role requires a factor and there is none, but the deadline is
 *   still ahead — show the interstitial, dismissible for the session.
 * - `hard`: past the deadline (or none was recorded) — not dismissible.
 *
 * Pure so the branches are testable without rendering a router and a query
 * client. `/account` always passes, so the user can reach the enrolment UI.
 */
export type MfaGateState = 'pass' | 'grace' | 'hard'

export function mfaGateState(
    status: MfaStatus | undefined,
    options: { now: number; dismissed: boolean; impersonating: boolean; pathname: string },
): MfaGateState {
    if (!status || options.impersonating) return 'pass'
    const enrolled = Boolean(status.totp?.confirmed_at) || status.passkeys.length > 0
    if (!status.required || enrolled || options.pathname === '/account') return 'pass'

    const inGrace = status.grace_until !== null && new Date(status.grace_until).getTime() > options.now
    if (inGrace) return options.dismissed ? 'pass' : 'grace'
    return 'hard'
}
