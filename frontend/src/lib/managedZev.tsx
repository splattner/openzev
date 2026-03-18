import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchZevs } from './api'
import { useAuth } from './auth'
import type { Zev } from '../types/api'

interface ManagedZevContextValue {
    managedZevs: Zev[]
    selectedZevId: string
    selectedZev: Zev | null
    isSelectable: boolean
    isLoading: boolean
    setSelectedZevId: (zevId: string) => void
}

const ManagedZevContext = createContext<ManagedZevContextValue | undefined>(undefined)

export function ManagedZevProvider({ children }: { children: ReactNode }) {
    const { user } = useAuth()
    const isAdmin = user?.role === 'admin'
    const isOwner = user?.role === 'zev_owner'
    const canManageZev = isAdmin || isOwner

    const zevsQuery = useQuery({
        queryKey: ['zevs'],
        queryFn: fetchZevs,
        enabled: canManageZev,
    })

    const managedZevs = useMemo(() => {
        const allZevs = zevsQuery.data?.results ?? []
        if (isAdmin) return allZevs
        if (isOwner && user) return allZevs.filter((zev) => zev.owner === user.id)
        return []
    }, [isAdmin, isOwner, user, zevsQuery.data?.results])

    const [selectedZevId, setSelectedZevIdState] = useState('')

    useEffect(() => {
        const stored = window.localStorage.getItem('openzev.selectedZevId')
        if (stored) {
            setSelectedZevIdState(stored)
        }
    }, [])

    useEffect(() => {
        if (!canManageZev) {
            setSelectedZevIdState('')
            return
        }

        if (!managedZevs.length) {
            setSelectedZevIdState('')
            return
        }

        if (isOwner) {
            const ownedZevId = managedZevs[0].id
            if (selectedZevId !== ownedZevId) {
                setSelectedZevIdState(ownedZevId)
                window.localStorage.setItem('openzev.selectedZevId', ownedZevId)
            }
            return
        }

        const isCurrentValid = managedZevs.some((zev) => zev.id === selectedZevId)
        if (!isCurrentValid) {
            const fallback = managedZevs[0].id
            setSelectedZevIdState(fallback)
            window.localStorage.setItem('openzev.selectedZevId', fallback)
        }
    }, [canManageZev, managedZevs, selectedZevId, isOwner])

    const selectedZev = managedZevs.find((zev) => zev.id === selectedZevId) ?? null

    const value = useMemo<ManagedZevContextValue>(
        () => ({
            managedZevs,
            selectedZevId,
            selectedZev,
            isSelectable: isAdmin,
            isLoading: zevsQuery.isLoading,
            setSelectedZevId: (zevId: string) => {
                if (!isAdmin) return
                setSelectedZevIdState(zevId)
                window.localStorage.setItem('openzev.selectedZevId', zevId)
            },
        }),
        [managedZevs, selectedZevId, selectedZev, isAdmin, zevsQuery.isLoading],
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
