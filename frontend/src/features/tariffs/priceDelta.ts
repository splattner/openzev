import type { TariffPeriod, TariffSeries, TariffVersion } from '../../types/api'
import { kwhPrice } from './rateLines'

/** How a price moves from one version to the next. */
export type PriceDelta = {
    diff: number
    /** Relative to the old price; `null` when that was zero, or for percentage points. */
    percent: number | null
    unit: 'price' | 'chf' | 'points'
}

export type VersionDeltas = {
    /** The fixed fee of a flat-fee tariff. */
    version: PriceDelta | null
    /** Per band of the new version, by band id. */
    bands: Map<string, PriceDelta>
}

const round = (value: number, digits: number) => Number(value.toFixed(digits))

function delta(from: number, to: number, unit: PriceDelta['unit']): PriceDelta | null {
    const diff = round(to - from, unit === 'chf' ? 2 : 5)
    if (diff === 0) return null
    return { diff, percent: unit === 'points' || from === 0 ? null : round((diff / from) * 100, 1), unit }
}

// A band is the same band when it applies to the same hours, days and months.
const bandKey = (period: TariffPeriod) => [
    period.period_type, period.label ?? '', period.time_from ?? '', period.time_to ?? '', period.weekdays ?? '', period.months ?? '',
].join('|')

/**
 * What `to` changes against `from`, band by band. A band that did not exist
 * before has nothing to compare with and gets no entry; a dynamic version has
 * no stored price to compare at all.
 */
export function versionDeltas(series: TariffSeries, from: TariffVersion, to: TariffVersion): VersionDeltas {
    const none: VersionDeltas = { version: null, bands: new Map() }
    if (from.dynamic_source || to.dynamic_source) return none
    if (series.billing_mode === 'energy' || series.billing_mode === 'percentage_of_energy') {
        const percentage = series.billing_mode === 'percentage_of_energy'
        const before = new Map(from.periods.map((period) => [bandKey(period), period]))
        const bands = new Map<string, PriceDelta>()
        for (const period of to.periods) {
            const old = before.get(bandKey(period))
            const [a, b] = percentage
                ? [old?.percentage, period.percentage]
                : [old?.price_chf_per_kwh, period.price_chf_per_kwh]
            if (a == null || b == null) continue
            const change = delta(Number(a), Number(b), percentage ? 'points' : 'price')
            if (change) bands.set(period.id, change)
        }
        return { version: null, bands }
    }
    return { version: delta(Number(from.fixed_price_chf || 0), Number(to.fixed_price_chf || 0), 'chf'), bands: none.bands }
}

/**
 * A change as a person reads it: `+0.020 (+6.8 %)`, or just the relative part
 * where the row has no room for the amount.
 */
export function formatDelta(value: PriceDelta, points: (diff: number) => string, short = false): string {
    const sign = value.diff > 0 ? '+' : '\u2212'
    const size = Math.abs(value.diff)
    const percent = value.percent != null ? `${sign}${Math.abs(value.percent)} %` : null
    if (short && percent) return percent
    const amount = value.unit === 'points' ? points(size) : value.unit === 'chf' ? size.toFixed(2) : kwhPrice.format(size)
    return percent ? `${sign}${amount} (${percent})` : `${sign}${amount}`
}

/**
 * The relative change of each price of `to`, in the order the overview lists
 * them (`+6.8 % / ±0`); `null` when nothing moved or there is nothing to compare.
 */
export function deltaSummary(
    series: TariffSeries, from: TariffVersion, to: TariffVersion, points: (diff: number) => string,
): string | null {
    const deltas = versionDeltas(series, from, to)
    const banded = series.billing_mode === 'energy' || series.billing_mode === 'percentage_of_energy'
    const parts = banded ? to.periods.map((period) => deltas.bands.get(period.id) ?? null) : [deltas.version]
    if (parts.every((part) => part === null)) return null
    return parts.map((part) => (part ? formatDelta(part, points, true) : '\u00b10')).join(' / ')
}
