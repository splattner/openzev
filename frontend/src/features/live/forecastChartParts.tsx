import { useXAxisScale, useYAxisScale } from 'recharts'
import { AXIS_COLOR, CHART_LOCAL } from '../../lib/chartTokens'
import { formatClockMinutes, kwFigure } from '../../lib/live'

/**
 * The expected production is drawn the same way on the Today and the Tomorrow tab: one light bar per hour (past hours
 * paler still), the forecast's band as a min–max whisker over it, and the same tooltip. Both charts use these parts so the
 * two cannot drift apart. The bars stay light: what is expected must not outweigh what was measured.
 */

export const HOUR_MS = 3_600_000
const BAR_OPACITY = 0.35
const PAST_BAR_OPACITY = 0.15
const WHISKER_OPACITY = 0.7
const PAST_WHISKER_OPACITY = 0.35
/** Share of an hour's width left empty on each side of its bar. */
const BAR_GAP = 0.1
/** Half the width of a whisker's caps, px. */
const CAP = 4

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
 * The hourly bars and their bands, drawn from the chart's own axes (they need a numeric x axis in epoch ms and a y axis in
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
                const past = hour.start < nowHour
                const bandHigh = hour.band ? yScale(hour.band[1]) : undefined
                const bandLow = hour.band ? yScale(hour.band[0]) : undefined
                const centre = x + width / 2
                return (
                    <g key={hour.start}>
                        <rect
                            x={x} y={top} width={width} height={Math.max(baseline - top, 0)}
                            fill={CHART_LOCAL} fillOpacity={past ? PAST_BAR_OPACITY : BAR_OPACITY}
                        />
                        {typeof bandHigh === 'number' && typeof bandLow === 'number' && bandLow - bandHigh > 0.5 && (
                            // The range as one thin line with caps, so it reads as "between" and not as a stacked part of the bar.
                            <path
                                d={`M${centre},${bandHigh}V${bandLow}M${centre - CAP},${bandHigh}H${centre + CAP}M${centre - CAP},${bandLow}H${centre + CAP}`}
                                stroke={CHART_LOCAL} strokeWidth={1.25} strokeOpacity={past ? PAST_WHISKER_OPACITY : WHISKER_OPACITY} fill="none"
                            />
                        )}
                    </g>
                )
            })}
        </g>
    )
}
