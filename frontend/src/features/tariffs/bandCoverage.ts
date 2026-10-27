import type { TariffPeriodType } from '../../types/api'
import { parseMonths } from './recurrence'

/**
 * Which hours of the year a version's bands price, and which they leave to the
 * engine's fallback.
 *
 * Mirrors `tariffs.periods.resolve_band`: months are checked first (a blank
 * mask is every month), a flat band prices its months outright, a timed band
 * needs both ends and its weekday, and its window is `[start, end)` — wrapping
 * past midnight when the end is not after the start, and a whole day when the
 * two are equal. Anything nothing matches is priced by the first band of the
 * season, in the model's order (type, start, id): that is the fallback the
 * warning names.
 */
export type CoverageBand = {
    id?: string
    period_type: TariffPeriodType
    label?: string | null
    price_chf_per_kwh?: string | null
    percentage?: string | null
    time_from?: string | null
    time_to?: string | null
    weekdays?: string
    months?: string
}

/** A recurring stretch no band prices: the months and weekdays it recurs on, and its hours in seconds of the day. */
export type CoverageGap = { months: number[], weekdays: number[], start: number, end: number }

export type BandCoverage<T extends CoverageBand> = {
    /** Some hour has no band of its own. */
    uncovered: boolean
    /** Some hour has more than one; the first match prices it. */
    overlaps: boolean
    gaps: CoverageGap[]
    /** The band that prices the uncovered hours, with the months it does so in. */
    fallbacks: Array<{ band: T, months: number[] }>
}

const DAY = 86400

function seconds(value?: string | null): number | null {
    if (!value) return null
    const [hours, minutes = 0, secs = 0] = value.split(':').map(Number)
    return hours * 3600 + minutes * 60 + secs
}

function parseWeekdays(raw?: string): number[] {
    return (raw ?? '').split(',').map((part) => part.trim()).filter(Boolean).map(Number).filter((day) => day >= 0 && day <= 6)
}

/**
 * The (month, weekday) pairs a version can see, or `undefined` for every one.
 * A version of a few weeks never meets most of them, so a band set that is
 * complete for its own weeks is not reported as full of holes.
 */
function reachablePairs(validFrom?: string, validTo?: string | null): Set<number> | undefined {
    if (!validFrom || !validTo) return undefined
    const day = new Date(`${validFrom}T12:00:00Z`)
    const end = new Date(`${validTo}T12:00:00Z`)
    if (!Number.isFinite(day.getTime()) || !Number.isFinite(end.getTime())) return undefined
    const pairs = new Set<number>()
    // The pairs repeat yearly: stop once all twelve months × seven days are in.
    for (; day <= end && pairs.size < 84; day.setUTCDate(day.getUTCDate() + 1)) {
        pairs.add(day.getUTCMonth() * 7 + (day.getUTCDay() + 6) % 7)
    }
    return pairs
}

export function bandCoverage<T extends CoverageBand>(
    bands: T[],
    validity?: { valid_from?: string, valid_to?: string | null },
): BandCoverage<T> {
    const reachable = reachablePairs(validity?.valid_from, validity?.valid_to)
    const ordered = bands
        .map((band) => ({ band, start: seconds(band.time_from), end: seconds(band.time_to), months: parseMonths(band.months), days: parseWeekdays(band.weekdays) }))
        .sort((a, b) => (a.band.period_type < b.band.period_type ? -1 : a.band.period_type > b.band.period_type ? 1 : 0)
            || (a.start ?? -1) - (b.start ?? -1)
            || (a.band.id ?? '').localeCompare(b.band.id ?? ''))
    // Every instant a window opens or closes: between two of them the set of
    // matching bands cannot change, so one probe per stretch is enough.
    const edges = [...new Set([0, DAY, ...ordered.flatMap(({ start, end }) => [start, end].filter((edge): edge is number => edge !== null))])]
        .sort((a, b) => a - b)

    const result: BandCoverage<T> = { uncovered: false, overlaps: false, gaps: [], fallbacks: [] }
    for (let month = 1; month <= 12; month++) {
        const inSeason = ordered.filter(({ months }) => months.length === 0 || months.includes(month))
        const monthGaps: Array<Omit<CoverageGap, 'months'>> = []
        for (let i = 0; i < edges.length - 1; i++) {
            const time = edges[i]
            const open: number[] = []
            for (let day = 0; day < 7; day++) {
                if (reachable && !reachable.has((month - 1) * 7 + day)) continue
                const matching = inSeason.filter(({ band, start, end, days }) => band.period_type === 'flat' || (
                    start !== null && end !== null && (days.length === 0 || days.includes(day))
                    && (start < end ? time >= start && time < end : time >= start || time < end)
                )).length
                if (matching === 0) open.push(day)
                if (matching > 1) result.overlaps = true
            }
            if (open.length === 0) continue
            result.uncovered = true
            const last = monthGaps.at(-1)
            if (last && last.end === time && last.weekdays.join() === open.join()) last.end = edges[i + 1]
            else monthGaps.push({ weekdays: open, start: time, end: edges[i + 1] })
        }
        for (const gap of monthGaps) {
            const same = result.gaps.find((entry) => entry.start === gap.start && entry.end === gap.end && entry.weekdays.join() === gap.weekdays.join())
            if (same) same.months.push(month)
            else result.gaps.push({ ...gap, months: [month] })
        }
        const fallback = (inSeason[0] ?? ordered[0])?.band
        if (monthGaps.length > 0 && fallback) {
            const same = result.fallbacks.find((entry) => entry.band === fallback)
            if (same) same.months.push(month)
            else result.fallbacks.push({ band: fallback, months: [month] })
        }
    }
    return result
}
