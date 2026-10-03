import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { act } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { ProtectedRoute } from '../src/components/ProtectedRoute'
import type { ShellRole } from '../src/lib/communityAccess'
import type { UserRole } from '../src/types/api'

vi.mock('react-i18next', () => ({
    useTranslation: () => ({ t: (k: string) => k }),
}))

const mockAuth = vi.fn()

vi.mock('../src/lib/auth', () => ({
    useAuth: () => mockAuth(),
}))

const mockManaged = vi.fn(() => ({}))

vi.mock('../src/lib/managedZev', () => ({
    useManagedZev: () => mockManaged(),
    useOptionalManagedZev: () => mockManaged(),
}))

function mockUser(role: UserRole, extra: Record<string, unknown> = {}) {
    mockAuth.mockReturnValue({
        isAuthenticated: true,
        isLoading: false,
        isImpersonating: Boolean(extra.impersonated_by),
        impersonator: extra.impersonated_by ?? null,
        user: {
            id: 7,
            username: `${role}@example.com`,
            email: `${role}@example.com`,
            first_name: '',
            last_name: '',
            role,
            must_change_password: false,
            preferred_zev: null,
            ...extra,
        },
    })
}

function renderGuard(allowedRoles?: ShellRole[]) {
    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)
    act(() => {
        root.render(
            createElement(
                MemoryRouter,
                null,
                createElement(
                    ProtectedRoute,
                    { allowedRoles },
                    createElement('div', { 'data-testid': 'guard-child' }, 'allowed'),
                ),
            ),
        )
    })
    return {
        allowed: () => container.querySelector('[data-testid="guard-child"]')?.textContent === 'allowed',
        unmount: () => {
            act(() => root.unmount())
            container.remove()
        },
    }
}

describe('ProtectedRoute unit (role matrix lives in route-guard-matrix.test.ts)', () => {
    beforeEach(() => {
        mockAuth.mockReset()
        mockManaged.mockReturnValue({})
    })

    it('is default-allow when allowedRoles is omitted (auth-only)', () => {
        mockUser('user')
        const page = renderGuard(undefined)
        expect(page.allowed()).toBe(true)
        page.unmount()
    })

    it('lets an impersonating admin through participant-only routes', () => {
        // Impersonation is on the account (#761): the session carries the
        // target's relations, so the guard sees a participant.
        mockUser('user', { impersonated_by: { id: 1, username: 'admin' } })
        mockManaged.mockReturnValue({ relation: 'participant' })
        const page = renderGuard(['participant'])
        expect(page.allowed()).toBe(true)
        page.unmount()
    })

    it('redirects unauthenticated users to /login', () => {
        mockAuth.mockReturnValue({ isAuthenticated: false, isLoading: false, user: null, isImpersonating: false })
        const page = renderGuard(['participant'])
        expect(page.allowed()).toBe(false)
        page.unmount()
    })
})
