import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MantineProvider } from '@mantine/core'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flush } from './pdf-test-utils'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('../src/lib/toast', () => ({ useToast: () => ({ pushToast: vi.fn() }) }))
vi.mock('../src/lib/appSettings', () => ({ useAppSettings: () => ({ settings: {} }), formatShortDate: (date: string) => date }))
vi.mock('../src/lib/api/auth', () => ({
    fetchOAuthProviders: vi.fn(),
    fetchSocialAccounts: vi.fn(() => Promise.resolve([])),
    deleteSocialAccount: vi.fn(),
    oauthLinkInitiate: vi.fn(),
}))

import { LinkedAccountsCard } from '../src/features/account/LinkedAccountsCard'
import * as authApi from '../src/lib/api/auth'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

async function render() {
    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    await act(async () => root.render(createElement(MantineProvider, null,
        createElement(QueryClientProvider, { client }, createElement(LinkedAccountsCard, { onUnlink: vi.fn() })),
    )))
    await flush()
    return { container, unmount: () => { act(() => root.unmount()); container.remove() } }
}

describe('LinkedAccountsCard providers', () => {
    beforeEach(() => vi.clearAllMocks())

    it('reports a failed load with a retry, not an empty list', async () => {
        vi.mocked(authApi.fetchOAuthProviders).mockRejectedValue(new Error('down'))
        const { container, unmount } = await render()
        expect(container.textContent).toContain('account.providersLoadError')
        expect(container.querySelector('button')).toBeTruthy()
        expect(container.textContent).not.toContain('account.noProviders')
        unmount()
    })

    it('says no provider is configured only after an empty response', async () => {
        vi.mocked(authApi.fetchOAuthProviders).mockResolvedValue([])
        const { container, unmount } = await render()
        expect(container.textContent).toContain('account.noProviders')
        expect(container.textContent).not.toContain('account.providersLoadError')
        unmount()
    })

    it('lists the configured providers', async () => {
        vi.mocked(authApi.fetchOAuthProviders).mockResolvedValue([{ id: 1, name: 'google', display_name: 'Google', enabled: true }])
        const { container, unmount } = await render()
        expect(container.textContent).toContain('Google')
        expect(container.textContent).not.toContain('account.noProviders')
        unmount()
    })
})
