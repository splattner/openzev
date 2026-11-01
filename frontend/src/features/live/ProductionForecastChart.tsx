import { useId } from 'react'
import { useTranslation } from 'react-i18next'
import { Area, Bar, CartesianGrid, ComposedChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { AXIS_COLOR, CHART_LOCAL, CHART_GRIDLINE } from '../../lib/chartTokens'
import { CHART_AXIS_TICK, CHART_TOOLTIP_STYLE } from '../../lib/chartTheme'
import { forecastRows, nextPeakWindow, peakDayKind, peakRange } from '../../lib/forecast'
import { formatClockMinutes, kwFigure } from '../../lib/live'
import type { ProductionForecast } from '../../types/api'

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
    const rows = forecastRows(forecast.hours)
    const hasBand = rows.some((row) => row.band)
    // A tick every three hours (six beyond a day and a half, so a phone fits them), and midnight names the day.
    const step = rows.length > 36 ? 6 : 3
    // One day needs no day name (the title says which), and the long label would collide with its neighbour on a phone.
    const namesDays = rows.length > 24
    const ticks = rows.filter((row) => localHour(row.ts) % step === 0).map((row) => row.ts)
    const now = new Date()
    const next = nextPeakWindow(forecast.peak_windows, now)
    const nowHour = Math.floor(now.getTime() / 3_600_000) * 3_600_000

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
                    <XAxis dataKey="ts" ticks={ticks} interval={0} tick={CHART_AXIS_TICK} stroke={AXIS_COLOR} tickFormatter={(ts: number) => tickLabel(ts, namesDays)} />
                    <YAxis tick={CHART_AXIS_TICK} stroke={AXIS_COLOR} unit=" kW" width={56} />
                    <Tooltip
                        contentStyle={CHART_TOOLTIP_STYLE}
                        labelFormatter={(label) => `${dayFormatter.format(new Date(Number(label)))} ${formatClockMinutes(Number(label))}`}
                        formatter={(value: unknown, name) => {
                            const text = Array.isArray(value) ? `${kwFigure(Number(value[0]) * 1000)}–${kwFigure(Number(value[1]) * 1000)} kW` : `${kwFigure(Number(value) * 1000)} kW`
                            return [text, name]
                        }}
                    />
                    <Bar dataKey="power" name={t('forecast.expected')} fill={CHART_LOCAL} fillOpacity={0.55} isAnimationActive={false}
                        shape={(props: { x?: number; y?: number; width?: number; height?: number; payload?: { ts: number } }) => (
                            <rect
                                x={props.x} y={props.y} width={props.width} height={props.height}
                                fill={CHART_LOCAL} fillOpacity={(props.payload?.ts ?? 0) < nowHour ? 0.25 : 0.6}
                            />
                        )}
                    />
                    {hasBand && (
                        <Area dataKey="band" name={t('forecast.band')} stroke="none" fill={CHART_LOCAL} fillOpacity={0.15} isAnimationActive={false} connectNulls={false} />
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
