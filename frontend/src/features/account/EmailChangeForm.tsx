import { useState, type FormEvent } from 'react'
import { useMutation } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../../lib/auth'
import { requestEmailChange } from '../../lib/api/auth'
import { formatApiError } from '../../lib/api/errors'
import { useToast } from '../../lib/toast'

/**
 * Changing the address the account signs in with.
 *
 * Not part of the profile form: the email is the credential's anchor, so it
 * takes the current password and a confirmation link sent to the *new* address
 * before anything changes. Accounts with no password (participants, OAuth-only)
 * cannot re-authenticate, so they are told who maintains their address instead.
 */
export function EmailChangeForm() {
    const { t } = useTranslation()
    const { user } = useAuth()
    const { pushToast } = useToast()

    const [open, setOpen] = useState(false)
    const [newEmail, setNewEmail] = useState('')
    const [password, setPassword] = useState('')
    const [error, setError] = useState<string | null>(null)

    const mutation = useMutation({
        mutationFn: () => requestEmailChange(newEmail.trim(), password),
        onSuccess: () => {
            pushToast(t('account.emailChange.sent', { email: newEmail.trim() }), 'success')
            setOpen(false)
            setNewEmail('')
            setPassword('')
            setError(null)
        },
        onError: (err) => setError(formatApiError(err, t('account.emailChange.failed'))),
    })

    function submit(event: FormEvent) {
        event.preventDefault()
        setError(null)
        mutation.mutate()
    }

    return (
        <div style={{ display: 'grid', gap: '0.5rem' }}>
            <label>
                <span>{t('account.email')}</span>
                <input type="email" value={user?.email ?? ''} disabled style={{ cursor: 'not-allowed' }} />
            </label>

            {user?.has_usable_password === false && <small className="muted">{t('account.emailChange.managed')}</small>}

            {user?.has_usable_password !== false && !open && (
                <div>
                    <button type="button" className="button button-secondary button-compact" onClick={() => setOpen(true)}>
                        {t('account.emailChange.button')}
                    </button>
                </div>
            )}

            {user?.has_usable_password !== false && open && (
                <form onSubmit={submit} style={{ display: 'grid', gap: '0.75rem' }}>
                    <small className="muted">{t('account.emailChange.hint')}</small>
                    <label>
                        <span>{t('account.emailChange.newEmail')}</span>
                        <input
                            type="email"
                            value={newEmail}
                            onChange={(event) => setNewEmail(event.target.value)}
                            autoComplete="off"
                            required
                        />
                    </label>
                    <label>
                        <span>{t('account.emailChange.currentPassword')}</span>
                        <input
                            type="password"
                            value={password}
                            onChange={(event) => setPassword(event.target.value)}
                            autoComplete="current-password"
                            required
                        />
                    </label>
                    {error && <div className="error-banner">{error}</div>}
                    <div className="actions-row actions-row-end actions-row-wrap">
                        <button type="button" className="button button-secondary" onClick={() => setOpen(false)}>
                            {t('common.cancel')}
                        </button>
                        <button type="submit" className="button button-primary" disabled={mutation.isPending}>
                            {t('account.emailChange.submit')}
                        </button>
                    </div>
                </form>
            )}
        </div>
    )
}
