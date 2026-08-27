import { useQuery } from '@tanstack/react-query'
import { Tabs } from '@mantine/core'
import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { PageSkeleton } from '../components/PageSkeleton'
import { useTranslation } from 'react-i18next'
import {
    Bar,
    BarChart,
    CartesianGrid,
    Legend,
    ResponsiveContainer,
    Tooltip,
    XAxis,
    YAxis,
} from 'recharts'
import { fetchZevs, fetchMeteringPoints } from '../lib/api/zev'
import { fetchChartData, fetchMeteringDataQualityStatus } from '../lib/api/metering'
import { formatApiError } from '../lib/api/errors'
import { queryKeys } from '../lib/api/queryKeys'
import { PeriodSelector } from '../components/PeriodSelector'
import { RawMeteringTable } from '../components/RawMeteringTable'
import { useAuth } from '../lib/auth'
import { useManagedZev } from '../lib/managedZev'
import {
    type BillingInterval,
    getCurrentBillingPeriod,
} from '../lib/billingPeriod'
import { useAppSettings } from '../lib/appSettings'
import { formatMeteringBucketLabel } from '../lib/meteringLabels'
import type { AppSettings, ChartDataPoint } from '../types/api'
import { CHART_GRID, CONS_COLORS, NEGATIVE_COLOR, PROD_COLORS } from '../lib/chartTokens'

// ── Summary stat card ─────────────────────────────────────────────────────────

function StatBadge({ label, value, color }: { label: string; value: string; color: string }) {
    return (
        <div
            style={{
                background: 'var(--surface-card)',
                border: `2px solid ${color}`,
                borderRadius: 8,
                padding: '0.6rem 1.2rem',
                minWidth: 140,
            }}
        >
            <p className="muted" style={{ margin: 0, fontSize: '0.78rem' }}>{label}</p>
            <p style={{ margin: 0, fontWeight: 700, fontSize: '1.15rem', color }}>{value}</p>
        </div>
    )
}

// ── Custom Tooltip ────────────────────────────────────────────────────────────

