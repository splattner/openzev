import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'

import { useAuth } from '../lib/auth'
import { consumeMagicLink } from '../lib/api/public'

type Step = 'signing-in' | 'error'

/**
 * Consume a one-time sign-in link and land in the participant portal.
 *
 * Mounted outside `ProtectedRoute`: the visitor has no session yet, and this
 * page is how they get one. On success the app takes over as an ordinary
 * participant session, with ordinary participant scoping — nothing about the
 * link survives into what they can see.
 */
export function MagicSignInPage() {
    const { t } = useTranslation()
    const navigate = useNavigate()
    const { token = '' } = useParams<{ token: string }>()
    const { refreshUser } = useAuth()
    const [step, setStep] = useState<Step>('signing-in')

    // A one-time token must be spent once. React 18 mounts twice in StrictMode,
    // and a second POST would consume the session the first one just created.
    const consumed = useRef(false)

    useEffect(() => {
        if (!token || consumed.current) {
            if (!token) setStep('error')
            return
        }
        consumed.current = true

        consumeMagicLink(token)
            .then(() => refreshUser())
            .then(() => navigate('/', { replace: true }))
            .catch(() => setStep('error'))
    }, [token, refreshUser, navigate])

    if (step === 'error') {
        return (
            <div className="center-screen">
                <div className="card public-invoice-card">
                    <h2>{t('pages.magicSignIn.errorTitle')}</h2>
                    <p className="muted">{t('pages.magicSignIn.errorBody')}</p>
                </div>
            </div>
        )
    }

    return (
        <div className="center-screen">
            <div className="card public-invoice-card">
                <p className="muted">{t('pages.magicSignIn.signingIn')}</p>
            </div>
        </div>
    )
}
