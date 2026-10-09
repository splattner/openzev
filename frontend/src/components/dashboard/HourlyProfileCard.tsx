import { useTranslation } from 'react-i18next'
import { Bar, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { AXIS_COLOR, CHART_GRID, CHART_GRIDLINE, CHART_LOCAL, FLOW_LOCAL_CONS } from '../../lib/chartTokens'
import { CHART_AXIS_TICK, CHART_TOOLTIP_STYLE } from '../../lib/chartTheme'
import type { HourlyProfileEntry } from '../../types/api'

type HourlyProfilePoint = HourlyProfileEntry & {
    label: string
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
    const hasOwnSystem = data.some((entry) => entry.own_system_consumption_kwh !== undefined)
    return (
        <section className="card chart-card">
            <h3>
                {t('pages.dashboard.hourlyProfile.title')}
                {participantName ? ` — ${participantName}` : ''}
            </h3>
            <p className="muted chart-card-description">{t('pages.dashboard.hourlyProfile.description')}</p>
            {hasOwnSystem && <p className="muted chart-card-description">{t('pages.dashboard.hourlyProfile.ownSystemNote')}</p>}
            <ResponsiveContainer width="100%" height={320}>
                <ComposedChart data={data} margin={{ top: 4, right: 4, bottom: 4, left: 0 }}>
                    <CartesianGrid stroke={CHART_GRIDLINE} strokeDasharray="3 3" vertical={false} />
                    <XAxis dataKey="label" tick={CHART_AXIS_TICK} stroke={AXIS_COLOR} />
                    <YAxis tick={CHART_AXIS_TICK} stroke={AXIS_COLOR} unit=" kWh" width={60} tickFormatter={hourlyKwhTick} />
                    <Tooltip contentStyle={CHART_TOOLTIP_STYLE} formatter={hourlyKwhTooltipValue} />
                    <Legend />
                    <Bar dataKey="from_zev_kwh" name={t('pages.dashboard.chart.fromZev')} stackId="c" fill={CHART_LOCAL} />
                    <Bar dataKey="from_grid_kwh" name={t('pages.dashboard.chart.fromGrid')} stackId="c" fill={CHART_GRID} radius={[3, 3, 0, 0]} />
                    {hasOwnSystem && (
                        <Line
                            type="monotone"
                            dataKey="own_system_consumption_kwh"
                            name={t('pages.dashboard.chart.ownSystemConsumption')}
                            stroke={FLOW_LOCAL_CONS}
                            strokeWidth={2}
                            strokeDasharray="5 4"
                            dot={false}
                        />
                    )}
                </ComposedChart>
            </ResponsiveContainer>
        </section>
    )
}
