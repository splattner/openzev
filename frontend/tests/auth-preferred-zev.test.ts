import { createRoot } from 'react-dom/client'
import { act, createElement, useEffect } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AuthProvider, useAuth } from '../src/lib/auth'
import type { User } from '../src/types/api'

const apiAuth = vi.hoisted(() => ({
    fetchMe: vi.fn(),
    impersonateParticipant: vi.fn(),
    login: vi.fn(),
    logout: vi.fn(),
    stopImpersonation: vi.fn(),
    updateProfile: vi.fn(),
}))

vi.mock('../src/lib/api/auth', () => ({
    fetchMe: apiAuth.fetchMe,
    impersonateParticipant: apiAuth.impersonateParticipant,
    login: apiAuth.login,
    logout: apiAuth.logout,
    stopImpersonation: apiAuth.stopImpersonation,
    updateProfile: apiAuth.updateProfile,
}))

const baseUser = (preferredZev: string | null): User => ({
    id: 1,
    username: 'owner1',
    email: 'owner1@example.com',
    first_name: 'Owner',
    last_name: 'One',
    role: 'zev_owner',
    must_change_password: false,
    preferred_zev: preferredZev,
})

const adminUser: User = {
    id: 9,
    username: 'admin1',
    email: 'admin1@example.com',
    first_name: 'Admin',
    last_name: 'One',
    role: 'admin',
    must_change_password: false,
    preferred_zev: null,
}

