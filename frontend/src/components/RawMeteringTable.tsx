import { useQuery } from '@tanstack/react-query'
import { CHART_LOCAL, FLOW_LOCAL_CONS } from '../lib/chartTokens'
import { Fragment, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { fetchRawMeteringData, fetchRawMeteringDay } from '../lib/api/metering'
import { queryKeys } from '../lib/api/queryKeys'
import { formatShortDate, useAppSettings } from '../lib/appSettings'
import type { RawMeteringReading } from '../types/api'

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
                                {HOURS.map((h) => (
                                    <td key={h}>{kwh(grid[slot][h])}</td>
                                ))}
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
function DaySparkline({ intervals, hasIn, hasOut }: { intervals: IntervalRow[]; hasIn: boolean; hasOut: boolean }) {
    const { t } = useTranslation()
    return (
        <div className="raw-metering-sparkline">
            <ResponsiveContainer width="100%" height={120}>
                <AreaChart data={intervals} margin={{ top: 8, right: 12, left: 4, bottom: 0 }}>
                    <defs>
                        <linearGradient id="rawSparkIn" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="0%" stopColor={CHART_LOCAL} stopOpacity={0.28} />
                            <stop offset="100%" stopColor={CHART_LOCAL} stopOpacity={0} />
                        </linearGradient>
                        <linearGradient id="rawSparkOut" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="0%" stopColor={FLOW_LOCAL_CONS} stopOpacity={0.28} />
                            <stop offset="100%" stopColor={FLOW_LOCAL_CONS} stopOpacity={0} />
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
                            stroke={CHART_LOCAL}
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
                            name={t('pages.meteringData.series.feedIn')}
                            stroke={FLOW_LOCAL_CONS}
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
}: {
    meteringPointId: string
    date: string
    colSpan: number
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
                        <DaySparkline intervals={intervals} hasIn={dayHasIn} hasOut={dayHasOut} />
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
                                caption={showCaptions ? t('pages.meteringData.rawTable.outKwh') : undefined}
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
}: {
    meteringPointId: string
    dateFrom: string
    dateTo: string
    hasOut: boolean
}) {
    const { t } = useTranslation()
    const { settings } = useAppSettings()
    const [expanded, setExpanded] = useState<string | null>(null)

    const summaryQuery = useQuery({
        queryKey: queryKeys.metering.rawData(meteringPointId, dateFrom, dateTo),
        queryFn: () => fetchRawMeteringData({ meteringPoint: meteringPointId, dateFrom, dateTo }),
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
                <div className="raw-metering-detail-status muted">{t('pages.meteringData.loadingRawTable')}</div>
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
                            {hasOut && <th className="raw-metering-num">{t('pages.meteringData.rawTable.outTotal')}</th>}
                            <th className="raw-metering-num">{t('pages.meteringData.rawTable.rawReadings')}</th>
                        </tr>
                    </thead>
                    <tbody>
                        {days.map((day) => {
                            const isOpen = expanded === day.date
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
