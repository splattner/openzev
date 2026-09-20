import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'

import { useAuth } from '../lib/auth'
import { consumeMagicLink } from '../lib/api/public'
import { submitMfaChallenge } from '../lib/api/auth'

type Step = 'signing-in' | 'mfa-required' | 'error'

/**
 * Consume a one-time sign-in link and land in the participant portal.
 *
 * Mounted outside `ProtectedRoute`: the visitor has no session yet, and this
 * page is how they get one. On success the app takes over as an ordinary
 * participant session, with ordinary participant scoping — nothing about the
 * link survives into what they can see.
 *
 * A participant may have enrolled in two-factor authentication (spec
 * 2026-09-two-factor-authentication.md §5.4 door 5) — the link is still
 * honoured, but a code is required before it hands over a session.
 */
export function MagicSignInPage() {
    const { t } = useTranslation()
    const navigate = useNavigate()
    const { token = '' } = useParams<{ token: string }>()
    const { refreshUser } = useAuth()
    const [step, setStep] = useState<Step>('signing-in')
    const [mfaToken, setMfaToken] = useState('')
    const [code, setCode] = useState('')
    const [mfaError, setMfaError] = useState<string | null>(null)
    const [mfaLoading, setMfaLoading] = useState(false)

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
            .then((result) => {
                if (result.mfaRequired) {
                    setMfaToken(result.mfaToken)
                    setStep('mfa-required')
                    return
                }
                return refreshUser().then(() => navigate('/', { replace: true }))
            })
            .catch(() => setStep('error'))
    }, [token, refreshUser, navigate])

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

    if (step === 'mfa-required') {
        return (
            <div className="center-screen">
                <form className="card public-invoice-card" onSubmit={handleMfaSubmit}>
                    <h2>{t('auth.mfa.title')}</h2>
                    <p className="muted">{t('pages.magicSignIn.mfaPrompt')}</p>
                    <label>
                        <span>{t('auth.mfa.codeLabel')}</span>
                        <input
                            type="text"
                            autoComplete="one-time-code"
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

    return (
        <div className="center-screen">
            <div className="card public-invoice-card">
                <p className="muted">{t('pages.magicSignIn.signingIn')}</p>
            </div>
        </div>
    )
}
