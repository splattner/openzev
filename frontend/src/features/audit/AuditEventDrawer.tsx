import { useEffect } from 'react'
import { Drawer } from '@mantine/core'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faXmark } from '@fortawesome/free-solid-svg-icons'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { fetchAuditEvent } from '../../lib/api/audit'
import { queryKeys } from '../../lib/api/queryKeys'
import { formatDateTime, useAppSettings } from '../../lib/appSettings'
import type { AuditEventStatus } from '../../types/api'
import { ChangesDiff } from './ChangesDiff'

type AuditEventDrawerProps = {
    eventId: string | null
    onClose: () => void
    statusBadgeClass: (status: AuditEventStatus) => string
}

function Field({ label, children }: { label: string, children: React.ReactNode }) {
    return (
        <div className="audit-detail-field">
            <strong>{label}</strong>
            <div>{children}</div>
        </div>
    )
}

export function AuditEventDrawer({ eventId, onClose, statusBadgeClass }: AuditEventDrawerProps) {
    const { t } = useTranslation()
    const { settings } = useAppSettings()

    const eventQuery = useQuery({
        queryKey: queryKeys.admin.auditEvent(eventId ?? ''),
        queryFn: () => fetchAuditEvent(eventId ?? ''),
        enabled: Boolean(eventId),
    })

    // The drawer is deliberately non-modal so the table behind it stays
    // clickable — picking the next row swaps the contents in place, which is
    // the whole point when stepping through a log. That costs us the Modal's
    // own key handling, so Escape is wired up here.
    useEffect(() => {
        if (!eventId) return
        function onKeyDown(event: KeyboardEvent) {
            if (event.key === 'Escape') onClose()
        }
        document.addEventListener('keydown', onKeyDown)
        return () => document.removeEventListener('keydown', onKeyDown)
    }, [eventId, onClose])

    const event = eventQuery.data

    return (
        <Drawer
            opened={Boolean(eventId)}
            onClose={onClose}
            position="right"
            withCloseButton={false}
            trapFocus={false}
            lockScroll={false}
            styles={{
                content: { width: 'min(100vw, 560px)', pointerEvents: 'auto', boxShadow: '-8px 0 24px -12px rgba(0, 0, 0, 0.35)' },
                inner: { padding: 0 },
                root: { pointerEvents: 'none' },
            }}
        >
            <div className="audit-drawer">
                <header className="audit-drawer-header">
                    <h3>{t('pages.auditLogs.detail.title')}</h3>
                    <button
                        type="button"
                        className="button button-secondary"
                        onClick={onClose}
                        aria-label={t('pages.auditLogs.detail.close')}
                    >
                        <FontAwesomeIcon icon={faXmark} fixedWidth />
                    </button>
                </header>

                <div className="audit-drawer-body page-stack">
                    {eventQuery.isLoading && <p>{t('pages.auditLogs.detail.loading')}</p>}
                    {eventQuery.isError && <p className="text-error">{t('pages.auditLogs.detail.loadError')}</p>}

                    {event && (
                        <>
                            <p className="audit-drawer-summary">{event.summary}</p>

                            <div className="audit-detail-grid">
                                <Field label={t('pages.auditLogs.detail.createdAt')}>
                                    {formatDateTime(event.created_at, settings)}
                                </Field>
                                <Field label={t('pages.auditLogs.detail.status')}>
                                    <span className={statusBadgeClass(event.status)}>
                                        {t(`pages.auditLogs.statuses.${event.status}`)}
                                    </span>
                                </Field>
                                <Field label={t('pages.auditLogs.detail.category')}>
                                    {t(`pages.auditLogs.categories.${event.action_category}`)}
                                </Field>
                                <Field label={t('pages.auditLogs.detail.action')}>
                                    <code>{event.action_type}</code>
                                </Field>
                                <Field label={t('pages.auditLogs.detail.actor')}>
                                    {event.actor_display || '—'}
                                </Field>
                                <Field label={t('pages.auditLogs.detail.source')}>
                                    <code>{event.source}</code>
                                </Field>
                                <Field label={t('pages.auditLogs.detail.target')}>
                                    {event.target_display || `${event.target_type}:${event.target_id || '-'}`}
                                </Field>
                                <Field label={t('pages.auditLogs.detail.requestId')}>
                                    <code>{event.request_id || '—'}</code>
                                </Field>
                                <Field label={t('pages.auditLogs.detail.correlationId')}>
                                    <code>{event.correlation_id || '—'}</code>
                                </Field>
                                <Field label={t('pages.auditLogs.detail.id')}>
                                    <code>{event.id}</code>
                                </Field>
                            </div>

                            {event.reason && (
                                <div>
                                    <strong>{t('pages.auditLogs.detail.reason')}</strong>
                                    <p style={{ marginTop: '0.5rem' }}>{event.reason}</p>
                                </div>
                            )}

                            <div>
                                <strong>{t('pages.auditLogs.detail.changes')}</strong>
                                <div style={{ marginTop: '0.5rem' }}>
                                    <ChangesDiff changes={event.changes_json} />
                                </div>
                            </div>

                            <div>
                                <strong>{t('pages.auditLogs.detail.metadata')}</strong>
                                <pre style={{ overflowX: 'auto' }}>
                                    {event.metadata_json && Object.keys(event.metadata_json).length > 0
                                        ? JSON.stringify(event.metadata_json, null, 2)
                                        : '—'}
                                </pre>
                            </div>
                        </>
                    )}
                </div>
            </div>
        </Drawer>
    )
}
