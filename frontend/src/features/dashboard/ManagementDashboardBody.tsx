import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import { fetchHourlyProfile, fetchMeteringDashboardSummary } from '../../lib/api/metering'
import { queryKeys } from '../../lib/api/queryKeys'
import { formatKwh, formatPercent } from '../../lib/numbers'
import { dashboardKwhStat, hourlyKwhTick, hourlyKwhTooltipValue, fromZevRate, kwhTick } from '../../lib/dashboardFormatting'
import { useAuth } from '../../lib/auth'
import { useManagedZev } from '../../lib/managedZev'
import { useEnergyDataEligibility } from '../../lib/supplementary'
import { PageSkeleton } from '../../components/PageSkeleton'
import { Notice } from '../../components/Notice'
import { StatCard } from '../../components/StatCard'
import { PeriodSelector } from '../../components/PeriodSelector'
import { GrossEnergyCallToAction, GrossEnergyCard } from '../../components/dashboard/GrossEnergyCard'
import { BalanceChart } from '../../components/dashboard/BalanceChart'
import { EnergyFlowCard } from '../../components/dashboard/EnergyFlowCard'
import { HourlyProfileCard } from '../../components/dashboard/HourlyProfileCard'
import { ParticipantTableCard } from '../../components/dashboard/ParticipantTableCard'
import { type DashboardBodyProps, type DashboardBucket, useBucketLabelFormatters, useHourlyProfileRows } from './dashboardShared'
import { ResolutionSelect } from './ResolutionSelect'

