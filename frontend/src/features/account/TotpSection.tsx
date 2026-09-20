import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import {
    beginTotpEnrolment,
    confirmTotpEnrolment,
    fetchMfaStatus,
    regenerateRecoveryCodes,
    removeTotp,
} from '../../lib/api/auth'
import { queryKeys } from '../../lib/api/queryKeys'
import { useToast } from '../../lib/toast'
import { copyToClipboard } from '../../lib/clipboard'
import { downloadBlob } from '../../lib/downloadBlob'
import type { TotpEnrolment } from '../../types/api'

interface Props {
    onRemove: (onConfirm: () => void) => void
}

/**
 * TOTP + recovery codes. Spec 2026-09-two-factor-authentication.md §7.2 —
 * the passkeys list joins this once WebAuthnCredential ships (PR 3); the
 * section title stays "Two-factor authentication" rather than "Authenticator
 * app" so it does not need renaming when that lands.
 */
export function TotpSection({ onRemove }: Props) {
    const { t } = useTranslation()
    const { pushToast } = useToast()
    const queryClient = useQueryClient()

    const [enrolment, setEnrolment] = useState<TotpEnrolment | null>(null)
    const [confirmCode, setConfirmCode] = useState('')
    // Recovery codes are shown exactly once — right after confirmation or a
    // regeneration — and never again. Held in component state only; the
    // backend never returns them a second time.
    const [freshCodes, setFreshCodes] = useState<string[] | null>(null)
    const [copied, setCopied] = useState(false)

    const statusQuery = useQuery({ queryKey: queryKeys.auth.mfa(), queryFn: fetchMfaStatus })

    const beginMutation = useMutation({
        mutationFn: beginTotpEnrolment,
        onSuccess: (data) => {
            setEnrolment(data)
            setConfirmCode('')
        },
        onError: (error: any) => pushToast(error.response?.data?.detail ?? t('common.error'), 'error'),
    })

    const confirmMutation = useMutation({
        mutationFn: () => confirmTotpEnrolment(confirmCode.trim()),
        onSuccess: ({ recovery_codes }) => {
            setEnrolment(null)
            setConfirmCode('')
            setFreshCodes(recovery_codes)
            setCopied(false)
            void queryClient.invalidateQueries({ queryKey: queryKeys.auth.mfa() })
            pushToast(t('account.mfa.enabledSuccess'), 'success')
        },
        onError: () => pushToast(t('account.mfa.invalidCode'), 'error'),
    })

    const removeMutation = useMutation({
        mutationFn: removeTotp,
        onSuccess: () => {
            void queryClient.invalidateQueries({ queryKey: queryKeys.auth.mfa() })
            pushToast(t('account.mfa.removedSuccess'), 'success')
        },
        onError: () => pushToast(t('common.error'), 'error'),
    })

    const regenerateMutation = useMutation({
        mutationFn: regenerateRecoveryCodes,
        onSuccess: ({ recovery_codes }) => {
            setFreshCodes(recovery_codes)
            setCopied(false)
            void queryClient.invalidateQueries({ queryKey: queryKeys.auth.mfa() })
        },
        onError: () => pushToast(t('common.error'), 'error'),
    })

    async function handleCopyCodes(codes: string[]) {
        const ok = await copyToClipboard(codes.join('\n'))
        if (ok) setCopied(true)
        else pushToast(t('account.mfa.copyFailed'), 'error')
    }

    function handleDownloadCodes(codes: string[]) {
        const blob = new Blob([codes.join('\n') + '\n'], { type: 'text/plain' })
        downloadBlob(blob, 'openzev-recovery-codes.txt')
    }

    if (statusQuery.isLoading) {
        return (
            <div className="card">
                <h2>{t('account.mfa.section')}</h2>
                <p className="muted">{t('common.loading')}</p>
            </div>
        )
    }

    const status = statusQuery.data
    const isActive = Boolean(status?.totp?.confirmed_at)

    return (
        <div className="card">
            <h2>{t('account.mfa.section')}</h2>
            <p className="muted" style={{ marginBottom: '1.5rem' }}>{t('account.mfa.description')}</p>

            {freshCodes && (
                <div className="warning-banner" role="alert">
                    <strong>{t('account.mfa.recoveryCodesShownOnceTitle')}</strong>
                    <p style={{ marginTop: '0.5rem' }}>{t('account.mfa.recoveryCodesShownOnceBody')}</p>
                    <code
                        style={{
                            display: 'block',
                            whiteSpace: 'pre-line',
                            background: 'var(--surface-card)',
                            padding: '0.75rem',
                            borderRadius: '4px',
                            border: '1px solid var(--warning-200)',
                        }}
                    >
                        {freshCodes.join('\n')}
                    </code>
                    <div className="actions-row" style={{ marginTop: '0.75rem' }}>
                        <button
                            type="button"
                            className="button button-primary button-compact"
                            onClick={() => void handleCopyCodes(freshCodes)}
                        >
                            {copied ? t('account.mfa.copied') : t('account.mfa.copy')}
                        </button>
                        <button
                            type="button"
                            className="button button-secondary button-compact"
                            onClick={() => handleDownloadCodes(freshCodes)}
                        >
                            {t('account.mfa.download')}
                        </button>
                        <button
                            type="button"
                            className="button button-secondary button-compact"
                            onClick={() => setFreshCodes(null)}
                        >
                            {t('account.mfa.dismissCodes')}
                        </button>
                    </div>
                </div>
            )}

            {isActive ? (
                <>
                    <div className="actions-row" style={{ alignItems: 'center', marginBottom: '1rem' }}>
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

                    <div style={{ borderTop: '1px solid var(--border)', paddingTop: '1rem' }}>
                        <strong>{t('account.mfa.recoveryCodesTitle')}</strong>
                        <p className="muted">
                            {t('account.mfa.recoveryCodesRemaining', { count: status?.recovery_codes_remaining ?? 0 })}
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
                </>
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
