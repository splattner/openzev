import { StrictMode, act, createElement, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, expect, it, vi } from 'vitest'
import { AccountProfilePage } from '../src/pages/AccountProfilePage'

const state = vi.hoisted(() => ({ params: new URLSearchParams(), pushToast: vi.fn(), updateParams: vi.fn() }))
vi.mock('../src/lib/usePageNavigation', () => ({ usePageNavigation: () => ({
    searchParams: state.params, updateParams: state.updateParams,
}) }))
vi.mock('../src/lib/auth', () => ({ useAuth: () => ({ user: {} }) }))
vi.mock('../src/lib/toast', () => ({ useToast: () => ({ pushToast: state.pushToast }) }))
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('@mantine/core', () => {
    const wrapper = ({ children }: { children: ReactNode }) => createElement('div', null, children)
    return { Tabs: Object.assign(wrapper, { List: wrapper, Tab: wrapper, Panel: wrapper }) }
})
vi.mock('../src/components/ConfirmDialog', () => ({ ConfirmDialog: () => null, useConfirmDialog: () => ({}) }))
vi.mock('../src/features/account/TokensSection', () => ({ TokensSection: () => null }))
vi.mock('../src/features/account/LinkedAccountsCard', () => ({ LinkedAccountsCard: () => null }))
vi.mock('../src/features/account/PasswordCard', () => ({ PasswordCard: () => null }))
vi.mock('../src/features/account/ProfileCard', () => ({ ProfileCard: () => null }))
vi.mock('../src/features/account/SessionsCard', () => ({ SessionsCard: () => null }))
vi.mock('../src/features/account/TwoFactorSection', () => ({ TwoFactorSection: () => null }))

describe('OAuth callback feedback', () => {
    it.each([
        ['oauth_error=email_not_verified', 'account.linkEmailNotVerified', 'error'],
        ['oauth_error=session_revoked', 'auth.oauth.errors.generic', 'error'],
        ['oauth_linked=true', 'account.linkSuccess', 'success'],
    ])('handles %s once in StrictMode', async (query, message, kind) => {
        vi.clearAllMocks()
        state.params = new URLSearchParams(query)
        const container = document.createElement('div')
        document.body.appendChild(container)
        const root = createRoot(container)
        try {
            await act(async () => root.render(createElement(StrictMode, null,
                createElement(QueryClientProvider, { client: new QueryClient(), children: createElement(AccountProfilePage) }),
            )))
            expect(state.pushToast.mock.calls).toEqual([[message, kind]])
            expect(state.updateParams).toHaveBeenCalledOnce()
            const updated = new URLSearchParams(state.params)
            state.updateParams.mock.calls[0][0](updated)
            expect(updated.get('tab')).toBe('security')
            expect(updated.has('oauth_error')).toBe(false)
            expect(updated.has('oauth_linked')).toBe(false)
        } finally {
            await act(async () => root.unmount())
            container.remove()
        }
    })
})
