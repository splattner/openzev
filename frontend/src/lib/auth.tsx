import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { fetchMe, impersonateParticipant as impersonateParticipantRequest, login as loginRequest } from './api'
import type { User } from '../types/api'

interface AuthContextValue {
    user: User | null
    isAuthenticated: boolean
    isLoading: boolean
    isImpersonating: boolean
    impersonator: User | null
    login: (username: string, password: string) => Promise<User>
    refreshUser: () => Promise<User>
    startImpersonation: (participantUserId: number) => Promise<void>
    stopImpersonation: () => Promise<void>
    logout: () => void
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined)

export function AuthProvider({ children }: { children: ReactNode }) {
    const ACCESS_KEY = 'openzev.access'
    const REFRESH_KEY = 'openzev.refresh'
    const IMPERSONATION_ACCESS_KEY = 'openzev.impersonation.original_access'
    const IMPERSONATION_REFRESH_KEY = 'openzev.impersonation.original_refresh'
    const IMPERSONATOR_KEY = 'openzev.impersonation.impersonator'

    const [user, setUser] = useState<User | null>(null)
    const [isLoading, setIsLoading] = useState(true)
    const [impersonator, setImpersonator] = useState<User | null>(null)

    async function loadCurrentUser() {
        const me = await fetchMe()
        setUser(me)
        return me
    }

    useEffect(() => {
        const access = localStorage.getItem(ACCESS_KEY)
        const storedImpersonator = localStorage.getItem(IMPERSONATOR_KEY)
        if (storedImpersonator) {
            try {
                setImpersonator(JSON.parse(storedImpersonator) as User)
            } catch {
                localStorage.removeItem(IMPERSONATOR_KEY)
            }
        }
        if (!access) {
            setIsLoading(false)
            return
        }
        void loadCurrentUser()
            .catch(() => {
                localStorage.removeItem(ACCESS_KEY)
                localStorage.removeItem(REFRESH_KEY)
                localStorage.removeItem(IMPERSONATION_ACCESS_KEY)
                localStorage.removeItem(IMPERSONATION_REFRESH_KEY)
                localStorage.removeItem(IMPERSONATOR_KEY)
                setImpersonator(null)
            })
            .finally(() => setIsLoading(false))
    }, [ACCESS_KEY, REFRESH_KEY, IMPERSONATION_ACCESS_KEY, IMPERSONATION_REFRESH_KEY, IMPERSONATOR_KEY])

    const value = useMemo<AuthContextValue>(
        () => ({
            user,
            isAuthenticated: Boolean(user),
            isLoading,
            isImpersonating: impersonator !== null,
            impersonator,
            async login(username: string, password: string) {
                const tokens = await loginRequest(username, password)
                localStorage.setItem(ACCESS_KEY, tokens.access)
                localStorage.setItem(REFRESH_KEY, tokens.refresh)
                localStorage.removeItem(IMPERSONATION_ACCESS_KEY)
                localStorage.removeItem(IMPERSONATION_REFRESH_KEY)
                localStorage.removeItem(IMPERSONATOR_KEY)
                setImpersonator(null)
                return loadCurrentUser()
            },
            refreshUser() {
                return loadCurrentUser()
            },
            async startImpersonation(participantUserId: number) {
                if (!user || user.role !== 'admin') {
                    throw new Error('Only admins can impersonate participants.')
                }

                const originalAccess = localStorage.getItem(ACCESS_KEY)
                const originalRefresh = localStorage.getItem(REFRESH_KEY)
                if (!originalAccess || !originalRefresh) {
                    throw new Error('Missing current auth tokens.')
                }

                const result = await impersonateParticipantRequest(participantUserId)
                localStorage.setItem(IMPERSONATION_ACCESS_KEY, originalAccess)
                localStorage.setItem(IMPERSONATION_REFRESH_KEY, originalRefresh)
                localStorage.setItem(IMPERSONATOR_KEY, JSON.stringify(result.impersonator))
                localStorage.setItem(ACCESS_KEY, result.access)
                localStorage.setItem(REFRESH_KEY, result.refresh)
                setImpersonator(result.impersonator)
                await loadCurrentUser()
            },
            async stopImpersonation() {
                const originalAccess = localStorage.getItem(IMPERSONATION_ACCESS_KEY)
                const originalRefresh = localStorage.getItem(IMPERSONATION_REFRESH_KEY)
                if (!originalAccess || !originalRefresh) {
                    throw new Error('No impersonation session found.')
                }

                localStorage.setItem(ACCESS_KEY, originalAccess)
                localStorage.setItem(REFRESH_KEY, originalRefresh)
                localStorage.removeItem(IMPERSONATION_ACCESS_KEY)
                localStorage.removeItem(IMPERSONATION_REFRESH_KEY)
                localStorage.removeItem(IMPERSONATOR_KEY)
                setImpersonator(null)
                await loadCurrentUser()
            },
            logout() {
                localStorage.removeItem(ACCESS_KEY)
                localStorage.removeItem(REFRESH_KEY)
                localStorage.removeItem(IMPERSONATION_ACCESS_KEY)
                localStorage.removeItem(IMPERSONATION_REFRESH_KEY)
                localStorage.removeItem(IMPERSONATOR_KEY)
                setUser(null)
                setImpersonator(null)
            },
        }),
        [
            isLoading,
            user,
            impersonator,
            ACCESS_KEY,
            REFRESH_KEY,
            IMPERSONATION_ACCESS_KEY,
            IMPERSONATION_REFRESH_KEY,
            IMPERSONATOR_KEY,
        ],
    )

    return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
    const context = useContext(AuthContext)
    if (!context) {
        throw new Error('useAuth must be used within AuthProvider')
    }
    return context
}
