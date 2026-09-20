import { useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useLocation } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../lib/auth'
import { fetchMfaStatus } from '../lib/api/auth'
import { queryKeys } from '../lib/api/queryKeys'
import { formatDateTime, useAppSettings } from '../lib/appSettings'
import { mfaGateState } from '../lib/mfaGate'

/**
 * The app shell is withheld from a user whose role must hold a second factor
 * and who has none. Spec 2026-09-two-factor-authentication.md §7.3.
 *
 * Before `grace_until` the interstitial can be dismissed for the session; after
 * it, it cannot. The grace period exists because switching the requirement on
 * must never lock out an account that already existed.
 *
 * This is a UI gate, not an API one: the account page (`/account`) is always
 * reachable through it so the user can enrol, and an impersonating admin is
 * never gated because they cannot enrol on someone else's behalf.
 */
export function MfaEnrolmentGate({ children }: { children: ReactNode }) {
    const { isAuthenticated, isImpersonating, logout } = useAuth()
    const location = useLocation()
    const [dismissed, setDismissed] = useState(false)
    // Read once: the gate re-evaluates on the next navigation or reload, and a
    // render-time Date.now() would make the output unstable between renders.
    const [now] = useState(() => Date.now())

    const statusQuery = useQuery({
        queryKey: queryKeys.auth.mfa(),
        queryFn: fetchMfaStatus,
        enabled: isAuthenticated && !isImpersonating,
    })

    const status = statusQuery.data
    const state = mfaGateState(status, { now, dismissed, impersonating: isImpersonating, pathname: location.pathname })
    if (state === 'pass' || !status) return <>{children}</>
    const inGrace = state === 'grace'

    return (
        <MfaInterstitial
            graceUntil={inGrace ? status.grace_until : null}
            onLater={() => setDismissed(true)}
            onLogout={logout}
        />
    )
}

function MfaInterstitial({
    graceUntil,
    onLater,
    onLogout,
}: {
    graceUntil: string | null
    onLater: () => void
    onLogout: () => void
}) {
    const { t } = useTranslation()
    // Only here, not in the gate: the gate wraps the whole app shell and must
    // not need settings context for the common case of not gating anyone.
    const { settings } = useAppSettings()

    return (
        <div className="center-screen">
            <div className="card public-invoice-card" role="alertdialog" aria-labelledby="mfa-gate-title">
                <h2 id="mfa-gate-title">{t('mfaGate.title')}</h2>
                <p>{t('mfaGate.body')}</p>
                {graceUntil ? (
                    <p className="muted">{t('mfaGate.graceUntil', { date: formatDateTime(graceUntil, settings) })}</p>
                ) : (
                    <p className="muted">{t('mfaGate.graceOver')}</p>
                )}
                <div className="actions-row">
                    <Link className="button button-primary" to="/account">
                        {t('mfaGate.setUp')}
                    </Link>
                    {graceUntil ? (
                        <button type="button" className="button button-secondary" onClick={onLater}>
                            {t('mfaGate.later')}
                        </button>
                    ) : (
                        <button type="button" className="button button-secondary" onClick={onLogout}>
                            {t('nav.logout')}
                        </button>
                    )}
                </div>
            </div>
        </div>
    )
}
