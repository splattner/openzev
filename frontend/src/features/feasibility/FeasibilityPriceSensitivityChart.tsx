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
import { ANNOTATION_COLOR, AXIS_COLOR, CHART_GRID, CHART_GRIDLINE, CONS_COLORS, PROD_COLORS } from '../../lib/chartTokens'
import { CHART_AXIS_TICK, CHART_TOOLTIP_STYLE, CHF_Y_AXIS_LABEL, ChartLegendSwatch, chartAxisLabel } from '../../lib/chartTheme'
import { formatChf, formatNumber, formatPercent } from '../../lib/numbers'

// Categorical pair (two distinct parties, not a polarity) — validated
// colorblind-safe (worst adjacent CVD deltaE 30.3, normal-vision 33.3).
// Forest means "producer/local energy" throughout the app and the PDFs; slate
// means consumption. The fair price range is a warm band behind both lines.
const PRODUCER_COLOR = PROD_COLORS[0]
const CONSUMER_COLOR = CONS_COLORS[0]
const FAIR_RANGE_FILL = CHART_GRID

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
        <div style={CHART_TOOLTIP_STYLE}>
            <p style={{ margin: 0, fontWeight: 600 }}>
                {formatPercent(point.pricePct, { maxDecimals: 0 })} ({formatNumber(point.priceChf, { minDecimals: 3, maxDecimals: 3 })} CHF/kWh)
            </p>
            <p style={{ margin: 0, color: PRODUCER_COLOR }}>{t('pages.feasibility.chart.producerGain')}: {formatChf(point.producerGain)}</p>
            <p style={{ margin: 0, color: CONSUMER_COLOR }}>{t('pages.feasibility.chart.consumerSavingsShort')}: {formatChf(point.consumerSavings)}</p>
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
            <h4 className="section-title">{t('pages.feasibility.chart.priceSensitivityTitle')}</h4>
            <p className="muted" style={{ margin: '0 0 0.3rem', fontSize: '0.85rem' }}>
                {t('pages.feasibility.chart.priceSensitivityDescription')}
            </p>
            <div style={{ display: 'flex', gap: '1rem', marginBottom: '0.4rem', fontSize: '0.78rem' }}>
                <span><ChartLegendSwatch color={PRODUCER_COLOR} />{t('pages.feasibility.chart.producerGain')}</span>
                <span><ChartLegendSwatch color={CONSUMER_COLOR} />{t('pages.feasibility.chart.consumerSavingsShort')}</span>
                {fairRangePct && (
                    <span><ChartLegendSwatch color={FAIR_RANGE_FILL} opacity={0.4} />{t('pages.feasibility.chart.fairRange')}</span>
                )}
            </div>
            <ResponsiveContainer width="100%" height={240}>
                <LineChart data={data} margin={{ top: 28, right: 20, left: 10, bottom: 10 }}>
                    <CartesianGrid stroke={CHART_GRIDLINE} vertical={false} />
                    <XAxis
                        dataKey="pricePct"
                        type="number"
                        domain={[0, 100]}
                        tickFormatter={(v: number) => formatPercent(v, { maxDecimals: 0 })}
                        stroke={AXIS_COLOR}
                        tick={CHART_AXIS_TICK}
                        label={chartAxisLabel(t('pages.feasibility.chart.internalPriceAxis'))}
                    />
                    <YAxis
                        tickFormatter={(v: number) => formatNumber(v, { maxDecimals: 0 })}
                        stroke={AXIS_COLOR}
                        tick={CHART_AXIS_TICK}
                        label={CHF_Y_AXIS_LABEL}
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
