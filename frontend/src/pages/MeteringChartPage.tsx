import { useQuery } from '@tanstack/react-query'
import { Tabs } from '@mantine/core'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { DataTable, type ColumnDef } from '../components/DataTable'
import { EmptyState } from '../components/EmptyState'
import { PageSkeleton } from '../components/PageSkeleton'
import { StatCard } from '../components/StatCard'
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
import { formatShortDate, useAppSettings } from '../lib/appSettings'
import { daysInPeriod, formatUtcIsoDate, isValidIsoDate } from '../lib/dates'
import { formatMeteringBucketLabel, meteringPointOptionLabel, outReadingLabelKey } from '../lib/meteringLabels'
import type { AppSettings, ChartDataPoint, DataQualitySeverity, MeteringPoint, MeteringPointDataQuality } from '../types/api'
import { CHART_GRID, CONS_COLORS, NEGATIVE_COLOR, PROD_COLORS } from '../lib/chartTokens'

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

/**
 * Beyond this many days, hourly resolution renders too many bars to be
 * useful (or safe) in the browser — a ZEV on an annual billing interval
 * defaults to a ~365-day period, which would otherwise be 8,760 bars.
 */
const MAX_HOURLY_RESOLUTION_DAYS = 31

/**
 * `data.length` is a count of chart *buckets*, not readings — the raw-data
 * table right below reports far more (e.g. 24 readings/day), so the label
 * has to say which one it is instead of a bare "Data points" (#645).
 */
const BUCKET_COUNT_LABEL_KEY: Record<'day' | 'hour' | 'month', string> = {
    day: 'pages.meteringData.stats.daysShown',
    hour: 'pages.meteringData.stats.hoursShown',
    month: 'pages.meteringData.stats.monthsShown',
}

/** Sortable numeric proxy for severity — worst first, so sorting the Status
 * column ascending brings the red rows to the top (#648). */
const SEVERITY_RANK: Record<DataQualitySeverity, number> = { red: 0, yellow: 1, green: 2 }

/** The active Data Quality severity filter from `?quality_severity=`, or
 * `'all'` if absent/invalid — a URL is never trusted input (#648). */
export function readSeverityFilter(searchParams: URLSearchParams): DataQualitySeverity | 'all' {
    const raw = searchParams.get('quality_severity')
    return raw === 'red' || raw === 'yellow' || raw === 'green' ? raw : 'all'
}

/**
 * The Data Quality rows to render: narrowed to `severityFilter` (or all of
 * them), each carrying a numeric `severityRank` so the Status column can be
 * sorted worst-first (#648).
 */
export function filterAndRankQualityRows(
    points: MeteringPointDataQuality[],
    severityFilter: DataQualitySeverity | 'all',
): Array<MeteringPointDataQuality & { severityRank: number }> {
    const filtered = severityFilter === 'all' ? points : points.filter((mp) => mp.severity === severityFilter)
    return filtered.map((mp) => ({ ...mp, severityRank: SEVERITY_RANK[mp.severity] }))
}

/**
 * The period from `?from=`/`?to=`, or `null` if either is missing/invalid
 * or the range is reversed. A URL is never trusted input (#647): a
 * hand-edited or stale pair falls back to the current billing period
 * instead of feeding a broken range to the chart/quality queries.
 */
export function readPeriodFromSearchParams(searchParams: URLSearchParams): { from: string; to: string } | null {
    const from = searchParams.get('from')
    const to = searchParams.get('to')
    if (!isValidIsoDate(from) || !isValidIsoDate(to) || from > to) {
        return null
    }
    return { from, to }
}

/**
 * The civil-day range a metering point actually has readings for, or `null`
 * if it has none yet. Used to turn the "no readings for this period" dead
 * end into a jump to a period that does have data (#642).
 *
 * `first_reading_at`/`last_reading_at` are full timestamps; converted with
 * UTC getters to match how the backend buckets/labels metering days
 * everywhere else on this page (#635).
 */
