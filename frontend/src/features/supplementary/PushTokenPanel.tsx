import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { copyToClipboard } from '../../lib/clipboard'
import { CSV_COLUMNS, ingestUrl } from '../../lib/supplementary'
import { useToast } from '../../lib/toast'

interface Props {
    token: string
    onDismiss: () => void
}

/**
 * A push token is stored as a hash: this is the one and only time it can be read.
 * Held in component state by the caller and dropped on dismiss.
 */
export function PushTokenPanel({ token, onDismiss }: Props) {
    const { t } = useTranslation()
    const { pushToast } = useToast()
    const [copied, setCopied] = useState(false)
    const url = ingestUrl()

    async function copy(value: string, markCopied = false) {
        const ok = await copyToClipboard(value)
        if (ok && markCopied) setCopied(true)
        if (!ok) pushToast(t('supplementary.push.copyFailed'), 'error')
    }

    return (
        <div className="warning-banner" role="alert" style={{ display: 'grid', gap: '0.75rem' }}>
            <strong>{t('supplementary.push.shownOnceTitle')}</strong>
            <p style={{ margin: 0 }}>{t('supplementary.push.shownOnceBody')}</p>
            <code
                data-testid="push-token"
                style={{
                    display: 'block',
                    wordBreak: 'break-all',
                    background: 'var(--surface-card)',
                    padding: '0.75rem',
                    borderRadius: '4px',
                    border: '1px solid var(--warning-200)',
                }}
            >
                {token}
            </code>
            <div className="actions-row actions-row-wrap">
                <button type="button" className="button button-primary button-compact" onClick={() => void copy(token, true)}>
                    {copied ? t('supplementary.push.copied') : t('supplementary.push.copy')}
                </button>
                <button type="button" className="button button-secondary button-compact" onClick={onDismiss}>
                    {t('supplementary.push.dismiss')}
                </button>
            </div>
            <div style={{ display: 'grid', gap: '0.35rem' }}>
                <strong>{t('supplementary.push.endpoint')}</strong>
                <code style={{ wordBreak: 'break-all' }}>POST {url}</code>
                <small className="muted">{t('supplementary.push.endpointHint')}</small>
                <button type="button" className="button button-secondary button-compact" onClick={() => void copy(url)}>
                    {t('supplementary.push.copyUrl')}
                </button>
            </div>
            <div style={{ display: 'grid', gap: '0.35rem' }}>
                <strong>{t('supplementary.push.columns')}</strong>
                <code>{CSV_COLUMNS.join(',')}</code>
                <small className="muted">{t('supplementary.push.columnsHint')}</small>
            </div>
        </div>
    )
}
