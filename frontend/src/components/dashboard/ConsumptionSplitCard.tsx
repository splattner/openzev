import { useTranslation } from 'react-i18next'
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { AXIS_COLOR, CHART_GRID, CHART_GRIDLINE, CHART_LOCAL } from '../../lib/chartTokens'
import { CHART_AXIS_TICK, CHART_TOOLTIP_STYLE } from '../../lib/chartTheme'

interface ConsumptionSplitPoint {
    bucket: string
    consumed_from_zev_kwh: number
    imported_from_grid_kwh: number
    total_consumed_kwh: number
}

interface ConsumptionSplitCardProps {
    data: ConsumptionSplitPoint[]
    formatBucketLabel: (value: string) => string
    formatBucketTooltipLabel: (label: unknown) => string
    kwhTick: (value: number) => string
    kwhTooltipValue: (value: unknown) => string
}

export function ConsumptionSplitCard({
    data,
    formatBucketLabel,
    formatBucketTooltipLabel,
    kwhTick,
    kwhTooltipValue,
}: ConsumptionSplitCardProps) {
    const { t } = useTranslation()
    return (
        <section className="card" style={{ minHeight: 360 }}>
            <h3 style={{ marginTop: 0 }}>{t('pages.dashboard.consumptionSplit')}</h3>
            {data.length === 0 ? (
                <p className="muted">{t('pages.dashboard.noData')}</p>
            ) : (
                <ResponsiveContainer width="100%" height={320}>
                    <BarChart data={data} margin={{ top: 4, right: 4, bottom: 4, left: 0 }}>
                        <CartesianGrid stroke={CHART_GRIDLINE} strokeDasharray="3 3" vertical={false} />
                        <XAxis dataKey="bucket" tick={CHART_AXIS_TICK} stroke={AXIS_COLOR} tickFormatter={formatBucketLabel} />
                        <YAxis tick={CHART_AXIS_TICK} stroke={AXIS_COLOR} unit=" kWh" width={60} tickFormatter={kwhTick} />
                        <Tooltip contentStyle={CHART_TOOLTIP_STYLE} formatter={kwhTooltipValue} labelFormatter={formatBucketTooltipLabel} />
                        <Legend />
                        <Bar dataKey="consumed_from_zev_kwh" name={t('pages.dashboard.chart.fromZev')} stackId="c" fill={CHART_LOCAL} />
                        <Bar dataKey="imported_from_grid_kwh" name={t('pages.dashboard.chart.fromGrid')} stackId="c" fill={CHART_GRID} radius={[3, 3, 0, 0]} />
                    </BarChart>
                </ResponsiveContainer>
            )}
        </section>
    )
}
