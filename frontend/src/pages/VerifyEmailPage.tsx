import { useEffect, useState, type FormEvent } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../lib/auth'
import { verifyEmail, setInitialPassword, type VerificationPurpose } from '../lib/api/auth'
import { createSelfSetupZev } from '../lib/api/zev'
import { formatApiError } from '../lib/api/errors'
import { todayBusinessIso } from '../lib/dates'
import { isValidIban, normalizeIban } from '../lib/iban'
import type { SelfSetupZevInput } from '../types/api'
import { GridOperatorField } from '../features/zev/GridOperatorField'
import { GridOperatorSuggestion } from '../features/zev/GridOperatorSuggestion'

type Step = 'verifying' | 'error' | 'set-password' | 'create-zev' | 'done'

export function VerifyEmailPage() {
    const { t } = useTranslation()
    const navigate = useNavigate()
    const [searchParams] = useSearchParams()
    const { refreshUser } = useAuth()

    const [step, setStep] = useState<Step>('verifying')
    const [purpose, setPurpose] = useState<VerificationPurpose>('signup')
    const [errorMsg, setErrorMsg] = useState<string | null>(null)

    // Set-password step state
    const [password, setPassword] = useState('')
    const [confirmPassword, setConfirmPassword] = useState('')
    const [pwLoading, setPwLoading] = useState(false)
    const [pwError, setPwError] = useState<string | null>(null)

    // Create-ZEV step state
    const [zevForm, setZevForm] = useState<SelfSetupZevInput>({
        name: '',
        start_date: todayBusinessIso(),
        zev_type: 'zev',
        billing_interval: 'annual',
        grid_operator: '',
        bank_iban: '',
        bank_name: '',
        owner_address_line1: '',
        owner_address_line2: '',
        owner_postal_code: '',
        owner_city: '',
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
            .then((verifiedPurpose) => {
                setPurpose(verifiedPurpose)
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
            await setInitialPassword(password)
            await refreshUser()
            // Someone invited to an existing ZEV has nothing to set up (#761).
            if (purpose === 'invitation') {
                navigate('/', { replace: true })
                return
            }
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
        if (zevForm.bank_iban?.trim() && !isValidIban(zevForm.bank_iban)) {
            setZevError(t('auth.verify.invalidIban'))
            setZevLoading(false)
            return
        }
        if (zevForm.bank_iban?.trim() && (
            !zevForm.owner_address_line1?.trim()
            || !zevForm.owner_postal_code?.trim()
            || !zevForm.owner_city?.trim()
        )) {
            setZevError(t('auth.verify.ownerAddressRequiredForIban'))
            setZevLoading(false)
            return
        }
        try {
            await createSelfSetupZev({
                ...zevForm,
                bank_iban: normalizeIban(zevForm.bank_iban ?? ''),
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
                            name="name"
                            value={zevForm.name}
                            onChange={(e) => setZevForm((f) => ({ ...f, name: e.target.value }))}
                            required
                        />
                    </label>

                    <label>
                        <span>{t('auth.verify.zevStartDate')}</span>
                        <input
                            name="start_date"
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
                        <span>{t('auth.verify.zevPostalCode')}</span>
                        <input
                            value={zevForm.postal_code ?? ''}
                            onChange={(e) => setZevForm((f) => ({ ...f, postal_code: e.target.value }))}
                        />
                        <small className="muted">{t('auth.verify.zevPostalCodeHint')}</small>
                    </label>

                    <GridOperatorField
                        label={t('auth.verify.zevGridOperator')}
                        value={zevForm.grid_operator ?? ''}
                        elcomId={zevForm.grid_operator_elcom_id ?? null}
                        onChange={(next) => setZevForm((f) => ({ ...f, ...next }))}
                    />

                    {(zevForm.postal_code ?? '').trim() && (
                        <GridOperatorSuggestion
                            postalCode={zevForm.postal_code ?? ''}
                            currentElcomId={zevForm.grid_operator_elcom_id}
                            onApplyOperator={(operator) =>
                                setZevForm((f) => ({ ...f, grid_operator: operator.name, grid_operator_elcom_id: operator.id }))
                            }
                            onApplyTariffUrl={() => {
                                // No zev id exists yet during self-setup, so
                                // GridOperatorSuggestion never offers the URL
                                // step here — nothing to wire up.
                            }}
                        />
                    )}
                    <div className="payment-recipient-section">
                        <strong>{t('auth.verify.paymentRecipientHeader')}</strong>
                        <p className="muted">{t('auth.verify.paymentRecipientHint')}</p>
                        <div className="payment-fields-grid">
                            <label>
                                <span>{t('auth.verify.addressLine1')}</span>
                                <input
                                    name="owner_address_line1"
                                    value={zevForm.owner_address_line1 ?? ''}
                                    maxLength={200}
                                    onChange={(e) => setZevForm((f) => ({ ...f, owner_address_line1: e.target.value }))}
                                />
                            </label>
                            <label>
                                <span>{t('auth.verify.addressLine2')}</span>
                                <input
                                    name="owner_address_line2"
                                    value={zevForm.owner_address_line2 ?? ''}
                                    maxLength={200}
                                    onChange={(e) => setZevForm((f) => ({ ...f, owner_address_line2: e.target.value }))}
                                />
                            </label>
                            <label>
                                <span>{t('auth.verify.postalCode')}</span>
                                <input
                                    name="owner_postal_code"
                                    value={zevForm.owner_postal_code ?? ''}
                                    maxLength={10}
                                    onChange={(e) => setZevForm((f) => ({ ...f, owner_postal_code: e.target.value }))}
                                />
                            </label>
                            <label>
                                <span>{t('auth.verify.city')}</span>
                                <input
                                    name="owner_city"
                                    value={zevForm.owner_city ?? ''}
                                    maxLength={100}
                                    onChange={(e) => setZevForm((f) => ({ ...f, owner_city: e.target.value }))}
                                />
                            </label>
                            <label>
                                <span>{t('auth.verify.zevBankName')}</span>
                                <input
                                    name="bank_name"
                                    value={zevForm.bank_name ?? ''}
                                    maxLength={200}
                                    onChange={(e) => setZevForm((f) => ({ ...f, bank_name: e.target.value }))}
                                />
                            </label>
                            <label>
                                <span>{t('auth.verify.zevIban')}</span>
                                <input
                                    name="bank_iban"
                                    value={zevForm.bank_iban ?? ''}
                                    maxLength={34}
                                    onChange={(e) => setZevForm((f) => ({ ...f, bank_iban: e.target.value }))}
                                    onBlur={(e) => setZevForm((f) => ({ ...f, bank_iban: normalizeIban(e.target.value) }))}
                                />
                            </label>
                        </div>
                        <small className="muted">{t('auth.verify.zevIbanHint')}</small>
                    </div>

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
