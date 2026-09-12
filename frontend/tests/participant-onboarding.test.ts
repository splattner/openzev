import { describe, it, expect, vi, beforeEach } from 'vitest'

import { consumeOnboardingLink } from '../src/lib/api/public'
import { getOnboardingLink, revokeOnboardingLink, sendOnboardingLink } from '../src/lib/api/zev'
import { api } from '../src/lib/api/client'

describe('consumeOnboardingLink', () => {
    beforeEach(() => vi.restoreAllMocks())

    it('posts the prefix and secret, and returns the sign-in context', async () => {
        const post = vi.spyOn(api, 'post').mockResolvedValue({
            data: { zev_name: 'Sonnenberg', participant_name: 'Ada Lovelace' },
        })

        const result = await consumeOnboardingLink('abc123', 'sec-ret')

        expect(post).toHaveBeenCalledWith('/public/onboarding/consume/', {
            prefix: 'abc123',
            s: 'sec-ret',
        })
        expect(result).toEqual({ zev_name: 'Sonnenberg', participant_name: 'Ada Lovelace' })
    })

    it('propagates a 404 rather than translating it', async () => {
        // Every failure is a 404 by design (see zev/onboarding.py resolve()),
        // so the client must not classify them further.
        vi.spyOn(api, 'post').mockRejectedValue({ response: { status: 404 } })

        await expect(consumeOnboardingLink('abc', 'bad')).rejects.toMatchObject({
            response: { status: 404 },
        })
    })
})

describe('sendOnboardingLink', () => {
    beforeEach(() => vi.restoreAllMocks())

    it('posts to the send-onboarding-link action with no body', async () => {
        const post = vi.spyOn(api, 'post').mockResolvedValue({
            data: { detail: 'sent', onboarding_url: 'https://example.com/join/x?s=y' },
        })

        await sendOnboardingLink('participant-1')

        expect(post).toHaveBeenCalledWith('/zev/participants/participant-1/send-onboarding-link/')
    })
})

describe('getOnboardingLink', () => {
    beforeEach(() => vi.restoreAllMocks())

    it('never sends a request body — nothing to email means nothing to supply', async () => {
        const post = vi.spyOn(api, 'post').mockResolvedValue({
            data: { onboarding_url: 'https://example.com/join/x?s=y', participant: {} },
        })

        await getOnboardingLink('participant-1')

        expect(post).toHaveBeenCalledWith('/zev/participants/participant-1/onboarding-link/')
    })
})

describe('revokeOnboardingLink', () => {
    beforeEach(() => vi.restoreAllMocks())

    it('posts to the revoke action', async () => {
        const post = vi.spyOn(api, 'post').mockResolvedValue({ data: {} })

        await revokeOnboardingLink('participant-1')

        expect(post).toHaveBeenCalledWith('/zev/participants/participant-1/revoke-onboarding-link/')
    })
})
