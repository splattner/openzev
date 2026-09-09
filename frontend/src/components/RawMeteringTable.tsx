import { useQuery } from '@tanstack/react-query'
import { CHART_LOCAL, FLOW_LOCAL_CONS } from '../lib/chartTokens'
import { Fragment, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { fetchRawMeteringData, fetchRawMeteringDay } from '../lib/api/metering'
import { fetchMeteringPointAssignments } from '../lib/api/zev'
import { queryKeys } from '../lib/api/queryKeys'
import { formatShortDate, useAppSettings } from '../lib/appSettings'
import { outReadingLabelKey } from '../lib/meteringLabels'
import { PageSkeleton } from './PageSkeleton'
import type { MeteringPoint, MeteringPointAssignment, RawMeteringDailyRow, RawMeteringReading } from '../types/api'

// ── Anomaly detection (#652) ──────────────────────────────────────────────────
//
// Lightweight, non-ML checks over readings already fetched for this page —
// no separate anomaly-detection endpoint. Flags surface as small warning
// badges rather than requiring the viewer to eyeball every value.

/** True if some assignment covers this metering point on this civil day. */
function hasAssignmentOnDay(assignments: MeteringPointAssignment[], date: string): boolean {
    return assignments.some((a) => a.valid_from <= date && (!a.valid_to || a.valid_to >= date))
}

/**
 * Day-summary-level flags: don't require expanding the day.
 *
 * `zeroConsumptionWithHolder` is scoped to days with an assignment holder —
 * a holder-less meter reading zero all day is unremarkable (nobody's
 * tracking it), so flagging it would just be noise on top of the
 * unassigned-readings warning the Data Quality tab already reports.
 */
export function dayAnomalyFlags(
    day: Pick<RawMeteringDailyRow, 'date' | 'in_kwh' | 'out_kwh'>,
    assignments: MeteringPointAssignment[],
): { zeroConsumptionWithHolder: boolean; negativeTotal: boolean } {
    return {
        zeroConsumptionWithHolder: day.in_kwh === 0 && hasAssignmentOnDay(assignments, day.date),
        negativeTotal: day.in_kwh < 0 || day.out_kwh < 0,
    }
}

/**
 * Reading-level flags: only available once a day's individual readings are
 * fetched (expanding it). A duplicate (timestamp, direction) pair is
 * otherwise silently summed into one interval by pivotByInterval/
 * buildHourGrid below — this is what would otherwise hide that from view.
 */
export function readingAnomalies(readings: RawMeteringReading[]): {
    negativeCount: number
    duplicateCount: number
} {
    const negativeCount = readings.filter((r) => r.energy_kwh < 0).length
    const seen = new Map<string, number>()
    for (const r of readings) {
        const key = `${r.timestamp}|${r.direction}`
        seen.set(key, (seen.get(key) ?? 0) + 1)
    }
    let duplicateCount = 0
    for (const count of seen.values()) {
        if (count > 1) duplicateCount += 1
    }
    return { negativeCount, duplicateCount }
}

/** UTC HH:MM — matches how the importer stored the timestamps (naive stamped as UTC). */
function formatTimeOnly(ts: string): string {
    const d = new Date(ts)
    if (isNaN(d.getTime())) return ts
    return `${String(d.getUTCHours()).padStart(2, '0')}:${String(d.getUTCMinutes()).padStart(2, '0')}`
}

interface IntervalRow {
    ts: string
    time: string
    in: number | null
    out: number | null
}

/** Collapse a day's flat in/out readings into one row per 15-minute interval. */
function pivotByInterval(readings: RawMeteringReading[]): IntervalRow[] {
    const map = new Map<string, IntervalRow>()
    for (const r of readings) {
        const row = map.get(r.timestamp) ?? { ts: r.timestamp, time: formatTimeOnly(r.timestamp), in: null, out: null }
        if (r.direction === 'in') row.in = (row.in ?? 0) + r.energy_kwh
        else if (r.direction === 'out') row.out = (row.out ?? 0) + r.energy_kwh
        map.set(r.timestamp, row)
    }
    return Array.from(map.values()).sort((a, b) => a.ts.localeCompare(b.ts))
}

function kwh(value: number | null): string {
    return value === null ? '–' : value.toFixed(4)
}

// ── Hour × 15-minute grid ───────────────────────────────────────────────────────

const SLOT_MINUTES = [0, 15, 30, 45]
const HOURS = Array.from({ length: 24 }, (_, h) => h)

/** Arrange one direction's readings into a [slot][hour] matrix of kWh values (UTC). */
function buildHourGrid(readings: RawMeteringReading[], direction: 'in' | 'out'): (number | null)[][] {
    const grid: (number | null)[][] = SLOT_MINUTES.map(() => Array<number | null>(24).fill(null))
    for (const r of readings) {
        if (r.direction !== direction) continue
        const d = new Date(r.timestamp)
        if (isNaN(d.getTime())) continue
        const slot = SLOT_MINUTES.indexOf(d.getUTCMinutes())
        const hour = d.getUTCHours()
        if (slot >= 0 && hour >= 0 && hour < 24) {
            grid[slot][hour] = (grid[slot][hour] ?? 0) + r.energy_kwh
        }
    }
    return grid
}

/** Compact grid: one column per hour (00–23), one row per 15-minute slot (:00–:45). */
function HourGrid({
    readings,
    direction,
    caption,
}: {
    readings: RawMeteringReading[]
    direction: 'in' | 'out'
    caption?: string
}) {
    const grid = buildHourGrid(readings, direction)
    return (
        <div className="raw-metering-grid-wrap">
            {caption && <p className="raw-metering-grid-caption">{caption}</p>}
            <div className="raw-metering-grid-scroll">
                <table className="raw-metering-grid">
                    <thead>
                        <tr>
                            <th className="raw-metering-grid-corner" aria-hidden />
                            {HOURS.map((h) => (
                                <th key={h}>{String(h).padStart(2, '0')}</th>
                            ))}
                        </tr>
                    </thead>
                    <tbody>
                        {SLOT_MINUTES.map((minute, slot) => (
                            <tr key={minute}>
                                <th scope="row">:{String(minute).padStart(2, '0')}</th>
                                {HOURS.map((h) => {
                                    const value = grid[slot][h]
                                    // A negative reading is corrupt data, not just unusual —
                                    // flagged in place rather than requiring the viewer to
                                    // eyeball every cell (#652).
                                    const isNegative = value !== null && value < 0
                                    return (
                                        <td key={h} style={isNegative ? { color: 'var(--danger-700)', fontWeight: 700 } : undefined}>
                                            {kwh(value)}
                                        </td>
                                    )
                                })}
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    )
}

// ── Intraday sparkline ──────────────────────────────────────────────────────────

function SparkTooltip({
    active,
    payload,
    label,
}: {
    active?: boolean
    payload?: Array<{ name: string; value: number; color: string }>
    label?: string
}) {
    if (!active || !payload?.length) return null
    return (
        <div className="raw-metering-spark-tooltip">
            <strong>{label}</strong>
            {payload.map((entry) => (
                <div key={entry.name} style={{ color: entry.color }}>
                    {entry.name}: {entry.value.toFixed(4)} kWh
                </div>
            ))}
        </div>
    )
}

/** Compact intraday curve of a day's 15-minute values; complements the exact-value grid below. */
function DaySparkline({
    intervals,
    hasIn,
    hasOut,
    meterType,
}: {
    intervals: IntervalRow[]
    hasIn: boolean
    hasOut: boolean
    meterType: MeteringPoint['meter_type'] | undefined
}) {
    const { t } = useTranslation()
    return (
        <div className="raw-metering-sparkline">
            <ResponsiveContainer width="100%" height={120}>
                <AreaChart data={intervals} margin={{ top: 8, right: 12, left: 4, bottom: 0 }}>
                    <defs>
                        <linearGradient id="rawSparkIn" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="0%" stopColor={FLOW_LOCAL_CONS} stopOpacity={0.28} />
                            <stop offset="100%" stopColor={FLOW_LOCAL_CONS} stopOpacity={0} />
                        </linearGradient>
                        <linearGradient id="rawSparkOut" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="0%" stopColor={CHART_LOCAL} stopOpacity={0.28} />
                            <stop offset="100%" stopColor={CHART_LOCAL} stopOpacity={0} />
                        </linearGradient>
                    </defs>
                    <XAxis
                        dataKey="time"
                        tick={{ fontSize: 10 }}
                        tickLine={false}
                        axisLine={false}
                        interval={15}
                        minTickGap={16}
                    />
                    <YAxis hide domain={[0, 'auto']} />
                    <Tooltip content={<SparkTooltip />} />
                    {hasIn && (
                        <Area
                            type="monotone"
                            dataKey="in"
                            name={t('pages.meteringData.series.consumption')}
                            stroke={FLOW_LOCAL_CONS}
                            strokeWidth={1.5}
                            fill="url(#rawSparkIn)"
                            dot={false}
                            isAnimationActive={false}
                        />
                    )}
                    {hasOut && (
                        <Area
                            type="monotone"
                            dataKey="out"
                            name={t(outReadingLabelKey(meterType, 'pages.meteringData.series.production', 'pages.meteringData.series.feedIn'))}
                            stroke={CHART_LOCAL}
                            strokeWidth={1.5}
                            fill="url(#rawSparkOut)"
                            dot={false}
                            isAnimationActive={false}
                        />
                    )}
                </AreaChart>
            </ResponsiveContainer>
        </div>
    )
}

// ── Expanded day detail (lazy-loaded) ──────────────────────────────────────────

function RawDayDetail({
    meteringPointId,
    date,
    colSpan,
    meterType,
}: {
    meteringPointId: string
    date: string
    colSpan: number
    meterType: MeteringPoint['meter_type'] | undefined
}) {
    const { t } = useTranslation()
    const query = useQuery({
        queryKey: queryKeys.metering.rawDay(meteringPointId, date),
        queryFn: () => fetchRawMeteringDay({ meteringPoint: meteringPointId, date }),
    })

    const readings = query.data ?? []
    const intervals = pivotByInterval(readings)
    const dayHasIn = readings.some((r) => r.direction === 'in')
    const dayHasOut = readings.some((r) => r.direction === 'out')
    // Only label the grids when both directions are present; otherwise it's unambiguous.
    const showCaptions = dayHasIn && dayHasOut
    const { negativeCount, duplicateCount } = readingAnomalies(readings)

    return (
        <tr className="raw-metering-detail-row">
            <td colSpan={colSpan} className="raw-metering-detail-cell">
                {query.isLoading ? (
                    <div className="raw-metering-detail-status muted">{t('pages.meteringData.loadingRawTable')}</div>
                ) : query.isError ? (
                    <div className="raw-metering-detail-status error-banner">{t('pages.meteringData.rawTableError')}</div>
                ) : readings.length === 0 ? (
                    <div className="raw-metering-detail-status muted">{t('pages.meteringData.noRawReadings')}</div>
                ) : (
                    <div className="raw-metering-detail-body">
                        {negativeCount > 0 && (
                            <div className="raw-metering-anomaly raw-metering-anomaly-danger">
                                {t('pages.meteringData.rawTable.negativeReadingsWarning', { count: negativeCount })}
                            </div>
                        )}
                        {duplicateCount > 0 && (
                            <div className="raw-metering-anomaly">
                                {t('pages.meteringData.rawTable.duplicateReadingsWarning', { count: duplicateCount })}
                            </div>
                        )}
                        <DaySparkline intervals={intervals} hasIn={dayHasIn} hasOut={dayHasOut} meterType={meterType} />
                        {dayHasIn && (
                            <HourGrid
                                readings={readings}
                                direction="in"
                                caption={showCaptions ? t('pages.meteringData.rawTable.inKwh') : undefined}
                            />
                        )}
                        {dayHasOut && (
                            <HourGrid
                                readings={readings}
                                direction="out"
                                caption={showCaptions ? t(outReadingLabelKey(meterType, 'pages.meteringData.rawTable.productionKwh', 'pages.meteringData.rawTable.outKwh')) : undefined}
                            />
                        )}
                    </div>
                )}
            </td>
        </tr>
    )
}

// ── Raw-data section ────────────────────────────────────────────────────────────

export function RawMeteringTable({
    meteringPointId,
    dateFrom,
    dateTo,
    hasOut,
    meterType,
}: {
    meteringPointId: string
    dateFrom: string
    dateTo: string
    hasOut: boolean
    meterType?: MeteringPoint['meter_type']
}) {
    const { t } = useTranslation()
    const { settings } = useAppSettings()
    const [expanded, setExpanded] = useState<string | null>(null)

    const summaryQuery = useQuery({
        queryKey: queryKeys.metering.rawData(meteringPointId, dateFrom, dateTo),
        queryFn: () => fetchRawMeteringData({ meteringPoint: meteringPointId, dateFrom, dateTo }),
        enabled: !!meteringPointId,
    })

    // Only needed to scope the zero-consumption anomaly flag to days with an
    // actual holder (#652) — not shown anywhere else in this table.
    const assignmentsQuery = useQuery({
        queryKey: queryKeys.metering.pointAssignments(meteringPointId),
        queryFn: () => fetchMeteringPointAssignments(meteringPointId),
        enabled: !!meteringPointId,
    })

    const days = summaryQuery.data ?? []
    // Date + In + Reading count, plus Feed-in when the meter exports.
    const colSpan = hasOut ? 4 : 3

    return (
        <div className="table-card raw-metering">
            <h3>{t('pages.meteringData.rawTable.title')}</h3>
            <p className="muted" style={{ marginTop: 0 }}>
                {t('pages.meteringData.rawTable.description')}
            </p>

            {summaryQuery.isLoading ? (
                <PageSkeleton variant="tableRows" />
            ) : summaryQuery.isError ? (
                <div className="error-banner">{t('pages.meteringData.rawTableError')}</div>
            ) : days.length === 0 ? (
                <div className="raw-metering-detail-status muted">{t('pages.meteringData.noRawReadings')}</div>
            ) : (
                <table className="raw-metering-days">
                    <thead>
                        <tr>
                            <th>{t('pages.meteringData.rawTable.day')}</th>
                            <th className="raw-metering-num">{t('pages.meteringData.rawTable.inTotal')}</th>
                            {hasOut && <th className="raw-metering-num">{t(outReadingLabelKey(meterType, 'pages.meteringData.rawTable.productionTotal', 'pages.meteringData.rawTable.outTotal'))}</th>}
                            <th className="raw-metering-num">{t('pages.meteringData.rawTable.rawReadings')}</th>
                        </tr>
                    </thead>
                    <tbody>
                        {days.map((day) => {
                            const isOpen = expanded === day.date
                            const flags = dayAnomalyFlags(day, assignmentsQuery.data ?? [])
                            return (
                                <Fragment key={day.date}>
                                    <tr
                                        className="raw-metering-day"
                                        role="button"
                                        tabIndex={0}
                                        aria-expanded={isOpen}
                                        onClick={() => setExpanded(isOpen ? null : day.date)}
                                        onKeyDown={(e) => {
                                            if (e.key === 'Enter' || e.key === ' ') {
                                                e.preventDefault()
                                                setExpanded(isOpen ? null : day.date)
                                            }
                                        }}
                                    >
                                        <td className="raw-metering-day-label">
                                            <span className="raw-metering-caret" data-open={isOpen || undefined} aria-hidden>
                                                ▸
                                            </span>
                                            {formatShortDate(day.date, settings)}
                                            {flags.negativeTotal && (
                                                <span className="raw-metering-day-flag raw-metering-day-flag-danger">
                                                    {t('pages.meteringData.rawTable.negativeTotalFlag')}
                                                </span>
                                            )}
                                            {flags.zeroConsumptionWithHolder && (
                                                <span className="raw-metering-day-flag">
                                                    {t('pages.meteringData.rawTable.zeroConsumptionFlag')}
                                                </span>
                                            )}
                                        </td>
                                        <td className="raw-metering-num">{day.in_kwh.toFixed(4)}</td>
                                        {hasOut && <td className="raw-metering-num">{day.out_kwh.toFixed(4)}</td>}
                                        <td className="raw-metering-num">{day.readings_count}</td>
                                    </tr>
                                    {isOpen && (
                                        <RawDayDetail
                                            meteringPointId={meteringPointId}
                                            date={day.date}
                                            colSpan={colSpan}
                                            meterType={meterType}
                                        />
                                    )}
                                </Fragment>
                            )
                        })}
                    </tbody>
                </table>
            )}
        </div>
    )
}
