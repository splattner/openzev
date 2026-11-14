import { useTranslation } from 'react-i18next'
import { Area, Bar, CartesianGrid, ComposedChart, Legend, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import {
    ANNOTATION_COLOR, AXIS_COLOR, CHART_GRID, CHART_GRIDLINE, CHART_LOCAL, FLOW_GRID_EXP, FLOW_LOCAL_CONS,
} from '../../lib/chartTokens'
import { CHART_AXIS_TICK, CHART_TOOLTIP_STYLE } from '../../lib/chartTheme'
import { nextPeakWindow, peakDayKind, peakRange } from '../../lib/forecast'
import { formatClockMinutes, liveDayAxis } from '../../lib/live'
import { ownProductionIsZevProduction, type TodayRow } from '../../lib/myEnergy'
import type { ForecastPeakWindow } from '../../types/api'
import {
    FORECAST_TOOLTIP_CURSOR, type ForecastHourBar, ForecastHourBars, forecastTooltipLabel, HOUR_MS, kwTooltipText, noBarShape,
} from '../live/forecastChartParts'

const LIVE_DASH = '5 3'
/** The own lines move to a right-hand axis when they would be this many times smaller than everything else on the left one. */
const OWN_AXIS_RATIO = 4

/**
 * Today in kW (SPEC-2026-live-energy-data §7.2). The ZEV's production and consumption are live
 * 5-minute means only. "Your" lines are one merged series: stored history of the own system up to the
 * hand-over (solid), live values after it (dashed). A gap stays a gap, nothing is interpolated.
 */
export function TodayChart({ date, rows, through, hasLive, isOwn = true, peakWindows = [] }: {
    date: string
    rows: TodayRow[]
    /** End of the last history interval; the hand-over from history to live. */
    through: string | null
    /** The live curve answered; without it the chart shows the history alone. */
    hasLive: boolean
    /** The "own" lines are the signed-in user's; for a manager looking at somebody else they speak of "the person". */
    isOwn?: boolean
    /** The forecast's peak windows; today's is named above the chart. */
    peakWindows?: ForecastPeakWindow[]
}) {
    const { t } = useTranslation()
    const who = isOwn ? 'own' : 'person'
    const axis = liveDayAxis(date)
    const has = (pick: (row: TodayRow) => number | null) => rows.some((row) => pick(row) !== null)
    const hasZev = has((row) => row.production)
    // Below tier `exact` the ZEV's consumption is not known: no line, and no legend entry for one.
    const hasZevConsumption = has((row) => row.consumption)
    const positive = (pick: (row: TodayRow) => number | null) => rows.some((row) => (pick(row) ?? 0) > 0)
    const hasOwnHistory = has((row) => row.ownHistory)
    const hasOwnLive = has((row) => row.ownLive)
    const hasForecast = has((row) => row.forecast)
    const hasBand = has((row) => (row.forecastBand ? row.forecastBand[1] : null))
    const peak = nextPeakWindow(peakWindows.filter((window) => window.date === date))
    const handOver = through ? Date.parse(through) : null
    const showHandOver = handOver !== null && hasOwnHistory && handOver > axis.start && handOver < axis.end
    // The forecast is flat across each hour in the rows; the bars are drawn once per hour.
    const forecastHours = new Map<number, ForecastHourBar>()
    for (const row of rows) {
        if (row.forecast === null) continue
        const start = Math.floor(row.ts / HOUR_MS) * HOUR_MS
        if (!forecastHours.has(start)) forecastHours.set(start, { start, power: row.forecast, band: row.forecastBand })
    }
    // A household's own consumption is a fraction of what the ZEV produces, so on one axis it would be a line on the floor.
    const maxOf = (picks: Array<(row: TodayRow) => number | null>) =>
        rows.reduce((max, row) => picks.reduce((inner, pick) => Math.max(inner, pick(row) ?? 0), max), 0)
    const ownMax = maxOf([(row) => row.ownHistory, (row) => row.ownLive, (row) => row.ownHistoryProduction, (row) => row.ownLiveProduction])
    const zevMax = maxOf([(row) => row.production, (row) => row.consumption, (row) => row.forecastBand?.[1] ?? row.forecast])
    const ownAxis = ownMax > 0 && ownMax * OWN_AXIS_RATIO < zevMax
    // The only producer's own live production is the ZEV's production: one line, not two on top of each other.
    const ownProductionIsZevs = ownProductionIsZevProduction(rows)
    const ownName = (name: string) => (ownAxis ? `${name} (${t('myEnergy.today.rightAxis')})` : name)
    const ownLine = (dataKey: keyof TodayRow, name: string, stroke: string, live: boolean) => (
        <Line
            yAxisId={ownAxis ? 'own' : undefined}
            type="monotone"
            dataKey={dataKey}
            name={ownName(name)}
            stroke={stroke}
            strokeWidth={2}
            strokeDasharray={live ? LIVE_DASH : undefined}
            dot={false}
            connectNulls={false}
            isAnimationActive={false}
        />
    )

    return (
        // The tab above already says "Today"; the card does not repeat it as a heading (UI patterns §10.3 rule 12).
        <section className={hasForecast ? 'card chart-card chart-card--forecast-legend' : 'card chart-card'}>
            {!hasZev && !hasOwnHistory && !hasOwnLive && !hasForecast ? (
                <p className="muted">{t(hasLive ? 'myEnergy.today.empty' : `myEnergy.today.${who}EmptyHistory`)}</p>
            ) : (
                <>
                    {peak && <p><strong>{t(`forecast.peak.${peakDayKind(peak)}`, { range: peakRange(peak) })}</strong></p>}
                    <ResponsiveContainer width="100%" height={280}>
                        <ComposedChart data={rows} margin={{ top: 16, right: ownAxis ? 0 : 20, bottom: 4, left: 0 }}>
                            <CartesianGrid stroke={CHART_GRIDLINE} strokeDasharray="3 3" vertical={false} />
                            <XAxis
                                type="number"
                                dataKey="ts"
                                domain={[axis.start, axis.end]}
                                ticks={axis.ticks}
                                tick={CHART_AXIS_TICK}
                                stroke={AXIS_COLOR}
                                tickFormatter={formatClockMinutes}
                            />
                            <YAxis tick={CHART_AXIS_TICK} stroke={AXIS_COLOR} unit=" kW" width={56} />
                            {ownAxis && <YAxis yAxisId="own" orientation="right" domain={[0, 'auto']} tick={CHART_AXIS_TICK} stroke={AXIS_COLOR} unit=" kW" width={68} />}
                            <Tooltip
                                contentStyle={CHART_TOOLTIP_STYLE}
                                cursor={FORECAST_TOOLTIP_CURSOR}
                                labelFormatter={(label) => forecastTooltipLabel(Number(label))}
                                formatter={kwTooltipText}
                            />
                            {/* Drawing order, not alphabetical: the order must not change with the language. */}
                            <Legend itemSorter={null} />
                            {showHandOver && (
                                <ReferenceLine
                                    x={handOver}
                                    stroke={ANNOTATION_COLOR}
                                    strokeDasharray="4 3"
                                    label={{ value: t('myEnergy.today.handOver'), position: 'top', fontSize: 11, fill: ANNOTATION_COLOR }}
                                />
                            )}
                            {hasForecast && <ForecastHourBars hours={[...forecastHours.values()]} nowMs={new Date().getTime()} />}
                            {hasForecast && (
                                <Bar dataKey="forecast" name={t('forecast.expected')} fill={CHART_LOCAL} fillOpacity={0.35} shape={noBarShape} isAnimationActive={false} />
                            )}
                            {hasBand && (
                                <Area dataKey="forecastBand" name={t('forecast.band')} stroke="none" fill="none" legendType="none" activeDot={false} isAnimationActive={false} connectNulls={false} />
                            )}
                            {hasZev && (
                                <Area
                                    type="monotone"
                                    dataKey="production"
                                    name={t('myEnergy.today.zevProduction')}
                                    stroke={CHART_LOCAL}
                                    fill={CHART_LOCAL}
                                    fillOpacity={0.15}
                                    strokeWidth={2}
                                    dot={false}
                                    connectNulls={false}
                                    isAnimationActive={false}
                                />
                            )}
                            {hasZevConsumption && (
                                <Line
                                    type="monotone"
                                    dataKey="consumption"
                                    name={t('myEnergy.today.zevConsumption')}
                                    stroke={FLOW_LOCAL_CONS}
                                    strokeWidth={2}
                                    dot={false}
                                    connectNulls={false}
                                    isAnimationActive={false}
                                />
                            )}
                            {hasOwnHistory && ownLine('ownHistory', t(`myEnergy.today.${who}History`), CHART_GRID, false)}
                            {hasOwnLive && ownLine('ownLive', t(`myEnergy.today.${who}Live`), CHART_GRID, true)}
                            {positive((row) => row.ownHistoryProduction) &&
                                ownLine('ownHistoryProduction', t(`myEnergy.today.${who}ProductionHistory`), FLOW_GRID_EXP, false)}
                            {positive((row) => row.ownLiveProduction) && !ownProductionIsZevs &&
                                ownLine('ownLiveProduction', t(`myEnergy.today.${who}ProductionLive`), FLOW_GRID_EXP, true)}
                        </ComposedChart>
                    </ResponsiveContainer>
                </>
            )}
        </section>
    )
}
