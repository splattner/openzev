import { waitForCondition } from './helpers/waitForCondition'
import { createRoot } from 'react-dom/client'
import { act, createElement, StrictMode, useEffect } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fetchZevs } from '../src/lib/api/zev'
import { ManagedZevProvider, resolveCommunitySelection, useManagedZev } from '../src/lib/managedZev'
import type { Membership, User, Zev } from '../src/types/api'

describe('resolveCommunitySelection — admin', () => {
    it('is always selectable and can pick any managed ZEV', () => {
        const resolution = resolveCommunitySelection({
            isAdmin: true,
            entryIds: ['z1', 'z2'],
            currentId: 'z1',
        })
        expect(resolution.isSelectable).toBe(true)
        expect(resolution.isAllowedId('z1')).toBe(true)
        expect(resolution.isAllowedId('z2')).toBe(true)
    })

    it('keeps the current selection while it exists', () => {
        const resolution = resolveCommunitySelection({
            isAdmin: true,
            entryIds: ['z1', 'z2'],
            currentId: 'z2',
        })
        expect(resolution.selection).toBe('z2')
    })

    it('falls back to the first ZEV when the stored id is stale', () => {
        const resolution = resolveCommunitySelection({
            isAdmin: true,
            entryIds: ['z1', 'z2'],
            currentId: 'deleted-zev',
        })
        expect(resolution.selection).toBe('z1')
        expect(resolution.isAllowedId('deleted-zev')).toBe(false)
    })

    it('uses the account preference instead of the first-by-name ZEV', () => {
        const resolution = resolveCommunitySelection({
            isAdmin: true,
            entryIds: ['z1', 'z2'],
            currentId: '',
            preferredZevId: 'z2',
        })
        expect(resolution.selection).toBe('z2')
    })

    it('ignores a preference for a ZEV that is no longer managed', () => {
        const resolution = resolveCommunitySelection({
            isAdmin: true,
            entryIds: ['z1'],
            currentId: '',
            preferredZevId: 'transferred-away',
        })
        expect(resolution.selection).toBe('z1')
    })
})

describe('resolveCommunitySelection — non-admin account', () => {
    it('pins a single community and is not selectable', () => {
        const resolution = resolveCommunitySelection({
            isAdmin: false,
            entryIds: ['own'],
            currentId: '',
        })
        expect(resolution.isSelectable).toBe(false)
        expect(resolution.selection).toBe('own')
        expect(resolution.isAllowedId('own')).toBe(true)
    })

    it('an account with more than one community can switch among them', () => {
        const resolution = resolveCommunitySelection({
            isAdmin: false,
            entryIds: ['own1', 'own2'],
            currentId: 'own1',
        })
        expect(resolution.isSelectable).toBe(true)
        expect(resolution.isAllowedId('own1')).toBe(true)
        expect(resolution.isAllowedId('own2')).toBe(true)
        expect(resolution.selection).toBe('own1')
    })

    it('falls back to the first owned ZEV when nothing is stored yet', () => {
        const resolution = resolveCommunitySelection({
            isAdmin: false,
            entryIds: ['own1', 'own2'],
            currentId: '',
        })
        expect(resolution.isSelectable).toBe(true)
        expect(resolution.selection).toBe('own1')
    })

    it('rejects a selection that is not one of the owned ZEVs', () => {
        const resolution = resolveCommunitySelection({
            isAdmin: false,
            entryIds: ['own1', 'own2'],
            currentId: 'own1',
        })
        expect(resolution.isAllowedId('someone-elses-zev')).toBe(false)
    })

    it('keeps an owned selection instead of re-pinning to the first entry', () => {
        const resolution = resolveCommunitySelection({
            isAdmin: false,
            entryIds: ['own1', 'own2'],
            currentId: 'own2',
        })
        expect(resolution.selection).toBe('own2')
    })

    it('prefers the explicit in-session pick over the account preference', () => {
        const resolution = resolveCommunitySelection({
            isAdmin: false,
            entryIds: ['own1', 'own2'],
            currentId: 'own2',
            preferredZevId: 'own1',
        })
        expect(resolution.selection).toBe('own2')
    })

    it('lands on the account preference when nothing is picked yet', () => {
        const resolution = resolveCommunitySelection({
            isAdmin: false,
            entryIds: ['own1', 'own2'],
            currentId: '',
            preferredZevId: 'own2',
        })
        expect(resolution.selection).toBe('own2')
    })

    it('falls back to the first owned ZEV when the stored id is stale', () => {
        const resolution = resolveCommunitySelection({
            isAdmin: false,
            entryIds: ['taken-over-1', 'taken-over-2'],
            currentId: 'transferred-away',
        })
        expect(resolution.isSelectable).toBe(true)
        expect(resolution.selection).toBe('taken-over-1')
        expect(resolution.isAllowedId('transferred-away')).toBe(false)
    })
})

