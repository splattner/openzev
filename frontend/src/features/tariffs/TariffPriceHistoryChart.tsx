import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import {
    CartesianGrid,
    Legend,
    Line,
    LineChart,
    ReferenceArea,
    ResponsiveContainer,
    Tooltip,
    XAxis,
    YAxis,
} from 'recharts'
import { formatShortDate } from '../../lib/appSettings'
import type { AppSettings, TariffSeries } from '../../types/api'
import { buildPriceHistory, type BandKey, type PriceUnit } from './priceHistory'
import { todayIso } from './validity'

// Blue and orange are the colourblind-safe pair and carry the two bands that
// actually co-occur (HT and NT). Flat never shares a version with HT/NT in
// practice, so its blue can be reused without an ambiguous adjacency.
const BAND_COLOR: Record<BandKey, string> = {
    flat: '#2563eb',
    high: '#ea580c',
    low: '#0891b2',
    amount: '#2563eb',
    effective: '#2563eb',
}
const AXIS_COLOR = '#9ca3af'
const GAP_FILL = '#ef4444'

type Props = {
    series: TariffSeries
    allSeries: TariffSeries[]
    settings: AppSettings
}

function decimalsFor(unit: PriceUnit): number {
    return unit === 'chf' ? 2 : 5
}

export function TariffPriceHistoryChart({ series, allSeries, settings }: Props) {
    const { t } = useTranslation()
    const today = todayIso()

    const history = useMemo(
        () => buildPriceHistory(series, allSeries, today),
        [series, allSeries, today],
    )

    // Recharts wants each band as a top-level key, while the builder keeps them
    // nested so the shape stays easy to assert in tests.
    const data = useMemo(
        () => history.points.map((point) => ({ t: point.t, note: point.note, ...point.values })),
        [history.points],
    )

    if (data.length < 2) return null

    const decimals = decimalsFor(history.unit)
    const unitLabel = history.unit === 'chf_per_kwh'
        ? t('pages.tariffs.chfPerKwh')
        : history.unit === 'chf'
            ? 'CHF'
            : '%'

    return (
        <div className="tariff-price-history">
            <div className="tariff-price-history-header">
                <h4>{t('pages.tariffs.priceHistory.title')}</h4>
                <span className="muted">{unitLabel}</span>
            </div>

            {history.derived && (
                <p className="muted tariff-price-history-note">
                    {t('pages.tariffs.priceHistory.derivedNote')}
                </p>
            )}

            <ResponsiveContainer width="100%" height={220}>
                <LineChart data={data} margin={{ top: 8, right: 16, left: 4, bottom: 4 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                    {/* Shade uncovered stretches: nothing was billed there, and the
                        broken line alone does not say why. */}
                    {history.gaps.map((gap) => (
                        <ReferenceArea
                            key={gap.from}
                            x1={gap.from}
                            x2={gap.to}
                            fill={GAP_FILL}
                            fillOpacity={0.1}
                            stroke="none"
                        />
                    ))}
                    <XAxis
                        dataKey="t"
                        type="number"
                        scale="time"
                        domain={['dataMin', 'dataMax']}
                        tickFormatter={(value: number) => formatShortDate(new Date(value).toISOString().slice(0, 10), settings)}
                        stroke={AXIS_COLOR}
                        fontSize={11}
                        minTickGap={40}
                    />
                    <YAxis
                        stroke={AXIS_COLOR}
                        fontSize={11}
                        tickFormatter={(value: number) => value.toFixed(decimals === 5 ? 3 : 2)}
                        width={56}
                    />
                    <Tooltip
                        labelFormatter={(value) => formatShortDate(new Date(Number(value)).toISOString().slice(0, 10), settings)}
                        formatter={(value, name) => [
                            value === null || value === undefined
                                ? t('pages.tariffs.priceHistory.noPrice')
                                : `${Number(value).toFixed(decimals)} ${unitLabel}`,
                            t(`pages.tariffs.priceHistory.bands.${name}` as Parameters<typeof t>[0], { defaultValue: String(name) }),
                        ]}
                        contentStyle={{ fontSize: '0.82rem', borderRadius: 6 }}
                    />
                    {history.bands.length > 1 && (
                        <Legend wrapperStyle={{ fontSize: '0.72rem' }} />
                    )}
                    {history.bands.map((band) => (
                        <Line
                            key={band}
                            // Stepped, not interpolated: a price holds for its whole
                            // validity window and then jumps. A smooth line would
                            // claim it drifted between two Januaries.
                            type="stepAfter"
                            dataKey={band}
                            name={t(`pages.tariffs.priceHistory.bands.${band}` as Parameters<typeof t>[0], { defaultValue: band })}
                            stroke={BAND_COLOR[band]}
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
