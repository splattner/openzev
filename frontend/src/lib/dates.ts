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

/**
 * Inclusive day count between two `YYYY-MM-DD` dates.
 *
 * Parses both as UTC midnight so a DST transition in the viewer's timezone
 * can't shift the count by a day — the two dates are calendar boundaries,
 * not instants, so there is no "local time" for them to begin with.
 */
export function daysInPeriod(from: string, to: string): number {
    if (!from || !to) return 0
    const fromMs = Date.parse(`${from}T00:00:00Z`)
    const toMs = Date.parse(`${to}T00:00:00Z`)
    if (Number.isNaN(fromMs) || Number.isNaN(toMs)) return 0
    return Math.round((toMs - fromMs) / 86_400_000) + 1
}

const ISO_DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/

/**
 * True for a well-formed `YYYY-MM-DD` string that parses to a real calendar
 * date. A URL query param is never trusted input — a hand-edited or stale
 * `?from=`/`?to=` must fall back to a default instead of producing an
 * `Invalid Date` somewhere downstream.
 */
export function isValidIsoDate(value: string | null | undefined): value is string {
    if (!value || !ISO_DATE_PATTERN.test(value)) return false
    const ms = Date.parse(`${value}T00:00:00Z`)
    if (Number.isNaN(ms)) return false
    // Date.parse rolls an out-of-range day/month over into the next one
    // (e.g. "2026-02-30" silently becomes March 2) instead of rejecting it —
    // round-tripping catches that instead of accepting a date that isn't
    // the one the string names.
    return formatUtcIsoDate(new Date(ms)) === value
}
