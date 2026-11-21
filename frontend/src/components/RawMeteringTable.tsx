import { SortableHeader, useTableSorting } from './tableSorting'
import { useQuery } from '@tanstack/react-query'
import { CHART_LOCAL, CONS_COLORS } from '../lib/chartTokens'
import { CHART_AXIS_TICK } from '../lib/chartTheme'
import { formatNumber } from '../lib/numbers'
import { Fragment, useId, useState } from 'react'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faChevronDown } from '@fortawesome/free-solid-svg-icons'
import { useTranslation } from 'react-i18next'
import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { fetchRawMeteringData, fetchRawMeteringDay } from '../lib/api/metering'
import { fetchMeteringPointAssignments } from '../lib/api/zev'
import { queryKeys } from '../lib/api/queryKeys'
import { formatShortDate, useAppSettings } from '../lib/appSettings'
import { zonedParts } from '../lib/dates'
import { conditionLabel, formatMeteringTimestamp, outReadingLabelKey } from '../lib/meteringLabels'
import { HeldReadingsPanel } from './HeldReadingsPanel'
import { PageSkeleton } from './PageSkeleton'
import type {
    MeteringPoint,
    MeteringPointAssignment,
    RawMeteringDailyRow,
    RawMeteringReading,
} from '../types/api'

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