function CustomTooltip({
    active,
    payload,
    label,
    resolution,
    settings,
}: {
    active?: boolean
    payload?: Array<{ name: string; value: number; color: string }>
    label?: string
    resolution: 'day' | 'hour' | 'month'
    settings: AppSettings
}) {
    if (!active || !payload?.length || !label) return null
    return (
        <div
            style={{
                background: 'var(--surface-card)',
                border: '1px solid var(--border-default)',
                borderRadius: 6,
                padding: '0.6rem 0.9rem',
                fontSize: '0.85rem',
                boxShadow: '0 2px 8px rgba(0,0,0,0.1)',
            }}
        >
            <p style={{ margin: '0 0 4px', fontWeight: 600 }}>{formatMeteringBucketLabel(label, resolution, settings)}</p>
            {payload.map((entry) => (
                <p key={entry.name} style={{ margin: '2px 0', color: entry.color }}>
                    {entry.name}: <strong>{entry.value.toFixed(3)} kWh</strong>
                </p>
            ))}
        </div>
    )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export function MeteringChartPage() {
    const [searchParams, setSearchParams] = useSearchParams()
    const { t } = useTranslation()
    const { user } = useAuth()
    const { settings } = useAppSettings()
    const { selectedZevId, selectedZev } = useManagedZev()
    const isManagedScope = user?.role === 'admin' || user?.role === 'zev_owner'
    const interval: BillingInterval = (selectedZev?.billing_interval as BillingInterval) ?? 'monthly'

    const activeTab = searchParams.get('tab') === 'quality' ? 'quality' : 'chart'

    // Controlled state
    const [selectedMpId, setSelectedMpId] = useState<string>(searchParams.get('metering_point') ?? '')
    const [period, setPeriod] = useState<{ from: string; to: string }>(() => getCurrentBillingPeriod(interval))
    const [bucket, setBucket] = useState<'day' | 'hour' | 'month'>('day')

    useEffect(() => {
        setPeriod(getCurrentBillingPeriod(interval))
    }, [selectedZevId, interval])

    // Data queries
    const zevsQuery = useQuery({ queryKey: queryKeys.zev.list(), queryFn: fetchZevs })
    const mpQuery = useQuery({ queryKey: queryKeys.metering.points(selectedZevId || undefined), queryFn: fetchMeteringPoints })

    const chartQuery = useQuery({
        queryKey: queryKeys.metering.chartData(selectedMpId, period.from, period.to, bucket),
        queryFn: () =>
            fetchChartData({ meteringPoint: selectedMpId, dateFrom: period.from, dateTo: period.to, bucket }),
        enabled: !!selectedMpId,
    })

    const qualityQuery = useQuery({
        queryKey: queryKeys.metering.qualityStatus(period.from, period.to, isManagedScope ? selectedZevId || undefined : undefined, selectedMpId || undefined),
        queryFn: () =>
            fetchMeteringDataQualityStatus({
                dateFrom: period.from,
                dateTo: period.to,
                zevId: selectedZevId && isManagedScope ? selectedZevId : undefined,
                meteringPointId: selectedMpId || undefined,
            }),
        enabled: true,
    })

    const meteringPoints = (mpQuery.data ?? []).filter(
        (meteringPoint) => !isManagedScope || !selectedZevId || meteringPoint.zev === selectedZevId,
    )
    const zevNameById = new Map((zevsQuery.data ?? []).map((z) => [z.id, z.name]))

    const data: ChartDataPoint[] = chartQuery.data ?? []

    const totalIn = data.reduce((sum, d) => sum + d.in_kwh, 0)
    const totalOut = data.reduce((sum, d) => sum + d.out_kwh, 0)
    const hasOut = data.some((d) => d.out_kwh > 0)

    // Sync the selected metering point to the URL
    const handleMpChange = useCallback((id: string) => {
        setSelectedMpId(id)
        const next = new URLSearchParams(searchParams)
        if (id) {
            next.set('metering_point', id)
        } else {
            next.delete('metering_point')
        }
        setSearchParams(next, { replace: true })
    }, [searchParams, setSearchParams])

    // ?tab=quality makes the quality view shareable
    const handleTabChange = (value: string | null) => {
        const next = new URLSearchParams(searchParams)
        if (value === 'quality') {
            next.set('tab', 'quality')
        } else {
            next.delete('tab')
        }
        setSearchParams(next, { replace: true })
    }

    const selectedMp = meteringPoints.find((m) => m.id === selectedMpId)

    useEffect(() => {
        if (!isManagedScope || !selectedZevId) {
            return
        }
        if (!selectedMpId) {
            return
        }
        const stillVisible = meteringPoints.some((meteringPoint) => meteringPoint.id === selectedMpId)
        if (!stillVisible) {
            handleMpChange('')
        }
    }, [isManagedScope, selectedZevId, selectedMpId, meteringPoints, handleMpChange])

    const tickFormatter = (value: string) => formatMeteringBucketLabel(value, bucket, settings)

    return (
        <div className="page-stack">
            <header>
                <h2>{t('pages.meteringData.title')}</h2>
                <p className="muted">{t('pages.meteringData.description')}</p>
            </header>

            <Tabs
                classNames={{ root: 'app-tabs', list: 'app-tabs-list', tab: 'app-tabs-tab' }}
                value={activeTab}
                keepMounted={false}
                onChange={handleTabChange}
            >
                <Tabs.List aria-label={t('pages.meteringData.title')}>
                    <Tabs.Tab value="chart">{t('nav.meteringData')}</Tabs.Tab>
                    <Tabs.Tab value="quality">{t('nav.meteringDataQuality')}</Tabs.Tab>
                </Tabs.List>

                <div
                    className="card"
                    style={{
                        display: 'grid',
                        gap: '1rem',
                    }}
                >
                    <PeriodSelector
                        interval={interval}
                        from={period.from}
                        to={period.to}
                        onChange={setPeriod}
                    />

                    {activeTab === 'chart' && (
                        <div
                            className="inline-form"
                            style={{
                                display: 'grid',
                                gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
                                gap: '1rem',
                                alignItems: 'end',
                            }}
                        >
                            <label>
                                <span>{t('pages.meteringData.meteringPoint')}</span>
                                <select
                                    value={selectedMpId}
                                    onChange={(e) => handleMpChange(e.target.value)}
                                >
                                    <option value="">{t('pages.meteringData.selectMeteringPoint')}</option>
                                    {meteringPoints.map((mp) => (
                                        <option key={mp.id} value={mp.id}>
                                            {mp.meter_id}
                                            {zevNameById.has(mp.zev) ? ` (${zevNameById.get(mp.zev)})` : ''}
                                        </option>
                                    ))}
                                </select>
                            </label>

                            <label>
                                <span>{t('pages.meteringData.resolution')}</span>
                                <select
                                    value={bucket}
                                    onChange={(e) => setBucket(e.target.value as 'day' | 'hour' | 'month')}
                                >
                                    <option value="hour">{t('pages.meteringData.resolutions.hour')}</option>
                                    <option value="day">{t('pages.meteringData.resolutions.day')}</option>
                                    <option value="month">{t('pages.meteringData.resolutions.month')}</option>
                                </select>
                            </label>
                        </div>
                    )}

                    {activeTab === 'quality' && (
                        <div
                            className="inline-form"
                            style={{
                                display: 'grid',
                                gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
                                gap: '1rem',
                                alignItems: 'end',
                            }}
                        >
                            <label>
                                <span>{t('pages.meteringData.meterIdOptional')}</span>
                                <select
                                    value={selectedMpId}
                                    onChange={(e) => handleMpChange(e.target.value)}
                                >
                                    <option value="">{t('pages.meteringData.allMeteringPoints')}</option>
                                    {meteringPoints.map((mp) => (
                                        <option key={mp.id} value={mp.id}>
                                            {mp.meter_id}
                                            {zevNameById.has(mp.zev) ? ` (${zevNameById.get(mp.zev)})` : ''}
                                        </option>
                                    ))}
                                </select>
                            </label>
                        </div>
                    )}
                </div>

                <Tabs.Panel value="chart">
                    <div className="page-stack">
                        {!selectedMpId && (
                            <div className="card" style={{ textAlign: 'center', padding: '3rem 1rem', color: 'var(--text-muted)' }}>
                                {t('pages.meteringData.noPointSelected')}
                            </div>
                        )}

                        {selectedMpId && chartQuery.isLoading && (
                            <div className="card" style={{ textAlign: 'center', padding: '2rem' }}>
                                {t('pages.meteringData.loadingChart')}
                            </div>
                        )}
                        {selectedMpId && chartQuery.isError && (
                            <div className="card error-banner">{t('pages.meteringData.chartError')}</div>
                        )}

                        {selectedMpId && chartQuery.isSuccess && (
                            <>
                                <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap' }}>
                                    {selectedMp && (
                                        <StatBadge
                                            label={t('pages.meteringData.stats.meterId')}
                                            value={selectedMp.meter_id}
                                            color="var(--text-primary)"
                                        />
                                    )}
                                    <StatBadge
                                        label={t('pages.meteringData.stats.totalConsumption')}
                                        value={`${totalIn.toFixed(2)} kWh`}
                                        color={PROD_COLORS[0]}
                                    />
                                    {hasOut && (
                                        <StatBadge
                                            label={t('pages.meteringData.stats.totalFeedIn')}
                                            value={`${totalOut.toFixed(2)} kWh`}
                                            color={CONS_COLORS[0]}
                                        />
                                    )}
                                    <StatBadge
                                        label={t('pages.meteringData.stats.dataPoints')}
                                        value={String(data.length)}
                                        color="var(--text-muted)"
                                    />
                                </div>

                                {data.length === 0 ? (
                                    <div className="card" style={{ textAlign: 'center', padding: '2rem', color: 'var(--text-muted)' }}>
                                        {t('pages.meteringData.noReadings')}
                                    </div>
                                ) : (
                                    <div className="card" style={{ padding: '1.5rem' }}>
                                        <ResponsiveContainer width="100%" height={380}>
                                            <BarChart
                                                data={data}
                                                margin={{ top: 8, right: 16, left: 0, bottom: 8 }}
                                                barCategoryGap="20%"
                                            >
                                                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                                                <XAxis
                                                    dataKey="bucket"
                                                    tickFormatter={tickFormatter}
                                                    tick={{ fontSize: 11 }}
                                                    tickLine={false}
                                                    interval="preserveStartEnd"
                                                />
                                                <YAxis
                                                    unit=" kWh"
                                                    tick={{ fontSize: 11 }}
                                                    tickLine={false}
                                                    axisLine={false}
                                                    width={72}
                                                />
                                                <Tooltip
                                                    content={<CustomTooltip resolution={bucket} settings={settings} />}
                                                />
                                                <Legend />
                                                <Bar
                                                    dataKey="in_kwh"
                                                    name={t('pages.meteringData.series.consumption')}
                                                    fill={PROD_COLORS[0]}
                                                    radius={[3, 3, 0, 0]}
                                                    maxBarSize={48}
                                                />
                                                {hasOut && (
                                                    <Bar
                                                        dataKey="out_kwh"
                                                        name={t('pages.meteringData.series.feedIn')}
                                                        fill={CONS_COLORS[0]}
                                                        radius={[3, 3, 0, 0]}
                                                        maxBarSize={48}
                                                    />
                                                )}
                                            </BarChart>
                                        </ResponsiveContainer>
                                    </div>
                                )}

                                <RawMeteringTable
                                    meteringPointId={selectedMpId}
                                    dateFrom={period.from}
                                    dateTo={period.to}
                                    hasOut={hasOut}
                                />
                            </>
                        )}
                    </div>
                </Tabs.Panel>

                <Tabs.Panel value="quality">
                    <div className="page-stack">
                        {qualityQuery.isLoading && <PageSkeleton variant="table" />}
                        {qualityQuery.isError && (
                            <div className="card error-banner">{formatApiError(qualityQuery.error as any)}</div>
                        )}
                        {qualityQuery.isSuccess && qualityQuery.data && (
                            <>
                                {qualityQuery.data.metering_points.length === 0 ? (
                                    <div className="card" style={{ textAlign: 'center', padding: '2rem', color: 'var(--text-muted)' }}>
                                        {t('meteringDataQuality.noData')}
                                    </div>
                                ) : (
                                    <>
                                        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '1rem', marginBottom: '1.5rem' }}>
                                            <div style={{ background: 'var(--success-100)', border: '1px solid var(--success-200)', borderRadius: '8px', padding: '1rem', textAlign: 'center' }}>
                                                <div style={{ fontSize: '1.5rem', fontWeight: 'bold', color: 'var(--success-700)' }}>
                                                    {qualityQuery.data.metering_points.filter((mp) => mp.severity === 'green').length}
                                                </div>
                                                <div style={{ fontSize: '0.875rem', color: 'var(--brand-mid)' }}>{t('meteringDataQuality.severityGreen')}</div>
                                            </div>
                                            <div style={{ background: 'var(--warning-100)', border: '1px solid var(--warning-200)', borderRadius: '8px', padding: '1rem', textAlign: 'center' }}>
                                                <div style={{ fontSize: '1.5rem', fontWeight: 'bold', color: 'var(--warning-800)' }}>
                                                    {qualityQuery.data.metering_points.filter((mp) => mp.severity === 'yellow').length}
                                                </div>
                                                <div style={{ fontSize: '0.875rem', color: 'var(--warning-800)' }}>{t('meteringDataQuality.severityYellow')}</div>
                                            </div>
                                            <div style={{ background: 'var(--danger-100)', border: '1px solid var(--danger-300)', borderRadius: '8px', padding: '1rem', textAlign: 'center' }}>
                                                <div style={{ fontSize: '1.5rem', fontWeight: 'bold', color: 'var(--danger-700)' }}>
                                                    {qualityQuery.data.metering_points.filter((mp) => mp.severity === 'red').length}
                                                </div>
                                                <div style={{ fontSize: '0.875rem', color: 'var(--danger-600)' }}>{t('meteringDataQuality.severityRed')}</div>
                                            </div>
                                        </div>

                                        <div className="table-card">
                                            <table>
                                                <thead>
                                                    <tr>
                                                        <th>{t('meteringDataQuality.meterId')}</th>
                                                        <th>{t('meteringDataQuality.participant')}</th>
                                                        <th>{t('meteringDataQuality.dataCompleteness')}</th>
                                                        <th>{t('meteringDataQuality.status')}</th>
                                                        <th>{t('meteringDataQuality.gaps')}</th>
                                                    </tr>
                                                </thead>
                                                <tbody>
                                                    {qualityQuery.data.metering_points.map((mp) => (
                                                        <tr key={mp.id}>
                                                            <td style={{ fontFamily: 'monospace', fontSize: '0.9em' }}>{mp.meter_id}</td>
                                                            <td>{mp.participant_name}</td>
                                                            <td>
                                                                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                                                    <div style={{ width: '80px', height: '20px', background: 'var(--line-subtle)', borderRadius: '4px', overflow: 'hidden' }}>
                                                                        <div
                                                                            style={{
                                                                                height: '100%',
                                                                                background:
                                                                                    mp.severity === 'green'
                                                                                        ? PROD_COLORS[0]
                                                                                        : mp.severity === 'yellow'
                                                                                          ? CHART_GRID
                                                                                          : NEGATIVE_COLOR,
                                                                                width: `${mp.data_completeness}%`,
                                                                            }}
                                                                        />
                                                                    </div>
                                                                    <span style={{ fontSize: '0.875rem', fontWeight: 'bold' }}>{mp.data_completeness}%</span>
                                                                </div>
                                                            </td>
                                                            <td>
                                                                <span
                                                                    style={{
                                                                        display: 'inline-block',
                                                                        padding: '0.25rem 0.75rem',
                                                                        borderRadius: '4px',
                                                                        fontSize: '0.875rem',
                                                                        fontWeight: 'bold',
                                                                        background:
                                                                            mp.severity === 'green'
                                                                                        ? 'var(--success-100)'
                                                                                        : mp.severity === 'yellow'
                                                                                          ? 'var(--warning-100)'
                                                                                          : 'var(--danger-100)',
                                                                        color:
                                                                            mp.severity === 'green'
                                                                                        ? 'var(--success-700)'
                                                                                        : mp.severity === 'yellow'
                                                                                          ? 'var(--warning-800)'
                                                                                          : 'var(--danger-700)',
                                                                    }}
                                                                >
                                                                    {t(`meteringDataQuality.severity${mp.severity.charAt(0).toUpperCase() + mp.severity.slice(1)}`)}
                                                                </span>
                                                                {mp.assignment_overlap && (
                                                                    <div className="metering-dq-warning">
                                                                        {t('meteringDataQuality.assignmentOverlapWarning')}
                                                                    </div>
                                                                )}
                                                                {mp.unassigned_readings > 0 && (
                                                                    <div className="metering-dq-warning">
                                                                        {t('meteringDataQuality.unassignedWarning', { readings: mp.unassigned_readings, days: mp.unassigned_days })}
                                                                    </div>
                                                                )}
                                                            </td>
                                                            <td style={{ fontSize: '0.875rem' }}>
                                                                {mp.gaps.length === 0 ? (
                                                                    <span style={{ color: 'var(--success-600)' }}>{t('meteringDataQuality.noGaps')}</span>
                                                                ) : (
                                                                    <div>
                                                                        {mp.gaps.slice(0, 1).map((gap, idx) => (
                                                                            <div key={idx} style={{ color: 'var(--text-body)' }}>
                                                                                {gap.start_date === gap.end_date ? (
                                                                                    <>{gap.start_date}</>
                                                                                ) : (
                                                                                    <>
                                                                                        {gap.start_date} → {gap.end_date}
                                                                                    </>
                                                                                )}
                                                                            </div>
                                                                        ))}
                                                                        {mp.gaps.length > 1 && (
                                                                            <div style={{ color: 'var(--text-muted)', fontSize: '0.8em' }}>
                                                                                +{mp.gaps.length - 1} {t('meteringDataQuality.moreGaps')}
                                                                            </div>
                                                                        )}
                                                                    </div>
                                                                )}
                                                            </td>
                                                        </tr>
                                                    ))}
                                                </tbody>
                                            </table>
                                        </div>
                                    </>
                                )}
                            </>
                        )}
                    </div>
                </Tabs.Panel>
            </Tabs>
        </div>
    )
}
