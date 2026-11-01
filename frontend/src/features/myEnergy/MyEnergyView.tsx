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
import { usePageNavigation } from '../../lib/usePageNavigation'
import { type DashboardBodyProps, useBucketLabelFormatters } from '../dashboard/dashboardShared'
import { LiveEnergyView } from '../live/LiveEnergyView'
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
 * a participant, never billing input (ADR 0030). "Right now" on top, then Today, 7 days and Period.
 */
export function MyEnergyView({ interval, period, onPeriodChange, periodReady }: DashboardBodyProps) {
    const { t } = useTranslation()
    const { user } = useAuth()
    const { selectedZevId } = useManagedZev()
    const { isZevScope } = useCommunityAccess()
    const energyData = useEnergyDataEligibility()
    const { searchParams, updateParams } = usePageNavigation()
    const range = parseMyEnergyRange(searchParams.get('range'))

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

            <AppTabs value={range} onChange={(value) => setRange(parseMyEnergyRange(value))} keepMounted={false}>
                <AppTabs.List aria-label={t('myEnergy.rangeLabel')}>
                    <AppTabs.Tab value="today">{t('myEnergy.tabs.today')}</AppTabs.Tab>
                    <AppTabs.Tab value="week">{t('myEnergy.tabs.week')}</AppTabs.Tab>
                    <AppTabs.Tab value="period">{t('myEnergy.tabs.period')}</AppTabs.Tab>
                </AppTabs.List>

                <section className="filter-bar">
                    {range === 'period' && interval && (
                        <PeriodSelector interval={interval} from={period.from} to={period.to} onChange={onPeriodChange} />
                    )}
                    {isZevScope && (
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
                    )}
                </section>

                <AppTabs.Panel value="today">
                    <TodayPanel zevId={selectedZevId || undefined} subject={subject} canConnect={canConnect} />
                </AppTabs.Panel>
                <AppTabs.Panel value="week">
                    <SeriesPanel
                        zevId={selectedZevId || undefined}
                        subject={subject}
                        canConnect={canConnect}
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
                        range={period}
                        bucket="day"
                        ready={periodReady}
                    />
                </AppTabs.Panel>
            </AppTabs>
        </>
    )
}

/** What to say where there is nothing of the own system to show. */
function NoOwnSystem({ subject, canConnect }: { subject: Subject; canConnect: boolean }) {
    const { t } = useTranslation()
    if (!subject.ready) return <p className="muted">{t('myEnergy.pickParticipantPrompt')}</p>
    if (subject.isOwn && canConnect) return <GrossEnergyCallToAction />
    return <p className="muted">{t(subject.isOwn ? 'myEnergy.noOwnSystem' : 'myEnergy.noOwnSystemParticipant')}</p>
}

/**
 * Today: the live curve (when the live view has data) with the own line merged from history and live,
 * or the history alone through the own-series endpoint when there is no live curve.
 */
function TodayPanel({ zevId, subject, canConnect }: { zevId: string | undefined; subject: Subject; canConnect: boolean }) {
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
    const rows = useMemo(() => todayRows(curve, history.rows, history.through), [curve, history])
    const hasOwn = history.rows.length > 0

    if (!curveSettled || seriesQuery.isLoading) return <PageSkeleton variant="kpiRow" />
    return (
        <>
            {seriesQuery.isError && <Notice tone="error">{t('myEnergy.loadFailed')}</Notice>}
            {(liveShown || hasOwn) && <TodayChart date={date} rows={rows} through={history.through} hasLive={!!curve} />}
            {!hasOwn && !seriesQuery.isError && <NoOwnSystem subject={subject} canConnect={canConnect} />}
        </>
    )
}

/** Seven days or the billing period: the own system's totals and chart, as the dashboards used to show them. */
function SeriesPanel({ zevId, subject, canConnect, range, bucket, ready = true, footer }: {
    zevId: string | undefined
    subject: Subject
    canConnect: boolean
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
                <NoOwnSystem subject={subject} canConnect={canConnect} />
            )}
            {footer}
        </>
    )
}
