import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import {
    fetchMe,
    impersonateParticipant as impersonateParticipantRequest,
    login as loginRequest,
    logout as logoutRequest,
    passkeyAuthenticateBegin,
    passkeyAuthenticateComplete,
    stopImpersonation as stopImpersonationRequest,
    submitMfaChallenge,
    updateProfile,
} from './api/auth'
import type { User } from '../types/api'
import { apiErrorPayload } from './api/errors'
import { getPasskey } from './webauthn'

/** Either the session is live (cookies set, `user` is the signed-in
 * account) or the account has a second factor and `completeMfaChallenge`
 * must be called with `mfaToken` + a code before one exists. */
export type LoginOutcome =
    | { status: 'authenticated'; user: User }
    | { status: 'mfa_required'; mfaToken: string; methods: ('totp' | 'recovery_code')[] }

interface AuthContextValue {
    user: User | null
    isAuthenticated: boolean
    isLoading: boolean
    isImpersonating: boolean
    impersonator: User | null
    login: (email: string, password: string) => Promise<LoginOutcome>
    completeMfaChallenge: (mfaToken: string, code: string) => Promise<User>
    /** Sign in with a passkey — no password (ADR 0020). Throws
     * `PasskeyCancelledError` when the user dismisses the browser prompt. */
    loginWithPasskey: (email?: string) => Promise<User>
    refreshUser: () => Promise<User>
    /** Persist the account's default community and refresh the cached user. */
    updatePreferredZev: (zevId: string | null) => Promise<void>
    startImpersonation: (participantUserId: number) => Promise<void>
    stopImpersonation: () => Promise<void>
    logout: () => void
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined)

export function AuthProvider({ children }: { children: ReactNode }) {
    const [user, setUser] = useState<User | null>(null)
    const [isLoading, setIsLoading] = useState(true)
    const queryClient = useQueryClient()
    const sessionVersion = useRef(0)

    // Serializes preference saves per user: each PATCH waits for the previous
    // one, and only the latest save for the current user merges its response.
    const prefSaveRef = useRef<{ userId: number | null; seq: number; tail: Promise<unknown> }>({
        userId: null,
        seq: 0,
        tail: Promise.resolve(),
    })

    // Discard identity loads and preference saves from the outgoing session.
    function invalidateSessionRequests() {
        sessionVersion.current += 1
        prefSaveRef.current = { userId: null, seq: 0, tail: Promise.resolve() }
    }

    // Most query keys (invoices, metering data, ...) aren't partitioned by
    // user identity, so a response still in flight for the outgoing account
    // can otherwise land in the cache the incoming one reads from (#573).
    // Cancelling first makes react-query discard that late resolution
    // instead of it repopulating the cache clear() just emptied. Call at
    // every session boundary: login, logout, and each impersonation edge.
    const resetQueryCache = useCallback(async () => {
        await queryClient.cancelQueries()
        queryClient.clear()
    }, [queryClient])

    async function loadCurrentUser() {
        const version = sessionVersion.current
        const me = await fetchMe()
        if (version === sessionVersion.current) setUser(me)
        return me
    }

    useEffect(() => {
        const version = sessionVersion.current
        void loadCurrentUser()
            .catch(() => {
                if (version === sessionVersion.current) setUser(null)
            })
            .finally(() => setIsLoading(false))
    }, [])

    const value = useMemo<AuthContextValue>(
        () => ({
            user,
            isAuthenticated: Boolean(user),
            isLoading,
            isImpersonating: Boolean(user?.impersonated_by),
            impersonator: user?.impersonated_by ?? null,
            async login(email: string, password: string) {
                invalidateSessionRequests()
                await resetQueryCache()
                const result = await loginRequest(email, password)
                if (result.mfaRequired) {
                    // No session yet — nothing to load. The cache was
                    // already reset above, which is correct either way:
                    // whichever account completes the challenge (or none)
                    // must not see a stale previous session's data.
                    return { status: 'mfa_required', mfaToken: result.mfaToken, methods: result.methods }
                }
                const user = await loadCurrentUser()
                return { status: 'authenticated', user }
            },
            async completeMfaChallenge(mfaToken: string, code: string) {
                invalidateSessionRequests()
                await resetQueryCache()
                await submitMfaChallenge(mfaToken, code)
                return loadCurrentUser()
            },
            async loginWithPasskey(email?: string) {
                invalidateSessionRequests()
                await resetQueryCache()
                const options = await passkeyAuthenticateBegin(email)
                const assertion = await getPasskey(options)
                await passkeyAuthenticateComplete(assertion)
                return loadCurrentUser()
            },
            refreshUser() {
                return loadCurrentUser()
            },
            async updatePreferredZev(zevId: string | null) {
                const callerId = user?.id ?? null
                const slot = prefSaveRef.current
                if (slot.userId !== callerId) {
                    slot.userId = callerId
                    slot.seq = 0
                }
                const mySeq = (slot.seq += 1)
                const run = slot.tail
                    .catch(() => undefined)
                    .then(() =>
                        // Dispatch guard: the session may have turned over while
                        // queued. Never issue a PATCH under the next account's
                        // cookies. Skipped saves resolve null, which the merge
                        // below already ignores.
                        prefSaveRef.current !== slot ? null : updateProfile({ preferred_zev: zevId }),
                    )
                // Keep the chain alive for later saves even when this one fails.
                slot.tail = run.catch(() => undefined)
                const me = await run
                // Drop late responses from a superseded save, account switch, or logout.
                const latest = prefSaveRef.current
                if (latest.userId !== callerId || latest.seq !== mySeq) return
                setUser((current) =>
                    current && me && current.id === me.id
                        ? { ...current, preferred_zev: me.preferred_zev }
                        : current,
                )
            },
            async startImpersonation(participantUserId: number) {
                if (!user || user.role !== 'admin') {
                    throw new Error('Only admins can impersonate participants.')
                }
                invalidateSessionRequests()
                await resetQueryCache()
                await impersonateParticipantRequest(participantUserId)
                await loadCurrentUser()
            },
            async stopImpersonation() {
                invalidateSessionRequests()
                await resetQueryCache()
                try {
                    await stopImpersonationRequest()
                } catch (error) {
                    if (apiErrorPayload(error)?.code === 'impersonation_session_expired') setUser(null)
                    throw error
                }
                setIsLoading(true)
                setUser(null)
                try {
                    await loadCurrentUser()
                } finally {
                    setIsLoading(false)
                }
            },
            logout() {
                invalidateSessionRequests()
                setUser(null)
                void resetQueryCache()
                void logoutRequest().catch(() => undefined)
            },
        }),
        [isLoading, resetQueryCache, user],
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
