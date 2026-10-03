import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, useLocation } from 'react-router-dom'

const auth = vi.hoisted(() => vi.fn())
vi.mock('../src/lib/auth', () => ({ useAuth: () => auth() }))
const managed = vi.hoisted(() => vi.fn())
vi.mock('../src/lib/managedZev', () => ({ useManagedZev: () => managed(), useOptionalManagedZev: () => managed() }))
vi.mock('../src/pages/OverviewPage', () => ({
    OverviewPage: () => createElement('div', { 'data-testid': 'overview' }),
}))
vi.mock('../src/pages/DashboardPage', () => ({
    DashboardPage: () => createElement('div', { 'data-testid': 'dashboard' }),
}))
vi.mock('../src/pages/GuestHomePage', () => ({
    GuestHomePage: () => createElement('div', { 'data-testid': 'guest' }),
}))

import { HomePage } from '../src/pages/HomePage'

const cleanups: Array<() => void> = []
afterEach(() => cleanups.splice(0).forEach((cleanup) => cleanup()))

/** An admin, or a non-admin account with this relation to the selected community (#761). */
function renderRole(persona: 'admin' | 'manager' | 'viewer' | 'participant' | 'former' | 'none') {
    auth.mockReturnValue({ user: { role: persona === 'admin' ? 'admin' : 'user' } })
    managed.mockReturnValue({ relation: persona === 'none' ? undefined : persona })
    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)
    function Location() {
        return createElement('div', { 'data-testid': 'location' }, useLocation().pathname)
    }
    act(() => root.render(createElement(MemoryRouter, null,
        createElement(HomePage), createElement(Location))))
    cleanups.push(() => {
        act(() => root.unmount())
        container.remove()
    })
    return container
}

describe('role-aware home page', () => {
    it.each(['admin', 'manager', 'viewer'] as const)('opens Overview for %s', (role) => {
        const page = renderRole(role)
        expect(page.querySelector('[data-testid="overview"]')).not.toBeNull()
        expect(page.querySelector('[data-testid="dashboard"]')).toBeNull()
    })

    it('keeps the dashboard at the root route for a current participant', () => {
        const page = renderRole('participant')
        expect(page.querySelector('[data-testid="dashboard"]')).not.toBeNull()
        expect(page.querySelector('[data-testid="overview"]')).toBeNull()
        expect(page.querySelector('[data-testid="guest"]')).toBeNull()
    })

    it('sends a former participant to their invoices', () => {
        const page = renderRole('former')
        expect(page.querySelector('[data-testid="location"]')?.textContent).toBe('/me/invoices')
        expect(page.querySelector('[data-testid="dashboard"]')).toBeNull()
        expect(page.querySelector('[data-testid="guest"]')).toBeNull()
    })

    it('explains the account state without community access', () => {
        const page = renderRole('none')
        expect(page.querySelector('[data-testid="guest"]')).not.toBeNull()
        expect(page.querySelector('[data-testid="dashboard"]')).toBeNull()
        expect(page.querySelector('[data-testid="overview"]')).toBeNull()
    })
})
