/** Swiss `de-CH` formatting (apostrophe grouping) for screen display. */
export function formatNumber(
    value: number,
    { maxDecimals = 2, minDecimals }: { maxDecimals?: number; minDecimals?: number } = {},
): string {
    return new Intl.NumberFormat('de-CH', {
        minimumFractionDigits: minDecimals ?? 0,
        maximumFractionDigits: Math.max(maxDecimals, minDecimals ?? 0),
    })
        .format(value)
        .replace(/\u2019/g, "'")
}

/** Format kWh with Swiss grouping — screen display caps at 1 decimal. */
export function formatKwh(
    value: number,
    { maxDecimals = 1 }: { maxDecimals?: number } = {},
): string {
    return formatNumber(value, { maxDecimals, minDecimals: 0 })
}

/**
 * Format a CHF amount with Swiss grouping, 2 decimals, and the typographic
 * minus sign (U+2212).
 *
 * The absolute value is formatted and the sign prefixed manually, so Intl
 * never emits a sign and the output is deterministic across ICU versions.
 * Values rounding to zero (|value| < 0.005) clamp to CHF 0.00 — never CHF −0.00.
 */
export function formatChf(value: number): string {
    if (!Number.isFinite(value)) return 'CHF 0.00'
    if (Math.abs(value) < 0.005) return 'CHF 0.00'

    const absFormatted = formatNumber(Math.abs(value), { minDecimals: 2, maxDecimals: 2 })

    return value < 0 ? `CHF \u2212${absFormatted}` : `CHF ${absFormatted}`
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
