import { useTranslation } from 'react-i18next'
import { Bar, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { AXIS_COLOR, CHART_GRID, CHART_GRIDLINE, CHART_LABEL, CHART_LOCAL, FLOW_GRID_EXP, FLOW_LOCAL_CONS } from '../../lib/chartTokens'
import { CHART_AXIS_TICK, CHART_TOOLTIP_STYLE } from '../../lib/chartTheme'
import { formatConsumptionMixTooltip, formatProductionMixTooltip } from '../../lib/dashboardTooltips'
import type { ZevOwnerDashboardSummary } from '../../types/api'

type OwnerChartRow = ZevOwnerDashboardSummary['timeline'][number] & {
    locally_consumed: number
    locally_produced: number
    from_zev_rate: number | null
    self_consumption_rate: number | null
}

interface BalanceChartProps {
    data: OwnerChartRow[]
    zevName?: string
    participantName?: string
    formatBucketLabel: (value: string) => string
    formatBucketTooltipLabel: (label: unknown) => string
    kwhTick: (value: number) => string
}

export function BalanceChart({
    data,
    zevName,
    participantName,
    formatBucketLabel,
    formatBucketTooltipLabel,
    kwhTick,
}: BalanceChartProps) {
    const { t } = useTranslation()
    return (
        <section className="card">
            <h3 style={{ marginTop: 0 }}>
                {t('pages.dashboard.consumptionAndProduction')}
                {zevName ? ` — ${zevName}` : ''}
                {participantName ? ` — ${participantName}` : ''}
            </h3>
            {data.length === 0 ? (
                <p className="muted">{t('pages.dashboard.noData')}</p>
            ) : (
                <div className="form-grid" style={{ gap: '2rem' }}>
                    <div>
                        <p style={{ margin: '0 0 0.5rem', fontWeight: 600, fontSize: '0.875rem', color: CHART_LABEL }}>
                            {t('pages.dashboard.consumption')}
                        </p>
                        <ResponsiveContainer width="100%" height={300}>
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
                                <Bar yAxisId="kwh" dataKey="locally_consumed" name={t('pages.dashboard.chart.fromZev')} stackId="c" fill={CHART_LOCAL} />
                                <Bar yAxisId="kwh" dataKey="imported_kwh" name={t('pages.dashboard.chart.fromGrid')} stackId="c" fill={CHART_GRID} radius={[3, 3, 0, 0]} />
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
                    </div>
                    <div>
                        <p style={{ margin: '0 0 0.5rem', fontWeight: 600, fontSize: '0.875rem', color: CHART_LABEL }}>
                            {t('pages.dashboard.production')}
                        </p>
                        <ResponsiveContainer width="100%" height={300}>
                            <ComposedChart data={data} margin={{ top: 4, right: 50, bottom: 4, left: 0 }}>
                                <CartesianGrid stroke={CHART_GRIDLINE} strokeDasharray="3 3" vertical={false} />
                                <XAxis dataKey="bucket" tick={CHART_AXIS_TICK} stroke={AXIS_COLOR} tickFormatter={formatBucketLabel} />
                                <YAxis yAxisId="kwh" tick={CHART_AXIS_TICK} stroke={AXIS_COLOR} unit=" kWh" width={60} tickFormatter={kwhTick} />
                                <YAxis yAxisId="pct" orientation="right" tick={CHART_AXIS_TICK} stroke={AXIS_COLOR} unit="%" width={44} domain={[0, 100]} />
                                <Tooltip
                                    contentStyle={CHART_TOOLTIP_STYLE}
                                    labelFormatter={formatBucketTooltipLabel}
                                    formatter={(v, name, props) =>
                                        formatProductionMixTooltip(v, String(name), props?.dataKey, t('pages.dashboard.chart.selfConsumedPct'))
                                    }
                                />
                                <Legend />
                                <Bar yAxisId="kwh" dataKey="locally_produced" name={t('pages.dashboard.chart.usedLocally')} stackId="p" fill={CHART_LOCAL} />
                                <Bar yAxisId="kwh" dataKey="exported_kwh" name={t('pages.dashboard.chart.exported')} stackId="p" fill={FLOW_GRID_EXP} radius={[3, 3, 0, 0]} />
                                <Line
                                    yAxisId="pct"
                                    type="monotone"
                                    dataKey="self_consumption_rate"
                                    name={t('pages.dashboard.chart.selfConsumedPct')}
                                    stroke={FLOW_LOCAL_CONS}
                                    dot={false}
                                    strokeWidth={2}
                                    connectNulls
                                />
                            </ComposedChart>
                        </ResponsiveContainer>
                    </div>
                </div>
            )}
        </section>
    )
}
