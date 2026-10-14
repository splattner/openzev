import { useState, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useDocumentTitle } from '../lib/useDocumentTitle'
import { confirmPasswordReset } from '../lib/api/auth'
import { formatApiError } from '../lib/api/errors'

/**
 * Landing page of the emailed reset link. Public: the token is the authority and
 * may be opened on another device. It only sets the password and signs the
 * account out everywhere; no session starts, so success points at the sign-in
 * page, where a second factor is asked for as usual.
 */
export function ResetPasswordPage() {
    const { t } = useTranslation()
    const [searchParams] = useSearchParams()
    const token = searchParams.get('token') ?? ''
    const [password, setPassword] = useState('')
    const [confirmPassword, setConfirmPassword] = useState('')
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const [done, setDone] = useState(false)

    useDocumentTitle(t(done ? 'auth.reset.successTitle' : 'auth.reset.title'))

    async function handleSubmit(event: FormEvent<HTMLFormElement>) {
        event.preventDefault()
        if (password !== confirmPassword) {
            setError(t('auth.reset.mismatch'))
            return
        }
        setLoading(true)
        setError(null)
        try {
            await confirmPasswordReset(token, password)
            setDone(true)
        } catch (err) {
            setError(formatApiError(err))
        } finally {
            setLoading(false)
        }
    }

    if (!token) {
        return (
            <div className="center-screen">
                <div className="card verify-card">
                    <h2>{t('auth.reset.errorTitle')}</h2>
                    <div className="error-banner">{t('auth.reset.missingToken')}</div>
                    <Link to="/forgot-password" className="button button-outline" style={{ textAlign: 'center' }}>
                        {t('auth.reset.requestNew')}
                    </Link>
                </div>
            </div>
        )
    }

    if (done) {
        return (
            <div className="center-screen">
                <div className="card verify-card">
                    <h2>{t('auth.reset.successTitle')}</h2>
                    <p className="muted">{t('auth.reset.successMessage')}</p>
                    <Link to="/login" className="button" style={{ textAlign: 'center' }}>
                        {t('auth.reset.toLogin')}
                    </Link>
                </div>
            </div>
        )
    }

    return (
        <div className="center-screen">
            <form className="card verify-card" onSubmit={handleSubmit}>
                <h2>{t('auth.reset.title')}</h2>
                <p className="muted">{t('auth.reset.description')}</p>

                <label>
                    <span>{t('auth.reset.newPassword')}</span>
                    <input
                        type="password"
                        autoComplete="new-password"
                        autoFocus
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                        minLength={8}
                        required
                    />
                </label>

                <label>
                    <span>{t('auth.reset.confirmPassword')}</span>
                    <input
                        type="password"
                        autoComplete="new-password"
                        value={confirmPassword}
                        onChange={(e) => setConfirmPassword(e.target.value)}
                        minLength={8}
                        required
                    />
                </label>

                {error ? <div className="error-banner">{error}</div> : null}

                <button className="button" type="submit" disabled={loading}>
                    {loading ? t('common.loading') : t('auth.reset.submit')}
                </button>
                <Link to="/forgot-password" className="button button-ghost" style={{ textAlign: 'center' }}>
                    {t('auth.reset.requestNew')}
                </Link>
            </form>
        </div>
    )
}
