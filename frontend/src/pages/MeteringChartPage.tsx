import { useQuery } from '@tanstack/react-query'
import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
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
import { fetchChartData, fetchMeteringPoints, fetchRawMeteringData, fetchZevs, api, formatApiError } from '../lib/api'
import { BillingPeriodSelector } from '../components/BillingPeriodSelector'
import { useAuth } from '../lib/auth'
import { useManagedZev } from '../lib/managedZev'
import {
    type BillingInterval,
    getCurrentBillingPeriod,
} from '../lib/billingPeriod'
import { formatDateTime, formatMonthYear, formatShortDate, useAppSettings } from '../lib/appSettings'
import type { ChartDataPoint, RawMeteringDailyRow, RawMeteringReading, DataQualityStatusResponse } from '../types/api'

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatTimeOnly(ts: string): string {
    const d = new Date(ts)
    if (isNaN(d.getTime())) return ts
    // Use UTC so display matches the imported CSV (importer stamps naive timestamps as UTC)
    return `${String(d.getUTCHours()).padStart(2, '0')}:${String(d.getUTCMinutes()).padStart(2, '0')}`
}

function groupReadingsByHour(readings: RawMeteringReading[]): { hour: string; items: RawMeteringReading[] }[] {
    const map = new Map<string, RawMeteringReading[]>()
    for (const r of readings) {
        const d = new Date(r.timestamp)
        // Use UTC hours to stay consistent with how the importer stored the data
        const hour = `${String(d.getUTCHours()).padStart(2, '0')}:00`
        const bucket = map.get(hour) ?? []
        bucket.push(r)
        map.set(hour, bucket)
    }
    return Array.from(map.entries())
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([hour, items]) => ({ hour, items }))
}

function formatBucketLabel(
    bucket: string,
    resolution: 'day' | 'hour' | 'month',
    formatters: {
        shortDate: (value: string) => string
        dateTime: (value: string) => string
        monthYear: (value: string) => string
    },
): string {
    try {
        if (resolution === 'hour') {
            return formatters.dateTime(bucket)
        }
        if (resolution === 'month') {
            return formatters.monthYear(bucket)
        }
        return formatters.shortDate(bucket)
    } catch {
        return bucket
    }
}

// ── Summary stat card ─────────────────────────────────────────────────────────

