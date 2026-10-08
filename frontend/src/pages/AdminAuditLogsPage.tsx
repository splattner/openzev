import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { fetchAuditEvents, fetchAuditFilterOptions } from '../lib/api/audit'
import { queryKeys } from '../lib/api/queryKeys'
import { formatDateTime, useAppSettings } from '../lib/appSettings'
import { useAuth } from '../lib/auth'
import { useManagedZev } from '../lib/managedZev'
import { useScopeNote } from '../lib/communityAccess'
import { CivilDateInput } from '../components/CivilDateInput'
import { AuditEventDrawer } from '../features/audit/AuditEventDrawer'
import type { AuditActionCategory, AuditEventFilters, AuditEventStatus } from '../types/api'
import { PageHeader } from '../components/PageHeader'
import { usePageNavigation } from '../lib/usePageNavigation'
import { Notice } from '../components/Notice'
import { PageSkeleton } from '../components/PageSkeleton'

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
    status: string
    zev: string
    actorUser: string
    dateFrom: string
    dateTo: string
    search: string
}

const DEFAULT_FILTERS: AuditFilterState = {
    page: 1,
    status: '',
    zev: '',
    actorUser: '',
    dateFrom: '',
    dateTo: '',
    search: '',
}

const LINK_FILTER_PARAMS = {
    actionCategory: 'action_category',
    actionType: 'action_type',
    targetType: 'target_type',
    targetId: 'target_id',
}

function statusBadgeClass(status: AuditEventStatus): string {
    if (status === 'success') return 'badge badge-success'
    if (status === 'failed' || status === 'denied') return 'badge badge-danger'
    if (status === 'queued') return 'badge badge-info'
    return 'badge badge-neutral'
}