describe('resolveCommunitySelection — no community', () => {
    it('selects nothing for an account without a community, or before it is loaded', () => {
        const resolution = resolveCommunitySelection({
            isAdmin: false,
            entryIds: [],
            currentId: 'z1',
        })
        expect(resolution.isSelectable).toBe(false)
        expect(resolution.selection).toBe('')
        expect(resolution.isAllowedId('z1')).toBe(false)
    })
})

/**
 * Provider-level coverage the pure helper cannot exercise: preference-first
 * selection, optimistic picks, failed-save tolerance, and account-switch
 * isolation (no cross-account leakage; no browser storage is consulted).
 */

const authState = vi.hoisted(() => ({ current: null as User | null }))
const updatePreferredZev = vi.hoisted(() => vi.fn<(zevId: string | null) => Promise<void>>())

vi.mock('../src/lib/auth', () => ({
    useAuth: () => ({ user: authState.current, updatePreferredZev }),
}))

vi.mock('../src/lib/api/zev', () => ({
    fetchZevs: vi.fn(),
}))

const fullZev = (id: string): Zev => ({
    id,
    name: id,
    start_date: '2026-01-01',
    zev_type: 'zev',
    grid_operator: 'op',
    billing_interval: 'monthly',
})

const managing = (zev: string): Membership => ({
    zev, zev_name: zev, zev_disabled: false, access: 'manager', participants: [],
})

/** A non-admin account; by default the manager of own1 and own2. */
const account = (memberships: Membership[] = [managing('own1'), managing('own2')]): User => ({
    id: 1,
    username: 'owner1',
    email: 'owner1@example.com',
    first_name: 'Owner',
    last_name: 'One',
    role: 'user',
    must_change_password: false,
    preferred_zev: null,
    memberships,
})

const adminUser = (id: number, preferredZev: string | null): User => ({
    id,
    username: `admin${id}`,
    email: `admin${id}@example.com`,
    first_name: 'Admin',
    last_name: `${id}`,
    role: 'admin',
    must_change_password: false,
    preferred_zev: preferredZev,
})

