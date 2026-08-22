import { type EmailLog } from '../types/api'
import { formatDateTime, useAppSettings } from '../lib/appSettings'
import { useTranslation } from 'react-i18next'

interface EmailLogsModalProps {
    invoiceNumber: string
    emailLogs: EmailLog[]
    isOpen: boolean
    onClose: () => void
    onRetry?: (emailLogId: string) => void
    isRetrying?: boolean
}

const statusColors: Record<string, string> = {
    pending: '#f59e0b',  // amber
    sent: '#10b981',     // green
    failed: '#ef4444',   // red
}

export function EmailLogsModal({
    invoiceNumber,
    emailLogs,
    isOpen,
    onClose,
    onRetry,
    isRetrying = false,
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
        <div
            style={{
                position: 'fixed',
                inset: 0,
                backgroundColor: 'rgba(0, 0, 0, 0.5)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                zIndex: 999,
            }}
            onClick={onClose}
        >
            <div
                className="card"
                style={{
                    maxWidth: '600px',
                    maxHeight: '80vh',
                    overflow: 'auto',
                    padding: '2rem',
                }}
                onClick={(e) => e.stopPropagation()}
            >
                <h3 style={{ marginBottom: '1.5rem' }}>{t('pages.invoices.emailLogs.title', { number: invoiceNumber })}</h3>

                {emailLogs.length === 0 ? (
                    <p style={{ color: '#888', textAlign: 'center', padding: '2rem 0' }}>{t('pages.invoices.emailLogs.empty')}</p>
                ) : (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                        {emailLogs.map((log) => (
                            <div
                                key={log.id}
                                style={{
                                    border: '1px solid #ddd',
                                    borderRadius: '0.4rem',
                                    padding: '1rem',
                                    backgroundColor: '#f9f9f9',
                                }}
                            >
                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '0.5rem' }}>
                                    <div>
                                        <strong>{log.recipient}</strong>
                                        <div style={{ fontSize: '0.85rem', color: '#888', marginTop: '0.25rem' }}>
                                            {t('pages.invoices.emailLogs.subject', { subject: log.subject })}
                                        </div>
                                    </div>
                                    <div
                                        style={{
                                            display: 'inline-block',
                                            padding: '0.35rem 0.8rem',
                                            borderRadius: '0.3rem',
                                            backgroundColor: statusColors[log.status] ?? '#9ca3af',
                                            color: '#fff',
                                            fontSize: '0.8rem',
                                            fontWeight: '600',
                                            textAlign: 'center',
                                            minWidth: '80px',
                                        }}
                                    >
                                        {statusLabels[log.status] ?? t('pages.invoices.emailLogs.status.unknown')}
                                    </div>
                                </div>

                                <div style={{ fontSize: '0.85rem', color: '#666', marginBottom: '0.5rem' }}>
                                    <div>{t('pages.invoices.emailLogs.queued')} {formatDateTime(log.created_at, settings)}</div>
                                    {log.sent_at && <div>{t('pages.invoices.emailLogs.sent')} {formatDateTime(log.sent_at, settings)}</div>}
                                </div>

                                {log.error_message && (
                                    <div
                                        style={{
                                            backgroundColor: '#fee2e2',
                                            border: '1px solid #fca5a5',
                                            borderRadius: '0.3rem',
                                            padding: '0.5rem 0.75rem',
                                            fontSize: '0.85rem',
                                            color: '#991b1b',
                                            marginBottom: '0.5rem',
                                            fontFamily: 'monospace',
                                        }}
                                    >
                                        {log.error_message}
                                    </div>
                                )}

                                {log.status === 'failed' && onRetry && (
                                    <button
                                        className="button button-secondary"
                                        style={{ fontSize: '0.85rem', padding: '0.4rem 0.8rem' }}
                                        onClick={() => onRetry(log.id)}
                                        disabled={isRetrying}
                                        type="button"
                                    >
                                        {isRetrying ? t('pages.invoices.emailLogs.retrying') : t('pages.invoices.emailLogs.retry')}
                                    </button>
                                )}
                            </div>
                        ))}
                    </div>
                )}

                <div style={{ marginTop: '2rem', display: 'flex', justifyContent: 'flex-end' }}>
                    <button className="button button-secondary" onClick={onClose} type="button">
                        {t('common.close')}
                    </button>
                </div>
            </div>
        </div>
    )
}
