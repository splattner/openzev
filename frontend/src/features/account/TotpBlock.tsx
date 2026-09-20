import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { beginTotpEnrolment, confirmTotpEnrolment, removeTotp } from '../../lib/api/auth'
import { formatApiError } from '../../lib/api/errors'
import { queryKeys } from '../../lib/api/queryKeys'
import { useToast } from '../../lib/toast'
import type { TotpDevice, TotpEnrolment } from '../../types/api'

interface Props {
    device: TotpDevice | null
    /** Called with the recovery codes when this was the account's first factor. */
    onRecoveryCodes: (codes: string[]) => void
    onRemove: (onConfirm: () => void) => void
}

/** Authenticator-app (TOTP) enrolment and removal. Spec
 * 2026-09-two-factor-authentication.md §7.2. */
export function TotpBlock({ device, onRecoveryCodes, onRemove }: Props) {
    const { t } = useTranslation()
    const { pushToast } = useToast()
    const queryClient = useQueryClient()

    const [enrolment, setEnrolment] = useState<TotpEnrolment | null>(null)
    const [confirmCode, setConfirmCode] = useState('')
    const isActive = Boolean(device?.confirmed_at)

    function refresh() {
        void queryClient.invalidateQueries({ queryKey: queryKeys.auth.mfa() })
    }

    const beginMutation = useMutation({
        mutationFn: beginTotpEnrolment,
        onSuccess: (data) => {
            setEnrolment(data)
            setConfirmCode('')
        },
        onError: (error) => pushToast(formatApiError(error, t('common.error')), 'error'),
    })

    const confirmMutation = useMutation({
        mutationFn: () => confirmTotpEnrolment(confirmCode.trim()),
        onSuccess: ({ recovery_codes }) => {
            setEnrolment(null)
            setConfirmCode('')
            refresh()
            if (recovery_codes.length > 0) onRecoveryCodes(recovery_codes)
            pushToast(t('account.mfa.enabledSuccess'), 'success')
        },
        onError: () => pushToast(t('account.mfa.invalidCode'), 'error'),
    })

    const removeMutation = useMutation({
        mutationFn: removeTotp,
        onSuccess: () => {
            refresh()
            pushToast(t('account.mfa.removedSuccess'), 'success')
        },
        onError: (error) => pushToast(formatApiError(error, t('common.error')), 'error'),
    })

    return (
        <div style={{ marginBottom: '1.5rem' }}>
            <strong>{t('account.mfa.authenticatorTitle')}</strong>
            <p className="muted">{t('account.mfa.description')}</p>

            {isActive ? (
                <div className="actions-row" style={{ alignItems: 'center' }}>
                    <span className="badge" style={{ background: 'var(--success-100)', color: 'var(--success-700)' }}>
                        {t('account.mfa.enabledBadge')}
                    </span>
                    <button
                        type="button"
                        className="button button-danger button-compact"
                        disabled={removeMutation.isPending}
                        onClick={() => onRemove(() => removeMutation.mutate())}
                    >
                        {t('account.mfa.remove')}
                    </button>
                </div>
            ) : enrolment ? (
                <form
                    onSubmit={(event) => {
                        event.preventDefault()
                        confirmMutation.mutate()
                    }}
                >
                    <p>{t('account.mfa.scanQr')}</p>
                    <div
                        style={{ maxWidth: '200px', margin: '0 auto 1rem' }}
                        // The backend renders this SVG server-side (qrcode + Pillow-free
                        // SvgPathImage) — no external QR service ever sees the secret.
                        dangerouslySetInnerHTML={{ __html: enrolment.qr_svg }}
                    />
                    <p className="muted">{t('account.mfa.orEnterSecret')}</p>
                    <code style={{ display: 'block', textAlign: 'center', marginBottom: '1rem', wordBreak: 'break-all' }}>
                        {enrolment.secret}
                    </code>

                    <label>
                        <span>{t('account.mfa.codeLabel')}</span>
                        <input
                            type="text"
                            inputMode="numeric"
                            autoComplete="one-time-code"
                            maxLength={6}
                            value={confirmCode}
                            onChange={(event) => setConfirmCode(event.target.value)}
                            required
                        />
                    </label>

                    <div className="actions-row">
                        <button type="submit" className="button button-primary" disabled={confirmMutation.isPending}>
                            {confirmMutation.isPending ? t('common.saving') : t('account.mfa.confirm')}
                        </button>
                        <button type="button" className="button button-secondary" onClick={() => setEnrolment(null)}>
                            {t('common.cancel')}
                        </button>
                    </div>
                </form>
            ) : (
                <button
                    type="button"
                    className="button button-primary"
                    disabled={beginMutation.isPending}
                    onClick={() => beginMutation.mutate()}
                >
                    {beginMutation.isPending ? t('common.loading') : t('account.mfa.setUp')}
                </button>
            )}
        </div>
    )
}
