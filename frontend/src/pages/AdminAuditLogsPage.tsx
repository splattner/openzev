import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { fetchAuditEvents } from '../lib/api/audit'
import { queryKeys } from '../lib/api/queryKeys'
import { formatDateTime, useAppSettings } from '../lib/appSettings'
import { useAuth } from '../lib/auth'
import { AuditEventDrawer } from '../features/audit/AuditEventDrawer'
import type { AuditActionCategory, AuditEvent, AuditEventFilters, AuditEventStatus } from '../types/api'

type AuditLogsScope = 'admin' | 'owner'

interface AuditLogsPageProps {
    scope: AuditLogsScope
}

const AUDIT_ACTION_CATEGORIES: AuditActionCategory[] = [
    'auth',
    'governance',
    'participant',
    'metering',
    'tariff',
    'invoice',
    'import',
    'template',
    'system',
]

const AUDIT_STATUSES: AuditEventStatus[] = ['started', 'queued', 'success', 'failed', 'denied']

interface AuditFilterState {
    page: number
    actionCategory: string
    actionType: string
    targetType: string
    status: string
    dateFrom: string
    dateTo: string
    search: string
}

const DEFAULT_FILTERS: AuditFilterState = {
    page: 1,
    actionCategory: '',
    actionType: '',
    targetType: '',
    status: '',
    dateFrom: '',
    dateTo: '',
    search: '',
}

function statusBadgeClass(status: AuditEventStatus): string {
    if (status === 'success') return 'badge badge-success'
    if (status === 'failed' || status === 'denied') return 'badge badge-danger'
    if (status === 'queued') return 'badge badge-info'
    return 'badge badge-neutral'
}

