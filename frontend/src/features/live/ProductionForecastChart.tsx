import { useMediaQuery } from '@mantine/hooks'
import { useId } from 'react'
import { useTranslation } from 'react-i18next'
import { Area, Bar, CartesianGrid, ComposedChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { AXIS_COLOR, CHART_LOCAL, CHART_GRIDLINE } from '../../lib/chartTokens'
import { CHART_AXIS_TICK, CHART_TOOLTIP_STYLE } from '../../lib/chartTheme'
import { forecastRows, nextPeakWindow, peakDayKind, peakRange } from '../../lib/forecast'
import { formatClockMinutes } from '../../lib/live'
import type { ProductionForecast } from '../../types/api'
import {
    FORECAST_TOOLTIP_CURSOR, ForecastHourBars, forecastTooltipLabel, HOUR_MS, kwTooltipText, noBarShape,
} from './forecastChartParts'

const dayFormatter = new Intl.DateTimeFormat(undefined, { timeZone: 'Europe/Zurich', weekday: 'short', day: 'numeric', month: 'numeric' })

const localHour = (ts: number) => Number(formatClockMinutes(ts).slice(0, 2))

/** `Mon 3.11.` for a day's start; a tick at midnight names the day, the others the time. */
function tickLabel(ts: number, namesDays: boolean): string {
    return namesDays && localHour(ts) === 0 ? dayFormatter.format(new Date(ts)) : formatClockMinutes(ts)
}

/**
 * The expected production of the ZEV's plants, hour by hour (SPEC-2026-live-energy-data §7.1).
 * Production only: it says when the plants are expected to produce most, never that power will be
 * spare. A band is drawn only where the forecast gives one.
 */
export function ProductionForecastChart({ forecast, title }: { forecast: ProductionForecast; title?: string }) {
    const { t } = useTranslation()
    const titleId = useId()
    const narrow = useMediaQuery('(max-width: 30em)')
    // A row sits in the middle of its hour, so the tooltip picks the hour the pointer is over; the bars are drawn from `start`.
    const rows = forecastRows(forecast.hours).map((row) => ({ ...row, start: row.ts, ts: row.ts + HOUR_MS / 2 }))
    const hasBand = rows.some((row) => row.band)
    // A tick every three hours, six beyond a day and a half or on a phone (nine labels do not fit its width), and midnight names the day.
    const step = narrow || rows.length > 36 ? 6 : 3
    // One day needs no day name (the title says which), and the long label would collide with its neighbour on a phone.
    const namesDays = rows.length > 24
    const ticks = rows.filter((row) => localHour(row.start) % step === 0).map((row) => row.start)
    const domain: [number, number] = rows.length > 0 ? [rows[0].start, rows[rows.length - 1].start + HOUR_MS] : [0, HOUR_MS]
    const now = new Date()
    const next = nextPeakWindow(forecast.peak_windows, now)

    return (
        <section className="card chart-card" aria-labelledby={titleId}>
            <div className="card-header">
                <h3 id={titleId}>{title ?? t('forecast.title')}</h3>
                {forecast.fetched_at && <span className="muted">{t('forecast.fetchedAt', { time: formatClockMinutes(forecast.fetched_at) })}</span>}
            </div>
            {next && (
                <p>
                    <strong>
                        {t(`forecast.peak.${peakDayKind(next, now)}`, { range: peakRange(next), date: dayFormatter.format(new Date(next.from)) })}
                    </strong>
                </p>
            )}
            <ResponsiveContainer width="100%" height={260}>
                <ComposedChart data={rows} margin={{ top: 8, right: 20, bottom: 4, left: 0 }}>
                    <CartesianGrid stroke={CHART_GRIDLINE} strokeDasharray="3 3" vertical={false} />
                    <XAxis
                        type="number" dataKey="ts" domain={domain} ticks={ticks} interval={0} tick={CHART_AXIS_TICK} stroke={AXIS_COLOR}
                        tickFormatter={(ts: number) => tickLabel(ts, namesDays)}
                    />
                    <YAxis tick={CHART_AXIS_TICK} stroke={AXIS_COLOR} unit=" kW" width={56} />
                    <Tooltip
                        contentStyle={CHART_TOOLTIP_STYLE}
                        cursor={FORECAST_TOOLTIP_CURSOR}
                        labelFormatter={(label) => forecastTooltipLabel(Number(label) - HOUR_MS / 2)}
                        formatter={kwTooltipText}
                    />
                    <ForecastHourBars hours={rows} nowMs={now.getTime()} />
                    <Bar dataKey="power" name={t('forecast.expected')} fill={CHART_LOCAL} fillOpacity={0.6} shape={noBarShape} isAnimationActive={false} />
                    {hasBand && (
                        <Area dataKey="band" name={t('forecast.band')} stroke="none" fill="none" legendType="none" activeDot={false} isAnimationActive={false} connectNulls={false} />
                    )}
                </ComposedChart>
            </ResponsiveContainer>
            {!forecast.complete && (
                <p className="muted">{t('forecast.partial', { count: forecast.plants_with_forecast, total: forecast.plants })}</p>
            )}
            <p className="muted">{t('forecast.hint')}</p>
        </section>
    )
}
