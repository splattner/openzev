import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { fetchMfaStatus, regenerateRecoveryCodes } from '../../lib/api/auth'
import { formatApiError } from '../../lib/api/errors'
import { queryKeys } from '../../lib/api/queryKeys'
import { formatDateTime, useAppSettings } from '../../lib/appSettings'
import { useToast } from '../../lib/toast'
import type { Passkey } from '../../types/api'
import { PasskeysBlock } from './PasskeysBlock'
import { RecoveryCodesNotice } from './RecoveryCodesNotice'
import { TotpBlock } from './TotpBlock'

interface Props {
    onRemoveTotp: (onConfirm: () => void) => void
    onRemovePasskey: (passkey: Passkey, onConfirm: () => void) => void
}

/**
 * The account page's second-factor card: passkeys, authenticator app and
 * recovery codes together, because recovery codes belong to the account, not
 * to one factor. Spec 2026-09-two-factor-authentication.md §7.2.
 */
export function TwoFactorSection({ onRemoveTotp, onRemovePasskey }: Props) {
    const { t } = useTranslation()
    const { pushToast } = useToast()
    const queryClient = useQueryClient()
    const { settings } = useAppSettings()
    // Held in component state only; the backend never returns them twice.
    const [freshCodes, setFreshCodes] = useState<string[] | null>(null)

    const statusQuery = useQuery({ queryKey: queryKeys.auth.mfa(), queryFn: fetchMfaStatus })

    const regenerateMutation = useMutation({
        mutationFn: regenerateRecoveryCodes,
        onSuccess: ({ recovery_codes }) => {
            setFreshCodes(recovery_codes)
            void queryClient.invalidateQueries({ queryKey: queryKeys.auth.mfa() })
        },
        onError: (error) => pushToast(formatApiError(error, t('common.error')), 'error'),
    })

    if (statusQuery.isLoading || !statusQuery.data) {
        return (
            <div className="card">
                <h2>{t('account.mfa.section')}</h2>
                <p className="muted">{t('common.loading')}</p>
            </div>
        )
    }

    const status = statusQuery.data
    const protectedAccount = Boolean(status.totp?.confirmed_at) || status.passkeys.length > 0

    return (
        <div className="card">
            <h2>{t('account.mfa.section')}</h2>

            {status.required && !protectedAccount && (
                <div className="warning-banner" role="status" style={{ marginBottom: '1rem' }}>
                    {status.grace_until
                        ? t('account.mfa.requiredUntil', { date: formatDateTime(status.grace_until, settings) })
                        : t('account.mfa.required')}
                </div>
            )}

            {freshCodes && <RecoveryCodesNotice codes={freshCodes} onDismiss={() => setFreshCodes(null)} />}

            <PasskeysBlock passkeys={status.passkeys} onRecoveryCodes={setFreshCodes} onRemove={onRemovePasskey} />
            <TotpBlock device={status.totp} onRecoveryCodes={setFreshCodes} onRemove={onRemoveTotp} />

            {protectedAccount && (
                <div style={{ borderTop: '1px solid var(--border)', paddingTop: '1rem' }}>
                    <strong>{t('account.mfa.recoveryCodesTitle')}</strong>
                    <p className="muted">
                        {t('account.mfa.recoveryCodesRemaining', { count: status.recovery_codes_remaining })}
                    </p>
                    <button
                        type="button"
                        className="button button-secondary button-compact"
                        disabled={regenerateMutation.isPending}
                        onClick={() => regenerateMutation.mutate()}
                    >
                        {regenerateMutation.isPending ? t('common.saving') : t('account.mfa.regenerateCodes')}
                    </button>
                </div>
            )}
        </div>
    )
}
