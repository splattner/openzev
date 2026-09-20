import { useState, type ChangeEvent, type FormEvent } from 'react'
import { useMutation } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../../lib/auth'
import { changePassword } from '../../lib/api/auth'
import { useToast } from '../../lib/toast'

/** Change the account password. Clears `must_change_password` on success. */
export function PasswordCard() {
    const { t } = useTranslation()
    const { refreshUser } = useAuth()
    const { pushToast } = useToast()

    const [form, setForm] = useState({ oldPassword: '', newPassword: '', confirmPassword: '' })

    const mutation = useMutation({
        mutationFn: () => changePassword(form.oldPassword, form.newPassword),
        onSuccess: async () => {
            setForm({ oldPassword: '', newPassword: '', confirmPassword: '' })
            await refreshUser()
            pushToast(t('account.passwordChangedSuccess'), 'success')
        },
        onError: (error: any) => {
            const message = error.response?.data?.detail || error.response?.data?.old_password?.[0] || t('common.error')
            pushToast(message, 'error')
        },
    })

    const handleChange = (event: ChangeEvent<HTMLInputElement>) => {
        const { name, value } = event.target
        setForm((previous) => ({ ...previous, [name]: value }))
    }

    const handleSubmit = (event: FormEvent) => {
        event.preventDefault()

        if (!form.oldPassword.trim()) {
            pushToast(t('account.oldPasswordRequired'), 'error')
            return
        }
        if (!form.newPassword.trim()) {
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

    return (
        <div className="card">
            <h2>{t('account.passwordSection')}</h2>
            <form onSubmit={handleSubmit}>
                <label>
                    <span>{t('account.oldPassword')}</span>
                    <input
                        type="password"
                        name="oldPassword"
                        value={form.oldPassword}
                        onChange={handleChange}
                        placeholder={t('account.enterCurrentPassword')}
                        required
                    />
                </label>

                <label>
                    <span>{t('account.newPassword')}</span>
                    <input
                        type="password"
                        name="newPassword"
                        value={form.newPassword}
                        onChange={handleChange}
                        placeholder={t('account.enterNewPassword')}
                        required
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
                    />
                </label>

                <button type="submit" className="button button-primary" disabled={mutation.isPending} style={{ width: '100%' }}>
                    {mutation.isPending ? t('common.saving') : t('account.changePassword')}
                </button>
            </form>
            <small className="muted" style={{ marginTop: '1rem', display: 'block' }}>
                {t('account.apiKeys.passwordChangeNote')}
            </small>
        </div>
    )
}