/** HH:MM in the business timezone (ADR 0026); a DST day lists 92 or 100 rows. */
function formatTimeOnly(ts: string): string {
    const d = new Date(ts)
    if (isNaN(d.getTime())) return ts
    const { hours, minutes } = zonedParts(d)
    return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}`
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

function kwh(value: number | null | undefined): string {
    return value == null ? '–' : formatNumber(value, { minDecimals: 4, maxDecimals: 4 })
}

/**
 * Data-bar width (0–100) for a value relative to the largest magnitude in
 * the period — an outlier day should be visible without reading every
 * number (#641). `Math.abs` so a negative total (already separately
 * flagged red, see dayAnomalyFlags) still gets a proportional bar instead
 * of a blank one.
 */
export function dataBarPercent(value: number, maxAbs: number): number {
    if (maxAbs <= 0) {
        return 0
    }
    return Math.min(100, (Math.abs(value) / maxAbs) * 100)
}

/** Rows-per-page for the day-summary table — a quarter (~91 days) or a year
 * (365) otherwise renders every row at once and dwarfs the chart above it
 * (#641). A month-ish chunk keeps each page a natural, readable unit. */
const DAYS_PER_PAGE = 31

// ── Hour × quarter-hour table ───────────────────────────────────────────────────

const SLOT_MINUTES = [0, 15, 30, 45]
const HOURS = Array.from({ length: 24 }, (_, h) => h)

interface GridCell {
    total: number | null
    readings: RawMeteringReading[]
}

/**
 * Arrange one direction's readings into a [slot][hour] matrix of kWh values,
 * by Swiss hour. The autumn DST day's two 02:00 hours add up in one cell; the
 * spring day has no 02:00 hour at all. Each cell keeps its constituent
 * readings so a mixed-quality hour cannot appear entirely unflagged.
 */
function buildHourGrid(readings: RawMeteringReading[], direction: 'in' | 'out'): GridCell[][] {
    const grid: GridCell[][] = SLOT_MINUTES.map(() =>
        HOURS.map(() => ({ total: null, readings: [] })),
    )
    for (const r of readings) {
        if (r.direction !== direction) continue
        const d = new Date(r.timestamp)
        if (isNaN(d.getTime())) continue
        const { hours: hour, minutes } = zonedParts(d)
        const slot = SLOT_MINUTES.indexOf(minutes)
        if (slot >= 0 && hour >= 0 && hour < 24) {
            const cell = grid[slot][hour]
            cell.total = (cell.total ?? 0) + r.energy_kwh
            cell.readings.push(r)
        }
    }
    return grid
}

export interface HourRow {
    hour: number
    /** One cell per entry of `slots`. */
    cells: GridCell[]
    /** Sum of the hour's cells; null when none holds a reading. */
    total: number | null
}

/**
 * Pivot one direction's readings into hour rows by Swiss hour (see buildHourGrid):
 * four quarter-hour columns when any of the direction's readings is 15-minute
 * or off the full hour, otherwise one (hourly or daily data). A missing
 * quarter-hour is an empty cell, not a missing column.
 */
export function buildHourTable(
    readings: RawMeteringReading[],
    direction: 'in' | 'out',
): { slots: number[]; rows: HourRow[] } {
    const grid = buildHourGrid(readings, direction)
    const quarterHourly =
        readings.some((r) => r.direction === direction && r.resolution === '15min') ||
        grid.slice(1).some((slot) => slot.some((cell) => cell.readings.length > 0))
    const used = quarterHourly ? [0, 1, 2, 3] : [0]
    const rows = HOURS.map((hour) => {
        const cells = used.map((slot) => grid[slot][hour])
        const filled = cells.filter((cell) => cell.total !== null)
        return { hour, cells, total: filled.length ? filled.reduce((sum, cell) => sum + (cell.total ?? 0), 0) : null }
    })
    return { slots: used.map((slot) => SLOT_MINUTES[slot]), rows }
}

const pad2 = (n: number) => String(n).padStart(2, '0')

/** One interval: its value and quality markers, as a button that opens its readings. */
function ReadingCell({
    cell,
    time,
    open,
    detailId,
    onToggle,
}: {
    cell: GridCell
    time: string
    open: boolean
    detailId: string
    onToggle: () => void
}) {
    const { t } = useTranslation()
    if (cell.readings.length === 0) return <td>–</td>
    // Highlight a negative cell total; the day banner counts individual negative readings.
    return (
        <td className={cell.total !== null && cell.total < 0 ? 'raw-metering-negative' : undefined}>
            <button
                type="button"
                className="raw-metering-cell-button"
                aria-expanded={open}
                aria-controls={open ? detailId : undefined}
                aria-label={t('pages.meteringData.rawTable.cellAria', {
                    time,
                    value: kwh(cell.total),
                    quality: [...new Set(cell.readings.map((reading) => conditionLabel(reading.condition, t)))].join(', '),
                    count: cell.readings.length,
                })}
                onClick={onToggle}
            >
                {kwh(cell.total)}
                {cell.readings.some((reading) => reading.condition === '56') && (
                    <span className="raw-metering-quality-marker" aria-hidden>
                        ≈
                    </span>
                )}
                {cell.readings.length > 1 && (
                    <span className="raw-metering-cell-count" aria-hidden>
                        ·{cell.readings.length}
                    </span>
                )}
            </button>
        </td>
    )
}

/** Hours 00–23 as rows, split 00–11 and 12–23 side by side (stacked when narrow). */
function HourTable({ readings, direction }: { readings: RawMeteringReading[]; direction: 'in' | 'out' }) {
    const { t } = useTranslation()
    const { settings } = useAppSettings()
    const detailId = useId()
    const { slots, rows } = buildHourTable(readings, direction)
    const [selected, setSelected] = useState<{ hour: number; slot: number } | null>(null)
    const selectedCell = selected ? rows[selected.hour].cells[selected.slot] : null
    const allCells = rows.flatMap((row) => row.cells)
    // Name the resolution when the day has no quarter-hours to show.
    const hourly = readings.every((reading) => reading.direction !== direction || reading.resolution === 'hourly')
    const legend = [
        t(hourly ? 'pages.meteringData.rawTable.hourlyValuesInKwh' : 'pages.meteringData.rawTable.valuesInKwh'),
        allCells.some((cell) => cell.readings.some((reading) => reading.condition === '56')) &&
            t('pages.meteringData.rawTable.qualityEstimatedLegend'),
        t('pages.meteringData.rawTable.qualityDetailLegend'),
        allCells.some((cell) => cell.readings.length > 1) && t('pages.meteringData.rawTable.qualityAggregatedLegend'),
    ].filter(Boolean).join(' · ')

    return (
        <>
            <div className="raw-metering-halves">
                {[0, 12].map((start) => (
                    <div className="raw-metering-grid-scroll" key={start}>
                        <table className="raw-metering-grid">
                            <thead>
                                <tr>
                                    <th scope="col">{t('pages.meteringData.rawTable.hour')}</th>
                                    {slots.map((minute) => (
                                        <th key={minute} scope="col">{slots.length === 1 ? 'kWh' : `:${pad2(minute)}`}</th>
                                    ))}
                                    {slots.length > 1 && (
                                        <th scope="col" title={t('pages.meteringData.rawTable.hourTotal')} aria-label={t('pages.meteringData.rawTable.hourTotal')}>Σ</th>
                                    )}
                                </tr>
                            </thead>
                            <tbody>
                                {rows.slice(start, start + 12).map((row) => (
                                    <tr key={row.hour}>
                                        <th scope="row">{pad2(row.hour)}</th>
                                        {row.cells.map((cell, slot) => {
                                            const open = selected?.slot === slot && selected?.hour === row.hour
                                            return (
                                                <ReadingCell
                                                    key={slots[slot]}
                                                    cell={cell}
                                                    time={`${pad2(row.hour)}:${pad2(slots[slot])}`}
                                                    open={open}
                                                    detailId={detailId}
                                                    onToggle={() => setSelected(open ? null : { hour: row.hour, slot })}
                                                />
                                            )
                                        })}
                                        {slots.length > 1 && (
                                            <td className={`raw-metering-hour-total${row.total !== null && row.total < 0 ? ' raw-metering-negative' : ''}`}>{kwh(row.total)}</td>
                                        )}
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                ))}
            </div>
            <p className="raw-metering-quality-legend">{legend}</p>
            {selectedCell && (
                <div
                    id={detailId}
                    className="raw-metering-cell-detail"
                    role="region"
                    aria-label={t('pages.meteringData.rawTable.cellDetailTitle')}
                >
                    <strong>{t('pages.meteringData.rawTable.cellDetailTitle')}</strong>
                    <ul role="list">
                        {selectedCell.readings.map((reading) => (
                            <li key={reading.timestamp}>
                                <span className="raw-metering-cell-detail-time">{formatMeteringTimestamp(reading.timestamp, settings)}</span>{' '}
                                {kwh(reading.energy_kwh)} kWh · {conditionLabel(reading.condition, t)}
                            </li>
                        ))}
                    </ul>
                </div>
            )}
        </>
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
                    {entry.name}: {kwh(entry.value)} kWh
                </div>
            ))}
        </div>
    )
}

/** Compact intraday curve of a day's values; complements the exact-value table below. */
function DaySparkline({
    intervals,
    hasIn,
    hasOut,
    labels,
}: {
    intervals: IntervalRow[]
    hasIn: boolean
    hasOut: boolean
    labels: Record<'in' | 'out', string>
}) {
    // A category axis can only label times present in the data.
    const ticks = ['00:00', '06:00', '12:00', '18:00'].filter((time) => intervals.some((interval) => interval.time === time))
    return (
        <div className="raw-metering-sparkline">
            <ResponsiveContainer width="100%" height={120}>
                <AreaChart data={intervals} margin={{ top: 8, right: 20, left: 20, bottom: 0 }}>
                    <XAxis
                        dataKey="time"
                        tick={CHART_AXIS_TICK}
                        tickLine={false}
                        axisLine={false}
                        ticks={ticks}
                        interval={0}
                    />
                    <YAxis hide domain={[0, 'auto']} />
                    <Tooltip content={<SparkTooltip />} />
                    {hasIn && (
                        <Area
                            type="monotone"
                            dataKey="in"
                            name={labels.in}
                            stroke={CONS_COLORS[0]}
                            strokeWidth={1.5}
                            fill={CONS_COLORS[0]}
                            fillOpacity={0.12}
                            dot={false}
                            isAnimationActive={false}
                        />
                    )}
                    {hasOut && (
                        <Area
                            type="monotone"
                            dataKey="out"
                            name={labels.out}
                            stroke={CHART_LOCAL}
                            strokeWidth={1.5}
                            fill={CHART_LOCAL}
                            fillOpacity={0.12}
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
    id,
    meteringPointId,
    date,
    colSpan,
    meterType,
}: {
    id: string
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

    return (
        <tr id={id}>
            <td colSpan={colSpan} className="raw-metering-detail-cell">
                {query.isLoading ? (
                    <div className="raw-metering-detail-status muted">{t('pages.meteringData.loadingRawTable')}</div>
                ) : query.isError ? (
                    <div className="raw-metering-detail-status error-banner">{t('pages.meteringData.rawTableError')}</div>
                ) : readings.length === 0 ? (
                    <div className="raw-metering-detail-status muted">{t('pages.meteringData.noRawReadings')}</div>
                ) : (
                    <RawDayBody readings={readings} meterType={meterType} />
                )}
            </td>
        </tr>
    )
}

function RawDayBody({
    readings,
    meterType,
}: {
    readings: RawMeteringReading[]
    meterType: MeteringPoint['meter_type'] | undefined
}) {
    const { t } = useTranslation()
    const intervals = pivotByInterval(readings)
    const dayHasIn = readings.some((r) => r.direction === 'in')
    const dayHasOut = readings.some((r) => r.direction === 'out')
    const both = dayHasIn && dayHasOut
    const [direction, setDirection] = useState<'in' | 'out'>(
        !dayHasIn || (dayHasOut && meterType === 'production') ? 'out' : 'in',
    )
    const { negativeCount, duplicateCount } = readingAnomalies(readings)
    const labels = {
        in: t('pages.meteringData.series.consumption'),
        out: t(outReadingLabelKey(meterType, 'pages.meteringData.series.production', 'pages.meteringData.series.feedIn')),
    }
    const totalOf = (dir: 'in' | 'out') =>
        readings.filter((r) => r.direction === dir).reduce((sum, r) => sum + r.energy_kwh, 0)

    return (
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
            {both && (
                <p className="raw-metering-detail-totals">
                    {(['in', 'out'] as const).map((dir) => (
                        <span key={dir}>
                            {labels[dir]}: <strong>{kwh(totalOf(dir))}</strong> kWh
                        </span>
                    ))}
                </p>
            )}
            <DaySparkline intervals={intervals} hasIn={dayHasIn} hasOut={dayHasOut} labels={labels} />
            {both && (
                <div className="actions-row raw-metering-direction" role="group" aria-label={t('pages.meteringData.rawTable.direction')}>
                    {(['in', 'out'] as const).map((dir) => (
                        <button
                            key={dir}
                            type="button"
                            className={`button button-compact ${direction === dir ? 'button-primary' : 'button-secondary'}`}
                            aria-pressed={direction === dir}
                            onClick={() => setDirection(dir)}
                        >
                            {labels[dir]}
                        </button>
                    ))}
                </div>
            )}
            <HourTable key={direction} readings={readings} direction={direction} />
        </div>
    )
}

// ── Raw-data section ────────────────────────────────────────────────────────────

function BarCell({ value, percent }: { value: number; percent: number }) {
    return (
        <td className="raw-metering-num">
            <div className="raw-metering-bar-cell">
                <span className="raw-metering-bar" aria-hidden>
                    <span style={{ width: `${percent}%` }} />
                </span>
                <span className="raw-metering-value">{kwh(value)}</span>
            </div>
        </td>
    )
}

export function RawMeteringTable({
    meteringPointId,
    dateFrom,
    dateTo,
    hasOut,
    meterType,
    canReadAssignments,
    canReadHeld,
}: {
    meteringPointId: string
    dateFrom: string
    dateTo: string
    hasOut: boolean
    meterType?: MeteringPoint['meter_type']
    /** Assignments are management data; participants cannot read them. */
    canReadAssignments: boolean
    /** Held observations require management access. */
    canReadHeld: boolean
}) {
    const { t } = useTranslation()
    const { settings } = useAppSettings()
    const [expanded, setExpanded] = useState<ReadonlySet<string>>(new Set())
    const toggleDay = (date: string) =>
        setExpanded((prev) => {
            const next = new Set(prev)
            if (!next.delete(date)) next.add(date)
            return next
        })
    const [page, setPage] = useState(0)

    const summaryQuery = useQuery({
        queryKey: queryKeys.metering.rawData(meteringPointId, dateFrom, dateTo),
        queryFn: () => fetchRawMeteringData({ meteringPoint: meteringPointId, dateFrom, dateTo }),
        enabled: !!meteringPointId,
    })

    // Only needed to scope the zero-consumption anomaly flag to days with an
    // actual holder (#652) — not shown anywhere else in this table.
    // Holder-dependent flags require assignment access, cached data included.
    const assignmentsQuery = useQuery({
        queryKey: queryKeys.metering.pointAssignments(meteringPointId),
        queryFn: () => fetchMeteringPointAssignments(meteringPointId),
        enabled: !!meteringPointId && canReadAssignments,
    })
    const assignments = canReadAssignments ? assignmentsQuery.data ?? [] : []

    // A new meter or period starts on page 1 with every day closed, rather than
    // stranding the viewer on e.g. page 4 of a now much-shorter list (#641) or
    // reopening the same dates for another meter. Reset while rendering, so a
    // stale day never mounts (and fetches) first.
    const selection = `${meteringPointId}|${dateFrom}|${dateTo}`
    const [shownSelection, setShownSelection] = useState(selection)
    if (shownSelection !== selection) {
        setShownSelection(selection)
        setPage(0)
        setExpanded(new Set())
    }

    const days = summaryQuery.data ?? []
    // Date + In + Reading count, plus Feed-in when the meter exports.
    const colSpan = hasOut ? 4 : 3
    const sorting = useTableSorting(days, {
        day: row => row.date,
        inTotal: row => row.in_kwh,
        outTotal: row => row.out_kwh,
        rawReadings: row => row.readings_count,
    })
    const pageCount = Math.max(1, Math.ceil(days.length / DAYS_PER_PAGE))
    const visibleDays = sorting.rows.slice(page * DAYS_PER_PAGE, (page + 1) * DAYS_PER_PAGE)
    // Bar scale spans the whole period, not just the visible page, so a
    // day's bar stays comparable after paging (#641).
    const maxIn = Math.max(0, ...days.map((d) => Math.abs(d.in_kwh)))
    const maxOut = Math.max(0, ...days.map((d) => Math.abs(d.out_kwh)))

    return (
        <div className="table-card raw-metering">
            <h3>{t('pages.meteringData.rawTable.title')}</h3>
            <p className="muted mt-0">
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
                    <colgroup>
                        <col />
                        <col className="raw-metering-col-num" />
                        {hasOut && <col className="raw-metering-col-num" />}
                        <col />
                    </colgroup>
                    <thead>
                        <tr>
                            <SortableHeader {...sorting.header('day')}>{t('pages.meteringData.rawTable.day')}</SortableHeader>
                            <SortableHeader {...sorting.header('inTotal')} className="raw-metering-num">{t('pages.meteringData.rawTable.inTotal')}</SortableHeader>
                            {hasOut && <SortableHeader {...sorting.header('outTotal')} className="raw-metering-num">{t(outReadingLabelKey(meterType, 'pages.meteringData.rawTable.productionTotal', 'pages.meteringData.rawTable.outTotal'))}</SortableHeader>}
                            <SortableHeader {...sorting.header('rawReadings')} className="raw-metering-num">{t('pages.meteringData.rawTable.rawReadings')}</SortableHeader>
                        </tr>
                    </thead>
                    <tbody>
                        {visibleDays.map((day) => {
                            const isOpen = expanded.has(day.date)
                            const detailId = `raw-metering-detail-${meteringPointId}-${day.date}`
                            const flags = dayAnomalyFlags(day, assignments)
                            return (
                                <Fragment key={day.date}>
                                    <tr className={`raw-metering-day${isOpen ? ' is-open' : ''}`}>
                                        <td>
                                            <div className="raw-metering-day-label">
                                                <button
                                                    type="button"
                                                    className="raw-metering-day-toggle disclosure-toggle"
                                                    aria-expanded={isOpen}
                                                    aria-controls={isOpen ? detailId : undefined}
                                                    onClick={() => toggleDay(day.date)}
                                                >
                                                    <FontAwesomeIcon icon={faChevronDown} className="disclosure-toggle-icon" fixedWidth />
                                                    {formatShortDate(day.date, settings)}
                                                </button>
                                                {flags.negativeTotal && (
                                                    <span className="badge badge-danger badge-quiet raw-metering-day-flag">
                                                        {t('pages.meteringData.rawTable.negativeTotalFlag')}
                                                    </span>
                                                )}
                                                {flags.zeroConsumptionWithHolder && (
                                                    <span className="badge badge-warning badge-quiet raw-metering-day-flag">
                                                        {t('pages.meteringData.rawTable.zeroConsumptionFlag')}
                                                    </span>
                                                )}
                                            </div>
                                        </td>
                                        {/* A slim bar scaled to the period's max makes an outlier
                                            day visible without reading every row (#641). */}
                                        <BarCell value={day.in_kwh} percent={dataBarPercent(day.in_kwh, maxIn)} />
                                        {hasOut && <BarCell value={day.out_kwh} percent={dataBarPercent(day.out_kwh, maxOut)} />}
                                        <td className="raw-metering-num">{day.readings_count}</td>
                                    </tr>
                                    {isOpen && (
                                        <RawDayDetail
                                            id={detailId}
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

            {days.length > DAYS_PER_PAGE && (
                <div className="data-table-footer actions-row actions-row-end muted">
                    <span>
                        {t('common.pagination.range', {
                            from: page * DAYS_PER_PAGE + 1,
                            to: Math.min((page + 1) * DAYS_PER_PAGE, days.length),
                            total: days.length,
                        })}
                    </span>
                    <span className="flex-1" />
                    <button
                        className="button button-secondary button-compact"
                        type="button"
                        aria-label={t('common.pagination.previous')}
                        onClick={() => setPage((p) => p - 1)}
                        disabled={page === 0}
                    >
                        ‹
                    </button>
                    <span>{page + 1} / {pageCount}</span>
                    <button
                        className="button button-secondary button-compact"
                        type="button"
                        aria-label={t('common.pagination.next')}
                        onClick={() => setPage((p) => p + 1)}
                        disabled={page >= pageCount - 1}
                    >
                        ›
                    </button>
                </div>
            )}

            {canReadHeld && (
                <HeldReadingsPanel
                    key={`${meteringPointId}:${dateFrom}:${dateTo}`}
                    meteringPointId={meteringPointId}
                    dateFrom={dateFrom}
                    dateTo={dateTo}
                />
            )}
        </div>
    )
}
