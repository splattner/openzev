import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchZevs } from './api/zev'
import { queryKeys } from './api/queryKeys'
import { useAuth } from './auth'
import type { UserRole, Zev } from '../types/api'

const STORAGE_KEY = 'openzev.selectedZevId'

interface ManagedZevContextValue {
    managedZevs: Zev[]
    selectedZevId: string
    selectedZev: Zev | null
    isSelectable: boolean
    isLoading: boolean
    setSelectedZevId: (zevId: string) => void
}

interface ManagedSelectionInput {
    role?: UserRole
    managedZevs: ReadonlyArray<Pick<Zev, 'id'>>
    currentId: string
}

interface ManagedSelection {
    /** User may switch between managed ZEVs. */
    isSelectable: boolean
    /** Reconciled selection: keeps the current ID while it is still managed, otherwise falls back to the first managed ZEV. */
    selection: string
    /** Whether a user-initiated selection request targets a managed ZEV. */
    isAllowedId: (zevId: string) => boolean
}

/**
 * Admin: always switch. Owner: switch only with 2+ ZEVs. Else: no selection.
 * (No hooks, unit-testable.)
 */
export function resolveManagedSelection({
    role,
    managedZevs,
    currentId,
}: ManagedSelectionInput): ManagedSelection {
    const isAdmin = role === 'admin'
    const isOwner = role === 'zev_owner'
    const canManage = isAdmin || isOwner
    const allowedIds = new Set(managedZevs.map((zev) => zev.id))

    return {
        isSelectable: isAdmin || (isOwner && managedZevs.length > 1),
        selection:
            canManage && managedZevs.length > 0
                ? (allowedIds.has(currentId) ? currentId : managedZevs[0].id)
                : '',
        isAllowedId: (zevId) => canManage && allowedIds.has(zevId),
    }
}

const ManagedZevContext = createContext<ManagedZevContextValue | undefined>(undefined)

export function ManagedZevProvider({ children }: { children: ReactNode }) {
    const { user } = useAuth()
    const isAdmin = user?.role === 'admin'
    const isOwner = user?.role === 'zev_owner'
    const canManageZev = isAdmin || isOwner

    const zevsQuery = useQuery({
        queryKey: queryKeys.zev.list(),
        queryFn: fetchZevs,
        enabled: canManageZev,
    })

    const managedZevs = useMemo(() => {
        const allZevs = zevsQuery.data ?? []
        if (isAdmin) return allZevs
        if (isOwner && user) return allZevs.filter((zev) => zev.owner === user.id)
        return []
    }, [isAdmin, isOwner, user, zevsQuery.data])

    // Restore the persisted selection directly, so it survives the loading
    // phase instead of being raced by the reconcile effect below.
    const [selectedZevId, setSelectedZevIdState] = useState(
        () => window.localStorage.getItem(STORAGE_KEY) ?? '',
    )

    const resolution = useMemo(
        () =>
            resolveManagedSelection({
                role: user?.role,
                managedZevs,
                currentId: selectedZevId,
            }),
        [user?.role, managedZevs, selectedZevId],
    )

    useEffect(() => {
        // Don't erase a restored ID while the managed list is still loading.
        if (canManageZev && zevsQuery.isLoading) return
        if (selectedZevId === resolution.selection) return
        setSelectedZevIdState(resolution.selection)
        if (resolution.selection) {
            window.localStorage.setItem(STORAGE_KEY, resolution.selection)
        } else {
            window.localStorage.removeItem(STORAGE_KEY)
        }
    }, [canManageZev, zevsQuery.isLoading, selectedZevId, resolution])

    const selectedZev = managedZevs.find((zev) => zev.id === selectedZevId) ?? null

    const value = useMemo<ManagedZevContextValue>(
        () => ({
            managedZevs,
            selectedZevId,
            selectedZev,
            isSelectable: resolution.isSelectable,
            isLoading: zevsQuery.isLoading,
            setSelectedZevId: (zevId: string) => {
                if (!resolution.isAllowedId(zevId)) return
                setSelectedZevIdState(zevId)
                window.localStorage.setItem(STORAGE_KEY, zevId)
            },
        }),
        [managedZevs, selectedZevId, selectedZev, resolution, zevsQuery.isLoading],
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
