import { useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { confirmEmailChange } from '../lib/api/auth'

type Step = 'confirming' | 'done' | 'error'

/**
 * Landing page of the link emailed to a *new* address. Public, because the link
 * is opened from a mailbox and may be opened on another device: the token is the
 * authority. Applying it signs the account out everywhere and starts no
 * session, so success points at the sign-in page.
 */
export function ConfirmEmailChangePage() {
    const { t } = useTranslation()
    const [searchParams] = useSearchParams()
    const [step, setStep] = useState<Step>('confirming')
    // The link is single-use: React's dev double-effect must not spend it twice.
    const started = useRef(false)

    useEffect(() => {
        if (started.current) return
        started.current = true
        const token = searchParams.get('token') ?? ''
        if (!token) {
            setStep('error')
            return
        }
        confirmEmailChange(token)
            .then(() => setStep('done'))
            .catch(() => setStep('error'))
    }, [searchParams])

    return (
        <div className="center-screen">
            <div className="card verify-card">
                {step === 'confirming' && <p className="muted">{t('auth.emailChange.confirming')}</p>}
                {step === 'done' && (
                    <>
                        <h2>{t('auth.emailChange.successTitle')}</h2>
                        <p className="muted">{t('auth.emailChange.successMessage')}</p>
                    </>
                )}
                {step === 'error' && (
                    <>
                        <h2>{t('auth.emailChange.errorTitle')}</h2>
                        <div className="error-banner">{t('auth.emailChange.errorMessage')}</div>
                    </>
                )}
                {step !== 'confirming' && (
                    <Link to="/login" className="button button-outline" style={{ textAlign: 'center' }}>
                        {t('auth.emailChange.toLogin')}
                    </Link>
                )}
            </div>
        </div>
    )
}
