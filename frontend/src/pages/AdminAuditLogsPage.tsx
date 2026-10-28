import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { isAxiosError } from 'axios'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { fetchAuditEvents, fetchAuditFilterOptions } from '../lib/api/audit'
import { formatApiError } from '../lib/api/errors'
import { queryKeys } from '../lib/api/queryKeys'
import { formatDateTime, useAppSettings } from '../lib/appSettings'
import { useAuth } from '../lib/auth'
import { useManagedZev } from '../lib/managedZev'
import { useCommunityAccess, useScopeNote } from '../lib/communityAccess'
import { CivilDateInput } from '../components/CivilDateInput'
import { AuditEventPane } from '../features/audit/AuditEventPane'
import type { AuditActionCategory, AuditEventFilters, AuditEventStatus } from '../types/api'
import { PageHeader } from '../components/PageHeader'
import { usePageNavigation } from '../lib/usePageNavigation'
import { useMinWidth } from '../lib/useMinWidth'
import { Notice } from '../components/Notice'
import { PageSkeleton } from '../components/PageSkeleton'

type AuditLogsScope = 'admin' | 'owner'

/** Content width from which the log and the event pane sit side by side;
 * below it the pane takes the whole area (SPEC-2026-10-ui-patterns §5 rule E). */
const SPLIT_MIN_REM = 72

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
    const { isZevScope } = useCommunityAccess()
    const { searchParams, updateParams } = usePageNavigation()
    const isAdminView = scope === 'admin'
    const { selectedZevId, selectedZev, isLoading: managedZevLoading } = useManagedZev()
    const canReadAudit = isAdminView
        ? user?.role === 'admin'
        : isZevScope && !!selectedZevId && selectedZev?.id === selectedZevId && !managedZevLoading
    const [localFilters, setFilters] = useState<AuditFilterState>(DEFAULT_FILTERS)
    const [searchDraft, setSearchDraft] = useState('')
    const searchTooLong = Array.from(searchDraft.trim()).length > 50
    const scopeContext = isAdminView ? 'admin' : selectedZevId
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
    const context = {
        scope: scopeContext,
        filters: JSON.stringify([
            contextualFilters.actionCategory,
            contextualFilters.actionType,
            contextualFilters.targetType,
            contextualFilters.targetId,
        ]),
    }
    const [previousContext, setPreviousContext] = useState(context)
    const [selectedEventId, setSelectedEventId] = useState<string | null>(null)
    const scopeChanged = previousContext.scope !== context.scope
    const contextChanged = scopeChanged || previousContext.filters !== context.filters
    // Reset before requesting a changed URL filter or community scope.
    if (contextChanged) {
        setPreviousContext(context)
        setFilters(previous => ({ ...previous, page: 1, ...(scopeChanged ? { search: '' } : {}) }))
        setSelectedEventId(null)
        setTextFilters(urlTextFilters)
        if (scopeChanged) setSearchDraft('')
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
        q: canReadAudit ? filters.search || undefined : undefined,
    }

    const canFetchAudit = canReadAudit && !contextChanged
    const eventsQuery = useQuery({
        queryKey: queryKeys.admin.auditEvents(apiFilters),
        queryFn: () => fetchAuditEvents(apiFilters),
        enabled: canFetchAudit,
        retry: (failureCount, error) => {
            const status = isAxiosError(error) ? error.response?.status : undefined
            return (status === undefined || status >= 500) && failureCount < 3
        },
        refetchOnWindowFocus: false,
    })

    function refreshEvents() {
        if (canFetchAudit) void eventsQuery.refetch()
    }

    // The ZEV/actor filter options come from the audit API itself, so they are
    // derived from the same visibility-scoped queryset as the events: owners
    // only see their own community (including owners/admins who actually acted
    // there), admins see everything, and no unrelated user accounts leak.
    const optionsQuery = useQuery({
        queryKey: queryKeys.admin.auditFilterOptions(),
        queryFn: fetchAuditFilterOptions,
        enabled: canReadAudit,
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

    // The log and the event pane sit side by side when both fit; otherwise the
    // pane replaces the log until it is closed (rule E).
    const [splitRef, fitsTwoPanes] = useMinWidth<HTMLDivElement>(SPLIT_MIN_REM)
    const paneOpen = selectedEventId !== null
    const listHidden = paneOpen && !fitsTwoPanes
    const paneTitleRef = useRef<HTMLHeadingElement>(null)
    // Focus follows the pane: to its title when it opens, back to the row that
    // opened it when it closes. Picking another row while it is open keeps
    // focus where it is, so a log can be stepped through from the keyboard.
    const focusRequest = useRef<{ kind: 'pane' } | { kind: 'row', id: string } | null>(null)
    const listScroll = useRef<number | null>(null)

    function selectEvent(id: string) {
        if (selectedEventId === null) {
            focusRequest.current = { kind: 'pane' }
            listScroll.current = window.scrollY
        }
        setSelectedEventId(id)
    }

    function closePane() {
        if (selectedEventId !== null) focusRequest.current = { kind: 'row', id: selectedEventId }
        setSelectedEventId(null)
    }

    useEffect(() => {
        const request = focusRequest.current
        if (!request) return
        if (request.kind === 'pane' && paneOpen) {
            // Beside the log the pane is already in view; only a pane that replaces it needs scrolling to.
            paneTitleRef.current?.focus({ preventScroll: fitsTwoPanes })
        } else if (request.kind === 'row' && !paneOpen) {
            document.querySelector<HTMLElement>(`[data-event-id="${CSS.escape(request.id)}"]`)?.focus()
        } else {
            return
        }
        focusRequest.current = null
    }, [paneOpen, fitsTwoPanes])

    // The log comes back where the user left it.
    useLayoutEffect(() => {
        if (!listHidden && listScroll.current !== null) {
            window.scrollTo(0, listScroll.current)
            listScroll.current = null
        }
    }, [listHidden])

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
        setSearchDraft('')
        setSelectedEventId(null)
        setLinkedActorUsername(null)
        setTextFilters({ actionType: '', targetType: '', targetId: '' })
        updateParams(params => Object.values(LINK_FILTER_PARAMS).forEach(param => params.delete(param)))
    }

    function commitSearch() {
        if (!canReadAudit || searchTooLong) return
        const search = searchDraft.trim()
        if (search !== filters.search) updateFilter('search', search)
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
                        value={searchDraft}
                        onChange={(event) => setSearchDraft(event.target.value)}
                        onBlur={commitSearch}
                        onKeyDown={event => { if (event.key === 'Enter') commitSearch() }}
                        aria-invalid={searchTooLong}
                        aria-describedby={canReadAudit ? 'audit-search-hint' : undefined}
                        placeholder={t('pages.auditLogs.filters.searchPlaceholder')}
                        disabled={!canReadAudit}
                    />
                </label>
                {canReadAudit && <p id="audit-search-hint" className={searchTooLong ? 'text-error' : 'muted'}>
                    {t(searchTooLong ? 'pages.auditLogs.filters.searchTooLong' : 'pages.auditLogs.filters.searchHint')}
                </p>}

                <div className="actions-row actions-row-wrap actions-row-end">
                    {/* Keep a pointer click on Clear from applying the focused draft on blur. */}
                    <button
                        type="button"
                        className="button button-secondary"
                        onPointerDown={event => event.preventDefault()}
                        onClick={clearFilters}
                    >
                        {t('pages.auditLogs.actions.clearFilters')}
                    </button>
                    <button type="button" className="button button-secondary" disabled={!canFetchAudit} onClick={refreshEvents}>
                        {t('pages.auditLogs.actions.refresh')}
                    </button>
                </div>
            </section>

            <div
                ref={splitRef}
                className="detail-split"
                data-layout={fitsTwoPanes ? 'wide' : 'narrow'}
                data-pane={paneOpen ? 'open' : 'closed'}
            >
                <div className="detail-split-list" hidden={listHidden}>
                    <section className="table-card">
                        {eventsQuery.isLoading && <PageSkeleton variant="tableRows" />}
                        {eventsQuery.isError && (
                            <Notice tone="error" onRetry={refreshEvents} isRetrying={eventsQuery.isFetching}>
                                {formatApiError(eventsQuery.error, t('pages.auditLogs.loadError'))}
                            </Notice>
                        )}
                        {!eventsQuery.isLoading && !eventsQuery.isError && events.length === 0 && <p className="muted">{t('pages.auditLogs.empty')}</p>}

                        {events.length > 0 && (
                            <>
                                <div className="table-scroll">
                                    <table>
                                        <thead>
                                            <tr>
                                                <th>{t('pages.auditLogs.columns.createdAt')}</th>
                                                <th>{t('pages.auditLogs.columns.summary')}</th>
                                                <th className="audit-col-secondary">{t('pages.auditLogs.columns.zev')}</th>
                                                <th className="audit-col-secondary">{t('pages.auditLogs.columns.category')}</th>
                                                <th className="audit-col-secondary">{t('pages.auditLogs.columns.action')}</th>
                                                <th>{t('pages.auditLogs.columns.target')}</th>
                                                <th>{t('pages.auditLogs.columns.actor')}</th>
                                                <th>{t('pages.auditLogs.columns.status')}</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {events.map((event) => (
                                                <tr
                                                    key={event.id}
                                                    className={selectedEventId === event.id ? 'audit-event-row is-selected' : 'audit-event-row'}
                                                    onClick={() => selectEvent(event.id)}
                                                >
                                                    <td>{formatDateTime(event.created_at, settings)}</td>
                                                    <td>
                                                        <button
                                                            type="button"
                                                            className="audit-event-select"
                                                            data-event-id={event.id}
                                                            aria-current={selectedEventId === event.id || undefined}
                                                            onClick={click => { click.stopPropagation(); selectEvent(event.id) }}
                                                        >
                                                            {event.summary}
                                                        </button>
                                                    </td>
                                                    <td className="audit-col-secondary">{event.zev ? zevNameById.get(event.zev) ?? event.zev : '—'}</td>
                                                    <td className="audit-col-secondary">{t(`pages.auditLogs.categories.${event.action_category}`)}</td>
                                                    <td className="audit-col-secondary"><code>{event.action_type}</code></td>
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
                                    <div className="actions-row actions-row-wrap actions-row-end mt-1">
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
                </div>

                {selectedEventId && (
                    <AuditEventPane
                        eventId={selectedEventId}
                        onClose={closePane}
                        statusBadgeClass={statusBadgeClass}
                        titleRef={paneTitleRef}
                    />
                )}
            </div>
        </div>
    )
}
