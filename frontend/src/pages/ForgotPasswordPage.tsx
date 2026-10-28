import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useDocumentTitle } from '../lib/useDocumentTitle'
import { requestPasswordReset } from '../lib/api/auth'
import { formatApiError } from '../lib/api/errors'

/**
 * Ask for a password-reset link. Public. The server answers the same for every
 * address, so success only says what *would* have happened: it never confirms
 * that the address has an account.
 */
export function ForgotPasswordPage() {
    const { t } = useTranslation()
    const [email, setEmail] = useState('')
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const [sent, setSent] = useState(false)

    useDocumentTitle(t('auth.forgot.title'))

    async function handleSubmit(event: FormEvent<HTMLFormElement>) {
        event.preventDefault()
        setLoading(true)
        setError(null)
        try {
            await requestPasswordReset(email.trim())
            setSent(true)
        } catch (err) {
            setError(formatApiError(err))
        } finally {
            setLoading(false)
        }
    }

    return (
        <div className="center-screen">
            <form className="card verify-card" onSubmit={handleSubmit}>
                <h2>{t('auth.forgot.title')}</h2>
                {sent ? (
                    <div className="success-banner">{t('auth.forgot.success')}</div>
                ) : (
                    <>
                        <p className="muted">{t('auth.forgot.description')}</p>
                        <label>
                            <span>{t('auth.email')}</span>
                            <input
                                type="email"
                                autoComplete="username"
                                autoFocus
                                value={email}
                                onChange={(e) => setEmail(e.target.value)}
                                required
                            />
                        </label>
                        {error ? <div className="error-banner">{error}</div> : null}
                        <button className="button button-primary" type="submit" disabled={loading}>
                            {loading ? t('common.loading') : t('auth.forgot.submit')}
                        </button>
                    </>
                )}
                <Link to="/login" className="button button-outline" style={{ textAlign: 'center' }}>
                    {t('auth.forgot.back')}
                </Link>
            </form>
        </div>
    )
}
