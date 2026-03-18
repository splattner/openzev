import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
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
import { fetchChartData, fetchMeteringPoints, fetchZevs } from '../lib/api'
import { DateRangeShortcutPicker } from '../components/DateRangeShortcutPicker'
import { useAuth } from '../lib/auth'
import { useManagedZev } from '../lib/managedZev'
import {
    daysAgoIso,
    todayIso,
} from '../lib/dateRangePresets'
import { formatDateTime, formatMonthYear, formatShortDate, useAppSettings } from '../lib/appSettings'
import type { ChartDataPoint } from '../types/api'

// ── Helpers ───────────────────────────────────────────────────────────────────

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
    const { user } = useAuth()
    const { settings } = useAppSettings()
    const { selectedZevId } = useManagedZev()
    const isManagedScope = user?.role === 'admin' || user?.role === 'zev_owner'

    // Controlled state
    const [selectedMpId, setSelectedMpId] = useState<string>(searchParams.get('metering_point') ?? '')
    const [dateFrom, setDateFrom] = useState<string>(daysAgoIso(30))
    const [dateTo, setDateTo] = useState<string>(todayIso())
    const [bucket, setBucket] = useState<'day' | 'hour' | 'month'>('day')

    // Data queries
    const zevsQuery = useQuery({ queryKey: ['zevs'], queryFn: fetchZevs })
    const mpQuery = useQuery({ queryKey: ['metering-points'], queryFn: fetchMeteringPoints })

    const chartQuery = useQuery({
        queryKey: ['chart-data', selectedMpId, dateFrom, dateTo, bucket],
        queryFn: () =>
            fetchChartData({ meteringPoint: selectedMpId, dateFrom, dateTo, bucket }),
        enabled: !!selectedMpId,
    })

    const meteringPoints = (mpQuery.data?.results ?? []).filter(
        (meteringPoint) => !isManagedScope || !selectedZevId || meteringPoint.zev === selectedZevId,
    )
    const zevNameById = new Map((zevsQuery.data?.results ?? []).map((z) => [z.id, z.name]))

    const data: ChartDataPoint[] = chartQuery.data ?? []

    const totalIn = data.reduce((sum, d) => sum + d.in_kwh, 0)
    const totalOut = data.reduce((sum, d) => sum + d.out_kwh, 0)
    const hasOut = data.some((d) => d.out_kwh > 0)

    // Sync the selected MP to the URL
    function handleMpChange(id: string) {
        setSelectedMpId(id)
        if (id) {
            setSearchParams({ metering_point: id }, { replace: true })
        } else {
            setSearchParams({}, { replace: true })
        }
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
    }, [isManagedScope, selectedZevId, selectedMpId, meteringPoints])

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
                <p className="muted">Visualize energy readings per metering point.</p>
            </header>

            {/* ── Controls ──────────────────────────────────────────────────────── */}
            <div
                className="card"
                style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))',
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

                <DateRangeShortcutPicker
                    from={dateFrom}
                    to={dateTo}
                    onChange={({ from, to }) => {
                        setDateFrom(from)
                        setDateTo(to)
                    }}
                />

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
                </>
            )}
        </div>
    )
}