describe('AuthProvider.updatePreferredZev serialization', () => {
    let container: HTMLDivElement
    let root: ReturnType<typeof createRoot>

    beforeEach(() => {
        apiAuth.fetchMe.mockReset()
        apiAuth.impersonateParticipant.mockReset()
        apiAuth.login.mockReset()
        apiAuth.logout.mockReset()
        apiAuth.stopImpersonation.mockReset()
        apiAuth.updateProfile.mockReset()
        apiAuth.fetchMe.mockResolvedValue(baseUser(null))
        apiAuth.impersonateParticipant.mockResolvedValue(undefined)
        apiAuth.login.mockResolvedValue(undefined)
        apiAuth.logout.mockResolvedValue(undefined)
        apiAuth.stopImpersonation.mockResolvedValue(undefined)
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

    // AuthProvider clears the surrounding QueryClient's cache at session
    // boundaries (see #573), so tests need a real client to assert against
    // rather than the mocked-away `useAuth` returned by other suites.
    function renderProvider(queryClient = new QueryClient()) {
        const latest = { current: null as ReturnType<typeof useAuth> | null }

        function Harness() {
            const context = useAuth()
            useEffect(() => {
                latest.current = context
            }, [context])
            return null
        }

        act(() => {
            root.render(
                createElement(
                    QueryClientProvider,
                    { client: queryClient },
                    createElement(AuthProvider, null, createElement(Harness)),
                ),
            )
        })

        return latest
    }

    async function flush() {
        await act(async () => {
            await new Promise((resolve) => setTimeout(resolve, 0))
            await new Promise((resolve) => setTimeout(resolve, 0))
        })
    }

    it('persists rapid selections in order so the latest choice wins', async () => {
        const latest = renderProvider()
        await flush()
        expect(latest.current?.user?.preferred_zev).toBeNull()

        let resolveB!: (value: User) => void
        let resolveC!: (value: User) => void
        apiAuth.updateProfile
            .mockImplementationOnce(() => new Promise<User>((resolve) => { resolveB = resolve }))
            .mockImplementationOnce(() => new Promise<User>((resolve) => { resolveC = resolve }))

        let saveB!: Promise<void>
        let saveC!: Promise<void>
        act(() => {
            saveB = latest.current!.updatePreferredZev('zB')
            saveC = latest.current!.updatePreferredZev('zC')
        })

        // The second PATCH waits for the first: only one request in flight.
        await flush()
        expect(apiAuth.updateProfile).toHaveBeenCalledTimes(1)
        expect(apiAuth.updateProfile).toHaveBeenLastCalledWith({ preferred_zev: 'zB' })

        await act(async () => {
            resolveB(baseUser('zB'))
            await saveB
            await new Promise((resolve) => setTimeout(resolve, 0))
            await new Promise((resolve) => setTimeout(resolve, 0))
        })
        expect(apiAuth.updateProfile).toHaveBeenCalledTimes(2)
        expect(apiAuth.updateProfile).toHaveBeenLastCalledWith({ preferred_zev: 'zC' })
        // The superseded response must not clobber the newer save.
        expect(latest.current?.user?.preferred_zev).toBeNull()

        await act(async () => {
            resolveC(baseUser('zC'))
            await saveC
            await new Promise((resolve) => setTimeout(resolve, 0))
        })
        expect(latest.current?.user?.preferred_zev).toBe('zC')
    })

    it('a logout in flight drops the late response instead of resurrecting state', async () => {
        const latest = renderProvider()
        await flush()

        let resolveSave!: (value: User) => void
        apiAuth.updateProfile.mockImplementationOnce(
            () => new Promise<User>((resolve) => { resolveSave = resolve }),
        )

        let save!: Promise<void>
        act(() => {
            save = latest.current!.updatePreferredZev('zB')
        })
        // Let the chained PATCH dispatch while the session is still current.
        await flush()
        expect(apiAuth.updateProfile).toHaveBeenCalledTimes(1)

        act(() => {
            latest.current!.logout()
        })

        await act(async () => {
            resolveSave(baseUser('zB'))
            await save.catch(() => undefined)
            await new Promise((resolve) => setTimeout(resolve, 0))
        })

        expect(latest.current?.user).toBeNull()
    })

    it('a logout before the first save resolves cancels the queued second PATCH', async () => {
        const latest = renderProvider()
        await flush()

        let resolveB!: (value: User) => void
        apiAuth.updateProfile.mockImplementationOnce(
            () => new Promise<User>((resolve) => { resolveB = resolve }),
        )

        let saveB!: Promise<void>
        let saveC!: Promise<void>
        act(() => {
            saveB = latest.current!.updatePreferredZev('zB')
            saveC = latest.current!.updatePreferredZev('zC')
        })
        // The first PATCH dispatches while the session is still current …
        await flush()
        expect(apiAuth.updateProfile).toHaveBeenCalledTimes(1)

        // … then the user logs out while it is pending.
        act(() => {
            latest.current!.logout()
        })

        await act(async () => {
            resolveB(baseUser('zB'))
            await saveB.catch(() => undefined)
            await saveC.catch(() => undefined)
            await new Promise((resolve) => setTimeout(resolve, 0))
            await new Promise((resolve) => setTimeout(resolve, 0))
        })

        // The queued save must never dispatch under the next session's cookies.
        expect(apiAuth.updateProfile).toHaveBeenCalledTimes(1)
        expect(latest.current?.user).toBeNull()
    })
})

// Query keys such as ['invoices', 'list', 'all', 'all'] are not partitioned
// by user identity (see queryKeys.ts), so the cache itself is the boundary
// that must turn over at login, logout and each impersonation edge —
// otherwise one account's cached invoices or metering data can render for
// the next (#573).
describe('AuthProvider clears the query cache at session boundaries', () => {
    let container: HTMLDivElement
    let root: ReturnType<typeof createRoot>
    let queryClient: QueryClient

    beforeEach(() => {
        apiAuth.fetchMe.mockReset()
        apiAuth.impersonateParticipant.mockReset()
        apiAuth.login.mockReset()
        apiAuth.logout.mockReset()
        apiAuth.stopImpersonation.mockReset()
        apiAuth.fetchMe.mockResolvedValue(baseUser(null))
        apiAuth.impersonateParticipant.mockResolvedValue(undefined)
        apiAuth.login.mockResolvedValue(undefined)
        apiAuth.logout.mockResolvedValue(undefined)
        apiAuth.stopImpersonation.mockResolvedValue(undefined)
        queryClient = new QueryClient()
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
        const latest = { current: null as ReturnType<typeof useAuth> | null }

        function Harness() {
            const context = useAuth()
            useEffect(() => {
                latest.current = context
            }, [context])
            return null
        }

        act(() => {
            root.render(
                createElement(
                    QueryClientProvider,
                    { client: queryClient },
                    createElement(AuthProvider, null, createElement(Harness)),
                ),
            )
        })

        return latest
    }

    async function flush() {
        await act(async () => {
            await new Promise((resolve) => setTimeout(resolve, 0))
            await new Promise((resolve) => setTimeout(resolve, 0))
        })
    }

    it('drops cached data on logout', async () => {
        const latest = renderProvider()
        await flush()
        queryClient.setQueryData(['invoices', 'list', 'all', 'all'], [{ id: 'inv-a' }])

        act(() => {
            latest.current!.logout()
        })
        await flush()

        expect(queryClient.getQueryData(['invoices', 'list', 'all', 'all'])).toBeUndefined()
    })

    it('drops the previous session\'s cache before a new login resolves', async () => {
        const latest = renderProvider()
        await flush()
        queryClient.setQueryData(['invoices', 'list', 'all', 'all'], [{ id: 'inv-a' }])

        await act(async () => {
            await latest.current!.login('owner2@example.com', 'pw')
        })

        expect(queryClient.getQueryData(['invoices', 'list', 'all', 'all'])).toBeUndefined()
    })

    it('drops the admin\'s cache when impersonation starts', async () => {
        apiAuth.fetchMe.mockResolvedValue(adminUser)
        const latest = renderProvider()
        await flush()
        expect(latest.current?.user?.role).toBe('admin')
        queryClient.setQueryData(['invoices', 'list', 'all', 'all'], [{ id: 'admin-inv' }])

        await act(async () => {
            await latest.current!.startImpersonation(42)
        })

        expect(queryClient.getQueryData(['invoices', 'list', 'all', 'all'])).toBeUndefined()
    })

    it('drops the impersonated participant\'s cache when impersonation stops', async () => {
        const latest = renderProvider()
        await flush()
        queryClient.setQueryData(['invoices', 'list', 'all', 'all'], [{ id: 'participant-inv' }])

        await act(async () => {
            await latest.current!.stopImpersonation()
        })

        expect(queryClient.getQueryData(['invoices', 'list', 'all', 'all'])).toBeUndefined()
    })

    it('cancels an in-flight request so its late response cannot repopulate the cache for the next account', async () => {
        const latest = renderProvider()
        await flush()

        // Participant A's dashboard is mid-fetch when the account switches —
        // this reproduces the issue's "delayed request" scenario.
        let resolveInvoices!: (value: unknown) => void
        const pending = queryClient.fetchQuery({
            queryKey: ['invoices', 'list', 'all', 'all'],
            queryFn: () => new Promise((resolve) => { resolveInvoices = resolve }),
        })
        // Attach a handler in this tick — cancelQueries() rejects it inside
        // logout()'s own async work below, and Node flags a rejection as
        // unhandled unless a .catch already exists by the time that happens.
        const settled = pending.catch(() => undefined)

        act(() => {
            latest.current!.logout()
        })
        await flush()

        // Participant A's response finally arrives after the switch.
        await act(async () => {
            resolveInvoices([{ id: 'stale-for-a' }])
            await settled
            await new Promise((resolve) => setTimeout(resolve, 0))
        })

        expect(queryClient.getQueryData(['invoices', 'list', 'all', 'all'])).toBeUndefined()
    })
})
