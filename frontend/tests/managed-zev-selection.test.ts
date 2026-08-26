import { createRoot } from 'react-dom/client'
import { act, createElement, useEffect } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fetchZevs } from '../src/lib/api/zev'
import { ManagedZevProvider, resolveManagedSelection, useManagedZev } from '../src/lib/managedZev'
import type { PaginatedResponse, User, UserRole, Zev } from '../src/types/api'

type IdOnly = Pick<Zev, 'id'>

const zev = (id: string): IdOnly => ({ id })

describe('resolveManagedSelection — admin', () => {
    it('is always selectable and can pick any managed ZEV', () => {
        const resolution = resolveManagedSelection({
            role: 'admin',
            managedZevs: [zev('z1'), zev('z2')],
            currentId: 'z1',
        })
        expect(resolution.isSelectable).toBe(true)
        expect(resolution.isAllowedId('z1')).toBe(true)
        expect(resolution.isAllowedId('z2')).toBe(true)
    })

    it('keeps the current selection while it exists', () => {
        const resolution = resolveManagedSelection({
            role: 'admin',
            managedZevs: [zev('z1'), zev('z2')],
            currentId: 'z2',
        })
        expect(resolution.selection).toBe('z2')
    })

    it('falls back to the first ZEV when the stored id is stale', () => {
        const resolution = resolveManagedSelection({
            role: 'admin',
            managedZevs: [zev('z1'), zev('z2')],
            currentId: 'deleted-zev',
        })
        expect(resolution.selection).toBe('z1')
        expect(resolution.isAllowedId('deleted-zev')).toBe(false)
    })
})

describe('resolveManagedSelection — zev_owner', () => {
    it('pins a single owned ZEV and is not selectable', () => {
        const resolution = resolveManagedSelection({
            role: 'zev_owner',
            managedZevs: [zev('own')],
            currentId: '',
        })
        expect(resolution.isSelectable).toBe(false)
        expect(resolution.selection).toBe('own')
        expect(resolution.isAllowedId('own')).toBe(true)
    })

    it('an owner with more than one ZEV can switch among them', () => {
        const resolution = resolveManagedSelection({
            role: 'zev_owner',
            managedZevs: [zev('own1'), zev('own2')],
            currentId: 'own1',
        })
        expect(resolution.isSelectable).toBe(true)
        expect(resolution.isAllowedId('own1')).toBe(true)
        expect(resolution.isAllowedId('own2')).toBe(true)
        expect(resolution.selection).toBe('own1')
    })

    it('falls back to the first owned ZEV when nothing is stored yet', () => {
        const resolution = resolveManagedSelection({
            role: 'zev_owner',
            managedZevs: [zev('own1'), zev('own2')],
            currentId: '',
        })
        expect(resolution.isSelectable).toBe(true)
        expect(resolution.selection).toBe('own1')
    })

    it('rejects a selection that is not one of the owned ZEVs', () => {
        const resolution = resolveManagedSelection({
            role: 'zev_owner',
            managedZevs: [zev('own1'), zev('own2')],
            currentId: 'own1',
        })
        expect(resolution.isAllowedId('someone-elses-zev')).toBe(false)
    })

    it('keeps an owned selection instead of re-pinning to the first entry', () => {
        const resolution = resolveManagedSelection({
            role: 'zev_owner',
            managedZevs: [zev('own1'), zev('own2')],
            currentId: 'own2',
        })
        expect(resolution.selection).toBe('own2')
    })

    it('falls back to the first owned ZEV when the stored id is stale', () => {
        const resolution = resolveManagedSelection({
            role: 'zev_owner',
            managedZevs: [zev('taken-over-1'), zev('taken-over-2')],
            currentId: 'transferred-away',
        })
        expect(resolution.isSelectable).toBe(true)
        expect(resolution.selection).toBe('taken-over-1')
        expect(resolution.isAllowedId('transferred-away')).toBe(false)
    })
})

describe('resolveManagedSelection — roles without management scope', () => {
    it.each(['participant', 'guest'] as const)('%s gets neither selection nor switching', (role) => {
        const resolution = resolveManagedSelection({
            role,
            managedZevs: [zev('z1')],
            currentId: 'z1',
        })
        expect(resolution.isSelectable).toBe(false)
        expect(resolution.selection).toBe('')
        expect(resolution.isAllowedId('z1')).toBe(false)
    })
})

describe('resolveManagedSelection — missing data', () => {
    it('selects nothing before the user or the list is loaded', () => {
        const resolution = resolveManagedSelection({
            role: undefined,
            managedZevs: [],
            currentId: '',
        })
        expect(resolution.isSelectable).toBe(false)
        expect(resolution.selection).toBe('')
        expect(resolution.isAllowedId('z1')).toBe(false)
    })
})

