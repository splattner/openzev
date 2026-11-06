import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { DeliveryResult } from '../src/types/api'

vi.mock('react-i18next', () => ({
    useTranslation: () => ({ t: (key: string, options?: { count?: number }) => (options?.count !== undefined ? `${key}:${options.count}` : key) }),
}))

const post = vi.fn()
vi.mock('../src/lib/api/client', async (importOriginal) => ({
    ...(await importOriginal<typeof import('../src/lib/api/client')>()),
    api: { post: (...args: unknown[]) => post(...args), get: vi.fn() },
}))

import { DeliveryResultNotice } from '../src/features/inbox/DeliveryResultNotice'
import { issueAnnualStatements, issueTariffOverview, uploadInboxDocument } from '../src/lib/api/inbox'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const result = (overrides: Partial<DeliveryResult> = {}): DeliveryResult => ({
    batch_id: 'b', delivered: 3, without_account: 0, emailed: 0, without_email: 0, documents: [], ...overrides,
})

beforeEach(() => {
    post.mockReset()
    post.mockResolvedValue({ data: result() })
})

describe('the notify flag', () => {
    it('is sent with an upload only when it is set', async () => {
        const file = new File(['%PDF-'], 'a.pdf', { type: 'application/pdf' })
        await uploadInboxDocument({ zev: 'z', title: 'T', file, audience: 'all' })
        expect((post.mock.calls[0][1] as FormData).has('notify')).toBe(false)

        await uploadInboxDocument({ zev: 'z', title: 'T', file, audience: 'all', notify: true })
        expect((post.mock.calls[1][1] as FormData).get('notify')).toBe('true')
    })

    it('is sent with an issue only when it is set', async () => {
        await issueAnnualStatements({ zev: 'z', year: 2025 })
        await issueTariffOverview({ zev: 'z', notify: true })
        expect(post.mock.calls[0][1].notify).toBeUndefined()
        expect(post.mock.calls[1][1].notify).toBe(true)
    })
})

describe('DeliveryResultNotice', () => {
    function text(value: DeliveryResult) {
        const container = document.createElement('div')
        act(() => { createRoot(container).render(createElement(DeliveryResultNotice, { result: value })) })
        return container.textContent ?? ''
    }

    it('says nothing about email when none was asked for', () => {
        const shown = text(result())
        expect(shown).toContain('inbox.result.delivered:3')
        expect(shown).not.toContain('inbox.result.emailed')
        expect(shown).not.toContain('inbox.result.withoutEmail')
    })

    it('reports the emails queued and the recipients without an address', () => {
        const shown = text(result({ emailed: 2, without_email: 1 }))
        expect(shown).toContain('inbox.result.emailed:2')
        expect(shown).toContain('inbox.result.withoutEmail:1')
    })
})
