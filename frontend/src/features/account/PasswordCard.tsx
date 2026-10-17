import { useEffect, useState, type ChangeEvent, type FormEvent } from 'react'
import { useMutation } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../../lib/auth'
import { changePassword, resetPassword, setInitialPassword } from '../../lib/api/auth'
import { useToast } from '../../lib/toast'
import { apiErrorPayload, formatApiError } from '../../lib/api/errors'

const EMPTY_FORM = { oldPassword: '', newPassword: '', confirmPassword: '' }

/** Set, change, or explicitly recover the account password. */
export function PasswordCard() {
    const { t } = useTranslation()
    const { user, refreshUser } = useAuth()
    const { pushToast } = useToast()

    const [form, setForm] = useState(EMPTY_FORM)
    const [recoveryDeadline, setRecoveryDeadline] = useState<number | null>(null)
    const [now, setNow] = useState(() => Date.now())
    const deadline = user?.password_recovery_expires_at ? Date.parse(user.password_recovery_expires_at) : 0
    const mode = user?.has_usable_password === false ? 'initial' : deadline && recoveryDeadline === deadline ? 'recovery' : 'change'
    const recoveryAvailable = deadline > now
    const submitLabel = { initial: 'account.setPassword', recovery: 'account.recoverPassword', change: 'account.changePassword' }[mode]

    useEffect(() => {
        if (!deadline) return
        const timer = setTimeout(() => setNow(Date.now()), Math.max(0, deadline - Date.now()))
        return () => clearTimeout(timer)
    }, [deadline])

    const mutation = useMutation({
        mutationFn: async () => {
            if (mode === 'initial') await setInitialPassword(form.newPassword)
            else if (mode === 'recovery') await resetPassword(form.newPassword)
            else await changePassword(form.oldPassword, form.newPassword)
        },
        onSuccess: async () => {
            setForm(EMPTY_FORM)
            setRecoveryDeadline(null)
            pushToast(t('account.passwordChangedSuccess'), 'success')
            await refreshUser().catch(() => pushToast(t('account.profileRefreshFailed'), 'info'))
        },
        onError: async (error) => {
            const expired = apiErrorPayload(error)?.code === 'password_recovery_required'
            pushToast(expired ? t('account.passwordRecoveryExpired') : formatApiError(error, t('common.error')), 'error')
            if (expired) {
                setRecoveryDeadline(null)
                await refreshUser().catch(() => pushToast(t('account.profileRefreshFailed'), 'info'))
            }
        },
    })

    const handleChange = (event: ChangeEvent<HTMLInputElement>) => {
        const { name, value } = event.target
        setForm((previous) => ({ ...previous, [name]: value }))
    }

    const handleSubmit = (event: FormEvent) => {
        event.preventDefault()

        if (mode === 'recovery' && deadline <= Date.now()) {
            pushToast(t('account.passwordRecoveryExpired'), 'error')
            return
        }
        if (mode === 'change' && !form.oldPassword) {
            pushToast(t('account.oldPasswordRequired'), 'error')
            return
        }
        if (!form.newPassword) {
            pushToast(t('account.newPasswordRequired'), 'error')
            return
        }
        if (form.newPassword !== form.confirmPassword) {
            pushToast(t('account.passwordsDoNotMatch'), 'error')
            return
        }
        if (form.newPassword.length < 8) {
            pushToast(t('account.passwordTooShort'), 'error')
            return
        }

        mutation.mutate()
    }

    const toggleRecovery = () => {
        setRecoveryDeadline(mode === 'recovery' ? null : deadline)
        setForm(EMPTY_FORM)
    }
    const submitDisabled = mutation.isPending || (mode === 'recovery' && !recoveryAvailable)

    return (
        <div className="card">
            <h2>{t(mode === 'initial' ? 'account.setPassword' : 'account.passwordSection')}</h2>
            {mode === 'initial' && <p className="muted">{t('account.setPasswordHelp')}</p>}
            {mode !== 'initial' && (recoveryAvailable || mode === 'recovery') && <>
                <p className="muted">{t('account.passwordRecoveryHelp')}</p>
                <button
                    type="button"
                    className="button button-secondary"
                    disabled={mutation.isPending}
                    onClick={toggleRecovery}
                >
                    {t(mode === 'recovery' ? 'account.useCurrentPassword' : 'account.recoverPassword')}
                </button>
                {mode === 'recovery' && <p role="status">{t(recoveryAvailable ? 'account.passwordRecoveryActive' : 'account.passwordRecoveryExpired')}</p>}
            </>}
            <form onSubmit={handleSubmit}>
                {mode === 'change' && <label>
                    <span>{t('account.oldPassword')}</span>
                    <input
                        type="password"
                        name="oldPassword"
                        value={form.oldPassword}
                        onChange={handleChange}
                        placeholder={t('account.enterCurrentPassword')}
                        required
                        autoComplete="current-password"
                    />
                </label>}

                <label>
                    <span>{t('account.newPassword')}</span>
                    <input
                        type="password"
                        name="newPassword"
                        value={form.newPassword}
                        onChange={handleChange}
                        placeholder={t('account.enterNewPassword')}
                        required
                        autoComplete="new-password"
                    />
                    <small className="muted">{t('account.passwordMinLength')}</small>
                </label>

                <label>
                    <span>{t('account.confirmPassword')}</span>
                    <input
                        type="password"
                        name="confirmPassword"
                        value={form.confirmPassword}
                        onChange={handleChange}
                        placeholder={t('account.reenterNewPassword')}
                        required
                        autoComplete="new-password"
                    />
                </label>

                <button type="submit" className="button button-primary" disabled={submitDisabled} style={{ width: '100%' }}>
                    {mutation.isPending ? t('common.saving') : t(submitLabel)}
                </button>
            </form>
            <small className="muted" style={{ marginTop: '1rem', display: 'block' }}>
                {t('account.apiKeys.passwordChangeNote')}
            </small>
        </div>
    )
}
