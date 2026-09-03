/**
 * Seasonal price bands: a `TariffPeriod` that applies only in some months.
 *
 * `months` is stored the way `weekdays` is — comma-separated numbers, blank
 * meaning every one of them — so a band that applies all year carries nothing
 * and reads exactly as it did before seasons existed.
 *
 * Mirrors `backend/tariffs/periods.py`; the two must agree on what a season
 * looks like, because one writes the labels on the contract PDF and the other
 * writes them on screen.
 */

export const MONTH_KEYS = [
    'jan', 'feb', 'mar', 'apr', 'may', 'jun',
    'jul', 'aug', 'sep', 'oct', 'nov', 'dec',
] as const

export function parseMonths(raw?: string | null): number[] {
    if (!raw) return []
    return raw
        .split(',')
        .map((part) => Number(part.trim()))
        .filter((month) => Number.isInteger(month) && month >= 1 && month <= 12)
        .sort((left, right) => left - right)
}

/**
 * Contiguous runs of months as `[first, last]` pairs, treating December and
 * January as adjacent — a winter season is one `Oct–Mar` range, not the two
 * ranges a reader would have to piece together themselves.
 *
 * A band covering every month (or none) has no season to name, so returns [].
 */
export function monthRanges(months: number[]): Array<[number, number]> {
    if (months.length === 0 || months.length === 12) return []

    const runs: number[][] = []
    months.forEach((month) => {
        const last = runs[runs.length - 1]
        if (last && month === last[last.length - 1] + 1) last.push(month)
        else runs.push([month])
    })

    if (runs.length > 1 && runs[0][0] === 1 && runs[runs.length - 1].at(-1) === 12) {
        runs[runs.length - 1].push(...runs.shift()!)
    }

    return runs.map((run) => [run[0], run[run.length - 1]] as [number, number])
}

/**
 * `"Oct–Mar"`, or `''` for a band that applies all year.
 *
 * `monthNames` is passed in rather than translated here so this stays a pure
 * function — it is the piece worth testing, and the twelve lookups belong to
 * whichever component is rendering.
 */
export function formatSeason(raw: string | undefined | null, monthNames: string[]): string {
    return monthRanges(parseMonths(raw))
        .map(([first, last]) => (
            first === last
                ? monthNames[first - 1]
                : `${monthNames[first - 1]}\u2013${monthNames[last - 1]}`
        ))
        .join(', ')
}

/**
 * Sort key putting year-round bands first, then seasons by the month they
 * start in. Without it seasonal siblings fall back to id order, which is
 * creation order and reads as random.
 */
export function seasonSortKey(raw?: string | null): number {
    const ranges = monthRanges(parseMonths(raw))
    return ranges.length === 0 ? -1 : ranges[0][0]
}
