import { useEffect, useState, type FormEvent } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../lib/auth'
import { verifyEmail, setInitialPassword, createSelfSetupZev, formatApiError } from '../lib/api'
import type { SelfSetupZevInput } from '../types/api'

type Step = 'verifying' | 'error' | 'set-password' | 'create-zev' | 'done'

export function VerifyEmailPage() {
    const { t } = useTranslation()
    const navigate = useNavigate()
    const [searchParams] = useSearchParams()
    const { refreshUser, storeTokens } = useAuth()

    const [step, setStep] = useState<Step>('verifying')
    const [errorMsg, setErrorMsg] = useState<string | null>(null)

    // Set-password step state
    const [password, setPassword] = useState('')
    const [confirmPassword, setConfirmPassword] = useState('')
    const [pwLoading, setPwLoading] = useState(false)
    const [pwError, setPwError] = useState<string | null>(null)

    // Create-ZEV step state
    const [zevForm, setZevForm] = useState<SelfSetupZevInput>({
        name: '',
        start_date: new Date().toISOString().slice(0, 10),
        zev_type: 'zev',
        billing_interval: 'annual',
        grid_operator: '',
    })
    const [zevLoading, setZevLoading] = useState(false)
    const [zevError, setZevError] = useState<string | null>(null)

    // Step 0: auto-verify on mount
    useEffect(() => {
        const token = searchParams.get('token') ?? ''
        if (!token) {
            setErrorMsg('No verification token found in the URL.')
            setStep('error')
            return
        }

        verifyEmail(token)
            .then((tokens) => {
                storeTokens(tokens)
                return refreshUser()
            })
            .then(() => {
                setStep('set-password')
            })
            .catch((err) => {
                setErrorMsg(formatApiError(err))
                setStep('error')
            })
        // only run once
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [])

    // Step 1: set password
    async function handleSetPassword(e: FormEvent) {
        e.preventDefault()
        if (password !== confirmPassword) {
            setPwError(t('auth.verify.passwordMismatch'))
            return
        }
        setPwLoading(true)
        setPwError(null)
        try {
            const tokens = await setInitialPassword(password)
            storeTokens(tokens)
            await refreshUser()
            setStep('create-zev')
        } catch (err) {
            setPwError(formatApiError(err))
        } finally {
            setPwLoading(false)
        }
    }

    // Step 2: create ZEV
    async function handleCreateZev(e: FormEvent) {
        e.preventDefault()
        setZevLoading(true)
        setZevError(null)
        try {
            await createSelfSetupZev({
                ...zevForm,
                grid_operator: zevForm.grid_operator || undefined,
            })
            // Refresh user in context so ProtectedRoute sees isAuthenticated
            // before the route change is committed.
            await refreshUser()
            navigate('/', { replace: true })
        } catch (err) {
            setZevError(formatApiError(err))
        } finally {
            setZevLoading(false)
        }
    }

    if (step === 'verifying') {
        return (
            <div className="center-screen">
                <div className="card verify-card">
                    <p className="muted">{t('auth.verify.verifying')}</p>
                </div>
            </div>
        )
    }

    if (step === 'error') {
        return (
            <div className="center-screen">
                <div className="card verify-card">
                    <h2>{t('auth.verify.errorTitle')}</h2>
                    <div className="error-banner">{errorMsg}</div>
                    <a href="/login" className="button button-outline" style={{ textAlign: 'center' }}>
                        {t('auth.submit')}
                    </a>
                </div>
            </div>
        )
    }

    if (step === 'set-password') {
        return (
            <div className="center-screen">
                <form className="card verify-card" onSubmit={handleSetPassword}>
                    <div className="verify-step-badge">1 / 2</div>
                    <h2>{t('auth.verify.passwordTitle')}</h2>
                    <p className="muted">{t('auth.verify.passwordDescription')}</p>

                    <label>
                        <span>{t('auth.verify.passwordLabel')}</span>
                        <input
                            type="password"
                            value={password}
                            onChange={(e) => setPassword(e.target.value)}
                            minLength={8}
                            required
                        />
                    </label>

                    <label>
                        <span>{t('auth.verify.passwordConfirm')}</span>
                        <input
                            type="password"
                            value={confirmPassword}
                            onChange={(e) => setConfirmPassword(e.target.value)}
                            minLength={8}
                            required
                        />
                    </label>

                    {pwError ? <div className="error-banner">{pwError}</div> : null}

                    <button className="button" type="submit" disabled={pwLoading}>
                        {pwLoading ? t('common.loading') : t('auth.verify.passwordSubmit')}
                    </button>
                </form>
            </div>
        )
    }

    if (step === 'create-zev') {
        return (
            <div className="center-screen">
                <form className="card verify-card" onSubmit={handleCreateZev}>
                    <div className="verify-step-badge">2 / 2</div>
                    <h2>{t('auth.verify.zevTitle')}</h2>
                    <p className="muted">{t('auth.verify.zevDescription')}</p>

                    <label>
                        <span>{t('auth.verify.zevName')}</span>
                        <input
                            value={zevForm.name}
                            onChange={(e) => setZevForm((f) => ({ ...f, name: e.target.value }))}
                            required
                        />
                    </label>

                    <label>
                        <span>{t('auth.verify.zevStartDate')}</span>
                        <input
                            type="date"
                            value={zevForm.start_date}
                            onChange={(e) => setZevForm((f) => ({ ...f, start_date: e.target.value }))}
                            required
                        />
                    </label>

                    <label>
                        <span>{t('auth.verify.zevType')}</span>
                        <select
                            value={zevForm.zev_type}
                            onChange={(e) => setZevForm((f) => ({ ...f, zev_type: e.target.value as 'zev' | 'vzev' }))}
                        >
                            <option value="zev">{t('auth.verify.zevTypeZev')}</option>
                            <option value="vzev">{t('auth.verify.zevTypeVzev')}</option>
                        </select>
                    </label>

                    <label>
                        <span>{t('auth.verify.zevBillingInterval')}</span>
                        <select
                            value={zevForm.billing_interval}
                            onChange={(e) =>
                                setZevForm((f) => ({
                                    ...f,
                                    billing_interval: e.target.value as SelfSetupZevInput['billing_interval'],
                                }))
                            }
                        >
                            <option value="monthly">{t('auth.verify.billingMonthly')}</option>
                            <option value="quarterly">{t('auth.verify.billingQuarterly')}</option>
                            <option value="semi_annual">{t('auth.verify.billingSemiAnnual')}</option>
                            <option value="annual">{t('auth.verify.billingAnnual')}</option>
                        </select>
                    </label>

                    <label>
                        <span>{t('auth.verify.zevGridOperator')}</span>
                        <input
                            value={zevForm.grid_operator ?? ''}
                            onChange={(e) => setZevForm((f) => ({ ...f, grid_operator: e.target.value }))}
                        />
                    </label>

                    {zevError ? <div className="error-banner">{zevError}</div> : null}

                    <button className="button" type="submit" disabled={zevLoading}>
                        {zevLoading ? t('common.loading') : t('auth.verify.zevSubmit')}
                    </button>
                </form>
            </div>
        )
    }

    return null
}
