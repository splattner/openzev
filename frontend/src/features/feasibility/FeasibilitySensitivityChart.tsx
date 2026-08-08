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
import { AXIS_COLOR, ANNOTATION_COLOR } from '../../lib/chartTokens'

// Blue/red diverging pair — validated colorblind-safe (worst adjacent CVD deltaE
// 29.9, normal-vision 38.2; see dataviz skill's validate_palette.js). Green/red
// was rejected here: it fails the deuteranopia check (deltaE 5.0).
const LINE_COLOR = '#2563eb'
const NEGATIVE_COLOR = '#dc2626'

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
        <div style={{ background: '#fff', border: '1px solid #e5e7eb', borderRadius: 6, padding: '0.5rem 0.7rem', fontSize: '0.82rem' }}>
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
                    <CartesianGrid stroke="#e5e7eb" vertical={false} />
                    <XAxis
                        dataKey="ratePct"
                        type="number"
                        domain={[0, 100]}
                        tickFormatter={(v: number) => `${v.toFixed(0)}%`}
                        stroke={AXIS_COLOR}
                        tick={{ fontSize: 11, fill: '#374151' }}
                        label={{ value: t('pages.feasibility.chart.selfConsumptionAxis'), position: 'insideBottom', offset: -5, fontSize: 11, fill: '#6b7280' }}
                    />
                    <YAxis
                        tickFormatter={(v: number) => v.toFixed(0)}
                        stroke={AXIS_COLOR}
                        tick={{ fontSize: 11, fill: '#374151' }}
                        label={{ value: 'CHF', angle: -90, position: 'insideLeft', fontSize: 11, fill: '#6b7280' }}
                    />
                    <Tooltip content={<CustomTooltip />} />
                    <ReferenceLine y={0} stroke="#d1d5db" strokeWidth={1} />
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
                        stroke="#fff"
                        strokeWidth={2}
                        label={{ value: t('pages.feasibility.chart.yourScenario'), position: 'top', fontSize: 11, fontWeight: 600, fill: '#111827' }}
                    />
                </LineChart>
            </ResponsiveContainer>
        </div>
    )
}
