import type { MfaChallenge } from '../types/api'

type Method = MfaChallenge['methods'][number]

/**
 * How a second-step form should behave for the methods the server offered.
 *
 * An account with an authenticator app can answer with a TOTP code or a
 * recovery code and may switch between them. An account whose only factor is a
 * passkey has nothing to generate a code with, so the only thing the form can
 * take is a recovery code — showing a 6-digit field there would be a dead end.
 * Spec 2026-09-two-factor-authentication.md §5.1.
 */
export function challengeInput(
    methods: readonly Method[],
    preferRecovery: boolean,
): { recovery: boolean; canToggle: boolean } {
    const totp = methods.includes('totp')
    const recovery = methods.includes('recovery_code')
    return {
        recovery: !totp || (recovery && preferRecovery),
        canToggle: totp && recovery,
    }
}
