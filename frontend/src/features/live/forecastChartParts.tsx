import { useXAxisScale, useYAxisScale } from 'recharts'
import { AXIS_COLOR, CHART_LOCAL } from '../../lib/chartTokens'
import { formatClockMinutes, kwFigure } from '../../lib/live'

/**
 * The expected production is drawn the same way on the Today and the Tomorrow tab: one solid bar per hour (past hours
 * paler), the forecast's band behind it, and the same tooltip. Both charts use these parts so the two cannot drift apart.
 */

export const HOUR_MS = 3_600_000
const BAR_OPACITY = 0.6
const PAST_BAR_OPACITY = 0.25
const BAND_OPACITY = 0.15
/** Share of an hour's width left empty on each side of its bar. */
const BAR_GAP = 0.1

/** One hour of the forecast; `start` is the hour's start (epoch ms), power and band in kW. */
export interface ForecastHourBar {
    start: number
    power: number
    band: [number, number] | null
}

const dayFormatter = new Intl.DateTimeFormat(undefined, { timeZone: 'Europe/Zurich', weekday: 'short', day: 'numeric', month: 'numeric' })

/** `Mon 3.11. 12:00`, the tooltip heading of both charts. */
export function forecastTooltipLabel(ts: number): string {
    return `${dayFormatter.format(new Date(ts))} ${formatClockMinutes(ts)}`
}

/** A kW value, or a `[min, max]` band as `3.8–6.5 kW`; the tooltip's text for every series of both charts. */
export function kwTooltipText(value: unknown): string {
    if (Array.isArray(value)) return `${kwFigure(Number(value[0]) * 1000)}–${kwFigure(Number(value[1]) * 1000)} kW`
    return typeof value === 'number' ? `${kwFigure(value * 1000)} kW` : String(value)
}

/** The tooltip's hover mark: a thin line, the same on both tabs. */
export const FORECAST_TOOLTIP_CURSOR = { stroke: AXIS_COLOR, strokeWidth: 1 }

/** A bar that draws nothing: the forecast series still takes part in the tooltip and the legend, while `ForecastHourBars` draws it. */
export const noBarShape = () => <g />

/**
 * The hourly bars and bands, drawn from the chart's own axes (they need a numeric x axis in epoch ms and a y axis in
 * kW). Rendered before the lines, so measured values stay in front of the expectation.
 */
export function ForecastHourBars({ hours, nowMs }: { hours: ForecastHourBar[]; nowMs: number }) {
    const xScale = useXAxisScale()
    const yScale = useYAxisScale()
    if (!xScale || !yScale) return null
    const nowHour = Math.floor(nowMs / HOUR_MS) * HOUR_MS
    const baseline = yScale(0)
    if (typeof baseline !== 'number') return null
    return (
        <g aria-hidden="true">
            {hours.map((hour) => {
                const left = xScale(hour.start)
                const right = xScale(hour.start + HOUR_MS)
                const top = yScale(hour.power)
                if (typeof left !== 'number' || typeof right !== 'number' || typeof top !== 'number') return null
                const gap = (right - left) * BAR_GAP
                const x = left + gap
                const width = Math.max(right - left - 2 * gap, 0)
                const bandTop = hour.band ? yScale(hour.band[1]) : undefined
                const bandBottom = hour.band ? yScale(hour.band[0]) : undefined
                return (
                    <g key={hour.start}>
                        {typeof bandTop === 'number' && typeof bandBottom === 'number' && (
                            <rect x={x} y={bandTop} width={width} height={Math.max(bandBottom - bandTop, 0)} fill={CHART_LOCAL} fillOpacity={BAND_OPACITY} />
                        )}
                        <rect
                            x={x} y={top} width={width} height={Math.max(baseline - top, 0)}
                            fill={CHART_LOCAL} fillOpacity={hour.start < nowHour ? PAST_BAR_OPACITY : BAR_OPACITY}
                        />
                    </g>
                )
            })}
        </g>
    )
}