function StatBadge({ label, value, color }: { label: string; value: string; color: string }) {
    return (
        <div
            style={{
                background: 'var(--color-surface, #fff)',
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
    formatters,
}: {
    active?: boolean
    payload?: Array<{ name: string; value: number; color: string }>
    label?: string
    resolution: 'day' | 'hour' | 'month'
    formatters: {
        shortDate: (value: string) => string
        dateTime: (value: string) => string
        monthYear: (value: string) => string
    }
}) {
    if (!active || !payload?.length || !label) return null
    return (
        <div
            style={{
                background: 'var(--color-surface, #fff)',
                border: '1px solid var(--color-border, #e0e0e0)',
                borderRadius: 6,
                padding: '0.6rem 0.9rem',
                fontSize: '0.85rem',
                boxShadow: '0 2px 8px rgba(0,0,0,0.1)',
            }}
        >
            <p style={{ margin: '0 0 4px', fontWeight: 600 }}>{formatBucketLabel(label, resolution, formatters)}</p>
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

    // Tab state
    const [activeTab, setActiveTab] = useState<'chart' | 'quality'>('chart')

    // Controlled state
    const [selectedMpId, setSelectedMpId] = useState<string>(searchParams.get('metering_point') ?? '')
    const [period, setPeriod] = useState<{ from: string; to: string }>(() => getCurrentBillingPeriod(interval))
    const [bucket, setBucket] = useState<'day' | 'hour' | 'month'>('day')

    useEffect(() => {
        setPeriod(getCurrentBillingPeriod(interval))
    }, [selectedZevId, interval])

    // Data queries
    const zevsQuery = useQuery({ queryKey: ['zevs'], queryFn: fetchZevs })
    const mpQuery = useQuery({ queryKey: ['metering-points'], queryFn: fetchMeteringPoints })

    const chartQuery = useQuery({
        queryKey: ['chart-data', selectedMpId, period.from, period.to, bucket],
        queryFn: () =>
            fetchChartData({ meteringPoint: selectedMpId, dateFrom: period.from, dateTo: period.to, bucket }),
        enabled: !!selectedMpId,
    })

    const rawDataQuery = useQuery({
        queryKey: ['raw-metering-data', selectedMpId, period.from, period.to],
        queryFn: () =>
            fetchRawMeteringData({ meteringPoint: selectedMpId, dateFrom: period.from, dateTo: period.to }),
        enabled: !!selectedMpId,
    })

    const qualityQuery = useQuery({
        queryKey: ['metering-data-quality', period.from, period.to, selectedZevId],
        queryFn: async () => {
            const params = new URLSearchParams({
                date_from: period.from,
                date_to: period.to,
                ...(selectedZevId && isManagedScope ? { zev_id: selectedZevId } : {}),
            })
            const { data } = await api.get<DataQualityStatusResponse>(
                `/metering/readings/data-quality-status/?${params}`
            )
            return data
        },
        enabled: true,
    })

    const meteringPoints = (mpQuery.data?.results ?? []).filter(
        (meteringPoint) => !isManagedScope || !selectedZevId || meteringPoint.zev === selectedZevId,
    )
    const zevNameById = new Map((zevsQuery.data?.results ?? []).map((z) => [z.id, z.name]))

    const data: ChartDataPoint[] = chartQuery.data ?? []
    const rawDailyRows: RawMeteringDailyRow[] = rawDataQuery.data ?? []

    const totalIn = data.reduce((sum, d) => sum + d.in_kwh, 0)
    const totalOut = data.reduce((sum, d) => sum + d.out_kwh, 0)
    const hasOut = data.some((d) => d.out_kwh > 0)

    // Sync the selected MP to the URL
    const handleMpChange = useCallback((id: string) => {
        setSelectedMpId(id)
        if (id) {
            setSearchParams({ metering_point: id }, { replace: true })
        } else {
            setSearchParams({}, { replace: true })
        }
    }, [setSearchParams])

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

    const bucketFormatters = {
        shortDate: (value: string) => formatShortDate(value, settings),
        dateTime: (value: string) => formatDateTime(value, settings),
        monthYear: (value: string) => formatMonthYear(value),
    }

    const tickFormatter = (value: string) => formatBucketLabel(value, bucket, bucketFormatters)

    return (
        <div className="page-stack">
            <header>
                <h2>Metering Data</h2>
                <p className="muted">Visualize energy readings and monitor data quality per metering point.</p>
            </header>

            {/* ── Tabs ──────────────────────────────────────────────────────────── */}
            <div style={{ display: 'flex', gap: '1rem', borderBottom: '1px solid var(--color-border, #e5e7eb)', marginBottom: '1.5rem' }}>
                <button
                    onClick={() => setActiveTab('chart')}
                    style={{
                        background: activeTab === 'chart' ? 'transparent' : 'transparent',
                        color: activeTab === 'chart' ? 'var(--color-text, #000)' : 'var(--color-text-muted, #888)',
                        borderBottom: activeTab === 'chart' ? '2px solid var(--color-primary, #0066cc)' : 'none',
                        padding: '0.75rem 1rem',
                        fontSize: '1rem',
                        fontWeight: activeTab === 'chart' ? 600 : 400,
                        cursor: 'pointer',
                        border: 'none',
                    }}
                >
                    {t('nav.meteringData')}
                </button>
                <button
                    onClick={() => setActiveTab('quality')}
                    style={{
                        background: activeTab === 'quality' ? 'transparent' : 'transparent',
                        color: activeTab === 'quality' ? 'var(--color-text, #000)' : 'var(--color-text-muted, #888)',
                        borderBottom: activeTab === 'quality' ? '2px solid var(--color-primary, #0066cc)' : 'none',
                        padding: '0.75rem 1rem',
                        fontSize: '1rem',
                        fontWeight: activeTab === 'quality' ? 600 : 400,
                        cursor: 'pointer',
                        border: 'none',
                    }}
                >
                    {t('nav.meteringDataQuality')}
                </button>
            </div>

            {/* ── Controls ──────────────────────────────────────────────────────── */}
            <div
                className="card"
                style={{
                    display: 'grid',
                    gap: '1rem',
                }}
            >
                <BillingPeriodSelector
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
                            <span>Metering Point *</span>
                            <select
                                value={selectedMpId}
                                onChange={(e) => handleMpChange(e.target.value)}
                            >
                                <option value="">Select metering point…</option>
                                {meteringPoints.map((mp) => (
                                    <option key={mp.id} value={mp.id}>
                                        {mp.meter_id}
                                        {zevNameById.has(mp.zev) ? ` (${zevNameById.get(mp.zev)})` : ''}
                                    </option>
                                ))}
                            </select>
                        </label>

                        <label>
                            <span>Resolution</span>
                            <select
                                value={bucket}
                                onChange={(e) => setBucket(e.target.value as 'day' | 'hour' | 'month')}
                            >
                                <option value="hour">Hourly</option>
                                <option value="day">Daily</option>
                                <option value="month">Monthly</option>
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
                            <span>{t('meteringDataQuality.meterId')} (optional)</span>
                            <select
                                value={selectedMpId}
                                onChange={(e) => handleMpChange(e.target.value)}
                            >
                                <option value="">All metering points…</option>
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

            {/* ── Chart Tab ─────────────────────────────────────────────────────── */}
            {activeTab === 'chart' && (
                <>
                    {/* ── No selection placeholder ──────────────────────────────────────── */}
                    {!selectedMpId && (
                        <div className="card" style={{ textAlign: 'center', padding: '3rem 1rem', color: 'var(--color-text-muted, #888)' }}>
                            Select a metering point above to view its energy readings.
                        </div>
                    )}

                    {/* ── Loading / error ───────────────────────────────────────────────── */}
                    {selectedMpId && chartQuery.isLoading && (
                        <div className="card" style={{ textAlign: 'center', padding: '2rem' }}>
                            Loading chart data…
                        </div>
                    )}
                    {selectedMpId && chartQuery.isError && (
                        <div className="card error-banner">Failed to load chart data.</div>
                    )}
                    {selectedMpId && rawDataQuery.isError && (
                        <div className="card error-banner">Failed to load raw metering data table.</div>
                    )}

                    {/* ── Results ───────────────────────────────────────────────────────── */}
                    {selectedMpId && chartQuery.isSuccess && (
                        <>
                            {/* Summary stats */}
                            <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap' }}>
                                {selectedMp && (
                                    <StatBadge
                                        label="Meter ID"
                                        value={selectedMp.meter_id}
                                        color="var(--color-text, #222)"
                                    />
                                )}
                                <StatBadge
                                    label="Total Consumption (IN)"
                                    value={`${totalIn.toFixed(2)} kWh`}
                                    color="#059669"
                                />
                                {hasOut && (
                                    <StatBadge
                                        label="Total Feed-in (OUT)"
                                        value={`${totalOut.toFixed(2)} kWh`}
                                        color="#0284c7"
                                    />
                                )}
                                <StatBadge
                                    label="Data points"
                                    value={String(data.length)}
                                    color="var(--color-text-muted, #888)"
                                />
                            </div>

                            {data.length === 0 ? (
                                <div className="card" style={{ textAlign: 'center', padding: '2rem', color: 'var(--color-text-muted, #888)' }}>
                                    No readings found for the selected period and metering point.
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
                                                content={<CustomTooltip resolution={bucket} formatters={bucketFormatters} />}
                                            />
                                            <Legend />
                                            <Bar
                                                dataKey="in_kwh"
                                                name="Consumption (IN)"
                                                fill="#059669"
                                                radius={[3, 3, 0, 0]}
                                                maxBarSize={48}
                                            />
                                            {hasOut && (
                                                <Bar
                                                    dataKey="out_kwh"
                                                    name="Feed-in (OUT)"
                                                    fill="#0284c7"
                                                    radius={[3, 3, 0, 0]}
                                                    maxBarSize={48}
                                                />
                                            )}
                                        </BarChart>
                                    </ResponsiveContainer>
                                </div>
                            )}

                            <div className="table-card">
                                <h3>Raw Data by Day</h3>
                                <p className="muted" style={{ marginTop: 0 }}>
                                    One row per day in the selected period. Each row contains all raw readings for that day.
                                </p>

                                {rawDataQuery.isLoading ? (
                                    <div style={{ padding: '1rem 0' }}>Loading raw data table…</div>
                                ) : rawDailyRows.length === 0 ? (
                                    <div style={{ padding: '1rem 0' }} className="muted">
                                        No raw metering readings found for the selected period.
                                    </div>
                                ) : (
                                    <table>
                                        <thead>
                                            <tr>
                                                <th>Day</th>
                                                <th>IN total (kWh)</th>
                                                <th>OUT total (kWh)</th>
                                                <th>Raw readings</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {rawDailyRows.map((dayRow) => (
                                                <tr key={dayRow.date}>
                                                    <td>{formatShortDate(dayRow.date, settings)}</td>
                                                    <td>{dayRow.in_kwh.toFixed(4)}</td>
                                                    <td>{dayRow.out_kwh.toFixed(4)}</td>
                                                    <td style={{ padding: 0 }}>
                                                        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.85em' }}>
                                                            <thead>
                                                                <tr>
                                                                    <th style={{ textAlign: 'left', padding: '0.2rem 0.5rem', color: 'var(--color-muted)' }}>Time</th>
                                                                    <th style={{ textAlign: 'left', padding: '0.2rem 0.5rem', color: 'var(--color-muted)' }}>Dir</th>
                                                                    <th style={{ textAlign: 'right', padding: '0.2rem 0.5rem', color: 'var(--color-muted)' }}>kWh</th>
                                                                </tr>
                                                            </thead>
                                                            {groupReadingsByHour(dayRow.readings).map(({ hour, items }) => (
                                                                <tbody key={hour}>
                                                                    <tr>
                                                                        <td
                                                                            colSpan={3}
                                                                            style={{
                                                                                padding: '0.2rem 0.5rem',
                                                                                fontWeight: 600,
                                                                                fontSize: '0.8em',
                                                                                color: 'var(--color-muted)',
                                                                                borderTop: '1px solid var(--color-border, #e5e7eb)',
                                                                                background: 'var(--color-surface-subtle, #f9fafb)',
                                                                            }}
                                                                        >
                                                                            {hour}&nbsp;–&nbsp;{String(Number(hour.split(':')[0]) + 1).padStart(2, '0')}:00
                                                                        </td>
                                                                    </tr>
                                                                    {items.map((r, i) => (
                                                                        <tr key={`${r.timestamp}-${r.direction}-${i}`}>
                                                                            <td style={{ padding: '0.15rem 0.5rem', fontVariantNumeric: 'tabular-nums' }}>{formatTimeOnly(r.timestamp)}</td>
                                                                            <td style={{ padding: '0.15rem 0.5rem' }}>{r.direction.toUpperCase()}</td>
                                                                            <td style={{ padding: '0.15rem 0.5rem', textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{r.energy_kwh.toFixed(4)}</td>
                                                                        </tr>
                                                                    ))}
                                                                </tbody>
                                                            ))}
                                                        </table>
                                                    </td>
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                )}
                            </div>
                        </>
                    )}
                </>
            )}

            {/* ── Data Quality Tab ──────────────────────────────────────────────── */}
            {activeTab === 'quality' && (
                <>
                    {qualityQuery.isLoading && (
                        <div className="card" style={{ textAlign: 'center', padding: '2rem' }}>
                            {t('common.loading')}
                        </div>
                    )}
                    {qualityQuery.isError && (
                        <div className="card error-banner">{formatApiError(qualityQuery.error as any)}</div>
                    )}
                    {qualityQuery.isSuccess && qualityQuery.data && (
                        <>
                            {qualityQuery.data.metering_points.length === 0 ? (
                                <div className="card" style={{ textAlign: 'center', padding: '2rem', color: 'var(--color-text-muted, #888)' }}>
                                    {t('meteringDataQuality.noData')}
                                </div>
                            ) : (
                                <>
                                    {/* Summary cards */}
                                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '1rem', marginBottom: '1.5rem' }}>
                                        <div style={{ background: '#dcfce7', border: '1px solid #86efac', borderRadius: '8px', padding: '1rem', textAlign: 'center' }}>
                                            <div style={{ fontSize: '1.5rem', fontWeight: 'bold', color: '#166534' }}>
                                                {qualityQuery.data.metering_points.filter((mp) => mp.severity === 'green').length}
                                            </div>
                                            <div style={{ fontSize: '0.875rem', color: '#34d399' }}>{t('meteringDataQuality.severityGreen')}</div>
                                        </div>
                                        <div style={{ background: '#fef3c7', border: '1px solid #fcd34d', borderRadius: '8px', padding: '1rem', textAlign: 'center' }}>
                                            <div style={{ fontSize: '1.5rem', fontWeight: 'bold', color: '#854d0e' }}>
                                                {qualityQuery.data.metering_points.filter((mp) => mp.severity === 'yellow').length}
                                            </div>
                                            <div style={{ fontSize: '0.875rem', color: '#f59e0b' }}>{t('meteringDataQuality.severityYellow')}</div>
                                        </div>
                                        <div style={{ background: '#fee2e2', border: '1px solid #fca5a5', borderRadius: '8px', padding: '1rem', textAlign: 'center' }}>
                                            <div style={{ fontSize: '1.5rem', fontWeight: 'bold', color: '#7f1d1d' }}>
                                                {qualityQuery.data.metering_points.filter((mp) => mp.severity === 'red').length}
                                            </div>
                                            <div style={{ fontSize: '0.875rem', color: '#ef4444' }}>{t('meteringDataQuality.severityRed')}</div>
                                        </div>
                                    </div>

                                    {/* Quality table */}
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
                                                                <div style={{ width: '80px', height: '20px', background: '#f0f0f0', borderRadius: '4px', overflow: 'hidden' }}>
                                                                    <div
                                                                        style={{
                                                                            height: '100%',
                                                                            background:
                                                                                mp.severity === 'green' ? '#10b981' :
                                                                                mp.severity === 'yellow' ? '#f59e0b' :
                                                                                '#ef4444',
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
                                                                        mp.severity === 'green' ? '#dcfce7' :
                                                                        mp.severity === 'yellow' ? '#fef3c7' :
                                                                        '#fee2e2',
                                                                    color:
                                                                        mp.severity === 'green' ? '#166534' :
                                                                        mp.severity === 'yellow' ? '#854d0e' :
                                                                        '#7f1d1d',
                                                                }}
                                                            >
                                                                {t(`meteringDataQuality.severity${mp.severity.charAt(0).toUpperCase() + mp.severity.slice(1)}`)}
                                                            </span>
                                                        </td>
                                                        <td style={{ fontSize: '0.875rem' }}>
                                                            {mp.gaps.length === 0 ? (
                                                                <span style={{ color: '#10b981' }}>{t('meteringDataQuality.noGaps')}</span>
                                                            ) : (
                                                                <div>
                                                                    {mp.gaps.slice(0, 1).map((gap, idx) => (
                                                                        <div key={idx} style={{ color: '#666' }}>
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
                                                                        <div style={{ color: '#999', fontSize: '0.8em' }}>
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
                </>
            )}
        </div>
    )
}
