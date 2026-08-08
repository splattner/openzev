/**
 * Shared date helpers.
 *
 * `formatIsoDate` renders a `Date` as a `YYYY-MM-DD` string in the local
 * timezone. This is the canonical formatter for billing-period boundaries,
 * quick-range presets and period selectors — prefer it over the UTC-based
 * `toISOString().slice(0, 10)`, which shifts the date for users west of UTC.
 */
export function formatIsoDate(date: Date): string {
    const year = date.getFullYear()
    const month = String(date.getMonth() + 1).padStart(2, '0')
    const day = String(date.getDate()).padStart(2, '0')
    return `${year}-${month}-${day}`
}

/**
 * A `Date` as `YYYY-MM-DD` using UTC getters.
 *
 * Use this for values whose instant is anchored to UTC midnight (e.g. tariff
 * price-history epochs built via `Date.parse(iso + 'T00:00:00Z')`), where local
 * getters would shift the displayed date for users west of UTC.
 */
export function formatUtcIsoDate(date: Date): string {
    const year = date.getUTCFullYear()
    const month = String(date.getUTCMonth() + 1).padStart(2, '0')
    const day = String(date.getUTCDate()).padStart(2, '0')
    return `${year}-${month}-${day}`
}

/**
 * Today as `YYYY-MM-DD` in the viewer's own timezone.
 *
 * Deliberately not `new Date().toISOString().slice(0, 10)`: that yields the UTC
 * date, so anywhere east of UTC (Switzerland included) the first hour or two
 * after midnight reports yesterday — long enough for a tariff that starts today
 * to be treated as not yet in force.
 */
export function todayLocalIso(): string {
    return formatIsoDate(new Date())
}
