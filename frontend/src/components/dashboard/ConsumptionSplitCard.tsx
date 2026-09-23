import { useTranslation } from 'react-i18next'
import { Bar, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { AXIS_COLOR, CHART_GRID, CHART_GRIDLINE, CHART_LOCAL, FLOW_LOCAL_CONS } from '../../lib/chartTokens'
import { CHART_AXIS_TICK, CHART_TOOLTIP_STYLE } from '../../lib/chartTheme'
import { formatConsumptionMixTooltip } from '../../lib/dashboardTooltips'
import type { ParticipantDashboardSummary } from '../../types/api'

type ConsumptionSplitPoint = ParticipantDashboardSummary['timeline'][number] & {
    from_zev_rate: number | null
}

interface ConsumptionSplitCardProps {
    data: ConsumptionSplitPoint[]
    formatBucketLabel: (value: string) => string
    formatBucketTooltipLabel: (label: unknown) => string
    kwhTick: (value: number) => string
}

export function ConsumptionSplitCard({
    data,
    formatBucketLabel,
    formatBucketTooltipLabel,
    kwhTick,
}: ConsumptionSplitCardProps) {
    const { t } = useTranslation()
    return (
        <section className="card" style={{ minHeight: 360 }}>
            <h3 style={{ marginTop: 0 }}>{t('pages.dashboard.consumptionSplit')}</h3>
            {data.length === 0 ? (
                <p className="muted">{t('pages.dashboard.noData')}</p>
            ) : (
                <ResponsiveContainer width="100%" height={320}>
                    <ComposedChart data={data} margin={{ top: 4, right: 50, bottom: 4, left: 0 }}>
                        <CartesianGrid stroke={CHART_GRIDLINE} strokeDasharray="3 3" vertical={false} />
                        <XAxis dataKey="bucket" tick={CHART_AXIS_TICK} stroke={AXIS_COLOR} tickFormatter={formatBucketLabel} />
                        <YAxis yAxisId="kwh" tick={CHART_AXIS_TICK} stroke={AXIS_COLOR} unit=" kWh" width={60} tickFormatter={kwhTick} />
                        <YAxis yAxisId="pct" orientation="right" tick={CHART_AXIS_TICK} stroke={AXIS_COLOR} unit="%" width={44} domain={[0, 100]} />
                        <Tooltip
                            contentStyle={CHART_TOOLTIP_STYLE}
                            labelFormatter={formatBucketTooltipLabel}
                            formatter={(v, name, props) =>
                                formatConsumptionMixTooltip(v, String(name), props?.dataKey, t('pages.dashboard.chart.fromZevPct'))
                            }
                        />
                        <Legend />
                        <Bar yAxisId="kwh" dataKey="consumed_from_zev_kwh" name={t('pages.dashboard.chart.fromZev')} stackId="c" fill={CHART_LOCAL} />
                        <Bar yAxisId="kwh" dataKey="imported_from_grid_kwh" name={t('pages.dashboard.chart.fromGrid')} stackId="c" fill={CHART_GRID} radius={[3, 3, 0, 0]} />
                        <Line
                            yAxisId="pct"
                            type="monotone"
                            dataKey="from_zev_rate"
                            name={t('pages.dashboard.chart.fromZevPct')}
                            stroke={FLOW_LOCAL_CONS}
                            dot={false}
                            strokeWidth={2}
                            connectNulls
                        />
                    </ComposedChart>
                </ResponsiveContainer>
            )}
        </section>
    )
}
