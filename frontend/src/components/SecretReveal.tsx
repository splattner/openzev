import { useEffect, useId, useRef, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { CopyButton } from './CopyButton'
import { Notice } from './Notice'

interface Props {
    secret: string
    /** Names the value, above it. */
    title: string
    /** The warning below it: shown only once, and what to do if it is lost. */
    body: string
    /** Clears the secret from the caller's state, on a page. A dialog leaves it out and closes with its own Done. */
    onDismiss?: () => void
    /** Buttons beside Copy (a download). */
    actions?: ReactNode
    /** Usage hints below the warning (an endpoint, a command). */
    children?: ReactNode
    testId?: string
}

/** Shows a credential the caller cannot show again, with Copy beside it. */
export function SecretReveal({ secret, title, body, onDismiss, actions, children, testId = 'secret-reveal' }: Props) {
    const { t } = useTranslation()
    const titleId = useId()
    const copyButton = useRef<HTMLButtonElement>(null)

    // The control that created the secret is usually gone: start on Copy rather than nowhere.
    useEffect(() => {
        if (document.activeElement === document.body) copyButton.current?.focus()
    }, [])

    return (
        <div style={{ display: 'grid', gap: '1rem' }}>
            <div>
                <strong id={titleId}>{title}</strong>
                <div className="copy-row mt-05">
                    <code data-testid={testId}>{secret}</code>
                    <div className="copy-row-actions">
                        <CopyButton ref={copyButton} value={secret} labelId={titleId} />
                        {actions}
                    </div>
                </div>
            </div>
            <Notice tone="warning" role="alert">{body}</Notice>
            {children}
            {onDismiss && (
                <div className="actions-row">
                    <button type="button" className="button button-secondary button-compact" onClick={onDismiss}>
                        {t('secretReveal.dismiss')}
                    </button>
                </div>
            )}
        </div>
    )
}