export function AuditLogsPage({ scope }: AuditLogsPageProps) {
    const { t } = useTranslation()
    const { settings } = useAppSettings()
    const { user } = useAuth()
    const [filters, setFilters] = useState<AuditFilterState>(DEFAULT_FILTERS)
    const [selectedEventId, setSelectedEventId] = useState<string | null>(null)

    const isAdminView = scope === 'admin'
    const canUseSearch = isAdminView && user?.role === 'admin'

    const apiFilters = useMemo<AuditEventFilters>(
        () => ({
            page: filters.page,
            action_category: (filters.actionCategory || undefined) as AuditActionCategory | undefined,
            action_type: filters.actionType || undefined,
            target_type: filters.targetType || undefined,
            status: (filters.status || undefined) as AuditEventStatus | undefined,
            date_from: filters.dateFrom || undefined,
            date_to: filters.dateTo || undefined,
            q: canUseSearch ? filters.search || undefined : undefined,
        }),
        [canUseSearch, filters.actionCategory, filters.actionType, filters.dateFrom, filters.dateTo, filters.page, filters.search, filters.status, filters.targetType],
    )

    const eventsQuery = useQuery({
        queryKey: queryKeys.admin.auditEvents(apiFilters),
        queryFn: () => fetchAuditEvents(apiFilters),
    })

    const events = eventsQuery.data?.results ?? []

    function updateFilter<K extends keyof AuditFilterState>(key: K, value: AuditFilterState[K]) {
        setFilters((previous) => ({
            ...previous,
            [key]: value,
            ...(key === 'page' ? null : { page: 1 }),
        }))
    }

    function selectEvent(event: AuditEvent) {
        setSelectedEventId(event.id)
    }

    function clearFilters() {
        setFilters(DEFAULT_FILTERS)
    }

    return (
        <div className="page-stack">
            <header>
                <p className="eyebrow">{t(isAdminView ? 'pages.auditLogs.eyebrowAdmin' : 'pages.auditLogs.eyebrowOwner')}</p>
                <h2>{t('pages.auditLogs.title')}</h2>
                <p className="muted">{t('pages.auditLogs.description')}</p>
            </header>

            <section className="card page-stack">
                <div className="form-grid">
                    <label>
                        {t('pages.auditLogs.filters.actionCategory')}
                        <select value={filters.actionCategory} onChange={(event) => updateFilter('actionCategory', event.target.value)}>
                            <option value="">{t('pages.auditLogs.filters.all')}</option>
                            {AUDIT_ACTION_CATEGORIES.map((category) => (
                                <option key={category} value={category}>
                                    {t(`pages.auditLogs.categories.${category}`)}
                                </option>
                            ))}
                        </select>
                    </label>
                    <label>
                        {t('pages.auditLogs.filters.status')}
                        <select value={filters.status} onChange={(event) => updateFilter('status', event.target.value)}>
                            <option value="">{t('pages.auditLogs.filters.all')}</option>
                            {AUDIT_STATUSES.map((status) => (
                                <option key={status} value={status}>
                                    {t(`pages.auditLogs.statuses.${status}`)}
                                </option>
                            ))}
                        </select>
                    </label>
                    <label>
                        {t('pages.auditLogs.filters.actionType')}
                        <input value={filters.actionType} onChange={(event) => updateFilter('actionType', event.target.value)} placeholder={t('pages.auditLogs.filters.actionTypePlaceholder')} />
                    </label>
                    <label>
                        {t('pages.auditLogs.filters.targetType')}
                        <input value={filters.targetType} onChange={(event) => updateFilter('targetType', event.target.value)} placeholder={t('pages.auditLogs.filters.targetTypePlaceholder')} />
                    </label>
                    <label>
                        {t('pages.auditLogs.filters.dateFrom')}
                        <input type="date" value={filters.dateFrom} onChange={(event) => updateFilter('dateFrom', event.target.value)} />
                    </label>
                    <label>
                        {t('pages.auditLogs.filters.dateTo')}
                        <input type="date" value={filters.dateTo} onChange={(event) => updateFilter('dateTo', event.target.value)} />
                    </label>
                </div>

                <label>
                    {t('pages.auditLogs.filters.search')}
                    <input
                        value={filters.search}
                        onChange={(event) => updateFilter('search', event.target.value)}
                        placeholder={t('pages.auditLogs.filters.searchPlaceholder')}
                        disabled={!canUseSearch}
                    />
                </label>
                {!canUseSearch && <p className="muted">{t('pages.auditLogs.filters.searchRestricted')}</p>}

                <div className="actions-row actions-row-wrap actions-row-end">
                    <button type="button" className="button button-secondary" onClick={clearFilters}>
                        {t('pages.auditLogs.actions.clearFilters')}
                    </button>
                    <button type="button" className="button button-secondary" onClick={() => void eventsQuery.refetch()}>
                        {t('pages.auditLogs.actions.refresh')}
                    </button>
                </div>
            </section>

            <section className="table-card">
                {eventsQuery.isLoading && <p>{t('pages.auditLogs.loading')}</p>}
                {eventsQuery.isError && <p className="text-error">{t('pages.auditLogs.loadError')}</p>}
                {!eventsQuery.isLoading && events.length === 0 && <p className="muted">{t('pages.auditLogs.empty')}</p>}

                {events.length > 0 && (
                    <>
                        <table>
                            <thead>
                                <tr>
                                    <th>{t('pages.auditLogs.columns.createdAt')}</th>
                                    <th>{t('pages.auditLogs.columns.summary')}</th>
                                    <th>{t('pages.auditLogs.columns.category')}</th>
                                    <th>{t('pages.auditLogs.columns.action')}</th>
                                    <th>{t('pages.auditLogs.columns.target')}</th>
                                    <th>{t('pages.auditLogs.columns.actor')}</th>
                                    <th>{t('pages.auditLogs.columns.status')}</th>
                                </tr>
                            </thead>
                            <tbody>
                                {events.map((event) => (
                                    <tr key={event.id} style={{ cursor: 'pointer', background: selectedEventId === event.id ? 'var(--surface-subtle)' : undefined }} onClick={() => selectEvent(event)}>
                                        <td>{formatDateTime(event.created_at, settings)}</td>
                                        <td>{event.summary}</td>
                                        <td>{t(`pages.auditLogs.categories.${event.action_category}`)}</td>
                                        <td><code>{event.action_type}</code></td>
                                        <td>{event.target_display || `${event.target_type}:${event.target_id || '-'}`}</td>
                                        <td>{event.actor_display || '—'}</td>
                                        <td><span className={statusBadgeClass(event.status)}>{t(`pages.auditLogs.statuses.${event.status}`)}</span></td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>

                        <div className="actions-row actions-row-wrap actions-row-end" style={{ marginTop: '1rem' }}>
                            <span className="muted">{t('pages.auditLogs.pagination.pageLabel', { page: filters.page, total: eventsQuery.data?.count ?? 0 })}</span>
                            <button
                                type="button"
                                className="button button-secondary"
                                onClick={() => updateFilter('page', Math.max(1, filters.page - 1))}
                                disabled={!eventsQuery.data?.previous}
                            >
                                {t('pages.auditLogs.pagination.previous')}
                            </button>
                            <button
                                type="button"
                                className="button button-secondary"
                                onClick={() => updateFilter('page', filters.page + 1)}
                                disabled={!eventsQuery.data?.next}
                            >
                                {t('pages.auditLogs.pagination.next')}
                            </button>
                        </div>
                    </>
                )}
            </section>

            <AuditEventDrawer
                eventId={selectedEventId}
                onClose={() => setSelectedEventId(null)}
                statusBadgeClass={statusBadgeClass}
            />
        </div>
    )
}

export function AdminAuditLogsPage() {
    return <AuditLogsPage scope="admin" />
}

export function OwnerAuditLogsPage() {
    return <AuditLogsPage scope="owner" />
}
