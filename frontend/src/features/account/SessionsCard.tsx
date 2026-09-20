import { useMutation } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { revokeOtherSessions } from '../../lib/api/auth'
import { formatApiError } from '../../lib/api/errors'
import { useToast } from '../../lib/toast'

/**
 * "Sign out other devices": ends every session but this one. There is no list
 * of sessions to pick from — sessions are stateless tokens, so the only
 * honest control is all-or-nothing (see ADR 0022).
 */
export function SessionsCard({ onRevoke }: { onRevoke: (onConfirm: () => Promise<void>) => void }) {
    const { t } = useTranslation()
    const { pushToast } = useToast()

    const mutation = useMutation({
        mutationFn: revokeOtherSessions,
        onSuccess: () => pushToast(t('account.sessions.success'), 'success'),
        onError: (error) => pushToast(formatApiError(error, t('account.sessions.failed')), 'error'),
    })

    return (
        <div className="card">
            <h2>{t('account.sessions.title')}</h2>
            <p className="muted">{t('account.sessions.description')}</p>
            <button
                type="button"
                className="button button-secondary"
                disabled={mutation.isPending}
                onClick={() => onRevoke(async () => { await mutation.mutateAsync() })}
            >
                {t('account.sessions.signOutOthers')}
            </button>
        </div>
    )
}
