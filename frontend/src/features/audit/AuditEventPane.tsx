import type { Ref } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { fetchAuditEvent } from '../../lib/api/audit'
import { queryKeys } from '../../lib/api/queryKeys'
import { formatDateTime, useAppSettings } from '../../lib/appSettings'
import type { AuditEventStatus } from '../../types/api'
import { DetailPane } from '../../components/DetailPane'
import { ChangesDiff } from './ChangesDiff'

type AuditEventPaneProps = {
    eventId: string
    onClose: () => void
    statusBadgeClass: (status: AuditEventStatus) => string
    /** The title is where focus lands when the pane is opened on purpose. */
    titleRef?: Ref<HTMLHeadingElement>
}

function Field({ label, children }: { label: string, children: React.ReactNode }) {
    return (
        <div className="audit-detail-field">
            <strong>{label}</strong>
            <div>{children}</div>
        </div>
    )
}

/**
 * One audit event in full, beside the log it was picked from. Picking another
 * row swaps the contents in place, which is the point when stepping through a
 * log (SPEC-2026-10-ui-patterns §5 rule C).
 */
export function AuditEventPane({ eventId, onClose, statusBadgeClass, titleRef }: AuditEventPaneProps) {
    const { t } = useTranslation()
    const { settings } = useAppSettings()

    const eventQuery = useQuery({
        queryKey: queryKeys.admin.auditEvent(eventId),
        queryFn: () => fetchAuditEvent(eventId),
    })

    const event = eventQuery.data

    return (
        <DetailPane title={t('pages.auditLogs.detail.title')} onClose={onClose} titleRef={titleRef}>
            <div className="detail-pane-body page-stack">
                {eventQuery.isLoading && <p>{t('pages.auditLogs.detail.loading')}</p>}
                {eventQuery.isError && <p className="text-error">{t('pages.auditLogs.detail.loadError')}</p>}

                {event && (
                    <>
                        <p className="audit-pane-summary">{event.summary}</p>

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
                                <p className="mt-05">{event.reason}</p>
                            </div>
                        )}

                        <div>
                            <strong>{t('pages.auditLogs.detail.changes')}</strong>
                            <div className="mt-05">
                                <ChangesDiff changes={event.changes_json} />
                            </div>
                        </div>

                        <div>
                            <strong>{t('pages.auditLogs.detail.metadata')}</strong>
                            <pre className="audit-pane-metadata">
                                {event.metadata_json && Object.keys(event.metadata_json).length > 0
                                    ? JSON.stringify(event.metadata_json, null, 2)
                                    : '—'}
                            </pre>
                        </div>
                    </>
                )}
            </div>
        </DetailPane>
    )
}
