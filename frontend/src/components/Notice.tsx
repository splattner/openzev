import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

export type NoticeTone = 'error' | 'warning'

export type NoticeProps = {
    tone: NoticeTone
    children: ReactNode
    /** Override the default live-region role. */
    role?: 'alert' | 'status'
    onRetry?: () => void
    isRetrying?: boolean
}

const NOTICE_CLASS: Record<NoticeTone, string> = {
    error: 'card error-banner',
    warning: 'warning-banner',
}

export function Notice({ tone, children, role, onRetry, isRetrying }: NoticeProps) {
    const { t } = useTranslation()
    return (
        <div
            className={`${NOTICE_CLASS[tone]}${onRetry ? ' notice--retry' : ''}`}
            role={role ?? (tone === 'error' ? 'alert' : 'status')}
        >
            {children}
            {onRetry && (
                <div className="actions-row">
                    <button
                        type="button"
                        className="button button-secondary button-compact"
                        onClick={onRetry}
                        disabled={isRetrying}
                        aria-busy={isRetrying || undefined}
                    >
                        {t(isRetrying ? 'common.loading' : 'common.retry')}
                    </button>
                </div>
            )}
        </div>
    )
}
