import { useId } from 'react'
import { useTranslation } from 'react-i18next'
import { Area, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { AXIS_COLOR, CHART_GRID, CHART_GRIDLINE, CHART_LOCAL, FLOW_LOCAL_CONS } from '../../lib/chartTokens'
import { CHART_AXIS_TICK, CHART_TOOLTIP_STYLE } from '../../lib/chartTheme'
import { formatClockMinutes, kwFigure, liveCurveRows, liveDayAxis } from '../../lib/live'
import type { LiveCurve } from '../../types/api'

/**
 * Today's production and consumption in 5-minute means. A bucket without enough live data is a gap in
 * the line, never an interpolated value; consumption exists only where the whole ZEV was covered.
 */
export function LiveCurveChart({ curve }: { curve: LiveCurve }) {
    const { t } = useTranslation()
    const titleId = useId()
    const rows = liveCurveRows(curve.buckets)
    const hasValues = rows.some((row) => row.production !== null)
    const hasOwn = rows.some((row) => row.own !== null)
    const axis = liveDayAxis(curve.date)
    const kwTooltip = (value: unknown) => (typeof value === 'number' ? `${kwFigure(value * 1000)} kW` : String(value))

    return (
        <section className="card chart-card" aria-labelledby={titleId}>
            <h3 id={titleId}>{t('live.curve.title')}</h3>
            {!hasValues ? (
                <p className="muted">{t('live.curve.empty')}</p>
            ) : (
                <>
                    <ResponsiveContainer width="100%" height={260}>
                        <ComposedChart data={rows} margin={{ top: 4, right: 20, bottom: 4, left: 0 }}>
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
                            <Area
                                type="monotone"
                                dataKey="production"
                                name={t('live.curve.production')}
                                stroke={CHART_LOCAL}
                                fill={CHART_LOCAL}
                                fillOpacity={0.15}
                                strokeWidth={2}
                                dot={false}
                                connectNulls={false}
                                isAnimationActive={false}
                            />
                            <Line
                                type="monotone"
                                dataKey="consumption"
                                name={t('live.curve.consumption')}
                                stroke={FLOW_LOCAL_CONS}
                                strokeWidth={2}
                                dot={false}
                                connectNulls={false}
                                isAnimationActive={false}
                            />
                            {hasOwn && (
                                <Line
                                    type="monotone"
                                    dataKey="own"
                                    name={t('live.curve.own')}
                                    stroke={CHART_GRID}
                                    strokeWidth={2}
                                    dot={false}
                                    connectNulls={false}
                                    isAnimationActive={false}
                                />
                            )}
                        </ComposedChart>
                    </ResponsiveContainer>
                    <p className="muted">{t('live.curve.hint')}</p>
                </>
            )}
        </section>
    )
}
