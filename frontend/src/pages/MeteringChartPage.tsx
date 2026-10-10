import { useQuery } from '@tanstack/react-query'
import { Tabs } from '@mantine/core'
import { useCallback, useEffect, useId, useMemo, useState } from 'react'
import { DataTable, type ColumnDef } from '../components/DataTable'
import { EmptyState } from '../components/EmptyState'
import { PageSkeleton } from '../components/PageSkeleton'
import { StatCard } from '../components/StatCard'
import { ImportsContent } from './ImportsPage'
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
import { useCommunityAccess, useScopeNote } from '../lib/communityAccess'
import {
    firstAlignedBillingPeriod,
    type BillingInterval,
} from '../lib/billingPeriod'
import { readBillingPeriodParams, useBillingPeriodParams } from '../lib/useBillingPeriodParams'
import { usePageNavigation } from '../lib/usePageNavigation'
import { formatShortDate, useAppSettings } from '../lib/appSettings'
import { daysInPeriod, formatBusinessIsoDate } from '../lib/dates'
import { formatKwh } from '../lib/numbers'
import { formatMeteringBucketLabel, meteringPointOptionLabel, outReadingLabelKey } from '../lib/meteringLabels'
import type { AppSettings, ChartDataPoint, DataQualitySeverity, MeteringPoint, MeteringPointDataQuality } from '../types/api'
import { AXIS_COLOR, CHART_GRID, CHART_GRIDLINE, CONS_COLORS, NEGATIVE_COLOR, PROD_COLORS } from '../lib/chartTokens'
import { CHART_AXIS_TICK, CHART_TOOLTIP_STYLE } from '../lib/chartTheme'
import { selectedCommunityName } from '../lib/membership'
import { PageHeader } from '../components/PageHeader'
import { ScopeGuard } from '../components/ScopeGuard'
import { Notice } from '../components/Notice'

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
            style={CHART_TOOLTIP_STYLE}
        >
            <p style={{ margin: '0 0 4px', fontWeight: 600 }}>{formatMeteringBucketLabel(label, resolution, settings)}</p>
            {payload.map((entry) => (
                <p key={entry.name} style={{ margin: '2px 0', color: entry.color }}>
                    {entry.name}: <strong>{formatKwh(entry.value, { maxDecimals: 3 })} kWh</strong>
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
 * The period encoded in the URL, or `null` if either date is missing/invalid
 * or the range is reversed. `period_start`/`period_end` is the canonical
 * shared billing form; `from`/`to` remains a read-only compatibility alias
 * for metering links created before the navigation regroup. If either
 * canonical key is present, that pair wins rather than mixing formats.
 */
export function readPeriodFromSearchParams(searchParams: URLSearchParams): { from: string; to: string } | null {
    return readBillingPeriodParams(searchParams, true)
}

/**
 * The civil-day range a metering point actually has readings for, or `null`
 * if it has none yet. Used to turn the "no readings for this period" dead
 * end into a jump to a period that does have data (#642).
 *
 * `first_reading_at`/`last_reading_at` are instants; their civil dates are
 * read in the business timezone, the same days the backend buckets by
 * (ADR 0026).
 */
export function meteringPointDataRange(
    mp: Pick<MeteringPoint, 'first_reading_at' | 'last_reading_at'> | undefined,
): { from: string; to: string } | null {
    if (!mp?.first_reading_at || !mp.last_reading_at) {
        return null
    }
    return {
        from: formatBusinessIsoDate(new Date(mp.first_reading_at)),
        to: formatBusinessIsoDate(new Date(mp.last_reading_at)),
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
 * a community aggregate, not a meter ID.
 */
export const ALL_METERING_POINTS_VALUE = '__zev_total__'

/**
 * Resolve `?metering_point=` against scope and the meter inventory. The
 * whole-community sentinel needs only management scope and a selected
 * community; real meter IDs need the resolved list. While a requested real
 * meter is still resolving, callers show loading — never "no point selected".
 */
export function resolveMeterSelection({
    requestedMpId,
    meterListResolved,
    meteringPointIds,
    isManagedScope,
    selectedZevId,
}: {
    requestedMpId: string
    meterListResolved: boolean
    meteringPointIds: ReadonlyArray<string>
    isManagedScope: boolean
    selectedZevId: string
}): { selectedMpId: string; isResolving: boolean; valid: boolean } {
    const isSentinel = requestedMpId === ALL_METERING_POINTS_VALUE
    const valid = isSentinel
        ? isManagedScope && !!selectedZevId
        : !requestedMpId || (meterListResolved && meteringPointIds.includes(requestedMpId))
    return {
        valid,
        selectedMpId: valid ? requestedMpId : '',
        isResolving: !!requestedMpId && !isSentinel && !meterListResolved,
    }
}

/**
 * Chart default without `?metering_point=`: the community total for management
 * readers, a participant's sole meter, else none. Derived; never written to the URL.
 */
export function defaultMeterSelection({
    isManagedScope,
    selectedZevId,
    meterListResolved,
    meteringPointIds,
}: {
    isManagedScope: boolean
    selectedZevId: string
    meterListResolved: boolean
    meteringPointIds: ReadonlyArray<string>
}): { selectedMpId: string; isResolving: boolean } {
    if (isManagedScope) {
        return { selectedMpId: selectedZevId ? ALL_METERING_POINTS_VALUE : '', isResolving: false }
    }
    if (!meterListResolved) return { selectedMpId: '', isResolving: true }
    return { selectedMpId: meteringPointIds.length === 1 ? meteringPointIds[0] : '', isResolving: false }
}

// ── Page ──────────────────────────────────────────────────────────────────────

export function MeteringChartPage({ tab }: { tab: 'chart' | 'quality' | 'imports' }) {
    const { searchParams, updateParams } = usePageNavigation()
    const { t } = useTranslation()
    const scopeNote = useScopeNote()
    const { user } = useAuth()
    const { settings } = useAppSettings()
    const { selectedZevId, selectedZev, entries, isLoading: scopeLoading, isError: scopeError } = useManagedZev()
    const { isZevScope: isManagedScope } = useCommunityAccess()
    const interval: BillingInterval = (selectedZev?.billing_interval as BillingInterval) ?? 'monthly'

    // The aligned floor only guards whole-period prev/next nav; custom ranges
    // stay free-form (pre-first-billing windows are legitimate on metering).
    const minPeriod = useMemo(
        () => firstAlignedBillingPeriod(selectedZev?.start_date ?? null, interval),
        [selectedZev?.start_date, interval],
    )
    const { period, setPeriod: handlePeriodChange, isReady: periodReady } = useBillingPeriodParams({
        interval,
        ready: isManagedScope ? !!selectedZev : !!user,
        scopeId: selectedZevId,
        fallback: 'current',
        legacyParams: true,
        scopeChange: 'preserve-url',
    })
    const [bucket, setBucket] = useState<'day' | 'hour' | 'month'>('day')

    const periodDays = daysInPeriod(period.from, period.to)
    const hourlyResolutionAvailable = periodDays <= MAX_HOURLY_RESOLUTION_DAYS
    const hourlyHintId = useId()
    const effectiveBucket = bucket === 'hour' && !hourlyResolutionAvailable ? 'day' : bucket

    // Fall back to daily if the period grows past the hourly cap (e.g. a
    // billing-interval switch, or navigating to a longer period) while
    // hourly was selected.
    useEffect(() => {
        if (bucket === 'hour' && !hourlyResolutionAvailable) {
            setBucket('day')
        }
    }, [bucket, hourlyResolutionAvailable])

    // Data queries
    // Operator-only lookup; /zevs/ is 403 for participants.
    const zevsQuery = useQuery({ queryKey: queryKeys.zev.list(), queryFn: fetchZevs, enabled: isManagedScope })
    const mpQuery = useQuery({
        queryKey: queryKeys.metering.points(selectedZevId || undefined),
        queryFn: () => fetchMeteringPoints(selectedZevId || undefined),
        enabled: periodReady && tab !== 'imports',
    })

    const meteringPoints = (mpQuery.data ?? []).filter(
        (meteringPoint) => !isManagedScope || !selectedZevId || meteringPoint.zev === selectedZevId,
    )
    const requestedMpId = searchParams.get('metering_point') ?? ''
    // The sentinel resolves from scope; real IDs resolve against the inventory (URL untouched until then).
    const isSentinelRequested = requestedMpId === ALL_METERING_POINTS_VALUE
    const meterListResolved = mpQuery.data !== undefined
    const meterListPending = mpQuery.isPending || mpQuery.isFetching
    const meteringPointIds = meteringPoints.map(mp => mp.id)
    const { selectedMpId, isResolving: selectionUnresolved, valid: validMpSelection } = resolveMeterSelection({
        requestedMpId,
        meterListResolved,
        meteringPointIds,
        isManagedScope,
        selectedZevId,
    })
    // Without an explicit meter the chart opens on a default (the Data
    // Quality tab keeps "all meters").
    const defaultSelection = defaultMeterSelection({ isManagedScope, selectedZevId, meterListResolved, meteringPointIds })
    const chartMpId = requestedMpId ? selectedMpId : defaultSelection.selectedMpId
    const isResolvingMpSelection = (selectionUnresolved && meterListPending)
        || (!requestedMpId && defaultSelection.isResolving && !mpQuery.isError)
    const hasNoMeters = meterListResolved && meteringPoints.length === 0
    const qualityBlockedOnMeterList = tab === 'quality' && !!requestedMpId && !isSentinelRequested && !meterListResolved
    const isZevTotal = chartMpId === ALL_METERING_POINTS_VALUE
    // The total is requested at once but only shown once the meter list is
    // known, so an empty community never flashes a chart.
    const awaitingMeterList = !!chartMpId && !meterListResolved && !mpQuery.isError
    const showChart = !!chartMpId && !hasNoMeters && !awaitingMeterList
    const chartQuery = useQuery({
        // Distinct cache entry per ZEV, since the "meteringPointId" slot of
        // the key is the same fixed sentinel regardless of which ZEV is
        // being totalled.
        queryKey: queryKeys.metering.chartData(
            isZevTotal ? `zev:${selectedZevId}` : chartMpId,
            period.from,
            period.to,
            effectiveBucket,
        ),
        queryFn: () =>
            isZevTotal
                ? fetchChartData({ zevId: selectedZevId, dateFrom: period.from, dateTo: period.to, bucket: effectiveBucket })
                : fetchChartData({ meteringPoint: chartMpId, dateFrom: period.from, dateTo: period.to, bucket: effectiveBucket }),
        enabled: periodReady && tab === 'chart' && !hasNoMeters && (isZevTotal ? !!selectedZevId : !!chartMpId),
    })

    // The Data Quality tab has no concept of "whole ZEV total" — it already
    // lists every metering point in the selected ZEV as its own row, which
    // is what the sentinel would mean here anyway. Forwarding it as a
    // metering_point filter would 500 the request (it isn't a UUID, #671),
    // so it's treated the same as "no meter filter" on this tab.
    const qualityMeteringPointFilter = selectedMpId === ALL_METERING_POINTS_VALUE ? undefined : selectedMpId || undefined

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
        enabled: periodReady && (!requestedMpId || isSentinelRequested || meterListResolved) && tab === 'quality' && (!isManagedScope || !!selectedZevId),
    })

    const zevNameById = new Map((zevsQuery.data ?? []).map((z) => [z.id, z.name]))

    const data: ChartDataPoint[] = chartQuery.data ?? []

    const totalIn = data.reduce((sum, d) => sum + d.in_kwh, 0)
    const totalOut = data.reduce((sum, d) => sum + d.out_kwh, 0)
    const hasOut = data.some((d) => d.out_kwh > 0)
    const averageIn = data.length > 0 ? totalIn / data.length : 0
    const peakIn = peakChartPoint(data, 'in_kwh')

    // Sync the selected metering point to the URL
    const handleMpChange = useCallback((id: string) => {
        updateParams(params => {
            if (id) params.set('metering_point', id)
            else params.delete('metering_point')
        })
    }, [updateParams])

    // Retain query parameters when switching route-based tabs.
    const handleTabChange = (value: string | null) => {
        updateParams(params => params.delete('tab'), {
            pathname: `/metering/${value === 'quality' ? 'quality' : value === 'imports' ? 'imports' : 'chart'}`,
        })
    }

    // Jumping from a Data Quality row to that meter's chart changes both the
    // route and ?metering_point= at once (#648). Keep the remaining filters so
    // the period survives the route-based tab switch.
    const handleJumpToChart = useCallback((meteringPointId: string) => {
        updateParams(params => {
            params.set('metering_point', meteringPointId)
            params.delete('tab')
        }, { pathname: '/metering/chart' })
    }, [updateParams])

    // Data Quality: click a severity card to filter the table to it; click
    // the active one again to clear (#648). Persisted in the URL like the
    // other filters/selectors on this page.
    const severityFilter = readSeverityFilter(searchParams)
    const handleSeverityFilterChange = useCallback((next: DataQualitySeverity | 'all') => {
        updateParams(nextParams => {
            if (next === 'all') {
                nextParams.delete('quality_severity')
            } else {
                nextParams.set('quality_severity', next)
            }
        })
    }, [updateParams])

    const toggleSeverity = useCallback(
        (severity: DataQualitySeverity) =>
            handleSeverityFilterChange(severityFilter === severity ? 'all' : severity),
        [handleSeverityFilterChange, severityFilter],
    )

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

    const selectedMp = meteringPoints.find((m) => m.id === chartMpId)
    const selectedMpDataRange = meteringPointDataRange(selectedMp)

    useEffect(() => {
        // ScopeGuard cannot stop this parent effect. A cold or failed scope
        // lookup has not established whether the aggregate link is valid.
        const scopeResolved = !isManagedScope || (!scopeLoading && (!scopeError || !!selectedZev))
        const resolvable = isSentinelRequested ? scopeResolved : meterListResolved
        if (requestedMpId && !validMpSelection && resolvable) handleMpChange('')
    }, [requestedMpId, validMpSelection, handleMpChange, meterListResolved, isSentinelRequested, scopeLoading, scopeError, selectedZev, isManagedScope])

    const tickFormatter = (value: string) => formatMeteringBucketLabel(value, effectiveBucket, settings)

    // Data Quality table rows: filtered to the active severity card, with a
    // sortable numeric rank alongside the string severity (#648).
    const qualityRows = useMemo(
        () => filterAndRankQualityRows(qualityQuery.data?.metering_points ?? [], severityFilter),
        [qualityQuery.data, severityFilter],
    )

    const severityCounts = useMemo(() => {
        const points = qualityQuery.data?.metering_points ?? []
        return {
            green: points.filter((mp) => mp.severity === 'green').length,
            yellow: points.filter((mp) => mp.severity === 'yellow').length,
            red: points.filter((mp) => mp.severity === 'red').length,
        }
    }, [qualityQuery.data])

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
            <PageHeader
                eyebrow={selectedCommunityName({ selectedZev, entries, selectedZevId })}
                communitySwitch
                scopeNote={scopeNote}
                title={t('pages.meteringData.title')}
                description={t('pages.meteringData.description')}
            />

            <ScopeGuard skeleton="table">
            <Tabs
                classNames={{ root: 'app-tabs', list: 'app-tabs-list', tab: 'app-tabs-tab' }}
                value={tab}
                keepMounted={false}
                onChange={handleTabChange}
            >
                <Tabs.List aria-label={t('pages.meteringData.title')}>
                    <Tabs.Tab value="chart">{t('nav.meteringCharts')}</Tabs.Tab>
                    {isManagedScope && <Tabs.Tab value="quality">{t('nav.meteringDataQuality')}</Tabs.Tab>}
                    {isManagedScope && <Tabs.Tab value="imports">{t('nav.meteringImportsTab')}</Tabs.Tab>}
                </Tabs.List>

                {tab !== 'imports' && <div className="filter-bar">
                    {mpQuery.isError && (
                        <Notice tone={meterListResolved ? 'warning' : 'error'} onRetry={() => void mpQuery.refetch()} isRetrying={mpQuery.isFetching}>
                            {formatApiError(mpQuery.error)}
                        </Notice>
                    )}
                    <PeriodSelector
                        interval={interval}
                        from={period.from}
                        to={period.to}
                        minFrom={minPeriod?.from}
                        onChange={handlePeriodChange}
                    />

                    {tab === 'chart' && (
                        <div className="filter-bar-fields">
                            {!hasNoMeters && (
                                <label>
                                    <span>{t('pages.meteringData.meteringPoint')}</span>
                                    <select
                                        value={chartMpId}
                                        onChange={(e) => handleMpChange(e.target.value)}
                                    >
                                            {!chartMpId && <option value="">{t('pages.meteringData.selectMeteringPoint')}</option>}
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
                            )}

                            <label>
                                <span>{t('pages.meteringData.resolution')}</span>
                                <select
                                    value={bucket}
                                    onChange={(e) => setBucket(e.target.value as 'day' | 'hour' | 'month')}
                                    aria-describedby={hourlyResolutionAvailable ? undefined : hourlyHintId}
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
                            </label>
                        </div>
                    )}
                    {/* Below the row, so the fields keep one baseline. */}
                    {tab === 'chart' && !hourlyResolutionAvailable && (
                        <p id={hourlyHintId} className="muted filter-bar-note">
                            {t('pages.meteringData.resolutions.hourlyUnavailableHint', { maxDays: MAX_HOURLY_RESOLUTION_DAYS })}
                        </p>
                    )}

                    {tab === 'quality' && (
                        <div className="filter-bar-fields">
                            <label>
                                <span>{t('pages.meteringData.meterIdOptional')}</span>
                                <select
                                    // The "whole ZEV total" sentinel has no matching option here
                                    // (this tab already lists every meter as its own row) — show
                                    // it as the "all metering points" option instead of a value
                                    // React can't match to anything (#671).
                                    value={selectedMpId === ALL_METERING_POINTS_VALUE ? '' : selectedMpId}
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
                </div>}

                <Tabs.Panel value="chart">
                    <div className="page-stack">
                        {isResolvingMpSelection || awaitingMeterList ? (
                            <PageSkeleton variant="card" />
                        ) : hasNoMeters ? (
                            isManagedScope ? (
                                <EmptyState
                                    titleKey="pages.meteringData.noMetersTitle"
                                    descriptionKey="pages.meteringData.noMeters"
                                    actions={[{ labelKey: 'nav.meteringPoints', to: '/metering/points' }]}
                                />
                            ) : (
                                <EmptyState
                                    titleKey="pages.meteringData.noOwnMetersTitle"
                                    descriptionKey="pages.meteringData.noOwnMeters"
                                />
                            )
                        ) : !chartMpId && !requestedMpId && meterListResolved ? (
                            <EmptyState
                                titleKey="pages.meteringData.noPointSelectedTitle"
                                descriptionKey="pages.meteringData.noPointSelected"
                            />
                        ) : null}

                        {showChart && chartQuery.isLoading && <PageSkeleton variant="card" />}
                        {showChart && chartQuery.isError && (
                            <Notice tone="error" onRetry={() => void chartQuery.refetch()} isRetrying={chartQuery.isFetching}>{formatApiError(chartQuery.error)}</Notice>
                        )}

                        {showChart && chartQuery.data && (
                            <>
                                <div className="stat-grid">
                                    <StatCard
                                        label={t('pages.meteringData.stats.totalConsumption')}
                                        value={`${formatKwh(totalIn, { maxDecimals: 2 })} kWh`}
                                    />
                                    {peakIn && (
                                        <>
                                            <StatCard
                                                label={t('pages.meteringData.stats.averageConsumption')}
                                                value={`${formatKwh(averageIn, { maxDecimals: 2 })} kWh`}
                                            />
                                            <StatCard
                                                label={t('pages.meteringData.stats.peakConsumption')}
                                                value={`${formatKwh(peakIn.in_kwh, { maxDecimals: 2 })} kWh`}
                                                hint={formatMeteringBucketLabel(peakIn.bucket, bucket, settings)}
                                            />
                                        </>
                                    )}
                                    {hasOut && (
                                        <StatCard
                                            label={t(outReadingLabelKey(selectedMp?.meter_type, 'pages.meteringData.stats.totalProduction', 'pages.meteringData.stats.totalFeedIn'))}
                                            value={`${formatKwh(totalOut, { maxDecimals: 2 })} kWh`}
                                        />
                                    )}
                                    <StatCard
                                        label={t(BUCKET_COUNT_LABEL_KEY[effectiveBucket])}
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
                                                <CartesianGrid stroke={CHART_GRIDLINE} strokeDasharray="3 3" vertical={false} />
                                                <XAxis
                                                    dataKey="bucket"
                                                    tickFormatter={tickFormatter}
                                                    tick={CHART_AXIS_TICK}
                                                    stroke={AXIS_COLOR}
                                                    tickLine={false}
                                                    interval="preserveStartEnd"
                                                />
                                                <YAxis
                                                    unit=" kWh"
                                                    tick={CHART_AXIS_TICK}
                                                    stroke={AXIS_COLOR}
                                                    tickLine={false}
                                                    axisLine={false}
                                                    width={72}
                                                    tickFormatter={(v: number) => formatKwh(v)}
                                                />
                                                <Tooltip
                                                    content={<CustomTooltip resolution={effectiveBucket} settings={settings} />}
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
                                        meteringPointId={chartMpId}
                                        dateFrom={period.from}
                                        dateTo={period.to}
                                        hasOut={hasOut}
                                        meterType={selectedMp?.meter_type}
                                        canReadAssignments={isManagedScope}
                                    />
                                )}
                            </>
                        )}
                    </div>
                </Tabs.Panel>

                <Tabs.Panel value="quality">
                    <div className="page-stack">
                        {qualityBlockedOnMeterList ? (
                            meterListPending ? <PageSkeleton variant="table" /> : null
                        ) : (
                        <>
                        {qualityQuery.isLoading && <PageSkeleton variant="table" />}
                        {qualityQuery.isError && (
                            <Notice tone="error" onRetry={() => void qualityQuery.refetch()} isRetrying={qualityQuery.isFetching}>{formatApiError(qualityQuery.error)}</Notice>
                        )}
                        {qualityQuery.data && (
                            <>
                                {qualityQuery.data.metering_points.length === 0 ? (
                                    <EmptyState
                                        titleKey="meteringDataQuality.noData"
                                        descriptionKey="meteringDataQuality.noDataDescription"
                                        actions={[{ labelKey: 'nav.meteringPoints', to: '/metering/points' }]}
                                    />
                                ) : (
                                    <>
                                        {/* Clickable filters (#648): click a card to narrow the table to
                                            that severity, click the active one again to clear. */}
                                        <div className="stat-grid">
                                            <StatCard
                                                label={t('meteringDataQuality.severityGreen')}
                                                value={severityCounts.green}
                                                tone="success"
                                                onPress={() => toggleSeverity('green')}
                                                pressed={severityFilter === 'green'}
                                            />
                                            <StatCard
                                                label={t('meteringDataQuality.severityYellow')}
                                                value={severityCounts.yellow}
                                                tone="warning"
                                                onPress={() => toggleSeverity('yellow')}
                                                pressed={severityFilter === 'yellow'}
                                            />
                                            <StatCard
                                                label={t('meteringDataQuality.severityRed')}
                                                value={severityCounts.red}
                                                tone="danger"
                                                onPress={() => toggleSeverity('red')}
                                                pressed={severityFilter === 'red'}
                                            />
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
                        </>
                        )}
                    </div>
                </Tabs.Panel>

                {/* Import history owns its wizard, queries and guards. */}
                {isManagedScope && (
                    <Tabs.Panel value="imports">
                        <ImportsContent />
                    </Tabs.Panel>
                )}
            </Tabs>
            </ScopeGuard>
        </div>
    )
}