/**
 * Provider-level coverage for the localStorage wiring that the pure helper
 * cannot exercise: the restored selection must survive the loading phase and
 * not be raced by the reconcile effect (cold cache), and a stale stored ID
 * must be healed back to the first managed ZEV.
 */

const authState = vi.hoisted(() => ({ current: null as User | null }))

vi.mock('../src/lib/auth', () => ({
    useAuth: () => ({ user: authState.current }),
}))

vi.mock('../src/lib/api/zev', () => ({
    fetchZevs: vi.fn(),
}))

const fullZev = (id: string, owner: number): Zev => ({
    id,
    name: id,
    start_date: '2026-01-01',
    owner,
    zev_type: 'zev',
    grid_operator: 'op',
    billing_interval: 'monthly',
})

const userWithRole = (role: UserRole): User => ({
    id: 1,
    username: 'owner1',
    email: 'owner1@example.com',
    first_name: 'Owner',
    last_name: 'One',
    role,
    must_change_password: false,
})

describe('ManagedZevProvider selection persistence', () => {
    let container: HTMLDivElement
    let root: ReturnType<typeof createRoot>
    let resolveFetch: ((value: PaginatedResponse<Zev>) => void) | undefined

    beforeEach(() => {
        ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
        localStorage.clear()
        authState.current = null
        resolveFetch = undefined
        vi.mocked(fetchZevs).mockReset()
        container = document.createElement('div')
        document.body.appendChild(container)
        root = createRoot(container)
    })

    afterEach(() => {
        act(() => {
            root.unmount()
        })
        container.remove()
    })

    function renderProvider() {
        const latest = { current: null as ReturnType<typeof useManagedZev> | null }

        function Harness() {
            const context = useManagedZev()
            useEffect(() => {
                latest.current = context
            }, [context])
            return null
        }

        act(() => {
            root.render(
                createElement(
                    QueryClientProvider,
                    { client: new QueryClient({ defaultOptions: { queries: { retry: false } } }) },
                    createElement(ManagedZevProvider, null, createElement(Harness)),
                ),
            )
        })

        return latest
    }

    function deferFetch() {
        vi.mocked(fetchZevs).mockImplementation(
            () => new Promise<PaginatedResponse<Zev>>((resolve) => { resolveFetch = resolve }),
        )
    }

    /**
     * Resolves the pending ZEV fetch and lets the react-query update land.
     * The observer update is delivered on a later scheduler tick, so a plain
     * microtask flush inside act is not enough — give it a timer tick.
     */
    function resolveTwoZevs() {
        return act(async () => {
            resolveFetch?.({
                count: 2,
                next: null,
                previous: null,
                results: [fullZev('own1', 1), fullZev('own2', 1)],
            })
            await new Promise((resolve) => setTimeout(resolve, 0))
            await new Promise((resolve) => setTimeout(resolve, 0))
        })
    }

    it('restores the persisted selection once the list has loaded (cold cache)', async () => {
        localStorage.setItem('openzev.selectedZevId', 'own2')
        authState.current = userWithRole('zev_owner')
        deferFetch()

        const latest = renderProvider()

        // While the list is loading, the restored ID must not be erased.
        expect(latest.current?.selectedZevId).toBe('own2')

        await resolveTwoZevs()

        expect(latest.current?.managedZevs.map((z) => z.id)).toEqual(['own1', 'own2'])
        expect(latest.current?.selectedZevId).toBe('own2')
        expect(localStorage.getItem('openzev.selectedZevId')).toBe('own2')
    })

    it('heals a stale stored ID back to the first managed ZEV and rewrites localStorage', async () => {
        localStorage.setItem('openzev.selectedZevId', 'transferred-away')
        authState.current = userWithRole('zev_owner')
        deferFetch()

        const latest = renderProvider()

        await resolveTwoZevs()

        expect(latest.current?.selectedZevId).toBe('own1')
        expect(localStorage.getItem('openzev.selectedZevId')).toBe('own1')
    })

    it('keeps a still-valid restored ID instead of re-pinning to the first entry', async () => {
        localStorage.setItem('openzev.selectedZevId', 'own2')
        authState.current = userWithRole('zev_owner')
        deferFetch()

        const latest = renderProvider()

        await resolveTwoZevs()

        expect(latest.current?.managedZevs.map((z) => z.id)).toEqual(['own1', 'own2'])
        expect(latest.current?.selectedZevId).toBe('own2')
        expect(latest.current?.isSelectable).toBe(true)
    })

    it('clears the selection and removes the stored key for a non-managing role', async () => {
        localStorage.setItem('openzev.selectedZevId', 'own1')
        authState.current = userWithRole('participant')

        const latest = renderProvider()

        expect(latest.current?.selectedZevId).toBe('')
        expect(latest.current?.isSelectable).toBe(false)
        expect(localStorage.getItem('openzev.selectedZevId')).toBeNull()
    })
})
