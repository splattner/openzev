import type { TFunction } from 'i18next'
import { formatShortDate } from '../../lib/appSettings'
import { businessDayStartMs, formatBusinessIsoDate, nextIsoDate } from '../../lib/dates'
import type { AppSettings, DynamicPriceHistory, DynamicPricePoint } from '../../types/api'

type PriceGap = DynamicPriceHistory['gaps'][number]

/**
 * The part of each gap that has already passed.
 *
 * A fetched series is published ahead of time, so a hole in the future is
 * simply not published yet. Only elapsed time is a problem: billing refuses a
 * period it has no price for, so a past hole holds invoices back.
 */
export function elapsedPriceGaps(gaps: PriceGap[], now: number): PriceGap[] {
    return gaps.flatMap((gap) => {
        const end = Math.min(Date.parse(gap.to), now)
        if (Date.parse(gap.from) >= end) return []
        return [end === Date.parse(gap.to) ? gap : { from: gap.from, to: new Date(end).toISOString() }]
    })
}

/**
 * Missing intervals as inclusive civil date ranges in the business timezone,
 * adjacent or overlapping ranges merged — the exact timestamps stay available
 * for whoever needs to chase one down.
 *
 * `gap.to` is exclusive, so the last missing day is the one containing the
 * instant just before it.
 */
export function missingPriceDates(gaps: PriceGap[]): Array<{ from: string, to: string }> {
    const days = gaps
        .map((gap) => ({
            from: formatBusinessIsoDate(new Date(gap.from)),
            to: formatBusinessIsoDate(new Date(Date.parse(gap.to) - 1)),
        }))
        .sort((left, right) => left.from.localeCompare(right.from))
    const ranges: Array<{ from: string, to: string }> = []
    for (const day of days) {
        const previous = ranges[ranges.length - 1]
        if (previous && day.from <= nextIsoDate(previous.to)) {
            if (day.to > previous.to) previous.to = day.to
        } else {
            ranges.push({ ...day })
        }
    }
    return ranges
}

/** One merged date range as a sentence: "No prices for 03.10.2026 – 05.10.2026". */
export function missingRangeLabel(
    range: { from: string, to: string },
    settings: AppSettings,
    t: TFunction,
): string {
    const from = formatShortDate(range.from, settings)
    const to = formatShortDate(range.to, settings)
    return from === to
        ? t('pages.dynamicSources.history.missingDate', { date: from })
        : t('pages.dynamicSources.history.missingDates', { from, to })
}

/**
 * Step-chart rows for a window: each price holds across its own interval, and
 * each gap breaks the line with a `null` so it is not drawn across the hole.
 */
export function dynamicChartData(
    points: DynamicPricePoint[],
    gaps: PriceGap[],
    start: number,
    end: number,
): Array<{ timestamp: number, price: number | null }> {
    const rows: Array<{ timestamp: number, price: number | null }> = []
    for (const point of points) {
        const from = Math.max(start, Date.parse(point.valid_from))
        const to = Math.min(end, Date.parse(point.valid_to))
        if (from >= to) continue
        const price = Number(point.price_chf_per_kwh)
        rows.push({ timestamp: from, price }, { timestamp: to - 1, price })
    }
    for (const gap of gaps) {
        rows.push({ timestamp: Date.parse(gap.from), price: null }, { timestamp: Date.parse(gap.to) - 1, price: null })
    }
    return rows.sort((left, right) => left.timestamp - right.timestamp)
}

/** The window `[dateFrom, dateTo]` as epoch ms, end exclusive, in business days. */
export function windowBounds(dateFrom: string, dateTo: string): { start: number, end: number } {
    if (!dateFrom || !dateTo) return { start: 0, end: 0 }
    return { start: businessDayStartMs(dateFrom), end: businessDayStartMs(nextIsoDate(dateTo)) }
}