export function meteringPointDataRange(
    mp: Pick<MeteringPoint, 'first_reading_at' | 'last_reading_at'> | undefined,
): { from: string; to: string } | null {
    if (!mp?.first_reading_at || !mp.last_reading_at) {
        return null
    }
    return {
        from: formatUtcIsoDate(new Date(mp.first_reading_at)),
        to: formatUtcIsoDate(new Date(mp.last_reading_at)),
    }
}

/**
 * The chart bucket with the highest value for `field`, or `null` for an
 * empty chart. 91 near-identical daily rows tell you nothing at a glance —
 * this is what lets a stat badge say which one actually stands out (#651).
 */
export function peakChartPoint(
    data: ChartDataPoint[],
    field: 'in_kwh' | 'out_kwh',
): ChartDataPoint | null {
    if (data.length === 0) {
        return null
    }
    return data.reduce((peak, point) => (point[field] > peak[field] ? point : peak), data[0])
}

/**
 * Sentinel `<select>` value for "every meter in the managed ZEV, summed" —
 * distinct from both a real metering-point UUID and the "" empty selection,
 * so it round-trips through the URL and query keys the same way a real
 * metering point does (#650). Offered only in managed scope with a ZEV
 * selected; a participant has no single "their ZEV" to aggregate by.
 */
