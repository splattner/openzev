import { useTranslation } from 'react-i18next'
import {
    Bar,
    BarChart,
    CartesianGrid,
    ReferenceLine,
    ResponsiveContainer,
    Tooltip,
    XAxis,
    YAxis,
} from 'recharts'
import { AXIS_COLOR, ANNOTATION_COLOR } from '../../lib/chartTokens'

// Same validated blue/red diverging pair as the sensitivity chart.
const POSITIVE_COLOR = '#2563eb'
const NEGATIVE_COLOR = '#dc2626'

type BarShapeProps = {
    x?: number
    y?: number
    width?: number
    height?: number
    payload?: { value: number }
}

// Recharts doesn't round bar corners per-sign automatically: a negative bar's
// rect grows *down* from the baseline (so its far end is the bottom), a
// positive bar's rect grows *up* to the baseline (so its far end is the top).
// Round only the far-from-baseline end, per the dataviz skill's bar spec.
function DivergingBarShape({ x = 0, y = 0, width = 0, height = 0, payload }: BarShapeProps) {
    const isNegative = (payload?.value ?? 0) < 0
    const r = Math.max(0, Math.min(4, width / 2, Math.abs(height)))
    const fill = isNegative ? NEGATIVE_COLOR : POSITIVE_COLOR

    const path = isNegative
        ? `M${x},${y} L${x + width},${y} L${x + width},${y + height - r}
           Q${x + width},${y + height} ${x + width - r},${y + height}
           L${x + r},${y + height} Q${x},${y + height} ${x},${y + height - r} Z`
        : `M${x},${y + r} Q${x},${y} ${x + r},${y} L${x + width - r},${y}
           Q${x + width},${y} ${x + width},${y + r}
           L${x + width},${y + height} L${x},${y + height} Z`

    return <path d={path} fill={fill} />
}

function CustomTooltip({ active, payload }: { active?: boolean; payload?: Array<{ value: number; payload: { year: number } }> }) {
    const { t } = useTranslation()
    if (!active || !payload?.length) return null
    const point = payload[0]
    return (
        <div style={{ background: '#fff', border: '1px solid #e5e7eb', borderRadius: 6, padding: '0.5rem 0.7rem', fontSize: '0.82rem' }}>
            <p style={{ margin: 0, fontWeight: 600 }}>{t('pages.feasibility.chart.yearLabel', { year: point.payload.year })}</p>
            <p style={{ margin: 0, color: point.value < 0 ? NEGATIVE_COLOR : POSITIVE_COLOR }}>
                CHF {point.value.toFixed(2)}
            </p>
        </div>
    )
}

type Props = {
    cashflowByYear: string[]
    paybackYears: number | null
}

export function FeasibilityCashflowChart({ cashflowByYear, paybackYears }: Props) {
    const { t } = useTranslation()
    const horizonYears = cashflowByYear.length - 1
    const data = cashflowByYear.map((value, year) => ({ year, value: Number(value) }))

    return (
        <div>
            <h4 style={{ margin: '0 0 0.2rem' }}>{t('pages.feasibility.chart.cashflowTitle')}</h4>
            <p className="muted" style={{ margin: '0 0 0.3rem', fontSize: '0.85rem' }}>
                {t('pages.feasibility.chart.cashflowDescription')}
            </p>
            <div style={{ display: 'flex', gap: '1rem', marginBottom: '0.4rem', fontSize: '0.78rem' }}>
                <span><span style={{ display: 'inline-block', width: 9, height: 9, background: POSITIVE_COLOR, borderRadius: 2, marginRight: 4 }} />{t('pages.feasibility.chart.cumulativeSurplus')}</span>
                <span><span style={{ display: 'inline-block', width: 9, height: 9, background: NEGATIVE_COLOR, borderRadius: 2, marginRight: 4 }} />{t('pages.feasibility.chart.cumulativeDeficit')}</span>
            </div>
            <ResponsiveContainer width="100%" height={240}>
                <BarChart data={data} margin={{ top: 28, right: 20, left: 10, bottom: 10 }}>
                    <CartesianGrid stroke="#e5e7eb" vertical={false} />
                    <XAxis
                        dataKey="year"
                        type="number"
                        domain={[0, horizonYears]}
                        allowDecimals={false}
                        stroke={AXIS_COLOR}
                        tick={{ fontSize: 11, fill: '#374151' }}
                        label={{ value: t('pages.feasibility.chart.yearAxis'), position: 'insideBottom', offset: -5, fontSize: 11, fill: '#6b7280' }}
                    />
                    <YAxis
                        tickFormatter={(v: number) => v.toFixed(0)}
                        stroke={AXIS_COLOR}
                        tick={{ fontSize: 11, fill: '#374151' }}
                        label={{ value: 'CHF', angle: -90, position: 'insideLeft', fontSize: 11, fill: '#6b7280' }}
                    />
                    <Tooltip content={<CustomTooltip />} />
                    <ReferenceLine y={0} stroke="#d1d5db" strokeWidth={1} />
                    {paybackYears !== null && paybackYears <= horizonYears && (
                        <ReferenceLine
                            x={paybackYears}
                            stroke={ANNOTATION_COLOR}
                            strokeDasharray="4 3"
                            label={{ value: t('pages.feasibility.chart.paybackLabel', { years: paybackYears.toFixed(1) }), position: 'top', fontSize: 11, fill: ANNOTATION_COLOR }}
                        />
                    )}
                    <Bar dataKey="value" shape={DivergingBarShape} isAnimationActive={false} />
                </BarChart>
            </ResponsiveContainer>
        </div>
    )
}
