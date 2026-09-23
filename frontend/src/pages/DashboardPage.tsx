import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import { fetchHourlyProfile, fetchMeteringDashboardSummary } from '../lib/api/metering'
import { fetchInvoices } from '../lib/api/invoices'
import { queryKeys } from '../lib/api/queryKeys'
import { formatKwh, formatPercent } from '../lib/numbers'
import { dashboardKwhStat, hourlyKwhTick, hourlyKwhTooltipValue, fromZevRate, kwhTick } from '../lib/dashboardFormatting'
import { formatMeteringBucketLabel } from '../lib/meteringLabels'
import { useAppSettings } from '../lib/appSettings'
import { useAuth } from '../lib/auth'
import { useManagedZev } from '../lib/managedZev'
import { PageSkeleton } from '../components/PageSkeleton'
import { StatCard } from '../components/StatCard'
import { PeriodSelector } from '../components/PeriodSelector'
import { BalanceChart } from '../components/dashboard/BalanceChart'
import { ConsumptionSplitCard } from '../components/dashboard/ConsumptionSplitCard'
import { EnergyFlowCard } from '../components/dashboard/EnergyFlowCard'
import { HourlyProfileCard } from '../components/dashboard/HourlyProfileCard'
import { ParticipantInvoicesCard } from '../components/dashboard/ParticipantInvoicesCard'
import { ParticipantTableCard } from '../components/dashboard/ParticipantTableCard'
import { type BillingInterval, getCurrentBillingPeriod } from '../lib/billingPeriod'

