import { createContext, useContext, useMemo, useRef, useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchZevs } from './api/zev'
import { queryKeys } from './api/queryKeys'
import { useAuth } from './auth'
import type { User, UserRole, Zev } from '../types/api'
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
    /** Every community the account relates to, sorted by name — what the switcher lists. */
    entries: CommunityEntry[]
    selectedZevId: string
    /** The selected community's ZEV record, when the account may read it (never for a participant-only entry). */
    selectedZev: Zev | null
    /** The account's relation to the selected community, or `undefined` when none is selected. */
    relation?: CommunityRelation
    isSelectable: boolean
    isLoading: boolean
    setSelectedZevId: (zevId: string) => void
}

interface ManagedSelectionInput {
    role?: UserRole
    managedZevs: ReadonlyArray<Pick<Zev, 'id'>>
    /** Explicit in-session pick ('' while the user has not switched yet). */
    currentId: string
    /** Account-level default community (``User.preferred_zev``), if any. */
    preferredZevId?: string | null
}

interface ManagedSelection {
    /** User may switch between managed ZEVs. */
    isSelectable: boolean
    /** Reconciled selection: explicit pick if still managed, else account preference, else first managed ZEV. */
    selection: string
    /** Whether a user-initiated selection request targets a managed ZEV. */
    isAllowedId: (zevId: string) => boolean
}

/**
 * Admin: always switch. Owner: switch only with 2+ ZEVs. Else: no selection.
 * The role-only rule for accounts whose memberships are not known (sessions
 * from before /auth/me listed them). (No hooks, unit-testable.)
 */
export function resolveManagedSelection({
    role,
    managedZevs,
    currentId,
    preferredZevId = '',
}: ManagedSelectionInput): ManagedSelection {
    const isAdmin = role === 'admin'
    const isOwner = role === 'zev_owner'
    const canManage = isAdmin || isOwner
    return resolveCommunitySelection({
        isAdmin,
        entryIds: canManage ? managedZevs.map((zev) => zev.id) : [],
        currentId,
        preferredZevId,
    })
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
 * (No hooks, unit-testable.)
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

/**
 * The communities an account can switch between. Admins: every ZEV. Accounts
 * with known memberships: those. Otherwise (a session from before /auth/me
 * carried memberships) the old role rule: an owner's own ZEVs.
 */
export function communityEntries(user: User | null | undefined, zevs: ReadonlyArray<Zev>): CommunityEntry[] {
    if (!user) return []
    if (user.role === 'admin') {
        return zevs.map((zev) => ({ id: zev.id, name: zev.name, relation: 'admin' as const }))
    }
    if (user.memberships) {
        return user.memberships.map((membership) => ({
            id: membership.zev,
            name: membership.zev_name,
            relation: relationOf(membership),
        }))
    }
    if (user.role === 'zev_owner') {
        return zevs
            .filter((zev) => zev.owner === user.id)
            .map((zev) => ({ id: zev.id, name: zev.name, relation: 'manager' as const }))
    }
    return []
}

const ManagedZevContext = createContext<ManagedZevContextValue | undefined>(undefined)

export function ManagedZevProvider({ children }: { children: ReactNode }) {
    const { user, updatePreferredZev } = useAuth()
    const isAdmin = user?.role === 'admin'
    const holdsAGrant = (user?.memberships ?? []).some((membership) => membership.access !== null)
    // ZEV records are readable through a grant (or as an admin); the old owner
    // role still reads its own before memberships are known.
    const mayReadZevs = isAdmin || holdsAGrant || (!user?.memberships && user?.role === 'zev_owner')

    const zevsQuery = useQuery({
        queryKey: queryKeys.zev.list(),
        queryFn: fetchZevs,
        enabled: mayReadZevs,
    })

    const entries = useMemo(() => communityEntries(user, zevsQuery.data ?? []), [user, zevsQuery.data])
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

    const value = useMemo<ManagedZevContextValue>(
        () => ({
            managedZevs,
            entries,
            selectedZevId,
            selectedZev,
            relation,
            isSelectable: resolution.isSelectable,
            isLoading: zevsQuery.isLoading,
            setSelectedZevId: (zevId: string) => {
                if (!resolution.isAllowedId(zevId)) return
                // Optimistic switch; the serialized account save follows. A
                // failed save keeps the local selection for this session.
                setExplicitPick(zevId)
                updatePreferredZev(zevId).catch(() => undefined)
            },
        }),
        [managedZevs, entries, selectedZevId, selectedZev, relation, resolution, zevsQuery.isLoading, updatePreferredZev],
    )

    return <ManagedZevContext.Provider value={value}>{children}</ManagedZevContext.Provider>
}

export function useManagedZev() {
    const context = useContext(ManagedZevContext)
    if (!context) {
        throw new Error('useManagedZev must be used within ManagedZevProvider')
    }
    return context
}