describe('ManagedZevProvider selection persistence', () => {
    let container: HTMLDivElement
    let root: ReturnType<typeof createRoot>
    let resolveFetch: ((value: Zev[]) => void) | undefined

    beforeEach(() => {
        authState.current = null
        resolveFetch = undefined
        vi.mocked(fetchZevs).mockReset()
        vi.mocked(updatePreferredZev).mockReset()
        vi.mocked(updatePreferredZev).mockResolvedValue(undefined)
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

        function render() {
            act(() => {
                root.render(
                    createElement(
                        QueryClientProvider,
                        { client: new QueryClient({ defaultOptions: { queries: { retry: false } } }) },
                        createElement(StrictMode, null, createElement(ManagedZevProvider, null, createElement(Harness))),
                    ),
                )
            })
        }

        render()
        return { latest, rerender: render }
    }

    function deferFetch() {
        vi.mocked(fetchZevs).mockImplementation(
            () => new Promise<Zev[]>((resolve) => { resolveFetch = resolve }),
        )
    }

    /**
     * Resolves the pending ZEV fetch and lets the react-query update land.
     * The observer update is delivered on a later scheduler tick, so a plain
     * microtask flush inside act is not enough — give it a timer tick.
     */
    function resolveTwoZevs() {
        return act(async () => {
            resolveFetch?.([fullZev('own1'), fullZev('own2')])
            await new Promise((resolve) => setTimeout(resolve, 0))
            await new Promise((resolve) => setTimeout(resolve, 0))
        })
    }

    it('lands on the account preference from its memberships, before the ZEV list arrives', async () => {
        authState.current = { ...account(), preferred_zev: 'own2' }
        deferFetch()

        const { latest } = renderProvider()

        expect(latest.current?.selectedZevId).toBe('own2')
        expect(latest.current?.selectedZev).toBeNull()

        await resolveTwoZevs()

        expect(latest.current?.managedZevs.map((z) => z.id)).toEqual(['own1', 'own2'])
        expect(latest.current?.selectedZevId).toBe('own2')
    })

    it('falls back to the first managed ZEV without an account preference', async () => {
        authState.current = account()
        deferFetch()

        const { latest } = renderProvider()

        await resolveTwoZevs()

        expect(latest.current?.selectedZevId).toBe('own1')
    })

    it('reconciles a stale management membership to a remaining readable community', async () => {
        authState.current = { ...account(), preferred_zev: 'own1' }
        deferFetch()
        const { latest } = renderProvider()
        await resolveTwoZevs()
        act(() => latest.current?.setSelectedZevId('own1'))
        vi.mocked(fetchZevs).mockResolvedValue([fullZev('own2', 1)])
        act(() => latest.current?.refetch())
        await waitForCondition(() => latest.current?.selectedZevId === 'own2', 'remaining community')
        expect(latest.current?.selectedZevId).toBe('own2')
        expect(latest.current?.entries.map(entry => entry.id)).toEqual(['own2'])
        expect(authState.current.memberships).toHaveLength(2)
    })

    it('keeps cached management memberships on a failed refetch', async () => {
        authState.current = { ...account(), preferred_zev: 'own1' }
        deferFetch()
        const { latest } = renderProvider()
        await resolveTwoZevs()
        vi.mocked(fetchZevs).mockRejectedValue(new Error('Refresh failed'))
        act(() => latest.current?.refetch())
        await waitForCondition(() => latest.current?.isError === true, 'scope refresh failure')
        expect(latest.current?.isError).toBe(true)
        expect(latest.current?.selectedZevId).toBe('own1')
        expect(latest.current?.entries.map(entry => entry.id)).toEqual(['own1', 'own2'])
    })

    it('retains participant scope without a readable management record', async () => {
        authState.current = { ...account([
            managing('own1'),
            { zev: 'own2', zev_name: 'own2', zev_disabled: false, access: null,
                participants: [{ id: 'p2', valid_from: '2026-01-01', valid_to: null, live: true }] },
        ]), preferred_zev: 'own2' }
        vi.mocked(fetchZevs).mockResolvedValue([fullZev('own1', 1)])
        const { latest } = renderProvider()
        await waitForCondition(() => latest.current?.relation === 'participant', 'participant scope')
        expect(latest.current?.selectedZevId).toBe('own2')
        expect(latest.current?.relation).toBe('participant')
        expect(latest.current?.selectedZev).toBeNull()
        expect(latest.current?.entries.map(entry => entry.id)).toEqual(['own1', 'own2'])
    })

    it('ignores an account preference for a ZEV that is no longer managed', async () => {
        authState.current = { ...account(), preferred_zev: 'transferred-away' }
        deferFetch()

        const { latest } = renderProvider()

        await resolveTwoZevs()

        expect(latest.current?.selectedZevId).toBe('own1')
    })

    it('keeps an explicit pick instead of re-pinning to the first entry', async () => {
        authState.current = account()
        deferFetch()

        const { latest } = renderProvider()

        await resolveTwoZevs()

        act(() => {
            latest.current?.setSelectedZevId('own2')
        })

        expect(latest.current?.selectedZevId).toBe('own2')
        expect(latest.current?.isSelectable).toBe(true)
    })

    it('prefers the explicit pick even when the account preference differs', async () => {
        authState.current = { ...account(), preferred_zev: 'own1' }
        deferFetch()

        const { latest } = renderProvider()

        await resolveTwoZevs()

        act(() => {
            latest.current?.setSelectedZevId('own2')
        })

        expect(latest.current?.selectedZevId).toBe('own2')
    })

    it('persists a user-initiated switch as the account preference', async () => {
        authState.current = account()
        deferFetch()

        const { latest } = renderProvider()

        await resolveTwoZevs()

        expect(latest.current?.selectedZevId).toBe('own1')

        act(() => {
            latest.current?.setSelectedZevId('own2')
        })

        expect(vi.mocked(updatePreferredZev)).toHaveBeenCalledWith('own2')
        expect(latest.current?.selectedZevId).toBe('own2')
    })

    it('does not persist a switch to a ZEV the user no longer manages', async () => {
        authState.current = account()
        deferFetch()

        const { latest } = renderProvider()

        await resolveTwoZevs()

        act(() => {
            latest.current?.setSelectedZevId('transferred-away')
        })

        expect(vi.mocked(updatePreferredZev)).not.toHaveBeenCalled()
        expect(latest.current?.selectedZevId).toBe('own1')
    })

    it('a failed preference save leaves the local selection usable', async () => {
        authState.current = account()
        deferFetch()

        const { latest } = renderProvider()

        await resolveTwoZevs()

        vi.mocked(updatePreferredZev).mockRejectedValueOnce(new Error('network down'))
        act(() => {
            latest.current?.setSelectedZevId('own2')
        })

        expect(vi.mocked(updatePreferredZev)).toHaveBeenCalledWith('own2')
        expect(latest.current?.selectedZevId).toBe('own2')
    })

    it('an account switch drops the previous pick and honors the new preference', async () => {
        authState.current = adminUser(1, 'own1')
        deferFetch()

        const { latest, rerender } = renderProvider()

        await resolveTwoZevs()

        expect(latest.current?.selectedZevId).toBe('own1')

        act(() => {
            latest.current?.setSelectedZevId('own2')
        })

        expect(latest.current?.selectedZevId).toBe('own2')

        // A second user on the same browser must land on their own preference.
        authState.current = adminUser(2, 'own1')
        rerender()
        await resolveTwoZevs()

        expect(latest.current?.selectedZevId).toBe('own1')
    })

    it('an account switch without a preference falls back to the first managed ZEV', async () => {
        authState.current = adminUser(1, 'own2')
        deferFetch()

        const { latest, rerender } = renderProvider()

        await resolveTwoZevs()

        expect(latest.current?.selectedZevId).toBe('own2')

        authState.current = adminUser(2, null)
        rerender()
        await resolveTwoZevs()

        expect(latest.current?.selectedZevId).toBe('own1')
    })

    it('clears the selection for an account without a community', async () => {
        authState.current = account([])

        const { latest } = renderProvider()

        expect(latest.current?.selectedZevId).toBe('')
        expect(latest.current?.isSelectable).toBe(false)
    })
})
