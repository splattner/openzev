import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MantineProvider } from '@mantine/core'
import { resolveAccountTab } from '../src/features/account/accountTabs'
import { AccountProfilePage } from '../src/pages/AccountProfilePage'

const auth = vi.hoisted(() => ({ mustChangePassword: false }))

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('../src/lib/toast', () => ({ useToast: () => ({ pushToast: vi.fn() }) }))
vi.mock('../src/lib/auth', () => ({
    useAuth: () => ({ user: { must_change_password: auth.mustChangePassword } }),
}))
// The cards have their own concerns and API calls; what is under test here is
// which of them the page shows for which tab.
vi.mock('../src/features/account/ProfileCard', () => ({ ProfileCard: () => createElement('div', null, 'profile-card') }))
vi.mock('../src/features/account/PasswordCard', () => ({ PasswordCard: () => createElement('div', null, 'password-card') }))
vi.mock('../src/features/account/LinkedAccountsCard', () => ({ LinkedAccountsCard: () => createElement('div', null, 'linked-card') }))
vi.mock('../src/features/account/SessionsCard', () => ({ SessionsCard: () => createElement('div', null, 'sessions-card') }))
vi.mock('../src/features/account/TwoFactorSection', () => ({ TwoFactorSection: () => createElement('div', null, 'two-factor-card') }))
vi.mock('../src/features/account/ApiKeysSection', () => ({ ApiKeysSection: () => createElement('div', null, 'api-keys-card') }))

const params = (query: string) => new URLSearchParams(query)

describe('resolveAccountTab', () => {
    it('opens Profile by default', () => {
        expect(resolveAccountTab(params(''), { mustChangePassword: false })).toBe('profile')
    })

    it('honours an explicit valid tab', () => {
        expect(resolveAccountTab(params('tab=api-keys'), { mustChangePassword: false })).toBe('api-keys')
        expect(resolveAccountTab(params('tab=security'), { mustChangePassword: false })).toBe('security')
    })

    it('falls back for an unknown tab rather than showing an empty page', () => {
        expect(resolveAccountTab(params('tab=bogus'), { mustChangePassword: false })).toBe('profile')
    })

    it('opens Security for a forced password change, where the password form lives', () => {
        expect(resolveAccountTab(params(''), { mustChangePassword: true })).toBe('security')
    })

    it('opens Security when returning from an OAuth link attempt', () => {
        expect(resolveAccountTab(params('oauth_linked=true'), { mustChangePassword: false })).toBe('security')
        expect(resolveAccountTab(params('oauth_error=already_linked_other'), { mustChangePassword: false })).toBe('security')
    })

    it('lets an explicit tab beat the contextual default', () => {
        expect(resolveAccountTab(params('tab=profile'), { mustChangePassword: true })).toBe('profile')
    })
})

function RoutedPage() {
    const location = useLocation()
    return createElement('div', null,
        createElement('output', null, location.pathname + location.search),
        createElement(AccountProfilePage),
    )
}

const cleanups: (() => void)[] = []
afterEach(() => {
    cleanups.splice(0).forEach((cleanup) => cleanup())
    auth.mustChangePassword = false
})

async function render(url: string) {
    const container = document.createElement('div')
    document.body.append(container)
    const root = createRoot(container)
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    cleanups.push(() => { act(() => root.unmount()); client.clear(); container.remove() })
    await act(async () => root.render(
        createElement(QueryClientProvider, { client },
            createElement(MantineProvider, null,
                createElement(MemoryRouter, { initialEntries: [url] }, createElement(RoutedPage)))),
    ))
    return container
}

const tab = (container: Element, value: string) =>
    Array.from(container.querySelectorAll<HTMLButtonElement>('[role="tab"]'))
        .find((button) => button.textContent === `account.tabs.${value}`)!

/** Panels stay mounted but hidden; the visible one is the active tab's. */
function visibleText(container: Element) {
    const active = container.querySelector('[role="tab"][data-active]')!
    return container.ownerDocument.getElementById(active.getAttribute('aria-controls')!)!.textContent
}

describe('account page tabs', () => {
    it('renders the standard tab strip with three tabs', async () => {
        const container = await render('/account')

        expect(container.querySelector('.app-tabs')).not.toBeNull()
        expect(container.querySelectorAll('[role="tab"]')).toHaveLength(3)
        expect(tab(container, 'profile').hasAttribute('data-active')).toBe(true)
        expect(visibleText(container)).toContain('profile-card')
        expect(visibleText(container)).not.toContain('password-card')
    })

    it('groups the ways to sign in under Security', async () => {
        const container = await render('/account?tab=security')

        const text = visibleText(container)
        expect(text).toContain('password-card')
        expect(text).toContain('linked-card')
        expect(text).toContain('two-factor-card')
        expect(text).not.toContain('api-keys-card')
    })

    it('shows API keys on their own tab', async () => {
        const container = await render('/account?tab=api-keys')

        expect(visibleText(container)).toContain('api-keys-card')
    })

    it('switches tabs and records the choice in the URL', async () => {
        const container = await render('/account')

        await act(async () => { tab(container, 'security').click() })

        expect(container.querySelector('output')?.textContent).toBe('/account?tab=security')
        expect(visibleText(container)).toContain('two-factor-card')
    })

    it('keeps every panel mounted, so one-time secrets survive a tab switch', async () => {
        // Recovery codes and a new API key are shown once, in component state.
        const container = await render('/account?tab=security')

        expect(container.textContent).toContain('two-factor-card')
        expect(container.textContent).toContain('api-keys-card')
    })

    it('lands a forced password change on Security and keeps the banner above the tabs', async () => {
        auth.mustChangePassword = true

        const container = await render('/account')

        expect(tab(container, 'security').hasAttribute('data-active')).toBe(true)
        expect(container.querySelector('.warning-banner')?.textContent).toContain('account.passwordChangeRequired')
    })
})
