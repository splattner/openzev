import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import { fetchHourlyProfile, fetchMeteringDashboardSummary } from '../../lib/api/metering'
import { fetchInvoices } from '../../lib/api/invoices'
import { queryKeys } from '../../lib/api/queryKeys'
import { formatKwh, formatPercent } from '../../lib/numbers'
import { dashboardKwhStat, fromZevRate, kwhTick } from '../../lib/dashboardFormatting'
import { useAuth } from '../../lib/auth'
import { personalInvoiceFilter, selectedCommunityName } from '../../lib/membership'
import { useManagedZev } from '../../lib/managedZev'
import { behindMeterHintKey, useEnergyDataEligibility } from '../../lib/supplementary'
import { PageSkeleton } from '../../components/PageSkeleton'
import { Notice } from '../../components/Notice'
import { StatCard } from '../../components/StatCard'
import { PeriodSelector } from '../../components/PeriodSelector'
import { ConsumptionSplitCard } from '../../components/dashboard/ConsumptionSplitCard'
import { GrossEnergyCallToAction, GrossEnergyCard } from '../../components/dashboard/GrossEnergyCard'
import { EnergyFlowCard } from '../../components/dashboard/EnergyFlowCard'
import { HourlyProfileSection } from '../../components/dashboard/HourlyProfileSection'
import { ParticipantInvoicesCard } from '../../components/dashboard/ParticipantInvoicesCard'
import { type DashboardBodyProps, type DashboardBucket, useBucketLabelFormatters, useHourlyProfileRows } from './dashboardShared'
import { ResolutionSelect } from './ResolutionSelect'

