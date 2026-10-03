import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useCommunityAccess } from '../src/lib/communityAccess'

const hooks = vi.hoisted(() => ({ auth: vi.fn(), managed: vi.fn() }))
vi.mock('../src/lib/auth', () => ({ useAuth: hooks.auth }))
vi.mock('../src/lib/managedZev', () => ({ useManagedZev: hooks.managed, useOptionalManagedZev: hooks.managed }))

function readAccess() {
    let access: ReturnType<typeof useCommunityAccess> | undefined
    function Harness() {
        access = useCommunityAccess()
        return null
    }
    const root = createRoot(document.createElement('div'))
    try {
        act(() => root.render(createElement(Harness)))
        return access
    } finally {
        act(() => root.unmount())
    }
}

afterEach(() => vi.resetAllMocks())

describe('community access provider failures', () => {
    it('permits the outer auth route before the community provider mounts without granting management access', () => {
        hooks.auth.mockReturnValue({ user: { role: 'user' } })
        hooks.managed.mockReturnValue(undefined)
        expect(readAccess()).toMatchObject({ shellRole: 'none', canManage: false })
    })

    it.each(['auth', 'managed'] as const)('propagates unexpected %s provider errors', (hook) => {
        hooks.auth.mockReturnValue({ user: { role: 'admin' } })
        hooks.managed.mockReturnValue({ relation: 'manager' })
        const error = new Error('Provider implementation failed')
        hooks[hook].mockImplementation(() => { throw error })
        expect(readAccess).toThrow(error)
    })

    it('requires AuthProvider instead of supplying a manager fallback', () => {
        hooks.auth.mockImplementation(() => { throw new Error('useAuth must be used within AuthProvider') })
        expect(readAccess).toThrow('useAuth must be used within AuthProvider')
    })
})
