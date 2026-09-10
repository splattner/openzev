import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { act } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { ProtectedRoute } from '../src/components/ProtectedRoute'
import type { UserRole } from '../src/types/api'

vi.mock('react-i18next', () => ({
    useTranslation: () => ({ t: (k: string) => k }),
}))

const mockAuth = vi.fn()

vi.mock('../src/lib/auth', () => ({
    useAuth: () => mockAuth(),
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
            ...extra,
        },
    })
}

function renderGuard(allowedRoles?: UserRole[]) {
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
    })

    it('is default-allow when allowedRoles is omitted (auth-only)', () => {
        mockUser('participant')
        const page = renderGuard(undefined)
        expect(page.allowed()).toBe(true)
        page.unmount()
    })

    it('lets an impersonating admin through participant-only routes', () => {
        // The backend mints the participant role into the impersonation JWT
        // (views_impersonation.py sets refresh["role"]), so role-based guards
        // see an impersonating admin as a participant.
        mockUser('participant', { impersonated_by: { id: 1, username: 'admin' } })
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
