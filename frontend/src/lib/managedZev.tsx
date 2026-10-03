import { createContext, useContext, useMemo, useRef, useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchZevs } from './api/zev'
import { queryKeys } from './api/queryKeys'
import { useAuth } from './auth'
import type { User, Zev } from '../types/api'
import { relationOf, type CommunityRelation } from './membership'

export type { CommunityRelation } from './membership'

/** One community the account can switch to. */
export interface CommunityEntry {
    id: string
    name: string
    relation: CommunityRelation
}

interface ManagedZevContextValue {
    /** Communities whose ZEV record the account may read: every one for an admin, else those it holds a grant for. */
    managedZevs: Zev[]
    /** Selectable communities, sorted by name; loaded records reconcile management memberships. */
    entries: CommunityEntry[]
    selectedZevId: string
    /** The selected community's ZEV record, when the account may read it (never for a participant-only entry). */
    selectedZev: Zev | null
    /** The account's relation to the selected community, or `undefined` when none is selected. */
    relation?: CommunityRelation
    isSelectable: boolean
    isLoading: boolean
    isFetching: boolean
    /** The ZEV list request failed — distinct from "this account has none". */
    isError: boolean
    refetch: () => void
    setSelectedZevId: (zevId: string) => void
}

interface ManagedSelection {
    /** User may switch between managed ZEVs. */
    isSelectable: boolean
    /** Reconciled selection: explicit pick if still managed, else account preference, else first managed ZEV. */
    selection: string
    /** Whether a user-initiated selection request targets a managed ZEV. */
    isAllowedId: (zevId: string) => boolean
}

interface CommunitySelectionInput {
    isAdmin: boolean
    /** Ids the account may select, in display order. */
    entryIds: ReadonlyArray<string>
    currentId: string
    preferredZevId?: string | null
}

/**
 * Selection among the communities the account relates to (#761): explicit
 * pick if still listed → account preference if listed → first by name. An
 * admin may always switch; anyone else once there is more than one entry.
 */
export function resolveCommunitySelection({
    isAdmin,
    entryIds,
    currentId,
    preferredZevId = '',
}: CommunitySelectionInput): ManagedSelection {
    const allowedIds = new Set(entryIds)
    const preferredId = preferredZevId ?? ''
    const selection =
        entryIds.length > 0
            ? (allowedIds.has(currentId) ? currentId : allowedIds.has(preferredId) ? preferredId : entryIds[0])
            : ''
    return {
        isSelectable: isAdmin || entryIds.length > 1,
        selection,
        isAllowedId: (zevId) => allowedIds.has(zevId),
    }
}

/** The communities an account can switch between. Admins: every ZEV; anyone else: its memberships. */
export function communityEntries(user: User | null | undefined, zevs: ReadonlyArray<Zev>): CommunityEntry[] {
    if (!user) return []
    if (user.role === 'admin') {
        return zevs.map((zev) => ({ id: zev.id, name: zev.name, relation: 'admin' as const }))
    }
    return (user.memberships ?? []).map((membership) => ({
        id: membership.zev,
        name: membership.zev_name,
        relation: relationOf(membership),
    }))
}

const ManagedZevContext = createContext<ManagedZevContextValue | undefined>(undefined)

export function ManagedZevProvider({ children }: { children: ReactNode }) {
    const { user, updatePreferredZev } = useAuth()
    const isAdmin = user?.role === 'admin'
    const holdsAGrant = (user?.memberships ?? []).some((membership) => membership.access !== null)
    // ZEV records are readable through a grant, or as an admin.
    const mayReadZevs = isAdmin || holdsAGrant

    const zevsQuery = useQuery({
        queryKey: queryKeys.zev.list(),
        queryFn: fetchZevs,
        enabled: mayReadZevs,
    })

    const entries = useMemo(() => {
        const memberships = communityEntries(user, zevsQuery.data ?? [])
        // Before the list arrives, memberships supply scope. Once loaded,
        // a missing management record is no longer selectable; participants need no record.
        if (zevsQuery.data === undefined) return memberships
        const readableIds = new Set(zevsQuery.data.map((zev) => zev.id))
        return memberships.filter((entry) =>
            entry.relation === 'participant' || entry.relation === 'former' || readableIds.has(entry.id),
        )
    }, [user, zevsQuery.data])
    const managedZevs = useMemo(() => {
        const zevs = zevsQuery.data ?? []
        if (isAdmin) return zevs
        const managedIds = new Set(entries.filter((entry) => entry.relation === 'manager' || entry.relation === 'viewer').map((entry) => entry.id))
        return zevs.filter((zev) => managedIds.has(zev.id))
    }, [isAdmin, entries, zevsQuery.data])

    // Explicit in-session pick (null until the user switches). Reset on every
    // account change so one account's choice never leaks into another session.
    // Not persisted: the saved account preference follows the user instead.
    const [explicitPick, setExplicitPick] = useState<string | null>(null)
    const accountId = user?.id ?? null
    const lastAccountId = useRef<number | null>(accountId)
    if (lastAccountId.current !== accountId) {
        lastAccountId.current = accountId
        setExplicitPick(null)
    }

    const resolution = useMemo(
        () =>
            resolveCommunitySelection({
                isAdmin,
                entryIds: entries.map((entry) => entry.id),
                currentId: explicitPick ?? '',
                preferredZevId: user?.preferred_zev ?? '',
            }),
        [isAdmin, user?.preferred_zev, entries, explicitPick],
    )

    const selectedZevId = resolution.selection
    const selectedZev = managedZevs.find((zev) => zev.id === selectedZevId) ?? null
    const relation = entries.find((entry) => entry.id === selectedZevId)?.relation

    const { isLoading: zevsLoading, isFetching: zevsFetching, isError: zevsError, refetch: refetchZevs } = zevsQuery

    const value = useMemo<ManagedZevContextValue>(
        () => ({
            managedZevs,
            entries,
            selectedZevId,
            selectedZev,
            relation,
            isSelectable: resolution.isSelectable,
            isLoading: zevsLoading,
            isFetching: zevsFetching,
            isError: zevsError,
            refetch: () => {
                void refetchZevs()
            },
            setSelectedZevId: (zevId: string) => {
                if (!resolution.isAllowedId(zevId)) return
                // Optimistic switch; the serialized account save follows. A
                // failed save keeps the local selection for this session.
                setExplicitPick(zevId)
                updatePreferredZev(zevId).catch(() => undefined)
            },
        }),
        [managedZevs, entries, selectedZevId, selectedZev, relation, resolution, zevsLoading, zevsFetching, zevsError, refetchZevs, updatePreferredZev],
    )

    return <ManagedZevContext.Provider value={value}>{children}</ManagedZevContext.Provider>
}

export function useOptionalManagedZev() {
    return useContext(ManagedZevContext)
}

export function useManagedZev() {
    const context = useOptionalManagedZev()
    if (!context) {
        throw new Error('useManagedZev must be used within ManagedZevProvider')
    }
    return context
}
