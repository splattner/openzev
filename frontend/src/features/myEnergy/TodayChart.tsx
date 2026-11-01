import { useId } from 'react'
import { useTranslation } from 'react-i18next'
import { Area, CartesianGrid, ComposedChart, Legend, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import {
    ANNOTATION_COLOR, AXIS_COLOR, CHART_GRID, CHART_GRIDLINE, CHART_LOCAL, FLOW_GRID_EXP, FLOW_LOCAL_CONS,
} from '../../lib/chartTokens'
import { CHART_AXIS_TICK, CHART_TOOLTIP_STYLE } from '../../lib/chartTheme'
import { nextPeakWindow, peakDayKind, peakRange } from '../../lib/forecast'
import { formatClockMinutes, kwFigure, liveDayAxis } from '../../lib/live'
import type { TodayRow } from '../../lib/myEnergy'
import type { ForecastPeakWindow } from '../../types/api'

const LIVE_DASH = '5 3'

/**
 * Today in kW (SPEC-2026-live-energy-data §7.2). The ZEV's production and consumption are live
 * 5-minute means only. "Your" lines are one merged series: stored history of the own system up to the
 * hand-over (solid), live values after it (dashed). A gap stays a gap, nothing is interpolated.
 */
export function TodayChart({ date, rows, through, hasLive, peakWindows = [] }: {
    date: string
    rows: TodayRow[]
    /** End of the last history interval; the hand-over from history to live. */
    through: string | null
    /** The live curve answered; without it the chart shows the history alone. */
    hasLive: boolean
    /** The forecast's peak windows; today's is named above the chart. */
    peakWindows?: ForecastPeakWindow[]
}) {
    const { t } = useTranslation()
    const titleId = useId()
    const axis = liveDayAxis(date)
    const has = (pick: (row: TodayRow) => number | null) => rows.some((row) => pick(row) !== null)
    const hasZev = has((row) => row.production)
    const positive = (pick: (row: TodayRow) => number | null) => rows.some((row) => (pick(row) ?? 0) > 0)
    const hasOwnHistory = has((row) => row.ownHistory)
    const hasOwnLive = has((row) => row.ownLive)
    const hasForecast = has((row) => row.forecast)
    const hasBand = has((row) => (row.forecastBand ? row.forecastBand[1] : null))
    const peak = nextPeakWindow(peakWindows.filter((window) => window.date === date))
        const handOver = through ? Date.parse(through) : null
    const showHandOver = handOver !== null && hasOwnHistory && handOver > axis.start && handOver < axis.end
    const kwTooltip = (value: unknown) => (typeof value === 'number' ? `${kwFigure(value * 1000)} kW` : String(value))
    const ownLine = (dataKey: keyof TodayRow, name: string, stroke: string, live: boolean) => (
        <Line
            type="monotone"
            dataKey={dataKey}
            name={name}
            stroke={stroke}
            strokeWidth={2}
            strokeDasharray={live ? LIVE_DASH : undefined}
            dot={false}
            connectNulls={false}
            isAnimationActive={false}
        />
    )

    return (
        <section className="card chart-card" aria-labelledby={titleId}>
            <h3 id={titleId}>{t('myEnergy.today.title')}</h3>
            {!hasZev && !hasOwnHistory && !hasOwnLive && !hasForecast ? (
                <p className="muted">{t(hasLive ? 'myEnergy.today.empty' : 'myEnergy.today.emptyHistory')}</p>
            ) : (
                <>
                    {peak && <p><strong>{t(`forecast.peak.${peakDayKind(peak)}`, { range: peakRange(peak) })}</strong></p>}
                    <ResponsiveContainer width="100%" height={280}>
                        <ComposedChart data={rows} margin={{ top: 16, right: 20, bottom: 4, left: 0 }}>
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
                            <Tooltip
                                contentStyle={CHART_TOOLTIP_STYLE}
                                labelFormatter={(label) => formatClockMinutes(Number(label))}
                                formatter={kwTooltip}
                            />
                            <Legend />
                            {showHandOver && (
                                <ReferenceLine
                                    x={handOver}
                                    stroke={ANNOTATION_COLOR}
                                    strokeDasharray="4 3"
                                    label={{ value: t('myEnergy.today.handOver'), position: 'top', fontSize: 11, fill: ANNOTATION_COLOR }}
                                />
                            )}
                            {hasBand && (
                                <Area
                                    type="stepAfter"
                                    dataKey="forecastBand"
                                    name={t('forecast.band')}
                                    stroke="none"
                                    fill={CHART_LOCAL}
                                    fillOpacity={0.1}
                                    legendType="none"
                                    connectNulls={false}
                                    isAnimationActive={false}
                                />
                            )}
                            {hasForecast && (
                                <Area
                                    type="stepAfter"
                                    dataKey="forecast"
                                    name={t('myEnergy.today.forecast')}
                                    stroke={CHART_LOCAL}
                                    strokeOpacity={0.55}
                                    strokeDasharray={LIVE_DASH}
                                    fill={CHART_LOCAL}
                                    fillOpacity={0.06}
                                    strokeWidth={1.5}
                                    dot={false}
                                    connectNulls={false}
                                    isAnimationActive={false}
                                />
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
                            {hasZev && (
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
                            {hasOwnHistory && ownLine('ownHistory', t('myEnergy.today.ownHistory'), CHART_GRID, false)}
                            {hasOwnLive && ownLine('ownLive', t('myEnergy.today.ownLive'), CHART_GRID, true)}
                            {positive((row) => row.ownHistoryProduction) &&
                                ownLine('ownHistoryProduction', t('myEnergy.today.ownProductionHistory'), FLOW_GRID_EXP, false)}
                            {positive((row) => row.ownLiveProduction) &&
                                ownLine('ownLiveProduction', t('myEnergy.today.ownProductionLive'), FLOW_GRID_EXP, true)}
                        </ComposedChart>
                    </ResponsiveContainer>
                    <p className="muted">{t('myEnergy.today.hint')}</p>
                    {hasZev && <p className="muted">{t('live.curve.hint')}</p>}
                    {hasForecast && <p className="muted">{t('myEnergy.today.forecastHint')}</p>}
                    {!hasLive && hasOwnHistory && <p className="muted">{t('myEnergy.today.historyOnly')}</p>}
                </>
            )}
        </section>
    )
}
