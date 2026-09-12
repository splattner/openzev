import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'

import { useAuth } from '../lib/auth'
import { consumeOnboardingLink } from '../lib/api/public'

type Step = 'signing-in' | 'welcome' | 'error'

/**
 * Land a newly (or returning) onboarded participant in their account.
 *
 * Unlike `MagicSignInPage`, this link is not spent by being used — see
 * `ParticipantOnboardingToken` for why — so there is no risk in visiting it
 * more than once. The guard against a duplicate POST on mount is here purely
 * to avoid firing the request twice under React 18 StrictMode, not because a
 * second call would be unsafe.
 */
export function ParticipantOnboardingPage() {
    const { t } = useTranslation()
    const navigate = useNavigate()
    const { prefix = '' } = useParams<{ prefix: string }>()
    const [searchParams] = useSearchParams()
    const secret = searchParams.get('s') ?? ''
    const { refreshUser } = useAuth()
    const [step, setStep] = useState<Step>('signing-in')
    const [zevName, setZevName] = useState('')

    const consumed = useRef(false)

    useEffect(() => {
        if (!prefix || !secret || consumed.current) {
            if (!prefix || !secret) setStep('error')
            return
        }
        consumed.current = true

        consumeOnboardingLink(prefix, secret)
            .then(async (result) => {
                setZevName(result.zev_name)
                await refreshUser()
                setStep('welcome')
                window.setTimeout(() => navigate('/', { replace: true }), 1500)
            })
            .catch(() => setStep('error'))
    }, [prefix, secret, refreshUser, navigate])

    if (step === 'error') {
        return (
            <div className="center-screen">
                <div className="card public-invoice-card">
                    <h2>{t('pages.onboarding.errorTitle')}</h2>
                    <p className="muted">{t('pages.onboarding.errorBody')}</p>
                </div>
            </div>
        )
    }

    if (step === 'welcome') {
        return (
            <div className="center-screen">
                <div className="card public-invoice-card">
                    <h2>{t('pages.onboarding.welcomeTitle', { zevName })}</h2>
                    <p className="muted">{t('pages.onboarding.welcomeBody')}</p>
                </div>
            </div>
        )
    }

    return (
        <div className="center-screen">
            <div className="card public-invoice-card">
                <p className="muted">{t('pages.onboarding.signingIn')}</p>
            </div>
        </div>
    )
}
