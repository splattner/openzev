import { useTranslation } from 'react-i18next'
import {
    CartesianGrid,
    Line,
    LineChart,
    ReferenceDot,
    ReferenceLine,
    ResponsiveContainer,
    Tooltip,
    XAxis,
    YAxis,
} from 'recharts'
import type { FeasibilitySensitivityPoint } from '../../types/api'
import { ANNOTATION_COLOR, AXIS_COLOR, CHART_GRIDLINE, CHART_INK, DIVERGING_POSITIVE, NEGATIVE_COLOR } from '../../lib/chartTokens'
import { CHART_AXIS_TICK, CHART_TOOLTIP_STYLE, CHF_Y_AXIS_LABEL, chartAxisLabel } from '../../lib/chartTheme'

// Blue/red diverging pair — validated colorblind-safe (worst adjacent CVD deltaE
// 29.9, normal-vision 38.2; see dataviz skill's validate_palette.js). Green/red
// was rejected here: it fails the deuteranopia check (deltaE 5.0).
const LINE_COLOR = DIVERGING_POSITIVE


type Props = {
    sensitivity: FeasibilitySensitivityPoint[]
    currentRatePct: number
    currentNetBenefitChf: number
    breakEvenRatePct: number | null
}

function CustomTooltip({ active, payload }: { active?: boolean; payload?: Array<{ value: number; payload: { ratePct: number } }> }) {
    const { t } = useTranslation()
    if (!active || !payload?.length) return null
    const point = payload[0]
    return (
        <div style={CHART_TOOLTIP_STYLE}>
            <p style={{ margin: 0, fontWeight: 600 }}>{point.payload.ratePct.toFixed(0)}% {t('pages.feasibility.chart.selfConsumptionShort')}</p>
            <p style={{ margin: 0, color: point.value < 0 ? NEGATIVE_COLOR : LINE_COLOR }}>
                CHF {point.value.toFixed(2)}
            </p>
        </div>
    )
}

export function FeasibilitySensitivityChart({ sensitivity, currentRatePct, currentNetBenefitChf, breakEvenRatePct }: Props) {
    const { t } = useTranslation()

    const data = sensitivity.map((point) => ({
        ratePct: Number(point.self_consumption_rate) * 100,
        value: Number(point.annual_net_benefit_chf),
    }))

    return (
        <div>
            <h4 style={{ margin: '0 0 0.2rem' }}>{t('pages.feasibility.chart.sensitivityTitle')}</h4>
            <p className="muted" style={{ margin: '0 0 0.6rem', fontSize: '0.85rem' }}>
                {t('pages.feasibility.chart.sensitivityDescription')}
            </p>
            <ResponsiveContainer width="100%" height={240}>
                <LineChart data={data} margin={{ top: 28, right: 20, left: 10, bottom: 10 }}>
                    <CartesianGrid stroke={CHART_GRIDLINE} vertical={false} />
                    <XAxis
                        dataKey="ratePct"
                        type="number"
                        domain={[0, 100]}
                        tickFormatter={(v: number) => `${v.toFixed(0)}%`}
                        stroke={AXIS_COLOR}
                        tick={CHART_AXIS_TICK}
                        label={chartAxisLabel(t('pages.feasibility.chart.selfConsumptionAxis'))}
                    />
                    <YAxis
                        tickFormatter={(v: number) => v.toFixed(0)}
                        stroke={AXIS_COLOR}
                        tick={CHART_AXIS_TICK}
                        label={CHF_Y_AXIS_LABEL}
                    />
                    <Tooltip content={<CustomTooltip />} />
                    <ReferenceLine y={0} stroke={CHART_GRIDLINE} strokeWidth={1} />
                    {breakEvenRatePct !== null && (
                        <ReferenceLine
                            x={breakEvenRatePct}
                            stroke={ANNOTATION_COLOR}
                            strokeDasharray="4 3"
                            label={{ value: t('pages.feasibility.chart.breakEvenLabel', { rate: breakEvenRatePct.toFixed(0) }), position: 'top', fontSize: 11, fill: ANNOTATION_COLOR }}
                        />
                    )}
                    <Line type="monotone" dataKey="value" stroke={LINE_COLOR} strokeWidth={2} dot={false} isAnimationActive={false} />
                    <ReferenceDot
                        x={currentRatePct}
                        y={currentNetBenefitChf}
                        r={5}
                        fill={currentNetBenefitChf < 0 ? NEGATIVE_COLOR : LINE_COLOR}
                        stroke="var(--surface-card)"
                        strokeWidth={2}
                        label={{ value: t('pages.feasibility.chart.yourScenario'), position: 'top', fontSize: 11, fontWeight: 600, fill: CHART_INK }}
                    />
                </LineChart>
            </ResponsiveContainer>
        </div>
    )
}
