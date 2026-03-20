import { useState, type FormEvent } from 'react'
import AppFooter from '../components/AppFooter'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../lib/auth'
import { register as apiRegister, formatApiError } from '../lib/api'

export function LoginPage() {
    const { t } = useTranslation()
    const navigate = useNavigate()
    const { login } = useAuth()

    // Login state
    const [username, setUsername] = useState('')
    const [password, setPassword] = useState('')
    const [error, setError] = useState<string | null>(null)
    const [loading, setLoading] = useState(false)

    // Register modal state
    const [showModal, setShowModal] = useState(false)
    const [regUsername, setRegUsername] = useState('')
    const [regEmail, setRegEmail] = useState('')
    const [regError, setRegError] = useState<string | null>(null)
    const [regLoading, setRegLoading] = useState(false)
    const [regSuccess, setRegSuccess] = useState<string | null>(null)

    async function handleSubmit(event: FormEvent<HTMLFormElement>) {
        event.preventDefault()
        setLoading(true)
        setError(null)
        try {
            const me = await login(username, password)
            navigate(me.must_change_password ? '/account' : '/')
        } catch {
            setError(t('auth.invalid'))
        } finally {
            setLoading(false)
        }
    }

    async function handleRegister(event: FormEvent<HTMLFormElement>) {
        event.preventDefault()
        setRegLoading(true)
        setRegError(null)
        try {
            await apiRegister({ username: regUsername, email: regEmail })
            setRegSuccess(t('auth.register.success', { email: regEmail }))
        } catch (err) {
            setRegError(formatApiError(err))
        } finally {
            setRegLoading(false)
        }
    }

    function openModal() {
        setRegUsername('')
        setRegEmail('')
        setRegError(null)
        setRegSuccess(null)
        setShowModal(true)
    }

    return (
        <div className="login-shell">
            <div className="login-split">
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
                        <span>{t('auth.username')}</span>
                        <input value={username} onChange={(e) => setUsername(e.target.value)} required />
                    </label>

                    <label>
                        <span>{t('auth.password')}</span>
                        <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
                    </label>

                    {error ? <div className="error-banner">{error}</div> : null}

                    <button className="button" type="submit" disabled={loading}>
                        {loading ? t('common.loading') : t('auth.submit')}
                    </button>
                </form>

                {/* Right: register panel */}
                <div className="login-register-panel">
                    <div className="login-register-inner">
                        <h2>{t('auth.register.title')}</h2>
                        <p>{t('auth.register.description')}</p>
                        <button className="button button-outline" type="button" onClick={openModal}>
                            {t('auth.register.cta')}
                        </button>
                    </div>
                </div>
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
                                    <span>{t('auth.username')}</span>
                                    <input
                                        value={regUsername}
                                        onChange={(e) => setRegUsername(e.target.value)}
                                        placeholder={t('auth.register.usernamePlaceholder')}
                                        required
                                    />
                                </label>

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
