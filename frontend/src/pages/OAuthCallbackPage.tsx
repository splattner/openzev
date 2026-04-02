import { useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../lib/auth'
import { oauthTokenExchange } from '../lib/api'

/**
 * Handles the redirect back from the OAuth provider callback.
 *
 * The backend redirects the browser to:
 *   /oauth/callback?code=<exchange_code>
 *
 * This page exchanges the short-lived code for JWT tokens via the API and
 * then stores them in the auth context exactly like a normal login.
 */
export function OAuthCallbackPage() {
    const { t } = useTranslation()
    const navigate = useNavigate()
    const [searchParams] = useSearchParams()
    const { storeTokens, refreshUser } = useAuth()
    const [error, setError] = useState<string | null>(null)
    const didRun = useRef(false)

    useEffect(() => {
        if (didRun.current) return
        didRun.current = true

        const oauthError = searchParams.get('oauth_error')
        if (oauthError) {
            setError(t('auth.oauth.errors.generic', { code: oauthError }))
            return
        }

        const code = searchParams.get('code')
        if (!code) {
            setError(t('auth.oauth.errors.missingCode'))
            return
        }

        oauthTokenExchange(code)
            .then((tokens) => {
                storeTokens(tokens)
                return refreshUser()
            })
            .then(() => {
                navigate('/', { replace: true })
            })
            .catch(() => {
                setError(t('auth.oauth.errors.exchangeFailed'))
            })
    }, []) // eslint-disable-line react-hooks/exhaustive-deps

    if (error) {
        return (
            <div className="login-shell">
                <div className="login-split login-split-single">
                    <div className="card login-card">
                        <h1>{t('auth.oauth.errors.title')}</h1>
                        <div className="error-banner">{error}</div>
                        <button
                            className="button"
                            type="button"
                            onClick={() => navigate('/login', { replace: true })}
                        >
                            {t('auth.oauth.backToLogin')}
                        </button>
                    </div>
                </div>
            </div>
        )
    }

    return (
        <div className="login-shell">
            <div className="login-split login-split-single">
                <div className="card login-card">
                    <p className="muted">{t('auth.oauth.completing')}</p>
                </div>
            </div>
        </div>
    )
}
