import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'

const auth = vi.hoisted(() => vi.fn())
vi.mock('../src/lib/auth', () => ({ useAuth: () => auth() }))
const managed = vi.hoisted(() => vi.fn())
vi.mock('../src/lib/managedZev', () => ({ useManagedZev: () => managed() }))
vi.mock('../src/pages/OverviewPage', () => ({
    OverviewPage: () => createElement('div', { 'data-testid': 'overview' }),
}))
vi.mock('../src/pages/DashboardPage', () => ({
    DashboardPage: () => createElement('div', { 'data-testid': 'dashboard' }),
}))

import { HomePage } from '../src/pages/HomePage'

const cleanups: Array<() => void> = []
afterEach(() => cleanups.splice(0).forEach((cleanup) => cleanup()))

/** An admin, or a non-admin account with this relation to the selected community (#761). */
function renderRole(persona: 'admin' | 'manager' | 'participant') {
    auth.mockReturnValue({ user: { role: persona === 'admin' ? 'admin' : 'user' } })
    managed.mockReturnValue({ relation: persona })
    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)
    act(() => root.render(createElement(HomePage)))
    cleanups.push(() => {
        act(() => root.unmount())
        container.remove()
    })
    return container
}

describe('role-aware home page', () => {
    it.each(['admin', 'manager'] as const)('opens Overview for %s', (role) => {
        const page = renderRole(role)
        expect(page.querySelector('[data-testid="overview"]')).not.toBeNull()
        expect(page.querySelector('[data-testid="dashboard"]')).toBeNull()
    })

    it('keeps the participant dashboard at the root route', () => {
        const page = renderRole('participant')
        expect(page.querySelector('[data-testid="dashboard"]')).not.toBeNull()
        expect(page.querySelector('[data-testid="overview"]')).toBeNull()
    })
})
