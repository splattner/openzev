import { useEffect, useState, type ChangeEvent, type FormEvent } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../../lib/auth'
import { updateProfile } from '../../lib/api/auth'
import { queryKeys } from '../../lib/api/queryKeys'
import { useToast } from '../../lib/toast'
import { EmailChangeForm } from './EmailChangeForm'

/** The account's own name, plus its email (changed through `EmailChangeForm`). The username is fixed at creation. */
export function ProfileCard() {
    const { t } = useTranslation()
    const { user } = useAuth()
    const { pushToast } = useToast()
    const queryClient = useQueryClient()

    const [form, setForm] = useState({
        first_name: user?.first_name || '',
        last_name: user?.last_name || '',
    })

    useEffect(() => {
        setForm({
            first_name: user?.first_name || '',
            last_name: user?.last_name || '',
        })
    }, [user])

    const mutation = useMutation({
        mutationFn: () => updateProfile(form),
        onSuccess: () => {
            queryClient.refetchQueries({ queryKey: queryKeys.auth.me() })
            pushToast(t('account.profileUpdatedSuccess'), 'success')
        },
        onError: (error: any) => {
            const message = error.response?.data?.detail || t('common.error')
            pushToast(message, 'error')
        },
    })

    const handleChange = (event: ChangeEvent<HTMLInputElement>) => {
        const { name, value } = event.target
        setForm((previous) => ({ ...previous, [name]: value }))
    }

    const handleSubmit = (event: FormEvent) => {
        event.preventDefault()
        mutation.mutate()
    }

    return (
        <div className="card">
            <h2>{t('account.profileSection')}</h2>
            <form onSubmit={handleSubmit}>
                <label>
                    <span>{t('account.username')}</span>
                    <input
                        type="text"
                        value={user?.username || ''}
                        disabled
                        style={{ backgroundColor: 'var(--surface)', cursor: 'not-allowed' }}
                    />
                    <small className="muted">{t('account.usernameReadOnly')}</small>
                </label>

                <label>
                    <span>{t('account.firstName')}</span>
                    <input type="text" name="first_name" value={form.first_name} onChange={handleChange} />
                </label>

                <label>
                    <span>{t('account.lastName')}</span>
                    <input type="text" name="last_name" value={form.last_name} onChange={handleChange} />
                </label>

                <button type="submit" className="button button-primary" disabled={mutation.isPending} style={{ width: '100%' }}>
                    {mutation.isPending ? t('common.saving') : t('account.updateProfile')}
                </button>
            </form>

            <hr style={{ margin: '1.25rem 0' }} />
            <EmailChangeForm />
        </div>
    )
}
