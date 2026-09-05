import { formatIsoDate } from './dates'

export type BillingInterval = 'monthly' | 'quarterly' | 'semi_annual' | 'annual'

export function startOfBillingPeriod(today: Date, interval: BillingInterval): Date {
    const year = today.getFullYear()
    const month = today.getMonth()

    if (interval === 'monthly') return new Date(year, month, 1)
    if (interval === 'quarterly') return new Date(year, Math.floor(month / 3) * 3, 1)
    if (interval === 'semi_annual') return new Date(year, month < 6 ? 0 : 6, 1)
    return new Date(year, 0, 1)
}

export function endOfBillingPeriod(start: Date, interval: BillingInterval): Date {
    const monthsToAdd = interval === 'monthly' ? 1 : interval === 'quarterly' ? 3 : interval === 'semi_annual' ? 6 : 12
    const nextStart = new Date(start.getFullYear(), start.getMonth() + monthsToAdd, 1)
    return new Date(nextStart.getFullYear(), nextStart.getMonth(), 0)
}

export function getCurrentBillingPeriod(interval: BillingInterval): { from: string; to: string } {
    const start = startOfBillingPeriod(new Date(), interval)
    return {
        from: formatIsoDate(start),
        to: formatIsoDate(endOfBillingPeriod(start, interval)),
    }
}

/**
 * The aligned billing period encoded in a range, or null.
 *
 * Destination contract for readiness/attention links: pages open on the exact
 * `period_start`/`period_end` the item carried instead of their own default.
 * Only an exact whole period of the ZEV's interval counts; `floorIso` rejects
 * periods before the community existed.
 */
export function billingPeriodFromRange(
    fromIso: string | null | undefined,
    toIso: string | null | undefined,
    interval: BillingInterval,
    floorIso?: string | null,
): { from: string; to: string } | null {
    if (!fromIso || !toIso) return null
    if (!isBillingAlignedPeriod(fromIso, toIso, interval)) return null
    if (floorIso && fromIso < floorIso) return null
    return { from: fromIso, to: toIso }
}

const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/

function isValidIsoDay(iso: string): boolean {
    if (!ISO_DAY.test(iso)) return false
    const [year, month, day] = iso.split('-').map(Number)
    const check = new Date(Date.UTC(year, month - 1, day))
    return check.getUTCFullYear() === year && check.getUTCMonth() === month - 1 && check.getUTCDate() === day
}

/**
 * Any real range from the URL ({from} ≤ {to}, calendar-valid dates), or null.
 * Accepts custom (unaligned) windows; malformed dates (e.g. 2026-02-30) fall back.
 */
export function billingRangeFromParams(
    fromIso: string | null | undefined,
    toIso: string | null | undefined,
): { from: string; to: string } | null {
    if (!fromIso || !toIso || !isValidIsoDay(fromIso) || !isValidIsoDay(toIso)) return null
    if (fromIso > toIso) return null
    return { from: fromIso, to: toIso }
}

/**
 * Invoice-page URL ranges: like `billingRangeFromParams`, but rejected before
 * the community start. Historical invoice periods from an earlier interval
 * may predate today's aligned floor, so the bound is the start, not the floor.
 */
export function invoiceRangeFromParams(
    fromIso: string | null | undefined,
    toIso: string | null | undefined,
    communityStartIso: string | null | undefined,
): { from: string; to: string } | null {
    const range = billingRangeFromParams(fromIso, toIso)
    if (!range || (communityStartIso && range.from < communityStartIso)) return null
    return range
}

/** Whole billing periods for the preset menu, newest first, capped at
 * `count`, never predating `minFrom` (the community's first period). */
export function recentBillingPeriods(
    interval: BillingInterval,
    count = 5,
    minFrom?: string | null,
): Array<{ from: string; to: string }> {
    const periods = [getCurrentBillingPeriod(interval)]
    for (let i = 0; i < count; i += 1) {
        periods.push(shiftBillingPeriod(periods[periods.length - 1].from, interval, -1))
    }
    return periods.filter((range) => !minFrom || range.from >= minFrom)
}

/**
 * True when {from, to} exactly spans one whole billing period.
 *
 * Prev/next navigation only makes sense on an aligned period, so the selector
 * disables the arrows when a custom range is active.
 */
export function isBillingAlignedPeriod(from: string, to: string, interval: BillingInterval): boolean {
    if (!from || !to) {
        return false
    }
    const start = startOfBillingPeriod(new Date(`${from}T00:00:00`), interval)
    return formatIsoDate(start) === from && formatIsoDate(endOfBillingPeriod(start, interval)) === to
}

export function shiftBillingPeriod(
    fromIso: string,
    interval: BillingInterval,
    direction: -1 | 1,
): { from: string; to: string } {
    const fromDate = new Date(`${fromIso}T00:00:00`)
    const monthsToShift = (interval === 'monthly' ? 1 : interval === 'quarterly' ? 3 : interval === 'semi_annual' ? 6 : 12) * direction
    const shiftedStart = new Date(fromDate.getFullYear(), fromDate.getMonth() + monthsToShift, 1)
    return {
        from: formatIsoDate(shiftedStart),
        to: formatIsoDate(endOfBillingPeriod(shiftedStart, interval)),
    }
}

/**
 * The earliest billable aligned period for a community: the first aligned
 * boundary on/after its start date (a mid-period start skips its partial
 * containing period). Mirrors the backend's period_starts rule.
 */
export function firstAlignedBillingPeriod(
    startIso: string | null | undefined,
    interval: BillingInterval,
): { from: string; to: string } | null {
    if (!startIso || !isValidIsoDay(startIso)) return null
    const start = new Date(`${startIso}T00:00:00`)
    const step = interval === 'monthly' ? 1 : interval === 'quarterly' ? 3 : interval === 'semi_annual' ? 6 : 12
    const monthIndex = start.getFullYear() * 12 + start.getMonth() - ((start.getMonth()) % step)
    const containing = new Date(Math.floor(monthIndex / 12), monthIndex % 12, 1)
    const aligned = start.getDate() === 1 && start.getMonth() % step === 0
    const firstStart = aligned ? containing : new Date(containing.getFullYear(), containing.getMonth() + step, 1)
    return { from: formatIsoDate(firstStart), to: formatIsoDate(endOfBillingPeriod(firstStart, interval)) }
}

/**
 * The most recent *complete* billing period.
 *
 * Billing pages open here rather than on the current period, which is still
 * running: it has partial metering data and no invoices, so opening on it means
 * every billing run starts by stepping back one period. Mirrors
 * ``previous_quarter`` in the backend's seed_demo command.
 */
export function getPreviousBillingPeriod(interval: BillingInterval): { from: string; to: string } {
    const currentStart = startOfBillingPeriod(new Date(), interval)
    return shiftBillingPeriod(formatIsoDate(currentStart), interval, -1)
}