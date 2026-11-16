import { type EmailLog } from '../types/api'
import type { RefObject } from 'react'
import { formatDateTime, useAppSettings } from '../lib/appSettings'
import { useTranslation } from 'react-i18next'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faRotate, faXmark } from '@fortawesome/free-solid-svg-icons'
import { FormModal } from './FormModal'

interface EmailLogsModalProps {
    invoiceNumber: string
    emailLogs: EmailLog[]
    isOpen: boolean
    onClose: () => void
    onRetry?: (emailLogId: string) => void
    isRetrying?: boolean
    returnFocusRef?: RefObject<HTMLElement | null>
}

const statusClasses: Record<string, string> = {
    pending: 'badge-info',
    sent: 'badge-success',
    failed: 'badge-danger badge-quiet',
}

export function EmailLogsModal({
    invoiceNumber,
    emailLogs,
    isOpen,
    onClose,
    onRetry,
    isRetrying = false,
    returnFocusRef,
}: EmailLogsModalProps) {
    const { t } = useTranslation()
    const { settings } = useAppSettings()

    const statusLabels: Record<string, string> = {
        pending: t('pages.invoices.emailLogs.status.pending'),
        sent: t('pages.invoices.emailLogs.status.sent'),
        failed: t('pages.invoices.emailLogs.status.failed'),
        unknown: t('pages.invoices.emailLogs.status.unknown'),
    }

    if (!isOpen) return null

    return (
        <FormModal
            isOpen={isOpen}
            title={t('pages.invoices.emailLogs.title', { number: invoiceNumber })}
            onClose={onClose}
            returnFocusRef={returnFocusRef}
        >
            {emailLogs.length === 0 ? (
                <p className="email-logs-empty">{t('pages.invoices.emailLogs.empty')}</p>
            ) : (
                <div className="email-logs-list">
                    {emailLogs.map((log) => (
                        <div key={log.id} className="email-log">
                            <div className="email-log-header">
                                <div className="email-log-recipient">
                                    <strong>{log.recipient}</strong>
                                    <div className="email-log-subject">
                                        {t('pages.invoices.emailLogs.subject', { subject: log.subject })}
                                    </div>
                                </div>
                                <span className={`badge ${statusClasses[log.status] ?? 'badge-neutral'}`}>
                                    {statusLabels[log.status] ?? statusLabels.unknown}
                                </span>
                            </div>

                            <div className="email-log-meta">
                                <div>{t('pages.invoices.emailLogs.queued')} {formatDateTime(log.created_at, settings)}</div>
                                {log.sent_at && <div>{t('pages.invoices.emailLogs.sent')} {formatDateTime(log.sent_at, settings)}</div>}
                            </div>

                            {log.error_message && (
                                <div className="email-log-error">
                                    {log.error_message}
                                </div>
                            )}

                            {log.status === 'failed' && onRetry && (
                                <button
                                    className="button button-primary button-compact"
                                    onClick={() => onRetry(log.id)}
                                    disabled={isRetrying}
                                    type="button"
                                >
                                    <FontAwesomeIcon icon={faRotate} fixedWidth />
                                    {isRetrying ? t('pages.invoices.emailLogs.retrying') : t('pages.invoices.emailLogs.retry')}
                                </button>
                            )}
                        </div>
                    ))}
                </div>
            )}

            <div className="actions-row actions-row-end email-logs-footer">
                <button className="button button-secondary" onClick={onClose} type="button">
                    <FontAwesomeIcon icon={faXmark} fixedWidth />
                    {t('common.close')}
                </button>
            </div>
        </FormModal>
    )
}
