import { useState, type FormEvent } from 'react'
import AppFooter from '../components/AppFooter'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../lib/auth'

export function LoginPage() {
    const { t } = useTranslation()
    const navigate = useNavigate()
    const { login } = useAuth()
    const [username, setUsername] = useState('')
    const [password, setPassword] = useState('')
    const [error, setError] = useState<string | null>(null)
    const [loading, setLoading] = useState(false)

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

    return (
        <div className="login-shell">
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
            <AppFooter />
        </div>
    )
}