export function ManagementDashboardBody({ interval, period, onPeriodChange, periodReady }: DashboardBodyProps) {
    const { t } = useTranslation()
    const { user } = useAuth()
    const { selectedZevId, selectedZev } = useManagedZev()
    const energyData = useEnergyDataEligibility()

    const [bucket, setBucket] = useState<DashboardBucket>('day')
    const [participantSelection, setParticipantSelection] = useState({ scopeId: selectedZevId, id: '' })
    if (participantSelection.scopeId !== selectedZevId) {
        setParticipantSelection({ scopeId: selectedZevId, id: '' })
    }
    // Derive before queries run, so a community switch cannot request the old participant.
    const selectedParticipantId = participantSelection.scopeId === selectedZevId ? participantSelection.id : ''
    const setSelectedParticipantId = (id: string) => setParticipantSelection({ scopeId: selectedZevId, id })
    const { formatBucketLabel, formatBucketTooltipLabel } = useBucketLabelFormatters(bucket)

    const summaryQuery = useQuery({
        queryKey: queryKeys.metering.dashboardSummary({
            role: user?.role,
            zevId: selectedZevId,
            participantId: selectedParticipantId,
            from: period.from,
            to: period.to,
            bucket,
        }),
        queryFn: () =>
            fetchMeteringDashboardSummary({
                dateFrom: period.from,
                dateTo: period.to,
                bucket,
                zevId: selectedZevId,
                participantId: selectedParticipantId || undefined,
            }),
        enabled: periodReady && !!selectedZevId,
    })
    const hourlyProfileQuery = useQuery({
        queryKey: queryKeys.metering.hourlyProfile(period.from, period.to, selectedZevId || undefined, selectedParticipantId || undefined),
        queryFn: () =>
            fetchHourlyProfile({
                dateFrom: period.from,
                dateTo: period.to,
                zevId: selectedZevId,
                participantId: selectedParticipantId || undefined,
            }),
        enabled: periodReady && !!selectedParticipantId,
    })

    const summary = summaryQuery.data
    // A manager is usually a participant too: their own rows in this community, marked in the table.
    const ownParticipantIds = useMemo(
        () =>
            (user?.memberships ?? [])
                .find((membership) => membership.zev === selectedZevId)
                ?.participants.filter((participant) => participant.live)
                .map((participant) => participant.id) ?? [],
        [user?.memberships, selectedZevId],
    )
    const wantsOwnEnergyData = energyData.eligible.some((point) => point.zev === selectedZevId && point.source === null)
    const highlightParticipantIds = useMemo(
        () => selectedParticipantId ? [selectedParticipantId] : undefined,
        [selectedParticipantId],
    )
    const selectedZevName = selectedZev?.name
    const selectedParticipantName = summary?.summary_kind === 'zev' ? summary.selected_participant_name : undefined
    // Behind-meter generation makes the selected participant's from-ZEV rate misleading (spec §7.2).
    const selectedParticipantHasGeneration =
        summary?.summary_kind === 'zev' &&
        !!selectedParticipantId &&
        summary.participant_stats.some(
            (participant) => participant.participant_id === selectedParticipantId && participant.has_behind_meter_generation,
        )
    const ownerChartData = useMemo(() => {
        if (summary?.summary_kind !== 'zev') return []
        return summary.timeline.map((entry) => {
            const locally_consumed = Math.max(0, entry.consumed_kwh - entry.imported_kwh)
            const locally_produced = Math.max(0, entry.produced_kwh - entry.exported_kwh)
            const self_consumption_rate =
                entry.produced_kwh > 0 ? Math.round((locally_produced / entry.produced_kwh) * 1000) / 10 : null
            const from_zev_rate = selectedParticipantHasGeneration ? null : fromZevRate(locally_consumed, entry.consumed_kwh)
            return { ...entry, locally_consumed, locally_produced, self_consumption_rate, from_zev_rate }
        })
    }, [summary, selectedParticipantHasGeneration])
    const hourlyProfileData = useHourlyProfileRows(hourlyProfileQuery.data?.hourly_profile)
    const ownerSelfConsumption = useMemo(() => {
        if (summary?.summary_kind !== 'zev') return null
        const { produced_kwh, exported_kwh } = summary.zev_totals
        if (produced_kwh <= 0) return null
        const localKwh = Math.max(0, produced_kwh - exported_kwh)
        return { pct: (localKwh / produced_kwh) * 100, localKwh, producedKwh: produced_kwh }
    }, [summary])

    return (
        <>
            <section className="card">
                <div className="grid">
                    {interval && <PeriodSelector interval={interval} from={period.from} to={period.to} onChange={onPeriodChange} />}
                    <div className="inline-form grid grid-2">
                        <label>
                            <span>{t('pages.dashboard.participant')}</span>
                            <select value={selectedParticipantId} onChange={(e) => setSelectedParticipantId(e.target.value)}>
                                <option value="">{t('pages.dashboard.allParticipants')}</option>
                                {summary?.summary_kind === 'zev' &&
                                    summary.participant_stats.map((participant) => (
                                        <option key={participant.participant_id} value={participant.participant_id}>
                                            {participant.participant_name || participant.participant_id}
                                            {ownParticipantIds.includes(participant.participant_id) ? ` (${t('pages.dashboard.youBadge')})` : ''}
                                        </option>
                                    ))}
                            </select>
                        </label>
                        <ResolutionSelect value={bucket} onChange={setBucket} />
                    </div>
                </div>
            </section>

            {summaryQuery.isLoading && <PageSkeleton variant="kpiRow" />}
            {summaryQuery.isError && (
                <Notice tone="error" onRetry={() => void summaryQuery.refetch()} isRetrying={summaryQuery.isFetching}>
                    {t('pages.dashboard.failedAnalytics')}
                </Notice>
            )}
            {summary && summary.summary_kind === 'zev' && (
                <>
                    {/* ZEV-wide KPIs; the participant filter does not apply (spec §5.1). */}
                    <section className="kpi-row">
                        <StatCard
                            accent
                            label={t('pages.dashboard.stats.selfConsumptionRate')}
                            value={ownerSelfConsumption ? formatPercent(ownerSelfConsumption.pct) : '—'}
                            hint={
                                ownerSelfConsumption
                                    ? t('pages.dashboard.hints.selfConsumption', {
                                          local: formatKwh(ownerSelfConsumption.localKwh, { maxDecimals: 0 }),
                                          total: formatKwh(ownerSelfConsumption.producedKwh, { maxDecimals: 0 }),
                                      })
                                    : undefined
                            }
                        />
                        <StatCard label={t('pages.dashboard.stats.producedInZev')} value={dashboardKwhStat(summary.zev_totals.produced_kwh)} />
                        <StatCard label={t('pages.dashboard.stats.consumedInZev')} value={dashboardKwhStat(summary.zev_totals.consumed_kwh)} />
                        <StatCard label={t('pages.dashboard.stats.importedFromGrid')} value={dashboardKwhStat(summary.zev_totals.imported_kwh)} />
                        <StatCard label={t('pages.dashboard.stats.exportedToGrid')} value={dashboardKwhStat(summary.zev_totals.exported_kwh)} />
                    </section>
                    {summary.zev_has_behind_meter_generation && <p className="muted">{t('behindMeter.zevNote')}</p>}
                    {summary.own_gross_energy && (
                        <GrossEnergyCard
                            gross={summary.own_gross_energy}
                            whose="own"
                            formatBucketLabel={formatBucketLabel}
                            formatBucketTooltipLabel={formatBucketTooltipLabel}
                        />
                    )}
                    {!summary.own_gross_energy && wantsOwnEnergyData && <GrossEnergyCallToAction />}
                    {summary.participant_stats.length > 0 && (
                        <EnergyFlowCard
                            totals={summary.zev_totals}
                            participantStats={summary.participant_stats}
                            highlightParticipantIds={highlightParticipantIds}
                            zevName={selectedZevName}
                        />
                    )}
                    <BalanceChart
                        data={ownerChartData}
                        zevName={selectedZevName}
                        participantName={selectedParticipantName ?? undefined}
                        formatBucketLabel={formatBucketLabel}
                        formatBucketTooltipLabel={formatBucketTooltipLabel}
                        kwhTick={kwhTick}
                    />
                    {selectedParticipantId && summary.selected_gross_energy && !ownParticipantIds.includes(selectedParticipantId) && (
                        <GrossEnergyCard
                            gross={summary.selected_gross_energy}
                            whose="participant"
                            participantName={selectedParticipantName ?? undefined}
                            formatBucketLabel={formatBucketLabel}
                            formatBucketTooltipLabel={formatBucketTooltipLabel}
                        />
                    )}
                    <ParticipantTableCard
                        participantStats={summary.participant_stats}
                        selectedParticipantId={selectedParticipantId}
                        onSelect={setSelectedParticipantId}
                        ownParticipantIds={ownParticipantIds}
                    />
                    {selectedParticipantId && hourlyProfileData.length > 0 && (
                        <HourlyProfileCard
                            data={hourlyProfileData}
                            hourlyKwhTick={hourlyKwhTick}
                            hourlyKwhTooltipValue={hourlyKwhTooltipValue}
                            participantName={selectedParticipantName ?? undefined}
                        />
                    )}
                </>
            )}
        </>
    )
}
