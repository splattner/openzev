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
 * The timezone every civil date and wall-clock time is shown in (ADR 0026).
 *
 * Mirrors the backend's `settings.TIME_ZONE`. Instants are formatted here, not
 * in the viewer's browser zone, so someone abroad sees the same days and hours
 * as the invoice and the tariff sheet.
 */
export const BUSINESS_TIME_ZONE = 'Europe/Zurich'

export interface ZonedParts {
    year: number
    month: number
    day: number
    hours: number
    minutes: number
}

/** App language with Swiss regional conventions, kept on `<html lang>` by `i18n/index.ts`. */
export function appLocale(): string {
    return (typeof document !== 'undefined' && document.documentElement.lang) || 'en-CH'
}

interface MonthNameOptions {
    /** Only for a document with its own language; defaults to `appLocale()`. */
    locale?: string
    /** Omit to read the date in the viewer's zone. */
    timeZone?: string
    month?: 'long' | 'short'
}

const dateNameFormatters = new Map<string, Intl.DateTimeFormat>()

function formatDateName(date: Date, { locale = appLocale(), ...options }: Intl.DateTimeFormatOptions & { locale?: string }): string {
    const key = `${locale}|${JSON.stringify(options)}`
    let formatter = dateNameFormatters.get(key)
    if (!formatter) {
        formatter = new Intl.DateTimeFormat(locale, options)
        dateNameFormatters.set(key, formatter)
    }
    return formatter.format(date)
}

/** A month's name, e.g. `Juli` in de-CH. */
export function formatMonthName(date: Date, { month = 'long', ...options }: MonthNameOptions = {}): string {
    return formatDateName(date, { ...options, month })
}

/** A month and year, e.g. `Juli 2026` in de-CH. */
export function formatMonthYear(date: Date, { month = 'long', ...options }: MonthNameOptions = {}): string {
    return formatDateName(date, { ...options, month, year: 'numeric' })
}

/** An instant's weekday and day in Zurich, for day-axis ticks: `Di., 3.11.` in de-CH, `Tue, 03.11` in en-CH. */
export function formatBusinessWeekday(date: Date): string {
    return formatDateName(date, { timeZone: BUSINESS_TIME_ZONE, weekday: 'short', day: 'numeric', month: 'numeric' })
}

const businessFormatter = new Intl.DateTimeFormat('en-CA', {
    timeZone: BUSINESS_TIME_ZONE,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
})

/** An instant's calendar and clock fields in the business timezone. */
export function zonedParts(value: Date): ZonedParts {
    const fields: Record<string, number> = {}
    for (const part of businessFormatter.formatToParts(value)) {
        if (part.type !== 'literal') fields[part.type] = Number(part.value)
    }
    return {
        year: fields.year,
        month: fields.month,
        day: fields.day,
        hours: fields.hour,
        minutes: fields.minute,
    }
}

/** An instant's civil date in the business timezone, as `YYYY-MM-DD`. */
export function formatBusinessIsoDate(value: Date): string {
    const { year, month, day } = zonedParts(value)
    return `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`
}

/** How far the business timezone is ahead of UTC at `ms`, in ms. */
function businessOffsetMs(ms: number): number {
    const p = zonedParts(new Date(ms))
    const wall = Date.UTC(p.year, p.month - 1, p.day, p.hours, p.minutes)
    return wall - Math.floor(ms / 60_000) * 60_000
}

/**
 * Epoch ms of 00:00 in the business timezone on a `YYYY-MM-DD` date.
 *
 * Two passes: the offset at UTC midnight can differ from the one at local
 * midnight on a DST day, so the second pass reads the offset at the first
 * estimate. The backend's `period_start_dt` is the same instant.
 */
export function businessDayStartMs(isoDate: string): number {
    const utcMidnight = Date.parse(`${isoDate}T00:00:00Z`)
    const estimate = utcMidnight - businessOffsetMs(utcMidnight)
    return utcMidnight - businessOffsetMs(estimate)
}

/** The civil date after a `YYYY-MM-DD` date. */
export function nextIsoDate(isoDate: string): string {
    return formatUtcIsoDate(new Date(Date.parse(`${isoDate}T00:00:00Z`) + 86_400_000))
}

/**
 * Today as `YYYY-MM-DD` in the business timezone.
 *
 * Deliberately not `new Date().toISOString().slice(0, 10)`: that yields the UTC
 * date, so the first hour or two after Swiss midnight reports yesterday — long
 * enough for a tariff that starts today to be treated as not yet in force. The
 * backend's `timezone.localdate()` agrees with this.
 */
export function todayBusinessIso(): string {
    return formatBusinessIsoDate(new Date())
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
