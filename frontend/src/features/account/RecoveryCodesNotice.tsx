import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useToast } from '../../lib/toast'
import { copyToClipboard } from '../../lib/clipboard'
import { downloadBlob } from '../../lib/downloadBlob'

interface Props {
    codes: string[]
    onDismiss: () => void
}

/**
 * The one-time display of recovery codes. Shown right after a first factor is
 * enrolled or the codes are regenerated, and never again: the backend keeps
 * only hashes, and this lives in component state only.
 */
export function RecoveryCodesNotice({ codes, onDismiss }: Props) {
    const { t } = useTranslation()
    const { pushToast } = useToast()
    const [copied, setCopied] = useState(false)

    async function handleCopy() {
        const ok = await copyToClipboard(codes.join('\n'))
        if (ok) setCopied(true)
        else pushToast(t('account.mfa.copyFailed'), 'error')
    }

    function handleDownload() {
        const blob = new Blob([codes.join('\n') + '\n'], { type: 'text/plain' })
        downloadBlob(blob, 'openzev-recovery-codes.txt')
    }

    return (
        <div className="warning-banner" role="alert" style={{ marginBottom: '1.5rem' }}>
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
                {codes.join('\n')}
            </code>
            <div className="actions-row" style={{ marginTop: '0.75rem' }}>
                <button type="button" className="button button-primary button-compact" onClick={() => void handleCopy()}>
                    {copied ? t('account.mfa.copied') : t('account.mfa.copy')}
                </button>
                <button type="button" className="button button-secondary button-compact" onClick={handleDownload}>
                    {t('account.mfa.download')}
                </button>
                <button type="button" className="button button-secondary button-compact" onClick={onDismiss}>
                    {t('account.mfa.dismissCodes')}
                </button>
            </div>
        </div>
    )
}
