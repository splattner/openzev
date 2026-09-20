import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '../src/lib/api/client'
import {
    login,
    passkeyAuthenticateBegin,
    passkeyAuthenticateComplete,
    passkeyRegisterComplete,
    removePasskey,
    renamePasskey,
    resetUserMfa,
    submitMfaChallenge,
} from '../src/lib/api/auth'
import { mfaGateState } from '../src/lib/mfaGate'
import {
    base64urlToBuffer,
    bufferToBase64url,
    createPasskey,
    getPasskey,
    isPasskeySupported,
    PasskeyCancelledError,
} from '../src/lib/webauthn'
import type { MfaStatus } from '../src/types/api'

describe('two-factor API client', () => {
    beforeEach(() => vi.restoreAllMocks())

    it('reports a password login that needs a second step, without a session', async () => {
        vi.spyOn(api, 'post').mockResolvedValue({
            data: { mfa_required: true, mfa_token: 'signed', methods: ['totp', 'recovery_code'] },
        } as never)

        expect(await login('a@example.com', 'pw')).toEqual({
            mfaRequired: true,
            mfaToken: 'signed',
            methods: ['totp', 'recovery_code'],
        })
    })

    it('completes a challenge with the token and a code', async () => {
        const post = vi.spyOn(api, 'post').mockResolvedValue({ data: {} } as never)

        await submitMfaChallenge('signed', '123456')

        expect(post).toHaveBeenCalledWith('/auth/token/mfa/', { mfa_token: 'signed', code: '123456' })
    })

    it('starts passkey sign-in with no email unless one is given', async () => {
        const post = vi.spyOn(api, 'post').mockResolvedValue({ data: { challenge: 'x' } } as never)

        await passkeyAuthenticateBegin()
        await passkeyAuthenticateBegin('a@example.com')

        expect(post).toHaveBeenNthCalledWith(1, '/auth/passkeys/authenticate/begin/', {})
        expect(post).toHaveBeenNthCalledWith(2, '/auth/passkeys/authenticate/begin/', { email: 'a@example.com' })
    })

    it('sends the assertion — and no password — to complete a passkey sign-in', async () => {
        const post = vi.spyOn(api, 'post').mockResolvedValue({ data: {} } as never)

        await passkeyAuthenticateComplete({ id: 'abc' })

        expect(post).toHaveBeenCalledWith('/auth/passkeys/authenticate/complete/', { credential: { id: 'abc' } })
    })

    it('registers, renames and removes passkeys under /me/passkeys/', async () => {
        const post = vi.spyOn(api, 'post').mockResolvedValue({ data: { passkey: {}, recovery_codes: [] } } as never)
        const patch = vi.spyOn(api, 'patch').mockResolvedValue({ data: {} } as never)
        const del = vi.spyOn(api, 'delete').mockResolvedValue({ data: {} } as never)

        await passkeyRegisterComplete({ id: 'c' }, 'Laptop')
        await renamePasskey('p1', 'Work')
        await removePasskey('p1')

        expect(post).toHaveBeenCalledWith('/auth/me/passkeys/register/complete/', { credential: { id: 'c' }, name: 'Laptop' })
        expect(patch).toHaveBeenCalledWith('/auth/me/passkeys/p1/', { name: 'Work' })
        expect(del).toHaveBeenCalledWith('/auth/me/passkeys/p1/')
    })

    it('lets an admin reset a user\'s second factor', async () => {
        const del = vi.spyOn(api, 'delete').mockResolvedValue({
            data: { removed: { totp: 1, passkeys: 2, recovery_codes: 10 } },
        } as never)

        const result = await resetUserMfa(7)

        expect(del).toHaveBeenCalledWith('/auth/users/7/mfa/')
        expect(result.removed.passkeys).toBe(2)
    })
})