export function DashboardPage() {
    const { t } = useTranslation()
    const { user } = useAuth()
    const { settings } = useAppSettings()
    const { managedZevs, selectedZevId, selectedZev, isLoading: managedZevLoading } = useManagedZev()

    const interval: BillingInterval = (selectedZev?.billing_interval as BillingInterval) ?? 'monthly'
    const [period, setPeriod] = useState<{ from: string; to: string }>(() => getCurrentBillingPeriod(interval))
    const [bucket, setBucket] = useState<'day' | 'hour' | 'month'>('day')
    const [selectedParticipantId, setSelectedParticipantId] = useState('')

    const isZevScopedRole = user?.role === 'admin' || user?.role === 'zev_owner'
    const formatBucketLabel = (value: string) => formatMeteringBucketLabel(value, bucket, settings)
    const formatBucketTooltipLabel = (label: unknown) => formatBucketLabel(String(label ?? ''))

    useEffect(() => {
        setSelectedParticipantId('')
    }, [selectedZevId])
    useEffect(() => {
        setPeriod(getCurrentBillingPeriod(interval))
    }, [selectedZevId, interval])

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
                zevId: isZevScopedRole ? selectedZevId : undefined,
                participantId: isZevScopedRole && selectedParticipantId ? selectedParticipantId : undefined,
            }),
        enabled: user?.role === 'participant' || (isZevScopedRole && !!selectedZevId),
    })
    const invoicesQuery = useQuery({
        queryKey: queryKeys.invoices.list(),
        queryFn: () => fetchInvoices(),
        // Managers use Overview's period cards. Participants still receive
        // their own invoices here from the role-scoped endpoint.
        enabled: user?.role === 'participant',
    })
    const hourlyProfileQuery = useQuery({
        queryKey: queryKeys.metering.hourlyProfile(period.from, period.to, selectedZevId || undefined, selectedParticipantId || undefined),
        queryFn: () =>
            fetchHourlyProfile({
                dateFrom: period.from,
                dateTo: period.to,
                zevId: isZevScopedRole ? selectedZevId : undefined,
                participantId: isZevScopedRole && selectedParticipantId ? selectedParticipantId : undefined,
            }),
        enabled: user?.role === 'participant' || (isZevScopedRole && !!selectedParticipantId),
    })

    const summary = summaryQuery.data
    const selectedZevName = selectedZev?.name
    const participantScopeName = user?.zev_count === 1 ? user?.zev_name : undefined
    const selectedParticipantName = summary?.role === 'zev_owner' ? summary.selected_participant_name : undefined
    const ownerTimeline = useMemo(() => (summary?.role === 'zev_owner' ? summary.timeline : []), [summary])
    const ownerChartData = useMemo(
        () =>
            ownerTimeline.map((entry) => {
                const locally_consumed = Math.max(0, entry.consumed_kwh - entry.imported_kwh)
                const locally_produced = Math.max(0, entry.produced_kwh - entry.exported_kwh)
                const self_consumption_rate =
                    entry.produced_kwh > 0 ? Math.round((locally_produced / entry.produced_kwh) * 1000) / 10 : null
                const from_zev_rate = fromZevRate(locally_consumed, entry.consumed_kwh)
                return { ...entry, locally_consumed, locally_produced, self_consumption_rate, from_zev_rate }
            }),
        [ownerTimeline],
    )
    const participantTimeline = useMemo(
        () =>
            summary?.role === 'participant'
                ? summary.timeline.map((entry) => ({
                      ...entry,
                      from_zev_rate: fromZevRate(entry.consumed_from_zev_kwh, entry.total_consumed_kwh),
                  }))
                : [],
        [summary],
    )
    const participantFromZev = useMemo(() => {
        if (summary?.role !== 'participant') return null
        const { consumed_from_zev_kwh, total_consumed_kwh } = summary.totals
        const pct = fromZevRate(consumed_from_zev_kwh, total_consumed_kwh)
        return pct === null ? null : { pct, zevKwh: consumed_from_zev_kwh, totalKwh: total_consumed_kwh }
    }, [summary])
    const hourlyProfile = hourlyProfileQuery.data?.hourly_profile ?? null
    const hourlyProfileData = useMemo(
        () => hourlyProfile?.map((entry) => ({ ...entry, label: `${String(entry.hour).padStart(2, '0')}:00` })) ?? [],
        [hourlyProfile],
    )
    const participantInvoicesWithPdf = useMemo(
        () =>
            (invoicesQuery.data ?? []).filter(
                (invoice) => ['approved', 'sent', 'paid'].includes(invoice.status) && !!invoice.pdf_url,
            ),
        [invoicesQuery.data],
    )
    const ownerSelfConsumption = useMemo(() => {
        if (summary?.role !== 'zev_owner') return null
        const { produced_kwh, exported_kwh } = summary.zev_totals
        if (produced_kwh <= 0) return null
        const localKwh = Math.max(0, produced_kwh - exported_kwh)
        return { pct: (localKwh / produced_kwh) * 100, localKwh, producedKwh: produced_kwh }
    }, [summary])

    return (
        <div className="page-stack">
            <header>
                {(selectedZevName || participantScopeName) ? <p className="eyebrow">{selectedZevName ?? participantScopeName}</p> : null}
                <h2>{t(isZevScopedRole ? 'pages.energyBalancePage.title' : 'dashboard.title')}</h2>
                <p className="muted">{t(isZevScopedRole ? 'pages.energyBalancePage.description' : 'dashboard.description')}</p>
            </header>

            {(user?.role === 'admin' || user?.role === 'zev_owner') && (
                <section className="card">
                    <div className="grid">
                        <PeriodSelector interval={interval} from={period.from} to={period.to} onChange={setPeriod} />
                        <div className="inline-form grid grid-2">
                            <label>
                                <span>{t('pages.dashboard.participant')}</span>
                                <select value={selectedParticipantId} onChange={(e) => setSelectedParticipantId(e.target.value)}>
                                    <option value="">{t('pages.dashboard.allParticipants')}</option>
                                    {summary?.role === 'zev_owner' &&
                                        summary.participant_stats.map((participant) => (
                                            <option key={participant.participant_id} value={participant.participant_id}>
                                                {participant.participant_name || participant.participant_id}
                                            </option>
                                        ))}
                                </select>
                            </label>
                            <label>
                                <span>{t('pages.dashboard.resolution')}</span>
                                <select value={bucket} onChange={(e) => setBucket(e.target.value as 'day' | 'hour' | 'month')}>
                                    <option value="hour">{t('pages.dashboard.hourly')}</option>
                                    <option value="day">{t('pages.dashboard.daily')}</option>
                                    <option value="month">{t('pages.dashboard.monthly')}</option>
                                </select>
                            </label>
                        </div>
                    </div>
                </section>
            )}

            {user?.role === 'participant' && (
                <section className="card">
                    <div className="grid">
                        <PeriodSelector interval={interval} from={period.from} to={period.to} onChange={setPeriod} />
                        <div className="inline-form" style={{ maxWidth: '320px' }}>
                            <label>
                                <span>{t('pages.dashboard.resolution')}</span>
                                <select value={bucket} onChange={(e) => setBucket(e.target.value as 'day' | 'hour' | 'month')}>
                                    <option value="hour">{t('pages.dashboard.hourly')}</option>
                                    <option value="day">{t('pages.dashboard.daily')}</option>
                                    <option value="month">{t('pages.dashboard.monthly')}</option>
                                </select>
                            </label>
                        </div>
                    </div>
                </section>
            )}

            {isZevScopedRole && !selectedZevId && !managedZevLoading && <div className="card">{t('pages.dashboard.noZev')}</div>}
            {isZevScopedRole && selectedZevId && !selectedZev && !managedZevLoading && managedZevs.length > 0 && (
                <div className="card">{t('pages.dashboard.selectZev')}</div>
            )}

            {summaryQuery.isLoading && <PageSkeleton variant="kpiRow" />}
            {summaryQuery.isError && <div className="card error-banner">{t('pages.dashboard.failedAnalytics')}</div>}

            {summary && summary.role === 'zev_owner' && (
                <>
                    {/* Hero + KPI row (spec §5.1): always ZEV-wide, even when a
                        participant drill-down filters the charts below. */}
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
                    {summary.participant_stats.length > 0 && (
                        <EnergyFlowCard
                            totals={summary.zev_totals}
                            participantStats={summary.participant_stats}
                            highlightParticipantId={selectedParticipantId || undefined}
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
                    <ParticipantTableCard
                        participantStats={summary.participant_stats}
                        selectedParticipantId={selectedParticipantId}
                        onSelect={setSelectedParticipantId}
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

            {summary && summary.role === 'participant' && (
                <>
                    <section style={{ display: 'grid', gap: '1rem', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))' }}>
                        <StatCard label={t('pages.dashboard.participantStats.consumedFromZev')} value={dashboardKwhStat(summary.totals.consumed_from_zev_kwh)} />
                        <StatCard label={t('pages.dashboard.participantStats.importedFromGrid')} value={dashboardKwhStat(summary.totals.imported_from_grid_kwh)} />
                        <StatCard label={t('pages.dashboard.participantStats.totalConsumption')} value={dashboardKwhStat(summary.totals.total_consumed_kwh)} />
                        <StatCard
                            label={t('pages.dashboard.participantStats.fromZevShare')}
                            value={participantFromZev ? formatPercent(participantFromZev.pct) : '—'}
                            hint={
                                participantFromZev
                                    ? t('pages.dashboard.hints.fromZevShare', {
                                          zev: formatKwh(participantFromZev.zevKwh, { maxDecimals: 0 }),
                                          total: formatKwh(participantFromZev.totalKwh, { maxDecimals: 0 }),
                                      })
                                    : undefined
                            }
                        />
                    </section>
                    {summary.zev_participant_stats.length > 0 && summary.current_participant_id && (
                        <EnergyFlowCard
                            totals={summary.zev_totals}
                            participantStats={summary.zev_participant_stats}
                            highlightParticipantId={summary.current_participant_id}
                        />
                    )}
                    <ConsumptionSplitCard
                        data={participantTimeline}
                        formatBucketLabel={formatBucketLabel}
                        formatBucketTooltipLabel={formatBucketTooltipLabel}
                        kwhTick={kwhTick}
                    />
                    {hourlyProfileData.length > 0 && (
                        <HourlyProfileCard
                            data={hourlyProfileData}
                            hourlyKwhTick={hourlyKwhTick}
                            hourlyKwhTooltipValue={hourlyKwhTooltipValue}
                        />
                    )}
                    <ParticipantInvoicesCard
                        invoices={participantInvoicesWithPdf}
                        isLoading={invoicesQuery.isLoading}
                        isError={invoicesQuery.isError}
                    />
                </>
            )}
        </div>
    )
}
