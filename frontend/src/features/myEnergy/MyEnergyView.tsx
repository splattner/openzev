import { type ReactNode, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { AppTabs } from '../../components/AppTabs'
import { Notice } from '../../components/Notice'
import { PageSkeleton } from '../../components/PageSkeleton'
import { PeriodSelector } from '../../components/PeriodSelector'
import { GrossEnergyCallToAction, GrossEnergyCard } from '../../components/dashboard/GrossEnergyCard'
import { listSupplementarySources } from '../../lib/api/supplementary'
import { fetchParticipants } from '../../lib/api/zev'
import { queryKeys } from '../../lib/api/queryKeys'
import { useAuth } from '../../lib/auth'
import { useCommunityAccess } from '../../lib/communityAccess'
import { todayBusinessIso } from '../../lib/dates'
import { forecastForDay, hasExpectedProduction, hasForecast, tomorrowBusinessIso, useProductionForecast } from '../../lib/forecast'
import { liveCardState, useLiveCurve, useLiveEnergy, useLiveEnabled } from '../../lib/live'
import { useManagedZev } from '../../lib/managedZev'
import {
    lastDaysRange,
    MY_ENERGY_DEFAULT_RANGE,
    type MyEnergyRange,
    ownHistoryFromSeries,
    parseMyEnergyRange,
    todayRows,
    useOwnSeries,
} from '../../lib/myEnergy'
import { useEnergyDataEligibility } from '../../lib/supplementary'
import type { ProductionForecast } from '../../types/api'
import { usePageNavigation } from '../../lib/usePageNavigation'
import { type DashboardBodyProps, useBucketLabelFormatters } from '../dashboard/dashboardShared'
import { LiveEnergyView } from '../live/LiveEnergyView'
import { ProductionForecastChart } from '../live/ProductionForecastChart'
import { TodayChart } from './TodayChart'

/** Who the own-system views are about, and whether that is the signed-in user. */
interface Subject {
    /** Sent to the server; `undefined` means "my own" (participants). */
    participantId: string | undefined
    /** Figures can be requested: a participant always, a manager once somebody is selected. */
    ready: boolean
    isOwn: boolean
    name: string | undefined
}

/**
 * My energy system (SPEC-2026-live-energy-data §7): what comes from devices, live and the own history of
 * a participant, never billing input (ADR 0030). "Right now" on top, then Today (with the production forecast),
 * Tomorrow (the forecast alone, when there is one), 7 days and Period.
 */
export function MyEnergyView({ interval, period, onPeriodChange, periodReady }: DashboardBodyProps) {
    const { t } = useTranslation()
    const { user } = useAuth()
    const { selectedZevId } = useManagedZev()
    const { isZevScope } = useCommunityAccess()
    const energyData = useEnergyDataEligibility()
    const { searchParams, updateParams } = usePageNavigation()
    // The live requests start with the page, in parallel with the eligibility check, not after it and the
    // flag: while the feature is off the server answers 404, which the hooks turn into `null`.
    const liveEnabledQuery = useLiveEnabled()
    const forecastQuery = useProductionForecast(selectedZevId || undefined)
    const forecast = hasForecast(forecastQuery.data) ? forecastQuery.data : null
    const snapshotQuery = useLiveEnergy(selectedZevId || undefined)
    const liveShown = !!liveCardState(snapshotQuery.data)
    // Tomorrow is only offered while the forecast has something to say about it.
    const tomorrow = tomorrowBusinessIso()
    const hasTomorrow = hasExpectedProduction(forecast, tomorrow)

    const participantsQuery = useQuery({
        queryKey: queryKeys.zev.participants(selectedZevId || undefined),
        queryFn: fetchParticipants,
        enabled: isZevScope && !!selectedZevId,
    })
    const today = todayBusinessIso()
    const participants = useMemo(
        () => (participantsQuery.data ?? []).filter(
            (participant) => participant.zev === selectedZevId && (!participant.valid_to || participant.valid_to >= today),
        ),
        [participantsQuery.data, selectedZevId, today],
    )
    const ownParticipantIds = useMemo(
        () =>
            (user?.memberships ?? [])
                .find((membership) => membership.zev === selectedZevId)
                ?.participants.filter((participant) => participant.live)
                .map((participant) => participant.id) ?? [],
        [user?.memberships, selectedZevId],
    )
    // A manager who is a participant with an own system (history or live) starts on themselves; anybody else picks.
    const defaultParticipantId = energyData.historyEligible.find(
        (point) => point.zev === selectedZevId && point.source !== null,
    )?.participant ?? ownParticipantIds[0] ?? ''
    const requested = searchParams.get('participant') ?? ''
    const selectedParticipantId = isZevScope
        ? (participants.some((participant) => participant.id === requested) ? requested : defaultParticipantId)
        : ''
    // Two participants may share a name (a household's members); the e-mail then tells them apart.
    const participantLabel = (participant: (typeof participants)[number]) => {
        const name = participant.display_name || participant.id
        const twins = participants.filter((other) => (other.display_name || other.id) === name).length > 1
        return twins && participant.email ? `${name} · ${participant.email}` : name
    }
    const selectedName = participants.find((participant) => participant.id === selectedParticipantId)?.display_name
    const subject: Subject = isZevScope
        ? {
            participantId: selectedParticipantId || undefined,
            ready: !!selectedParticipantId && participantsQuery.isSuccess,
            isOwn: ownParticipantIds.includes(selectedParticipantId),
            name: selectedName,
        }
        : { participantId: undefined, ready: true, isOwn: true, name: undefined }
    const canConnect = energyData.historyEligible.some((point) => point.zev === selectedZevId && point.source === null)
    // The user's own system already has a source (so "nothing yet" means it has not synced, not that nothing is connected).
    const hasOwnSource = energyData.historyEligible.some((point) => point.zev === selectedZevId && point.source !== null)
    // A manager looks at other people's histories, which exist only where some source provides one; asked for
    // only while the page is a manager's, and shared with the Energy data tab through the same query key.
    const sourcesQuery = useQuery({
        queryKey: queryKeys.metering.supplementarySources(),
        queryFn: listSupplementarySources,
        enabled: isZevScope && energyData.featureOn,
    })
    // A history can only appear for a participant whose meter has a plant behind it, or wherever a source provides one.
    const historyPossible = isZevScope
        ? sourcesQuery.isPending || (sourcesQuery.data ?? []).some((source) => source.zev === selectedZevId && source.provides_history)
        : energyData.historyEligible.some((point) => point.zev === selectedZevId)
    // Without a plant, a live source or a forecast there is nothing to put under the live card's own setup prompt.
    const liveSettled = liveEnabledQuery.data === false || !snapshotQuery.isPending
    const hasViews = historyPossible || liveShown || !!forecast || !liveSettled
    const requestedRange = parseMyEnergyRange(searchParams.get('range'))
    const offered = requestedRange === 'today' || (requestedRange === 'tomorrow' ? hasTomorrow : historyPossible)
    const range: MyEnergyRange = offered ? requestedRange : MY_ENERGY_DEFAULT_RANGE
    // A single view needs no tab strip.
    const showTabs = historyPossible || hasTomorrow

    const setRange = (next: MyEnergyRange) => updateParams((params) => {
        if (next === MY_ENERGY_DEFAULT_RANGE) params.delete('range')
        else params.set('range', next)
    }, { replace: false })
    const setParticipant = (id: string) => updateParams((params) => {
        if (id) params.set('participant', id)
        else params.delete('participant')
    })

    if (energyData.isLoading) return <PageSkeleton variant="kpiRow" />
    if (energyData.isError) {
        return (
            <Notice tone="error" onRetry={() => void energyData.refetch()} isRetrying={energyData.isFetching}>
                {t('myEnergy.loadFailed')}
            </Notice>
        )
    }
    if (!energyData.featureOn) return <Notice tone="warning">{t('myEnergy.disabled')}</Notice>

    return (
        <>
            <LiveEnergyView zevId={selectedZevId || undefined} />

            {hasViews && isZevScope && (
                // The picker decides what the views below show, so it comes first (UI patterns §10.3 rule 2). It stays on every
                // tab, Tomorrow included, so the tab strip does not jump when the tab changes.
                <section className="filter-bar">
                    <div className="filter-bar-fields">
                        <label>
                            <span>{t('pages.dashboard.participant')}</span>
                            <select value={selectedParticipantId} onChange={(event) => setParticipant(event.target.value)}>
                                {!selectedParticipantId && <option value="">{t('myEnergy.pickParticipant')}</option>}
                                {participants.map((participant) => (
                                    <option key={participant.id} value={participant.id}>
                                        {participantLabel(participant)}
                                        {ownParticipantIds.includes(participant.id) ? ` (${t('pages.dashboard.youBadge')})` : ''}
                                    </option>
                                ))}
                            </select>
                        </label>
                    </div>
                </section>
            )}

            {hasViews && (
                <AppTabs value={range} onChange={(value) => setRange(parseMyEnergyRange(value))} keepMounted={false}>
                    {showTabs && (
                        <AppTabs.List aria-label={t('myEnergy.rangeLabel')}>
                            <AppTabs.Tab value="today">{t('myEnergy.tabs.today')}</AppTabs.Tab>
                            {hasTomorrow && <AppTabs.Tab value="tomorrow">{t('myEnergy.tabs.tomorrow')}</AppTabs.Tab>}
                            {historyPossible && <AppTabs.Tab value="week">{t('myEnergy.tabs.week')}</AppTabs.Tab>}
                            {historyPossible && <AppTabs.Tab value="period">{t('myEnergy.tabs.period')}</AppTabs.Tab>}
                        </AppTabs.List>
                    )}

                    {range === 'period' && interval && (
                        <section className="filter-bar">
                            <PeriodSelector interval={interval} from={period.from} to={period.to} onChange={onPeriodChange} />
                        </section>
                    )}

                    <AppTabs.Panel value="today">
                        <TodayPanel zevId={selectedZevId || undefined} subject={subject} canConnect={canConnect} hasOwnSource={hasOwnSource} historyPossible={historyPossible} forecast={forecast} />
                    </AppTabs.Panel>
                    {hasTomorrow && forecast && (
                        <AppTabs.Panel value="tomorrow">
                            <ProductionForecastChart forecast={forecastForDay(forecast, tomorrow)} title={t('myEnergy.tomorrow.title')} />
                        </AppTabs.Panel>
                    )}
                    <AppTabs.Panel value="week">
                        <SeriesPanel
                            zevId={selectedZevId || undefined}
                            subject={subject}
                            canConnect={canConnect}
                            hasOwnSource={hasOwnSource}
                            historyPossible={historyPossible}
                            range={lastDaysRange(today, 7)}
                            bucket="hour"
                            footer={
                                <p className="muted">
                                    {t(subject.isOwn ? 'myEnergy.week.note' : 'myEnergy.week.notePerson')}{' '}
                                    <Link className="text-link" to="/dashboard">{t('myEnergy.week.noteLink')}</Link>
                                </p>
                            }
                        />
                    </AppTabs.Panel>
                    <AppTabs.Panel value="period">
                        <SeriesPanel
                            zevId={selectedZevId || undefined}
                            subject={subject}
                            canConnect={canConnect}
                            hasOwnSource={hasOwnSource}
                            historyPossible={historyPossible}
                            range={period}
                            bucket="day"
                            ready={periodReady}
                        />
                    </AppTabs.Panel>
                </AppTabs>
            )}
        </>
    )
}

/** What to say where there is nothing of the own system to show. */
function NoOwnSystem({ subject, canConnect, hasOwnSource, historyPossible }: {
    subject: Subject
    canConnect: boolean
    hasOwnSource: boolean
    historyPossible: boolean
}) {
    const { t } = useTranslation()
    // The picker's placeholder asks for a participant; a meter that cannot have a history has nothing to wait for.
    if (!subject.ready || (subject.isOwn && !historyPossible)) return null
    if (!subject.isOwn) return <p className="muted">{t('myEnergy.noOwnSystemParticipant')}</p>
    if (canConnect) return <GrossEnergyCallToAction />
    // A source exists: the data is on its way, and the connection is where to look when it is not.
    return (
        <p className="muted">
            {t(hasOwnSource ? 'myEnergy.notSynced' : 'myEnergy.noOwnSystem')}{' '}
            <Link className="text-link" to="/me/metering-points">{t('myEnergy.toMeteringPoints')}</Link>
        </p>
    )
}

/**
 * Today: the live curve (when the live view has data) with the own line merged from history and live,
 * or the history alone through the own-series endpoint when there is no live curve.
 */
function TodayPanel({ zevId, subject, canConnect, hasOwnSource, historyPossible, forecast }: {
    zevId: string | undefined
    subject: Subject
    canConnect: boolean
    hasOwnSource: boolean
    historyPossible: boolean
    forecast: ProductionForecast | null
}) {
    const { t } = useTranslation()
    const date = todayBusinessIso()
    const enabledQuery = useLiveEnabled()
    const snapshotQuery = useLiveEnergy(zevId)
    const liveShown = !!liveCardState(snapshotQuery.data)
    const curveQuery = useLiveCurve(zevId, liveShown, subject.participantId)
    const curve = curveQuery.data ?? null
    // Whether there is a live curve to wait for is known once the flag and the snapshot have answered.
    const liveKnown = !enabledQuery.isPending && (!snapshotQuery.isPending || !zevId)
    const curveSettled = liveKnown && (!liveShown || !curveQuery.isPending)
    const seriesQuery = useOwnSeries(
        { zevId, dateFrom: date, dateTo: date, bucket: 'quarter', participantId: subject.participantId },
        subject.ready && curveSettled && !curve,
    )

    const history = useMemo(
        () => curve ? { rows: curve.own_history, through: curve.own_history_through } : ownHistoryFromSeries(seriesQuery.data),
        [curve, seriesQuery.data],
    )
    const rows = useMemo(
        () => todayRows(curve, history.rows, history.through, forecast ? { date, hours: forecast.hours } : undefined),
        [curve, history, forecast, date],
    )
    const hasOwn = history.rows.length > 0
    // Somebody else's live line is data, so "no own system" must not be said under it; their own system is a story of the history.
    const hasPersonLive = !subject.isOwn && rows.some((row) => row.ownLive !== null || row.ownLiveProduction !== null)

    if (!curveSettled || seriesQuery.isLoading) return <PageSkeleton variant="kpiRow" />
    return (
        <>
            {seriesQuery.isError && <Notice tone="error">{t('myEnergy.loadFailed')}</Notice>}
            {(liveShown || hasOwn || rows.some((row) => row.forecast !== null)) && (
                <TodayChart date={date} rows={rows} through={history.through} hasLive={!!curve} isOwn={subject.isOwn} peakWindows={forecast?.peak_windows} />
            )}
            {!hasOwn && !hasPersonLive && !seriesQuery.isError && <NoOwnSystem subject={subject} canConnect={canConnect} hasOwnSource={hasOwnSource} historyPossible={historyPossible} />}
        </>
    )
}

/** Seven days or the billing period: the own system's totals and chart, as the dashboards used to show them. */
function SeriesPanel({ zevId, subject, canConnect, hasOwnSource, historyPossible, range, bucket, ready = true, footer }: {
    zevId: string | undefined
    subject: Subject
    canConnect: boolean
    hasOwnSource: boolean
    historyPossible: boolean
    range: { from: string; to: string }
    bucket: 'hour' | 'day'
    ready?: boolean
    footer?: ReactNode
}) {
    const { t } = useTranslation()
    const { formatBucketLabel, formatBucketTooltipLabel } = useBucketLabelFormatters(bucket)
    const query = useOwnSeries(
        { zevId, dateFrom: range.from, dateTo: range.to, bucket, participantId: subject.participantId },
        subject.ready && ready,
    )
    const gross = query.data?.gross ?? null

    // Nobody picked yet (a manager, viewer or admin): say what to do instead of showing an empty tab.
    if (!subject.ready) return subject.participantId ? null : <p className="muted">{t('myEnergy.pickParticipantHint')}</p>
    if (query.isError) {
        return (
            <Notice tone="error" onRetry={() => void query.refetch()} isRetrying={query.isFetching}>
                {t('myEnergy.loadFailed')}
            </Notice>
        )
    }
    if (subject.ready && query.isPending) return <PageSkeleton variant="kpiRow" />
    return (
        <>
            {gross ? (
                <GrossEnergyCard
                    gross={gross}
                    whose={subject.isOwn ? 'own' : 'participant'}
                    participantName={subject.name}
                    formatBucketLabel={formatBucketLabel}
                    formatBucketTooltipLabel={formatBucketTooltipLabel}
                    dayAxis={bucket === 'hour'}
                />
            ) : (
                <NoOwnSystem subject={subject} canConnect={canConnect} hasOwnSource={hasOwnSource} historyPossible={historyPossible} />
            )}
            {footer}
        </>
    )
}
