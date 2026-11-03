import { useTranslation } from 'react-i18next'
import {
    CartesianGrid,
    Legend,
    Line,
    LineChart,
    ReferenceArea,
    ReferenceLine,
    ResponsiveContainer,
    Tooltip,
    XAxis,
    YAxis,
} from 'recharts'
import { formatShortDate } from '../../../lib/appSettings'
import { AXIS_COLOR, CHART_GRID, CHART_GRIDLINE, CHART_INK, CHART_LOCAL, CHART_MUTED, FLOW_GRID_EXP, FLOW_LOCAL_CONS, NEGATIVE_COLOR } from '../../../lib/chartTokens'
import { CHART_AXIS_TICK, CHART_TOOLTIP_STYLE } from '../../../lib/chartTheme'
import { formatUtcIsoDate } from '../../../lib/dates'
import { formatNumber } from '../../../lib/numbers'
import type { AppSettings, TariffProgression } from '../../../types/api'
import { dayMs, type ProgressionChartData } from './progression'

/** Distinct hues, each also given its own dash pattern so colour is never the only cue. */
const LINE_COLORS = [FLOW_LOCAL_CONS, CHART_GRID, CHART_LOCAL, CHART_INK, FLOW_GRID_EXP, CHART_MUTED]
const LINE_DASHES = [undefined, '6 3', '2 3', '8 3 2 3', '1 3', '10 4']

type Props = {
    progression: TariffProgression
    data: ProgressionChartData
    lineNames: Record<string, string>
    settings: AppSettings
    /** The day the composition table shows, drawn as a vertical rule. */
    day: string
    onPickDay: (day: string) => void
}

export function TariffProgressionChart({ progression, data, lineNames, settings, day, onPickDay }: Props) {
    const { t } = useTranslation()
    const unit = t('pages.tariffs.chfPerKwh')

    return (
        <div className="tariff-progression-chart">
            <ResponsiveContainer width="100%" height={280}>
                <LineChart
                    data={data.points}
                    margin={{ top: 8, right: 16, left: 4, bottom: 4 }}
                    onClick={(state) => {
                        // The chart reports the data point nearest the click, the same one the
                        // tooltip shows, so the table below describes what was just read.
                        const label = Number((state as { activeLabel?: unknown } | undefined)?.activeLabel)
                        if (Number.isFinite(label)) onPickDay(formatUtcIsoDate(new Date(label)))
                    }}
                >
                    <CartesianGrid strokeDasharray="3 3" stroke={CHART_GRIDLINE} />
                    {/* Shade stretches whose total is understated or missing: the line alone
                        would read as the real price. */}
                    {data.flagged.map((stretch) => (
                        <ReferenceArea
                            key={stretch.from}
                            x1={stretch.from}
                            x2={stretch.to}
                            fill={NEGATIVE_COLOR}
                            fillOpacity={0.1}
                            stroke="none"
                        />
                    ))}
                    <XAxis
                        dataKey="t"
                        type="number"
                        scale="time"
                        domain={[dayMs(progression.from), dayMs(progression.to)]}
                        allowDataOverflow
                        tickFormatter={(value: number) => formatShortDate(formatUtcIsoDate(new Date(value)), settings)}
                        stroke={AXIS_COLOR}
                        tick={CHART_AXIS_TICK}
                        minTickGap={40}
                    />
                    <YAxis
                        stroke={AXIS_COLOR}
                        tick={CHART_AXIS_TICK}
                        tickFormatter={(value: number) => formatNumber(value, { minDecimals: 3, maxDecimals: 3 })}
                        width={56}
                    />
                    <Tooltip
                        labelFormatter={(value) => formatShortDate(formatUtcIsoDate(new Date(Number(value))), settings)}
                        formatter={(value, name) => [
                            value === null || value === undefined
                                ? t('pages.tariffs.priceHistory.noPrice')
                                : `${formatNumber(Number(value), { minDecimals: 3, maxDecimals: 5 })} ${unit}`,
                            lineNames[String(name)] ?? String(name),
                        ]}
                        contentStyle={CHART_TOOLTIP_STYLE}
                    />
                    <ReferenceLine x={dayMs(day)} stroke={CHART_MUTED} strokeDasharray="2 2" />
                    {progression.lines.length > 1 && <Legend wrapperStyle={{ fontSize: '0.72rem' }} formatter={(value) => lineNames[String(value)] ?? String(value)} />}
                    {progression.lines.map((line, index) => (
                        <Line
                            key={line.key}
                            // Stepped, not interpolated: a price holds for its whole validity
                            // window and then jumps.
                            type="stepAfter"
                            dataKey={line.key}
                            name={line.key}
                            stroke={LINE_COLORS[index % LINE_COLORS.length]}
                            strokeDasharray={LINE_DASHES[index % LINE_DASHES.length]}
                            strokeWidth={2}
                            dot={{ r: 3 }}
                            activeDot={{ r: 5 }}
                            connectNulls={false}
                            isAnimationActive={false}
                        />
                    ))}
                </LineChart>
            </ResponsiveContainer>
        </div>
    )
}
