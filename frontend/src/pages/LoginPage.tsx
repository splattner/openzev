import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useQuery } from '@tanstack/react-query'
import AppFooter from '../components/AppFooter'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../lib/auth'
import { fetchRegistrationEnabled, fetchOAuthProviders, oauthLoginInitiate, register as apiRegister } from '../lib/api/auth'
import { formatApiError } from '../lib/api/errors'
import { queryKeys } from '../lib/api/queryKeys'

export function LoginPage() {
    const { t } = useTranslation()
    const navigate = useNavigate()
    const { login } = useAuth()
    const featureFlagsQuery = useQuery({
        queryKey: queryKeys.auth.registrationEnabled(),
        queryFn: fetchRegistrationEnabled,
        staleTime: 60_000,
    })
    const oauthProvidersQuery = useQuery({
        queryKey: queryKeys.auth.oauthProviders(),
        queryFn: fetchOAuthProviders,
        staleTime: 60_000,
    })

    // Login state
    const [email, setEmail] = useState('')
    const [password, setPassword] = useState('')
    const [error, setError] = useState<string | null>(null)
    const [loading, setLoading] = useState(false)
    const [oauthLoading, setOauthLoading] = useState<string | null>(null)

    // Register modal state
    const [showModal, setShowModal] = useState(false)
    const [regEmail, setRegEmail] = useState('')
    const [regError, setRegError] = useState<string | null>(null)
    const [regLoading, setRegLoading] = useState(false)
    const [regSuccess, setRegSuccess] = useState<string | null>(null)
    // Fail closed: if the registration-enabled request is missing, errored, or
    // blocked, do not advertise self-registration. The backend still enforces
    // the flag, so this only affects UI/operational correctness.
    const selfRegistrationEnabled = featureFlagsQuery.data === true

    const oauthProviders = oauthProvidersQuery.data ?? []

    // A failed OAuth login redirects back here with ?oauth_error=<slug>. Until
    // this ran, every one of those slugs was dropped silently and the user was
    // returned to the login form with no explanation at all.
    const [searchParams, setSearchParams] = useSearchParams()
    const handledOauthError = useRef(false)
    useEffect(() => {
        if (handledOauthError.current) return
        const oauthError = searchParams.get('oauth_error')
        if (!oauthError) return
        handledOauthError.current = true
        const key = `auth.oauth.errors.${oauthError}`
        const translated = t(key)
        setError(translated === key ? t('auth.oauth.errors.generic', { code: oauthError }) : translated)
        const next = new URLSearchParams(searchParams)
        next.delete('oauth_error')
        setSearchParams(next, { replace: true })
    }, [searchParams, setSearchParams, t])

    async function handleSubmit(event: FormEvent<HTMLFormElement>) {
        event.preventDefault()
        setLoading(true)
        setError(null)
        const form = event.currentTarget
        const formData = new FormData(form)
        const submittedEmail = String(formData.get('email') ?? '').trim()
        const submittedPassword = String(formData.get('password') ?? '')
        setEmail(submittedEmail)
        setPassword(submittedPassword)
        try {
            const me = await login(submittedEmail, submittedPassword)
            navigate(me.must_change_password ? '/account' : '/')
        } catch {
            setError(t('auth.invalid'))
        } finally {
            setLoading(false)
        }
    }

    async function handleOAuthLogin(providerSlug: string) {
        setOauthLoading(providerSlug)
        setError(null)
        try {
            const { redirect_url } = await oauthLoginInitiate(providerSlug)
            window.location.assign(redirect_url)
        } catch {
            setError(t('auth.oauth.errors.initFailed'))
            setOauthLoading(null)
        }
    }

    async function handleRegister(event: FormEvent<HTMLFormElement>) {
        event.preventDefault()
        setRegLoading(true)
        setRegError(null)
        try {
            await apiRegister({ email: regEmail })
            setRegSuccess(t('auth.register.success', { email: regEmail }))
        } catch (err) {
            setRegError(formatApiError(err))
        } finally {
            setRegLoading(false)
        }
    }

    function openModal() {
        setRegEmail('')
        setRegError(null)
        setRegSuccess(null)
        setShowModal(true)
    }

    return (
        <div className="login-shell">
            <div className={`login-split${selfRegistrationEnabled ? '' : ' login-split-single'}`}>
                {/* Left: sign-in card */}
                <form className="card login-card" onSubmit={handleSubmit}>
                    <div className="login-brand">
                        <img
                            src="/openzevlogo_whitebg.png"
                            alt={t('app.title')}
                            className="login-logo"
                        />
                    </div>
                    <h1>{t('auth.welcome')}</h1>
                    <p className="muted">{t('auth.signIn')}</p>

                    <label>
                        <span>{t('auth.email')}</span>
                        <input
                            type="email"
                            name="email"
                            autoComplete="username"
                            value={email}
                            onChange={(e) => setEmail(e.target.value)}
                            required
                        />
                    </label>

                    <label>
                        <span>{t('auth.password')}</span>
                        <input
                            type="password"
                            name="password"
                            autoComplete="current-password"
                            value={password}
                            onChange={(e) => setPassword(e.target.value)}
                            required
                        />
                    </label>

                    {error ? <div className="error-banner">{error}</div> : null}

                    <button className="button" type="submit" disabled={loading}>
                        {loading ? t('common.loading') : t('auth.submit')}
                    </button>

                    {oauthProviders.length > 0 && (
                        <>
                            <div className="login-divider">
                                <span>{t('auth.oauth.or')}</span>
                            </div>
                            <div className="oauth-provider-list">
                                {oauthProviders.map((provider) => (
                                    <button
                                        key={provider.name}
                                        type="button"
                                        className="button button-outline oauth-provider-button"
                                        disabled={oauthLoading !== null}
                                        onClick={() => void handleOAuthLogin(provider.name)}
                                    >
                                        {oauthLoading === provider.name
                                            ? t('common.loading')
                                            : t('auth.oauth.loginWith', { provider: provider.display_name })}
                                    </button>
                                ))}
                            </div>
                        </>
                    )}
                </form>

                {/* Right: register panel */}
                {selfRegistrationEnabled && (
                    <div className="login-register-panel">
                        <div className="login-register-inner">
                            <h2>{t('auth.register.title')}</h2>
                            <p>{t('auth.register.description')}</p>
                            <button className="button button-outline" type="button" onClick={openModal}>
                                {t('auth.register.cta')}
                            </button>
                        </div>
                    </div>
                )}
            </div>

            {/* Register modal */}
            {showModal && (
                <div className="modal-backdrop" onClick={() => setShowModal(false)}>
                    <div className="modal-box card" onClick={(e) => e.stopPropagation()}>
                        <h2>{t('auth.register.modalTitle')}</h2>

                        {regSuccess ? (
                            <div className="success-banner">{regSuccess}</div>
                        ) : (
                            <form onSubmit={handleRegister}>
                                <label>
                                    <span>{t('auth.register.email')}</span>
                                    <input
                                        type="email"
                                        value={regEmail}
                                        onChange={(e) => setRegEmail(e.target.value)}
                                        placeholder={t('auth.register.emailPlaceholder')}
                                        required
                                    />
                                </label>

                                {regError ? <div className="error-banner">{regError}</div> : null}

                                <div className="modal-actions">
                                    <button
                                        type="button"
                                        className="button button-ghost"
                                        onClick={() => setShowModal(false)}
                                    >
                                        {t('common.cancel')}
                                    </button>
                                    <button className="button" type="submit" disabled={regLoading}>
                                        {regLoading ? t('common.loading') : t('auth.register.submitModal')}
                                    </button>
                                </div>
                            </form>
                        )}

                        {regSuccess && (
                            <div className="modal-actions">
                                <button className="button" type="button" onClick={() => setShowModal(false)}>
                                    {t('common.close')}
                                </button>
                            </div>
                        )}
                    </div>
                </div>
            )}

            <AppFooter />
        </div>
    )
}
