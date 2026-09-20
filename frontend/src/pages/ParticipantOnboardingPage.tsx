import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'

import { useAuth } from '../lib/auth'
import { consumeOnboardingLink } from '../lib/api/public'
import { submitMfaChallenge } from '../lib/api/auth'
import { challengeInput } from '../lib/mfaChallenge'

type Step = 'signing-in' | 'mfa-required' | 'welcome' | 'error'

/**
 * Land a newly (or returning) onboarded participant in their account.
 *
 * Unlike `MagicSignInPage`, this link is not spent by being used — see
 * `ParticipantOnboardingToken` for why — so there is no risk in visiting it
 * more than once. The guard against a duplicate POST on mount is here purely
 * to avoid firing the request twice under React 18 StrictMode, not because a
 * second call would be unsafe.
 *
 * A participant may have enrolled in two-factor authentication (spec
 * 2026-09-two-factor-authentication.md §5.4 door 6) — the link is still
 * honoured, but a code is required before it hands over a session.
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
    const [mfaToken, setMfaToken] = useState('')
    const [mfaMethods, setMfaMethods] = useState<('totp' | 'recovery_code')[]>(['totp', 'recovery_code'])
    const [code, setCode] = useState('')
    const [mfaError, setMfaError] = useState<string | null>(null)
    const [mfaLoading, setMfaLoading] = useState(false)

    const consumed = useRef(false)

    useEffect(() => {
        if (!prefix || !secret || consumed.current) {
            if (!prefix || !secret) setStep('error')
            return
        }
        consumed.current = true

        consumeOnboardingLink(prefix, secret)
            .then(async (result) => {
                if (result.mfaRequired) {
                    setMfaToken(result.mfaToken)
                    setMfaMethods(result.methods)
                    setStep('mfa-required')
                    return
                }
                setZevName(result.zev_name)
                await refreshUser()
                setStep('welcome')
                window.setTimeout(() => navigate('/', { replace: true }), 1500)
            })
            .catch(() => setStep('error'))
    }, [prefix, secret, refreshUser, navigate])

    async function handleMfaSubmit(event: FormEvent<HTMLFormElement>) {
        event.preventDefault()
        setMfaLoading(true)
        setMfaError(null)
        try {
            await submitMfaChallenge(mfaToken, code)
            await refreshUser()
            navigate('/', { replace: true })
        } catch {
            setMfaError(t('auth.mfa.invalidCode'))
        } finally {
            setMfaLoading(false)
        }
    }

    // A passkey-only account can only answer with a recovery code.
    const recoveryOnly = challengeInput(mfaMethods, false).recovery

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

    if (step === 'mfa-required') {
        return (
            <div className="center-screen">
                <form className="card public-invoice-card" onSubmit={handleMfaSubmit}>
                    <h2>{t('auth.mfa.title')}</h2>
                    <p className="muted">
                        {t(recoveryOnly ? 'auth.mfa.recoveryOnlyHint' : 'pages.onboarding.mfaPrompt')}
                    </p>
                    <label>
                        <span>{t(recoveryOnly ? 'auth.mfa.recoveryCodeLabel' : 'auth.mfa.codeLabel')}</span>
                        <input
                            type="text"
                            autoComplete={recoveryOnly ? 'off' : 'one-time-code'}
                            autoFocus
                            value={code}
                            onChange={(e) => setCode(e.target.value)}
                            required
                        />
                    </label>
                    {mfaError && <div className="error-banner">{mfaError}</div>}
                    <button className="button" type="submit" disabled={mfaLoading}>
                        {mfaLoading ? t('common.loading') : t('auth.submit')}
                    </button>
                </form>
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