export function ParticipantDashboardBody({ interval, period, onPeriodChange, periodReady }: DashboardBodyProps) {
    const { t } = useTranslation()
    const { user } = useAuth()
    const { entries, selectedZevId, selectedZev } = useManagedZev()
    const energyData = useEnergyDataEligibility()

    const [bucket, setBucket] = useState<DashboardBucket>('day')
    const hasMultipleCommunities = (entries?.length ?? 0) > 1
    const participantZevId = hasMultipleCommunities ? selectedZevId : undefined
    const { formatBucketLabel, formatBucketTooltipLabel } = useBucketLabelFormatters(bucket)

    const summaryQuery = useQuery({
        queryKey: queryKeys.metering.dashboardSummary({
            role: user?.role,
            zevId: selectedZevId,
            participantId: '',
            from: period.from,
            to: period.to,
            bucket,
        }),
        queryFn: () =>
            fetchMeteringDashboardSummary({
                dateFrom: period.from,
                dateTo: period.to,
                bucket,
                zevId: participantZevId,
            }),
        enabled: periodReady,
    })
    const isPersonalInvoice = personalInvoiceFilter(user)
    const invoicesQuery = useQuery({
        queryKey: queryKeys.invoices.mine(),
        queryFn: () => fetchInvoices(undefined),
        refetchInterval: (query) => query.state.data?.some(
            (invoice) => isPersonalInvoice(invoice) && invoice.pdf_status === 'pending',
        ) ? 15000 : false,
    })
    const hourlyProfileQuery = useQuery({
        queryKey: queryKeys.metering.hourlyProfile(period.from, period.to, selectedZevId || undefined),
        queryFn: () =>
            fetchHourlyProfile({
                dateFrom: period.from,
                dateTo: period.to,
                zevId: participantZevId,
            }),
        enabled: periodReady,
    })

    const summary = summaryQuery.data
    const currentParticipantId = summary?.summary_kind === 'participant' ? summary.current_participant_id : null
    const highlightParticipantIds = useMemo(() => {
        const ids = (user?.memberships ?? []).flatMap(membership =>
            membership.participants.filter(participant => participant.live).map(participant => participant.id),
        )
        return ids.length ? ids : currentParticipantId ? [currentParticipantId] : []
    }, [user?.memberships, currentParticipantId])
    const scopeName = selectedCommunityName({ selectedZev, entries, selectedZevId })
    const participantTimeline = useMemo(
        () =>
            summary?.summary_kind === 'participant'
                ? summary.timeline.map((entry) => ({
                      ...entry,
                      from_zev_rate: summary.has_behind_meter_generation
                          ? null
                          : fromZevRate(entry.consumed_from_zev_kwh, entry.total_consumed_kwh),
                  }))
                : [],
        [summary],
    )
    const participantFromZev = useMemo(() => {
        if (summary?.summary_kind !== 'participant' || summary.has_behind_meter_generation) return null
        const { consumed_from_zev_kwh, total_consumed_kwh } = summary.totals
        const pct = fromZevRate(consumed_from_zev_kwh, total_consumed_kwh)
        return pct === null ? null : { pct, zevKwh: consumed_from_zev_kwh, totalKwh: total_consumed_kwh }
    }, [summary])
    const hourlyProfileData = useHourlyProfileRows(hourlyProfileQuery.data?.hourly_profile)
    const participantInvoices = invoicesQuery.data?.filter(isPersonalInvoice)

    return (
        <>
            <section className="card">
                <div className="grid">
                    {interval && <PeriodSelector interval={interval} from={period.from} to={period.to} onChange={onPeriodChange} />}
                    <div className="inline-form inline-form--narrow">
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
            {summary && summary.summary_kind === 'participant' && (
                <>
                    <section className="stat-grid stat-grid--wide">
                        <StatCard label={t('pages.dashboard.participantStats.consumedFromZev')} value={dashboardKwhStat(summary.totals.consumed_from_zev_kwh)} />
                        <StatCard label={t('pages.dashboard.participantStats.importedFromGrid')} value={dashboardKwhStat(summary.totals.imported_from_grid_kwh)} />
                        <StatCard
                            label={t('pages.dashboard.participantStats.totalConsumption')}
                            value={dashboardKwhStat(summary.totals.total_consumed_kwh)}
                            hint={summary.has_behind_meter_generation ? t(behindMeterHintKey('own', summary.gross_energy)) : undefined}
                        />
                        <StatCard
                            label={t('pages.dashboard.participantStats.fromZevShare')}
                            value={participantFromZev ? formatPercent(participantFromZev.pct) : '—'}
                            hint={
                                summary.has_behind_meter_generation
                                    ? t(behindMeterHintKey('own', summary.gross_energy))
                                    : participantFromZev
                                      ? t('pages.dashboard.hints.fromZevShare', {
                                            zev: formatKwh(participantFromZev.zevKwh, { maxDecimals: 0 }),
                                            total: formatKwh(participantFromZev.totalKwh, { maxDecimals: 0 }),
                                        })
                                      : undefined
                            }
                        />
                    </section>
                    {summary.zev_has_behind_meter_generation && <p className="muted">{t('behindMeter.zevNote')}</p>}
                    {summary.has_behind_meter_generation && summary.gross_energy && (
                        <GrossEnergyCard
                            gross={summary.gross_energy}
                            whose="own"
                            formatBucketLabel={formatBucketLabel}
                            formatBucketTooltipLabel={formatBucketTooltipLabel}
                        />
                    )}
                    {summary.has_behind_meter_generation && !summary.gross_energy && energyData.tabAvailable && (
                        <GrossEnergyCallToAction />
                    )}
                    {summary.zev_participant_stats.length > 0 && summary.current_participant_id && (
                        <EnergyFlowCard
                            totals={summary.zev_totals}
                            participantStats={summary.zev_participant_stats}
                            highlightParticipantIds={highlightParticipantIds}
                            zevName={scopeName}
                        />
                    )}
                    <ConsumptionSplitCard
                        data={participantTimeline}
                        formatBucketLabel={formatBucketLabel}
                        formatBucketTooltipLabel={formatBucketTooltipLabel}
                        kwhTick={kwhTick}
                    />
                </>
            )}
            <HourlyProfileSection query={hourlyProfileQuery} data={hourlyProfileData} />
            <ParticipantInvoicesCard
                showCommunity={(user?.memberships?.length ?? 0) > 1}
                invoices={participantInvoices}
                isError={invoicesQuery.isError}
                isRetrying={invoicesQuery.isFetching}
                onRetry={() => void invoicesQuery.refetch()}
            />
        </>
    )
}
