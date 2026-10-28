import { useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { copyToClipboard } from '../lib/clipboard'
import { useToast } from '../lib/toast'

interface Props {
    /** The secret, held in the caller's state only until dismissed. */
    secret: string
    onDismiss: () => void
    /** Heading and explanation; the defaults are generic, a caller may say what was created. */
    title?: string
    body?: string
    /** Button labels, for callers that keep their own wording. */
    labels?: { copy?: string; copied?: string; dismiss?: string; copyFailed?: string }
    /** Usage hints shown below the secret (an endpoint, a command). */
    children?: ReactNode
    testId?: string
}

/**
 * The one place a credential is shown. The backend stores only a hash, so this
 * is the one and only time the secret can be read; copy it now or create a new one.
 */
export function SecretReveal({ secret, onDismiss, title, body, labels, children, testId = 'secret-reveal' }: Props) {
    const { t } = useTranslation()
    const { pushToast } = useToast()
    const [copied, setCopied] = useState(false)

    async function copy() {
        const ok = await copyToClipboard(secret)
        if (ok) setCopied(true)
        else pushToast(labels?.copyFailed ?? t('secretReveal.copyFailed'), 'error')
    }

    return (
        <div className="warning-banner" role="alert" style={{ display: 'grid', gap: '0.75rem' }}>
            <strong>{title ?? t('secretReveal.title')}</strong>
            <p className="m-0">{body ?? t('secretReveal.body')}</p>
            <code
                data-testid={testId}
                style={{
                    display: 'block',
                    wordBreak: 'break-all',
                    background: 'var(--surface-card)',
                    padding: '0.75rem',
                    borderRadius: '4px',
                    border: '1px solid var(--warning-200)',
                }}
            >
                {secret}
            </code>
            <div className="actions-row actions-row-wrap">
                <button type="button" className="button button-primary button-compact" onClick={() => void copy()}>
                    {copied ? (labels?.copied ?? t('secretReveal.copied')) : (labels?.copy ?? t('secretReveal.copy'))}
                </button>
                <button type="button" className="button button-secondary button-compact" onClick={onDismiss}>
                    {labels?.dismiss ?? t('secretReveal.dismiss')}
                </button>
            </div>
            {children}
        </div>
    )
}
