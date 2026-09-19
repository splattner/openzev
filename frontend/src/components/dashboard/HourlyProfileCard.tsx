import { useTranslation } from 'react-i18next'
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { AXIS_COLOR, CHART_GRID, CHART_GRIDLINE, CHART_LOCAL } from '../../lib/chartTokens'
import { CHART_AXIS_TICK, CHART_TOOLTIP_STYLE } from '../../lib/chartTheme'

interface HourlyProfilePoint {
    label: string
    from_zev_kwh: number
    from_grid_kwh: number
}

interface HourlyProfileCardProps {
    data: HourlyProfilePoint[]
    hourlyKwhTick: (value: number) => string
    hourlyKwhTooltipValue: (value: unknown) => string
    participantName?: string
}

/** Average 24 h draw, split between local ZEV energy and grid import. */
export function HourlyProfileCard({ data, hourlyKwhTick, hourlyKwhTooltipValue, participantName }: HourlyProfileCardProps) {
    const { t } = useTranslation()
    if (data.length === 0) return null
    return (
        <section className="card" style={{ minHeight: 360 }}>
            <h3 style={{ marginTop: 0 }}>
                {t('pages.dashboard.hourlyProfile.title')}
                {participantName ? ` — ${participantName}` : ''}
            </h3>
            <p className="muted" style={{ marginTop: 0, fontSize: '0.875rem' }}>{t('pages.dashboard.hourlyProfile.description')}</p>
            <ResponsiveContainer width="100%" height={320}>
                <BarChart data={data} margin={{ top: 4, right: 4, bottom: 4, left: 0 }}>
                    <CartesianGrid stroke={CHART_GRIDLINE} strokeDasharray="3 3" vertical={false} />
                    <XAxis dataKey="label" tick={CHART_AXIS_TICK} stroke={AXIS_COLOR} />
                    <YAxis tick={CHART_AXIS_TICK} stroke={AXIS_COLOR} unit=" kWh" width={60} tickFormatter={hourlyKwhTick} />
                    <Tooltip contentStyle={CHART_TOOLTIP_STYLE} formatter={hourlyKwhTooltipValue} />
                    <Legend />
                    <Bar dataKey="from_zev_kwh" name={t('pages.dashboard.chart.fromZev')} stackId="c" fill={CHART_LOCAL} />
                    <Bar dataKey="from_grid_kwh" name={t('pages.dashboard.chart.fromGrid')} stackId="c" fill={CHART_GRID} radius={[3, 3, 0, 0]} />
                </BarChart>
            </ResponsiveContainer>
        </section>
    )
}