const ALL_METERING_POINTS_VALUE = '__zev_total__'

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
    const [period, setPeriodState] = useState<{ from: string; to: string }>(
        () => readPeriodFromSearchParams(searchParams) ?? getCurrentBillingPeriod(interval),
    )
    const [bucket, setBucket] = useState<'day' | 'hour' | 'month'>('day')

    // Sync the selected period to the URL, so a shared link reproduces it
    // (#647). Uses the functional setSearchParams form so this callback's
    // identity stays stable regardless of other URL changes (tab, metering
    // point) — it's only meant to fire on a genuine period change.
    const handlePeriodChange = useCallback((next: { from: string; to: string }) => {
        setPeriodState(next)
        setSearchParams((previous) => {
            const nextParams = new URLSearchParams(previous)
            nextParams.set('from', next.from)
            nextParams.set('to', next.to)
            return nextParams
        }, { replace: true })
    }, [setSearchParams])

    // Skip exactly the first auto-reset below when the URL already named an
    // explicit period (a restored/shared link) — otherwise the ZEV query
    // settling from its placeholder interval to the real one on first load
    // would immediately overwrite the restored period.
    const skipInitialAutoResetRef = useRef(readPeriodFromSearchParams(searchParams) !== null)

    useEffect(() => {
        if (skipInitialAutoResetRef.current) {
            skipInitialAutoResetRef.current = false
            return
        }
        handlePeriodChange(getCurrentBillingPeriod(interval))
    }, [selectedZevId, interval, handlePeriodChange])

    const periodDays = daysInPeriod(period.from, period.to)
    const hourlyResolutionAvailable = periodDays <= MAX_HOURLY_RESOLUTION_DAYS

    // Fall back to daily if the period grows past the hourly cap (e.g. a
    // billing-interval switch, or navigating to a longer period) while
    // hourly was selected.
    useEffect(() => {
        if (bucket === 'hour' && !hourlyResolutionAvailable) {
            setBucket('day')
        }
    }, [bucket, hourlyResolutionAvailable])

    // Data queries
    const zevsQuery = useQuery({ queryKey: queryKeys.zev.list(), queryFn: fetchZevs })
    const mpQuery = useQuery({
        queryKey: queryKeys.metering.points(selectedZevId || undefined),
        queryFn: () => fetchMeteringPoints(selectedZevId || undefined),
    })

    const isZevTotal = selectedMpId === ALL_METERING_POINTS_VALUE
    const chartQuery = useQuery({
        // Distinct cache entry per ZEV, since the "meteringPointId" slot of
        // the key is the same fixed sentinel regardless of which ZEV is
        // being totalled.
        queryKey: queryKeys.metering.chartData(
            isZevTotal ? `zev:${selectedZevId}` : selectedMpId,
            period.from,
            period.to,
            bucket,
        ),
        queryFn: () =>
            isZevTotal
                ? fetchChartData({ zevId: selectedZevId, dateFrom: period.from, dateTo: period.to, bucket })
                : fetchChartData({ meteringPoint: selectedMpId, dateFrom: period.from, dateTo: period.to, bucket }),
        enabled: isZevTotal ? !!selectedZevId : !!selectedMpId,
    })

    // The Data Quality tab has no concept of "whole ZEV total" — it already
    // lists every metering point in the selected ZEV as its own row, which
    // is what the sentinel would mean here anyway. Forwarding it as a
    // metering_point filter would 500 the request (it isn't a UUID, #671),
    // so it's treated the same as "no meter filter" on this tab.
    const qualityMeteringPointFilter = isZevTotal ? undefined : selectedMpId || undefined

    const qualityQuery = useQuery({
        queryKey: queryKeys.metering.qualityStatus(period.from, period.to, isManagedScope ? selectedZevId || undefined : undefined, qualityMeteringPointFilter),
        queryFn: () =>
            fetchMeteringDataQualityStatus({
                dateFrom: period.from,
                dateTo: period.to,
                zevId: selectedZevId && isManagedScope ? selectedZevId : undefined,
                meteringPointId: qualityMeteringPointFilter,
            }),
        // Expensive (one query per visible metering point server-side) and
        // only shown on the Data Quality tab — don't run it just because the
        // Chart tab happened to be open (#638).
        enabled: activeTab === 'quality',
    })

    const meteringPoints = (mpQuery.data ?? []).filter(
        (meteringPoint) => !isManagedScope || !selectedZevId || meteringPoint.zev === selectedZevId,
    )
    const zevNameById = new Map((zevsQuery.data ?? []).map((z) => [z.id, z.name]))

    const data: ChartDataPoint[] = chartQuery.data ?? []

    const totalIn = data.reduce((sum, d) => sum + d.in_kwh, 0)
    const totalOut = data.reduce((sum, d) => sum + d.out_kwh, 0)
    const hasOut = data.some((d) => d.out_kwh > 0)
    const averageIn = data.length > 0 ? totalIn / data.length : 0
    const peakIn = peakChartPoint(data, 'in_kwh')

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

    // Jumping from a Data Quality row to that meter's chart changes both
    // ?metering_point= and ?tab= at once (#648). Both handleMpChange and
    // handleTabChange build their update from the render-time `searchParams`
    // snapshot, so calling them back to back in one handler would have the
    // second overwrite the first's change before either commits — this does
    // both in a single functional update instead.
    const handleJumpToChart = useCallback((meteringPointId: string) => {
        setSelectedMpId(meteringPointId)
        setSearchParams((previous) => {
            const next = new URLSearchParams(previous)
            next.set('metering_point', meteringPointId)
            next.delete('tab')
            return next
        }, { replace: true })
    }, [setSearchParams])

    // Data Quality: click a severity card to filter the table to it; click
    // the active one again to clear (#648). Persisted in the URL like the
    // other filters/selectors on this page.
    const severityFilter = readSeverityFilter(searchParams)
    const handleSeverityFilterChange = useCallback((next: DataQualitySeverity | 'all') => {
        setSearchParams((previous) => {
            const nextParams = new URLSearchParams(previous)
            if (next === 'all') {
                nextParams.delete('quality_severity')
            } else {
                nextParams.set('quality_severity', next)
            }
            return nextParams
        }, { replace: true })
    }, [setSearchParams])

    // Data Quality: which rows have their full gap list expanded in place,
    // instead of the "+N more" dead end (#648).
    const [expandedGapsIds, setExpandedGapsIds] = useState<ReadonlySet<string>>(new Set())
    const toggleGapsExpanded = useCallback((meteringPointId: string) => {
        setExpandedGapsIds((previous) => {
            const next = new Set(previous)
            if (next.has(meteringPointId)) {
                next.delete(meteringPointId)
            } else {
                next.add(meteringPointId)
            }
            return next
        })
    }, [])

    const selectedMp = meteringPoints.find((m) => m.id === selectedMpId)
    const selectedMpDataRange = meteringPointDataRange(selectedMp)

    useEffect(() => {
        if (!isManagedScope || !selectedZevId) {
            return
        }
        if (!selectedMpId || selectedMpId === ALL_METERING_POINTS_VALUE) {
            return
        }
        // Wait for the real list before reconciling — meteringPoints is []
        // while mpQuery is still loading, which would otherwise read as
        // "not visible" and clear a `?metering_point=` deep link before it
        // ever had a chance to match (#674).
        if (!mpQuery.isSuccess) {
            return
        }
        const stillVisible = meteringPoints.some((meteringPoint) => meteringPoint.id === selectedMpId)
        if (!stillVisible) {
            handleMpChange('')
        }
    }, [isManagedScope, selectedZevId, selectedMpId, meteringPoints, handleMpChange, mpQuery.isSuccess])

    const tickFormatter = (value: string) => formatMeteringBucketLabel(value, bucket, settings)

    // Data Quality table rows: filtered to the active severity card, with a
    // sortable numeric rank alongside the string severity (#648).
    const qualityRows = useMemo(
        () => filterAndRankQualityRows(qualityQuery.data?.metering_points ?? [], severityFilter),
        [qualityQuery.data, severityFilter],
    )

    const qualityColumns = useMemo<ColumnDef<(typeof qualityRows)[number], unknown>[]>(() => [
        {
            accessorKey: 'meter_id',
            header: t('meteringDataQuality.meterId'),
            cell: (ctx) => (
                <button
                    type="button"
                    className="table-inline-link"
                    style={{ fontFamily: 'monospace', fontSize: '0.9em' }}
                    onClick={() => handleJumpToChart(ctx.row.original.id)}
                >
                    {ctx.row.original.meter_id}
                </button>
            ),
        },
        {
            accessorKey: 'participant_name',
            header: t('meteringDataQuality.participant'),
        },
        {
            accessorKey: 'data_completeness',
            header: t('meteringDataQuality.dataCompleteness'),
            cell: (ctx) => {
                const mp = ctx.row.original
                return (
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <div style={{ width: '80px', height: '20px', background: 'var(--line-subtle)', borderRadius: '4px', overflow: 'hidden' }}>
                            <div
                                style={{
                                    height: '100%',
                                    background: mp.severity === 'green' ? PROD_COLORS[0] : mp.severity === 'yellow' ? CHART_GRID : NEGATIVE_COLOR,
                                    width: `${mp.data_completeness}%`,
                                }}
                            />
                        </div>
                        <span style={{ fontSize: '0.875rem', fontWeight: 'bold' }}>{mp.data_completeness}%</span>
                    </div>
                )
            },
        },
        {
            accessorKey: 'severityRank',
            header: t('meteringDataQuality.status'),
            cell: (ctx) => {
                const mp = ctx.row.original
                return (
                    <>
                        <span
                            style={{
                                display: 'inline-block',
                                padding: '0.25rem 0.75rem',
                                borderRadius: '4px',
                                fontSize: '0.875rem',
                                fontWeight: 'bold',
                                background: mp.severity === 'green' ? 'var(--success-100)' : mp.severity === 'yellow' ? 'var(--warning-100)' : 'var(--danger-100)',
                                color: mp.severity === 'green' ? 'var(--success-700)' : mp.severity === 'yellow' ? 'var(--warning-800)' : 'var(--danger-700)',
                            }}
                        >
                            {t(`meteringDataQuality.severity${mp.severity.charAt(0).toUpperCase() + mp.severity.slice(1)}`)}
                        </span>
                        {mp.assignment_overlap && (
                            <div className="metering-dq-warning">{t('meteringDataQuality.assignmentOverlapWarning')}</div>
                        )}
                        {mp.unassigned_readings > 0 && (
                            <div className="metering-dq-warning">
                                {t('meteringDataQuality.unassignedWarning', { readings: mp.unassigned_readings, days: mp.unassigned_days })}
                            </div>
                        )}
                    </>
                )
            },
        },
        {
            id: 'gaps',
            header: t('meteringDataQuality.gaps'),
            enableSorting: false,
            cell: (ctx) => {
                const mp = ctx.row.original
                if (mp.gaps.length === 0) {
                    return <span style={{ color: 'var(--success-600)' }}>{t('meteringDataQuality.noGaps')}</span>
                }
                const expanded = expandedGapsIds.has(mp.id)
                const visibleGaps = expanded ? mp.gaps : mp.gaps.slice(0, 1)
                return (
                    <div style={{ fontSize: '0.875rem' }}>
                        {visibleGaps.map((gap, idx) => (
                            <div key={idx} style={{ color: 'var(--text-body)' }}>
                                {gap.start_date === gap.end_date ? <>{gap.start_date}</> : <>{gap.start_date} → {gap.end_date}</>}
                            </div>
                        ))}
                        {mp.gaps.length > 1 && (
                            <button type="button" className="table-inline-link" onClick={() => toggleGapsExpanded(mp.id)}>
                                {expanded
                                    ? t('meteringDataQuality.showFewerGaps')
                                    : `+${mp.gaps.length - 1} ${t('meteringDataQuality.moreGaps')}`}
                            </button>
                        )}
                    </div>
                )
            },
        },
    ], [t, expandedGapsIds, handleJumpToChart, toggleGapsExpanded])

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
                        onChange={handlePeriodChange}
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
                                    {isManagedScope && selectedZevId && (
                                        <option value={ALL_METERING_POINTS_VALUE}>
                                            {t('pages.meteringData.wholeZevTotal')}
                                        </option>
                                    )}
                                    {meteringPoints.map((mp) => (
                                        <option key={mp.id} value={mp.id}>
                                            {meteringPointOptionLabel(mp, zevNameById.get(mp.zev), t)}
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
                                    <option
                                        value="hour"
                                        disabled={!hourlyResolutionAvailable}
                                        title={hourlyResolutionAvailable ? undefined : t('pages.meteringData.resolutions.hourlyUnavailableHint', { maxDays: MAX_HOURLY_RESOLUTION_DAYS })}
                                    >
                                        {t('pages.meteringData.resolutions.hour')}
                                    </option>
                                    <option value="day">{t('pages.meteringData.resolutions.day')}</option>
                                    <option value="month">{t('pages.meteringData.resolutions.month')}</option>
                                </select>
                                {!hourlyResolutionAvailable && (
                                    <small className="muted">
                                        {t('pages.meteringData.resolutions.hourlyUnavailableHint', { maxDays: MAX_HOURLY_RESOLUTION_DAYS })}
                                    </small>
                                )}
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
                                    // The "whole ZEV total" sentinel has no matching option here
                                    // (this tab already lists every meter as its own row) — show
                                    // it as the "all metering points" option instead of a value
                                    // React can't match to anything (#671).
                                    value={isZevTotal ? '' : selectedMpId}
                                    onChange={(e) => handleMpChange(e.target.value)}
                                >
                                    <option value="">{t('pages.meteringData.allMeteringPoints')}</option>
                                    {meteringPoints.map((mp) => (
                                        <option key={mp.id} value={mp.id}>
                                            {meteringPointOptionLabel(mp, zevNameById.get(mp.zev), t)}
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
                            <EmptyState
                                titleKey="pages.meteringData.noPointSelectedTitle"
                                descriptionKey="pages.meteringData.noPointSelected"
                            />
                        )}

                        {/* "Whole ZEV total" is only offered when isManagedScope && selectedZevId
                            (see the dropdown below), but the selection is shareable via URL
                            (#647) — a participant, or an owner with no ZEV selected, can land
                            here with the sentinel set and no ZEV to total. chartQuery stays
                            disabled in that case, so without this branch nothing renders at
                            all (#673). */}
                        {isZevTotal && !selectedZevId && (
                            <EmptyState
                                titleKey="pages.meteringData.zevTotalUnavailableTitle"
                                descriptionKey="pages.meteringData.zevTotalUnavailable"
                            />
                        )}

                        {selectedMpId && chartQuery.isLoading && <PageSkeleton variant="card" />}
                        {selectedMpId && chartQuery.isError && (
                            <div className="card error-banner">{formatApiError(chartQuery.error)}</div>
                        )}

                        {selectedMpId && chartQuery.isSuccess && (
                            <>
                                {/* Matches the inline grid the other stat rows use; there is no
                                    shared `.stat-grid` class in the stylesheet. */}
                                <div
                                    style={{
                                        display: 'grid',
                                        gap: '1rem',
                                        gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))',
                                    }}
                                >
                                    {selectedMp && (
                                        <StatCard
                                            label={t('pages.meteringData.stats.meterId')}
                                            value={selectedMp.meter_id}
                                        />
                                    )}
                                    {isZevTotal && (
                                        <StatCard
                                            label={t('pages.meteringData.stats.zev')}
                                            value={zevNameById.get(selectedZevId) ?? selectedZevId}
                                        />
                                    )}
                                    <StatCard
                                        label={t('pages.meteringData.stats.totalConsumption')}
                                        value={`${totalIn.toFixed(2)} kWh`}
                                    />
                                    {peakIn && (
                                        <>
                                            <StatCard
                                                label={t('pages.meteringData.stats.averageConsumption')}
                                                value={`${averageIn.toFixed(2)} kWh`}
                                            />
                                            <StatCard
                                                label={t('pages.meteringData.stats.peakConsumption')}
                                                value={`${peakIn.in_kwh.toFixed(2)} kWh`}
                                                hint={formatMeteringBucketLabel(peakIn.bucket, bucket, settings)}
                                            />
                                        </>
                                    )}
                                    {hasOut && (
                                        <StatCard
                                            label={t(outReadingLabelKey(selectedMp?.meter_type, 'pages.meteringData.stats.totalProduction', 'pages.meteringData.stats.totalFeedIn'))}
                                            value={`${totalOut.toFixed(2)} kWh`}
                                        />
                                    )}
                                    <StatCard
                                        label={t(BUCKET_COUNT_LABEL_KEY[bucket])}
                                        value={String(data.length)}
                                    />
                                </div>

                                {data.length === 0 ? (
                                    <EmptyState
                                        titleKey="pages.meteringData.noReadingsTitle"
                                        descriptionKey={selectedMpDataRange ? 'pages.meteringData.noReadingsWithRange' : 'pages.meteringData.noReadings'}
                                        descriptionOptions={selectedMpDataRange ? {
                                            from: formatShortDate(selectedMpDataRange.from, settings),
                                            to: formatShortDate(selectedMpDataRange.to, settings),
                                        } : undefined}
                                        actions={selectedMpDataRange ? [{
                                            labelKey: 'pages.meteringData.jumpToAvailableData',
                                            onClick: () => handlePeriodChange(selectedMpDataRange),
                                        }] : undefined}
                                    />
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
                                                    fill={CONS_COLORS[0]}
                                                    radius={[3, 3, 0, 0]}
                                                    maxBarSize={48}
                                                />
                                                {hasOut && (
                                                    <Bar
                                                        dataKey="out_kwh"
                                                        name={t(outReadingLabelKey(selectedMp?.meter_type, 'pages.meteringData.series.production', 'pages.meteringData.series.feedIn'))}
                                                        fill={PROD_COLORS[0]}
                                                        radius={[3, 3, 0, 0]}
                                                        maxBarSize={48}
                                                    />
                                                )}
                                            </BarChart>
                                        </ResponsiveContainer>
                                    </div>
                                )}

                                {isZevTotal ? (
                                    <p className="muted">{t('pages.meteringData.rawTable.unavailableForZevTotal')}</p>
                                ) : (
                                    <RawMeteringTable
                                        meteringPointId={selectedMpId}
                                        dateFrom={period.from}
                                        dateTo={period.to}
                                        hasOut={hasOut}
                                        meterType={selectedMp?.meter_type}
                                    />
                                )}
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
                                        {/* Clickable filters (#648): click a card to narrow the table to
                                            that severity, click the active one again to clear. */}
                                        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '1rem', marginBottom: '1.5rem' }}>
                                            <button
                                                type="button"
                                                aria-pressed={severityFilter === 'green'}
                                                onClick={() => handleSeverityFilterChange(severityFilter === 'green' ? 'all' : 'green')}
                                                style={{
                                                    background: 'var(--success-100)',
                                                    border: `1px solid ${severityFilter === 'green' ? 'var(--success-700)' : 'var(--success-200)'}`,
                                                    boxShadow: severityFilter === 'green' ? '0 0 0 2px var(--success-700)' : 'none',
                                                    borderRadius: '8px',
                                                    padding: '1rem',
                                                    textAlign: 'center',
                                                    cursor: 'pointer',
                                                    font: 'inherit',
                                                }}
                                            >
                                                <div style={{ fontSize: '1.5rem', fontWeight: 'bold', color: 'var(--success-700)' }}>
                                                    {qualityQuery.data.metering_points.filter((mp) => mp.severity === 'green').length}
                                                </div>
                                                <div style={{ fontSize: '0.875rem', color: 'var(--brand-mid)' }}>{t('meteringDataQuality.severityGreen')}</div>
                                            </button>
                                            <button
                                                type="button"
                                                aria-pressed={severityFilter === 'yellow'}
                                                onClick={() => handleSeverityFilterChange(severityFilter === 'yellow' ? 'all' : 'yellow')}
                                                style={{
                                                    background: 'var(--warning-100)',
                                                    border: `1px solid ${severityFilter === 'yellow' ? 'var(--warning-800)' : 'var(--warning-200)'}`,
                                                    boxShadow: severityFilter === 'yellow' ? '0 0 0 2px var(--warning-800)' : 'none',
                                                    borderRadius: '8px',
                                                    padding: '1rem',
                                                    textAlign: 'center',
                                                    cursor: 'pointer',
                                                    font: 'inherit',
                                                }}
                                            >
                                                <div style={{ fontSize: '1.5rem', fontWeight: 'bold', color: 'var(--warning-800)' }}>
                                                    {qualityQuery.data.metering_points.filter((mp) => mp.severity === 'yellow').length}
                                                </div>
                                                <div style={{ fontSize: '0.875rem', color: 'var(--warning-800)' }}>{t('meteringDataQuality.severityYellow')}</div>
                                            </button>
                                            <button
                                                type="button"
                                                aria-pressed={severityFilter === 'red'}
                                                onClick={() => handleSeverityFilterChange(severityFilter === 'red' ? 'all' : 'red')}
                                                style={{
                                                    background: 'var(--danger-100)',
                                                    border: `1px solid ${severityFilter === 'red' ? 'var(--danger-700)' : 'var(--danger-300)'}`,
                                                    boxShadow: severityFilter === 'red' ? '0 0 0 2px var(--danger-700)' : 'none',
                                                    borderRadius: '8px',
                                                    padding: '1rem',
                                                    textAlign: 'center',
                                                    cursor: 'pointer',
                                                    font: 'inherit',
                                                }}
                                            >
                                                <div style={{ fontSize: '1.5rem', fontWeight: 'bold', color: 'var(--danger-700)' }}>
                                                    {qualityQuery.data.metering_points.filter((mp) => mp.severity === 'red').length}
                                                </div>
                                                <div style={{ fontSize: '0.875rem', color: 'var(--danger-600)' }}>{t('meteringDataQuality.severityRed')}</div>
                                            </button>
                                        </div>

                                        <div className="table-card">
                                            <DataTable
                                                // Remounts on filter change so pagination/sort state (internal
                                                // to DataTable) doesn't strand the viewer on a now-empty page.
                                                key={severityFilter}
                                                data={qualityRows}
                                                columns={qualityColumns}
                                                getRowId={(row) => row.id}
                                                emptyMessage={t('meteringDataQuality.noneMatchFilter')}
                                            />
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
