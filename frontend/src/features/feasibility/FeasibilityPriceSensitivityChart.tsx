import { useTranslation } from 'react-i18next'
import {
    CartesianGrid,
    Line,
    LineChart,
    ReferenceArea,
    ReferenceLine,
    ResponsiveContainer,
    Tooltip,
    XAxis,
    YAxis,
} from 'recharts'
import type { FeasibilityFairPriceRange, FeasibilityPriceSensitivityPoint } from '../../types/api'
import { AXIS_COLOR, ANNOTATION_COLOR } from '../../lib/chartTokens'

// Categorical pair (two distinct parties, not a polarity) — validated
// colorblind-safe (worst adjacent CVD deltaE 30.3, normal-vision 33.3).
// Green already means "producer/local energy" throughout the app (PDF
// invoices, dashboard); blue already means "consumer/self-consumption benefit"
// in the other feasibility charts.
const PRODUCER_COLOR = '#16a34a'
const CONSUMER_COLOR = '#2563eb'
const FAIR_RANGE_FILL = '#9ca3af'

type Props = {
    priceSensitivity: FeasibilityPriceSensitivityPoint[]
    retailPriceChfPerKwh: number
    equalSplitPriceChfPerKwh: number | null
    fairPriceRange: FeasibilityFairPriceRange | null
}

function CustomTooltip({
    active,
    payload,
}: {
    active?: boolean
    payload?: Array<{ payload: { pricePct: number; priceChf: number; producerGain: number; consumerSavings: number } }>
}) {
    const { t } = useTranslation()
    if (!active || !payload?.length) return null
    const point = payload[0].payload
    return (
        <div style={{ background: '#fff', border: '1px solid #e5e7eb', borderRadius: 6, padding: '0.5rem 0.7rem', fontSize: '0.82rem' }}>
            <p style={{ margin: 0, fontWeight: 600 }}>
                {point.pricePct.toFixed(0)}% ({point.priceChf.toFixed(3)} CHF/kWh)
            </p>
            <p style={{ margin: 0, color: PRODUCER_COLOR }}>{t('pages.feasibility.chart.producerGain')}: CHF {point.producerGain.toFixed(2)}</p>
            <p style={{ margin: 0, color: CONSUMER_COLOR }}>{t('pages.feasibility.chart.consumerSavingsShort')}: CHF {point.consumerSavings.toFixed(2)}</p>
        </div>
    )
}

export function FeasibilityPriceSensitivityChart({
    priceSensitivity,
    retailPriceChfPerKwh,
    equalSplitPriceChfPerKwh,
    fairPriceRange,
}: Props) {
    const { t } = useTranslation()

    const data = priceSensitivity.map((point) => ({
        pricePct: Number(point.internal_price_pct_of_retail) * 100,
        priceChf: Number(point.internal_price_chf_per_kwh),
        producerGain: Number(point.producer_gain_chf),
        consumerSavings: Number(point.consumer_savings_chf),
    }))

    const toPct = (chf: number) => (retailPriceChfPerKwh > 0 ? (chf / retailPriceChfPerKwh) * 100 : 0)
    const equalSplitPct = equalSplitPriceChfPerKwh !== null ? toPct(equalSplitPriceChfPerKwh) : null
    const fairRangePct = fairPriceRange
        ? { low: toPct(Number(fairPriceRange.low_chf_per_kwh)), high: toPct(Number(fairPriceRange.high_chf_per_kwh)) }
        : null

    return (
        <div>
            <h4 style={{ margin: '0 0 0.2rem' }}>{t('pages.feasibility.chart.priceSensitivityTitle')}</h4>
            <p className="muted" style={{ margin: '0 0 0.3rem', fontSize: '0.85rem' }}>
                {t('pages.feasibility.chart.priceSensitivityDescription')}
            </p>
            <div style={{ display: 'flex', gap: '1rem', marginBottom: '0.4rem', fontSize: '0.78rem' }}>
                <span><span style={{ display: 'inline-block', width: 9, height: 9, background: PRODUCER_COLOR, borderRadius: 2, marginRight: 4 }} />{t('pages.feasibility.chart.producerGain')}</span>
                <span><span style={{ display: 'inline-block', width: 9, height: 9, background: CONSUMER_COLOR, borderRadius: 2, marginRight: 4 }} />{t('pages.feasibility.chart.consumerSavingsShort')}</span>
                {fairRangePct && (
                    <span><span style={{ display: 'inline-block', width: 9, height: 9, background: FAIR_RANGE_FILL, opacity: 0.4, borderRadius: 2, marginRight: 4 }} />{t('pages.feasibility.chart.fairRange')}</span>
                )}
            </div>
            <ResponsiveContainer width="100%" height={240}>
                <LineChart data={data} margin={{ top: 28, right: 20, left: 10, bottom: 10 }}>
                    <CartesianGrid stroke="#e5e7eb" vertical={false} />
                    <XAxis
                        dataKey="pricePct"
                        type="number"
                        domain={[0, 100]}
                        tickFormatter={(v: number) => `${v.toFixed(0)}%`}
                        stroke={AXIS_COLOR}
                        tick={{ fontSize: 11, fill: '#374151' }}
                        label={{ value: t('pages.feasibility.chart.internalPriceAxis'), position: 'insideBottom', offset: -5, fontSize: 11, fill: '#6b7280' }}
                    />
                    <YAxis
                        tickFormatter={(v: number) => v.toFixed(0)}
                        stroke={AXIS_COLOR}
                        tick={{ fontSize: 11, fill: '#374151' }}
                        label={{ value: 'CHF', angle: -90, position: 'insideLeft', fontSize: 11, fill: '#6b7280' }}
                    />
                    <Tooltip content={<CustomTooltip />} />
                    {fairRangePct && (
                        <ReferenceArea x1={fairRangePct.low} x2={fairRangePct.high} fill={FAIR_RANGE_FILL} fillOpacity={0.12} />
                    )}
                    {equalSplitPct !== null && (
                        <ReferenceLine
                            x={equalSplitPct}
                            stroke={ANNOTATION_COLOR}
                            strokeDasharray="4 3"
                            label={{ value: t('pages.feasibility.chart.equalSplitLabel'), position: 'top', fontSize: 11, fill: ANNOTATION_COLOR }}
                        />
                    )}
                    <Line type="monotone" dataKey="producerGain" stroke={PRODUCER_COLOR} strokeWidth={2} dot={false} isAnimationActive={false} />
                    <Line type="monotone" dataKey="consumerSavings" stroke={CONSUMER_COLOR} strokeWidth={2} dot={false} isAnimationActive={false} />
                </LineChart>
            </ResponsiveContainer>
            <p className="muted" style={{ fontSize: '0.78rem', margin: '0.4rem 0 0' }}>
                {t('pages.feasibility.chart.fairRangeHint')}
            </p>
        </div>
    )
}
