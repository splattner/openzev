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