describe('webauthn browser bridge', () => {
    afterEach(() => {
        vi.unstubAllGlobals()
    })

    it('round-trips bytes through base64url without padding or unsafe characters', () => {
        const bytes = new Uint8Array([251, 255, 254, 0, 1, 2, 250])
        const encoded = bufferToBase64url(bytes.buffer)

        expect(encoded).not.toMatch(/[+/=]/)
        expect(Array.from(new Uint8Array(base64urlToBuffer(encoded)))).toEqual(Array.from(bytes))
    })

    it('hides passkeys where the browser has no PublicKeyCredential', () => {
        vi.stubGlobal('PublicKeyCredential', undefined)

        expect(isPasskeySupported()).toBe(false)
    })

    it('offers passkeys where WebAuthn exists', () => {
        vi.stubGlobal('PublicKeyCredential', class {})
        vi.stubGlobal('navigator', { credentials: { create: vi.fn(), get: vi.fn() } })

        expect(isPasskeySupported()).toBe(true)
    })

    it('treats a dismissed browser prompt as a cancellation, not an error', async () => {
        const notAllowed = new DOMException('dismissed', 'NotAllowedError')
        vi.stubGlobal('navigator', { credentials: { create: vi.fn().mockRejectedValue(notAllowed), get: vi.fn().mockRejectedValue(notAllowed) } })

        await expect(
            createPasskey({ challenge: 'AA', user: { id: 'AA', name: 'n', displayName: 'n' }, rp: { name: 'x' }, pubKeyCredParams: [] }),
        ).rejects.toBeInstanceOf(PasskeyCancelledError)
        await expect(getPasskey({ challenge: 'AA' })).rejects.toBeInstanceOf(PasskeyCancelledError)
    })

    it('lets unexpected browser errors through unchanged', async () => {
        const boom = new Error('boom')
        vi.stubGlobal('navigator', { credentials: { get: vi.fn().mockRejectedValue(boom) } })

        await expect(getPasskey({ challenge: 'AA' })).rejects.toBe(boom)
    })
})

describe('enrolment gate', () => {
    const NOW = new Date('2026-06-15T12:00:00Z').getTime()
    const base: MfaStatus = {
        totp: null,
        passkeys: [],
        recovery_codes_remaining: 0,
        required: true,
        grace_until: '2026-06-20T12:00:00Z',
    }
    const at = (overrides: Partial<MfaStatus> = {}, extra: Partial<{ dismissed: boolean; impersonating: boolean; pathname: string }> = {}) =>
        mfaGateState({ ...base, ...overrides }, { now: NOW, dismissed: false, impersonating: false, pathname: '/', ...extra })

    it('lets a user through while the status is still loading', () => {
        expect(mfaGateState(undefined, { now: NOW, dismissed: false, impersonating: false, pathname: '/' })).toBe('pass')
    })

    it('does not gate a role the policy does not name', () => {
        expect(at({ required: false, grace_until: null })).toBe('pass')
    })

    it('does not gate a user who already has a factor', () => {
        expect(at({ passkeys: [{ id: 'p', name: 'k', aaguid: '', transports: [], created_at: '', last_used_at: null }] })).toBe('pass')
        expect(at({ totp: { id: 't', confirmed_at: '2026-06-01T00:00:00Z', created_at: '' } })).toBe('pass')
    })

    it('is dismissible before the deadline and stays dismissed for the session', () => {
        expect(at()).toBe('grace')
        expect(at({}, { dismissed: true })).toBe('pass')
    })

    it('is not dismissible after the deadline', () => {
        const expired = { grace_until: '2026-06-10T12:00:00Z' }
        expect(at(expired)).toBe('hard')
        expect(at(expired, { dismissed: true })).toBe('hard')
    })

    it('always lets the account page through so enrolment stays reachable', () => {
        expect(at({ grace_until: '2026-06-10T12:00:00Z' }, { pathname: '/account' })).toBe('pass')
    })

    it('never gates an impersonating admin', () => {
        expect(at({ grace_until: '2026-06-10T12:00:00Z' }, { impersonating: true })).toBe('pass')
    })

    it('treats a required role with no recorded deadline as a hard gate', () => {
        expect(at({ grace_until: null })).toBe('hard')
    })
})