/** `embedded` drops the page header inside the Overview and Settings hubs. */
export function AuditLogsPage({ scope, embedded = false }: AuditLogsPageProps & { embedded?: boolean }) {
    const { t } = useTranslation()
    const scopeNote = useScopeNote()
    const { settings } = useAppSettings()
    const { user } = useAuth()
    const { searchParams, updateParams } = usePageNavigation()
    const isAdminView = scope === 'admin'
    const canUseSearch = isAdminView && user?.role === 'admin'
    const { selectedZevId, selectedZev, isLoading: managedZevLoading } = useManagedZev()
    const [localFilters, setFilters] = useState<AuditFilterState>(DEFAULT_FILTERS)
    const category = searchParams.get('action_category')
    const urlTextFilters = {
        actionType: searchParams.get('action_type') ?? '',
        targetType: searchParams.get('target_type') ?? '',
        targetId: searchParams.get('target_id') ?? '',
    }
    const contextualFilters = {
        actionCategory: category && AUDIT_ACTION_CATEGORIES.includes(category as AuditActionCategory) ? category : '',
        ...urlTextFilters,
    }
    const [textFilters, setTextFilters] = useState(urlTextFilters)
    const context = JSON.stringify([
        isAdminView ? 'admin' : selectedZevId,
        contextualFilters.actionCategory,
        contextualFilters.actionType,
        contextualFilters.targetType,
        contextualFilters.targetId,
    ])
    const [previousContext, setPreviousContext] = useState(context)
    const [selectedEventId, setSelectedEventId] = useState<string | null>(null)
    const contextChanged = previousContext !== context
    // Reset before requesting a changed URL filter or community scope.
    if (contextChanged) {
        setPreviousContext(context)
        setFilters(previous => ({ ...previous, page: 1 }))
        setSelectedEventId(null)
        setTextFilters(urlTextFilters)
    }
    const filters = { ...localFilters, ...contextualFilters, page: contextChanged ? 1 : localFilters.page }

    const [linkedActorUsername, setLinkedActorUsername] = useState<string | null>(null)

    // Preserve the existing one-time account-activity intent; keep other URL context.
    useEffect(() => {
        if (!isAdminView) return
        const actor = searchParams.get('actor')
        if (!actor) return
        setFilters(previous => ({ ...previous, actorUser: actor, page: 1 }))
        setSelectedEventId(null)
        setLinkedActorUsername(searchParams.get('actorUsername'))
        updateParams(params => {
            params.delete('actor')
            params.delete('actorUsername')
        })
    }, [isAdminView, searchParams, updateParams])

    const apiFilters: AuditEventFilters = {
        page: filters.page,
        action_category: (filters.actionCategory || undefined) as AuditActionCategory | undefined,
        action_type: filters.actionType || undefined,
        target_type: filters.targetType || undefined,
        target_id: filters.targetId || undefined,
        status: (filters.status || undefined) as AuditEventStatus | undefined,
        zev: isAdminView ? filters.zev || undefined : selectedZevId || undefined,
        actor_user: filters.actorUser ? Number(filters.actorUser) : undefined,
        date_from: filters.dateFrom || undefined,
        date_to: filters.dateTo || undefined,
        q: canUseSearch ? filters.search || undefined : undefined,
    }

    const eventsQuery = useQuery({
        queryKey: queryKeys.admin.auditEvents(apiFilters),
        queryFn: () => fetchAuditEvents(apiFilters),
        enabled: isAdminView || (!managedZevLoading && !!selectedZevId),
    })

    // The ZEV/actor filter options come from the audit API itself, so they are
    // derived from the same visibility-scoped queryset as the events: owners
    // only see their own community (including owners/admins who actually acted
    // there), admins see everything, and no unrelated user accounts leak.
    const optionsQuery = useQuery({
        queryKey: queryKeys.admin.auditFilterOptions(),
        queryFn: fetchAuditFilterOptions,
    })

    const zevNameById = useMemo(() => {
        const names = new Map<string, string>()
        for (const zev of optionsQuery.data?.zevs ?? []) {
            names.set(zev.id, zev.name)
        }
        return names
    }, [optionsQuery.data])

    // The actor dropdown only lists accounts the audit queryset has already
    // seen acting — an account deep-linked here with no audit history yet
    // (a brand-new account) would otherwise show as an unlabelled selection.
    const actorOptions = useMemo(() => {
        const options = optionsQuery.data?.actors ?? []
        if (filters.actorUser && linkedActorUsername && !options.some((actor) => String(actor.id) === filters.actorUser)) {
            return [...options, { id: Number(filters.actorUser), username: linkedActorUsername }]
        }
        return options
    }, [optionsQuery.data, filters.actorUser, linkedActorUsername])

    const events = eventsQuery.data?.results ?? []

    function updateFilter<K extends keyof typeof filters>(key: K, value: (typeof filters)[K]) {
        if (key in LINK_FILTER_PARAMS) {
            const param = LINK_FILTER_PARAMS[key as keyof typeof LINK_FILTER_PARAMS]
            updateParams(params => {
                if (value) params.set(param, String(value))
                else params.delete(param)
            })
        } else {
            setFilters(previous => ({
                ...previous,
                [key]: value,
                ...(key === 'page' ? null : { page: 1 }),
            }))
        }
    }

    function clearFilters() {
        setFilters(DEFAULT_FILTERS)
        setSelectedEventId(null)
        setLinkedActorUsername(null)
        setTextFilters({ actionType: '', targetType: '', targetId: '' })
        updateParams(params => Object.values(LINK_FILTER_PARAMS).forEach(param => params.delete(param)))
    }

    function commitTextFilters() {
        if (Object.entries(textFilters).every(([key, value]) => value === urlTextFilters[key as keyof typeof textFilters])) return
        updateParams(params => {
            for (const [key, value] of Object.entries(textFilters)) {
                const param = LINK_FILTER_PARAMS[key as keyof typeof textFilters]
                if (value) params.set(param, value)
                else params.delete(param)
            }
        })
    }

    const scopeDescription = isAdminView
        ? t('pages.auditLogs.platformDescription')
        : selectedZev ? t('pages.auditLogs.communityDescription', { name: selectedZev.name }) : undefined

    return (
        <div className="page-stack">
            {!embedded && (
                <PageHeader
                    eyebrow={isAdminView ? t('nav.platformScope') : selectedZev?.name}
                    communitySwitch={!isAdminView}
                    scopeNote={isAdminView ? undefined : scopeNote}
                    title={t('pages.auditLogs.title')}
                    description={scopeDescription}
                />
            )}

            {embedded && !isAdminView && scopeDescription && <p className="muted">{scopeDescription}</p>}

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
                    {isAdminView && (
                        <label>
                            {t('pages.auditLogs.filters.zev')}
                            <select value={filters.zev} onChange={(event) => updateFilter('zev', event.target.value)}>
                                <option value="">{t('pages.auditLogs.filters.all')}</option>
                                {(optionsQuery.data?.zevs ?? []).map((zev) => (
                                    <option key={zev.id} value={zev.id}>
                                        {zev.name}
                                    </option>
                                ))}
                            </select>
                        </label>
                    )}
                    <label>
                        {t('pages.auditLogs.filters.actor')}
                        <select value={filters.actorUser} onChange={(event) => updateFilter('actorUser', event.target.value)}>
                            <option value="">{t('pages.auditLogs.filters.all')}</option>
                            {actorOptions.map((actor) => (
                                <option key={actor.id} value={String(actor.id)}>
                                    {actor.username}
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
                        <input
                            value={textFilters.actionType}
                            onChange={(event) => setTextFilters(previous => ({ ...previous, actionType: event.target.value }))}
                            onBlur={commitTextFilters}
                            onKeyDown={event => { if (event.key === 'Enter') commitTextFilters() }}
                            placeholder={t('pages.auditLogs.filters.actionTypePlaceholder')}
                        />
                    </label>
                    <label>
                        {t('pages.auditLogs.filters.targetType')}
                        <input
                            value={textFilters.targetType}
                            onChange={(event) => setTextFilters(previous => ({ ...previous, targetType: event.target.value }))}
                            onBlur={commitTextFilters}
                            onKeyDown={event => { if (event.key === 'Enter') commitTextFilters() }}
                            placeholder={t('pages.auditLogs.filters.targetTypePlaceholder')}
                        />
                    </label>
                    <label>
                        {t('pages.auditLogs.filters.targetId')}
                        <input
                            value={textFilters.targetId}
                            onChange={(event) => setTextFilters(previous => ({ ...previous, targetId: event.target.value }))}
                            onBlur={commitTextFilters}
                            onKeyDown={event => { if (event.key === 'Enter') commitTextFilters() }}
                        />
                    </label>
                    <label>
                        {t('pages.auditLogs.filters.dateFrom')}
                        <CivilDateInput value={filters.dateFrom || null} onChange={(iso) => updateFilter('dateFrom', iso ?? '')} />
                    </label>
                    <label>
                        {t('pages.auditLogs.filters.dateTo')}
                        <CivilDateInput value={filters.dateTo || null} onChange={(iso) => updateFilter('dateTo', iso ?? '')} />
                    </label>
                </div>
                <p className="muted">{t('pages.auditLogs.filters.textApplyHint')}</p>

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
                {eventsQuery.isLoading && <PageSkeleton variant="tableRows" />}
                {eventsQuery.isError && <Notice tone="error" onRetry={() => void eventsQuery.refetch()} isRetrying={eventsQuery.isFetching}>{t('pages.auditLogs.loadError')}</Notice>}
                {!eventsQuery.isLoading && !eventsQuery.isError && events.length === 0 && <p className="muted">{t('pages.auditLogs.empty')}</p>}

                {events.length > 0 && (
                    <>
                        <div className="table-scroll">
                            <table>
                                <thead>
                                    <tr>
                                        <th>{t('pages.auditLogs.columns.createdAt')}</th>
                                        <th>{t('pages.auditLogs.columns.summary')}</th>
                                        <th>{t('pages.auditLogs.columns.zev')}</th>
                                        <th>{t('pages.auditLogs.columns.category')}</th>
                                        <th>{t('pages.auditLogs.columns.action')}</th>
                                        <th>{t('pages.auditLogs.columns.target')}</th>
                                        <th>{t('pages.auditLogs.columns.actor')}</th>
                                        <th>{t('pages.auditLogs.columns.status')}</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {events.map((event) => (
                                        <tr key={event.id} style={{ cursor: 'pointer', background: selectedEventId === event.id ? 'var(--surface-subtle)' : undefined }} onClick={() => setSelectedEventId(event.id)}>
                                            <td>{formatDateTime(event.created_at, settings)}</td>
                                            <td>
                                                <button
                                                    type="button"
                                                    className="audit-event-select"
                                                    onClick={click => { click.stopPropagation(); setSelectedEventId(event.id) }}
                                                >
                                                    {event.summary}
                                                </button>
                                            </td>
                                            <td>{event.zev ? zevNameById.get(event.zev) ?? event.zev : '—'}</td>
                                            <td>{t(`pages.auditLogs.categories.${event.action_category}`)}</td>
                                            <td><code>{event.action_type}</code></td>
                                            <td>{event.target_display || `${event.target_type}:${event.target_id || '-'}`}</td>
                                            <td>{event.actor_display || '—'}</td>
                                            <td><span className={statusBadgeClass(event.status)}>{t(`pages.auditLogs.statuses.${event.status}`)}</span></td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>

                        {/* Only rendered when the result spans more than one page:
                            DRF returns next = previous = null exactly when count <= page size. */}
                        {(eventsQuery.data?.next || eventsQuery.data?.previous) && (
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
                        )}
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
