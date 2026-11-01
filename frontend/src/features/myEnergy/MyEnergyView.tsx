import { type ReactNode, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { AppTabs } from '../../components/AppTabs'
import { Notice } from '../../components/Notice'
import { PageSkeleton } from '../../components/PageSkeleton'
import { PeriodSelector } from '../../components/PeriodSelector'
import { GrossEnergyCallToAction, GrossEnergyCard } from '../../components/dashboard/GrossEnergyCard'
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
    // Nothing is asked while the energy data feature is off.
    const liveEnabled = useLiveEnabled({ enabled: energyData.featureOn }).data === true
    const forecastQuery = useProductionForecast(selectedZevId || undefined, liveEnabled)
    const forecast = hasForecast(forecastQuery.data) ? forecastQuery.data : null
    const snapshotQuery = useLiveEnergy(liveEnabled ? selectedZevId || undefined : undefined)
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
    // A manager who is a participant with an own system starts on themselves; anybody else picks.
    const defaultParticipantId = energyData.historyEligible.find(
        (point) => point.zev === selectedZevId && point.source !== null,
    )?.participant ?? ''
    const requested = searchParams.get('participant') ?? ''
    const selectedParticipantId = isZevScope
        ? (participants.some((participant) => participant.id === requested) ? requested : defaultParticipantId)
        : ''
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
    // A history can only appear for a participant whose meter has a plant behind it; a manager looks at other people's.
    const historyPossible = isZevScope || energyData.historyEligible.some((point) => point.zev === selectedZevId)
    // Without a plant, a live source or a forecast there is nothing to put under the live card's own setup prompt.
    const liveSettled = !liveEnabled || !snapshotQuery.isPending
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

                    <section className="filter-bar">
                        {range === 'period' && interval && (
                            <PeriodSelector interval={interval} from={period.from} to={period.to} onChange={onPeriodChange} />
                        )}
                        {isZevScope && range !== 'tomorrow' && (
                            <>
                                <div className="filter-bar-fields">
                                    <label>
                                        <span>{t('pages.dashboard.participant')}</span>
                                        <select value={selectedParticipantId} onChange={(event) => setParticipant(event.target.value)}>
                                            {!selectedParticipantId && <option value="">{t('myEnergy.pickParticipant')}</option>}
                                            {participants.map((participant) => (
                                                <option key={participant.id} value={participant.id}>
                                                    {participant.display_name || participant.id}
                                                    {ownParticipantIds.includes(participant.id) ? ` (${t('pages.dashboard.youBadge')})` : ''}
                                                </option>
                                            ))}
                                        </select>
                                    </label>
                                </div>
                                {!subject.ready && <p className="muted filter-bar-note">{t('myEnergy.pickParticipantPrompt')}</p>}
                            </>
                        )}
                    </section>

                    <AppTabs.Panel value="today">
                        <TodayPanel zevId={selectedZevId || undefined} subject={subject} canConnect={canConnect} historyPossible={historyPossible} forecast={forecast} />
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
                            historyPossible={historyPossible}
                            range={lastDaysRange(today, 7)}
                            bucket="hour"
                            footer={
                                <p className="muted">
                                    {t('myEnergy.week.note')}{' '}
                                    <Link to="/dashboard">{t('myEnergy.week.noteLink')}</Link>
                                </p>
                            }
                        />
                    </AppTabs.Panel>
                    <AppTabs.Panel value="period">
                        <SeriesPanel
                            zevId={selectedZevId || undefined}
                            subject={subject}
                            canConnect={canConnect}
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
function NoOwnSystem({ subject, canConnect, historyPossible }: { subject: Subject; canConnect: boolean; historyPossible: boolean }) {
    const { t } = useTranslation()
    // The prompt to pick a participant sits by the picker; a meter that cannot have a history has nothing to wait for.
    if (!subject.ready || (subject.isOwn && !historyPossible)) return null
    if (subject.isOwn && canConnect) return <GrossEnergyCallToAction />
    return <p className="muted">{t(subject.isOwn ? 'myEnergy.noOwnSystem' : 'myEnergy.noOwnSystemParticipant')}</p>
}

/**
 * Today: the live curve (when the live view has data) with the own line merged from history and live,
 * or the history alone through the own-series endpoint when there is no live curve.
 */
function TodayPanel({ zevId, subject, canConnect, historyPossible, forecast }: {
    zevId: string | undefined
    subject: Subject
    canConnect: boolean
    historyPossible: boolean
    forecast: ProductionForecast | null
}) {
    const { t } = useTranslation()
    const date = todayBusinessIso()
    const enabledQuery = useLiveEnabled()
    const enabled = enabledQuery.data === true
    const snapshotQuery = useLiveEnergy(enabled ? zevId : undefined)
    const liveShown = !!liveCardState(snapshotQuery.data)
    const curveQuery = useLiveCurve(zevId, liveShown, subject.participantId)
    const curve = curveQuery.data ?? null
    // Whether there is a live curve to wait for is known once the flag and the snapshot have answered.
    const liveKnown = !enabledQuery.isPending && (!enabled || !snapshotQuery.isPending || !zevId)
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

    if (!curveSettled || seriesQuery.isLoading) return <PageSkeleton variant="kpiRow" />
    return (
        <>
            {seriesQuery.isError && <Notice tone="error">{t('myEnergy.loadFailed')}</Notice>}
            {(liveShown || hasOwn || rows.some((row) => row.forecast !== null)) && (
                <TodayChart date={date} rows={rows} through={history.through} hasLive={!!curve} peakWindows={forecast?.peak_windows} />
            )}
            {!hasOwn && !seriesQuery.isError && <NoOwnSystem subject={subject} canConnect={canConnect} historyPossible={historyPossible} />}
        </>
    )
}

/** Seven days or the billing period: the own system's totals and chart, as the dashboards used to show them. */
function SeriesPanel({ zevId, subject, canConnect, historyPossible, range, bucket, ready = true, footer }: {
    zevId: string | undefined
    subject: Subject
    canConnect: boolean
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
                />
            ) : (
                <NoOwnSystem subject={subject} canConnect={canConnect} historyPossible={historyPossible} />
            )}
            {footer}
        </>
    )
}
