/** Decimal formatting (`de-CH`, no thousands grouping). */
export function formatNumber(
    value: number,
    { maxDecimals = 2, minDecimals }: { maxDecimals?: number; minDecimals?: number } = {},
): string {
    return new Intl.NumberFormat('de-CH', {
        minimumFractionDigits: minDecimals ?? 0,
        maximumFractionDigits: Math.max(maxDecimals, minDecimals ?? 0),
        useGrouping: false,
    }).format(value)
}

/** Format kWh — up to 1 decimal by default. */
export function formatKwh(
    value: number,
    { maxDecimals = 1 }: { maxDecimals?: number } = {},
): string {
    if (!Number.isFinite(value)) return '–'
    return formatNumber(value, { maxDecimals, minDecimals: 0 })
}

/** Format a percentage — up to one decimal by default, with % appended. */
export function formatPercent(
    value: number,
    { maxDecimals = 1 }: { maxDecimals?: number } = {},
): string {
    if (!Number.isFinite(value)) return '–'
    return `${formatPercentFigure(value, { maxDecimals })}\u00a0%`
}

/** A percentage without the sign, for a figure whose unit is set apart (`StatCard`). */
export function formatPercentFigure(
    value: number,
    { maxDecimals = 1 }: { maxDecimals?: number } = {},
): string {
    if (!Number.isFinite(value)) return '–'
    return formatNumber(value, { maxDecimals })
}

/**
 * Format a CHF amount (2 decimals, typographic minus U+2212).
 *
 * The absolute value is formatted and the sign prefixed manually, so Intl
 * never emits a sign and the output is deterministic across ICU versions.
 * Values rounding to zero (|value| < 0.005) clamp to CHF 0.00 — never CHF −0.00.
 */
export function formatChf(value: number): string {
    return `CHF ${formatChfAmount(value)}`
}

/** A CHF amount without the currency, for a column whose header names it. */
export function formatChfAmount(value: number): string {
    if (!Number.isFinite(value) || Math.abs(value) < 0.005) return '0.00'

    const absFormatted = formatNumber(Math.abs(value), { minDecimals: 2, maxDecimals: 2 })

    return value < 0 ? `\u2212${absFormatted}` : absFormatted
}

/** Human-readable byte size for the admin system-health tab (phase 3):
 * binary prefixes (KiB…), one decimal except for exact bytes. */
export function formatBytes(value: number): string {
    if (!Number.isFinite(value) || value < 0) return '–'
    if (value < 1024) return `${Math.round(value)} B`
    const units = ['KiB', 'MiB', 'GiB', 'TiB']
    let scaled = value
    let unitIndex = -1
    do {
        scaled /= 1024
        unitIndex += 1
    } while (scaled >= 1024 && unitIndex < units.length - 1)
    return `${formatNumber(scaled, { minDecimals: 1, maxDecimals: 1 })} ${units[unitIndex]}`
}
