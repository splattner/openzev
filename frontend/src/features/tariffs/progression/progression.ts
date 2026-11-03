import type {
    TariffProgression,
    TariffProgressionFixedFee,
    TariffProgressionIncompleteReason,
    TariffProgressionInterval,
    TariffProgressionRule,
    TariffProgressionSlot,
    TariffProgressionVatMode,
} from '../../../types/api'
import { formatSeason, formatWeekdays } from '../recurrence'

/** Which of the two values a progression shows. */
export type PriceBasis = 'net' | 'gross'

type Translate = (key: string, opts?: Record<string, unknown>) => string

const DAY_MS = 24 * 60 * 60 * 1000

/** Parsed as UTC midnight, like `priceHistory.ts`, so the axis ignores the viewer's zone. */
export function dayMs(isoDate: string): number {
    return Date.parse(`${isoDate}T00:00:00Z`)
}

/** Whether the ZEV has a second, gross value to switch to. */
export function hasGross(vatMode: TariffProgressionVatMode): boolean {
    return vatMode !== 'not_registered'
}

/** The value of a slot (or subtotal) on the chosen basis; gross falls back to net where there is none. */
export function valueOf(item: { net: string, gross: string | null }, basis: PriceBasis): string {
    return basis === 'gross' && item.gross !== null ? item.gross : item.net
}

export type ProgressionPoint = { t: number } & Record<string, number | null>

export type ProgressionChartData = {
    points: ProgressionPoint[]
    /** Stretches whose total is understated or missing, as epoch ms (end exclusive). */
    flagged: Array<{ from: number, to: number }>
}

/**
 * Turn a progression into a step-chart dataset: a point at every interval
 * boundary, `null` for a line that does not exist in that interval (so it
 * breaks instead of implying the old price continued), and a last point at the
 * end so the final step is visible.
 */
export function buildChartData(progression: TariffProgression, basis: PriceBasis): ProgressionChartData {
    const { intervals, lines } = progression
    const points: ProgressionPoint[] = []
    const flagged: ProgressionChartData['flagged'] = []

    const valuesOf = (interval: TariffProgressionInterval): Record<string, number | null> => {
        const byLine = new Map(interval.slots.map((slot) => [slot.line, slot]))
        return Object.fromEntries(lines.map((line) => {
            const slot = byLine.get(line.key)
            return [line.key, slot ? Number(valueOf(slot, basis)) : null]
        }))
    }

    intervals.forEach((interval) => {
        points.push({ t: dayMs(interval.from), ...valuesOf(interval) })
        if (interval.slots.length === 0 || interval.missing_categories.length > 0 || interval.incomplete.length > 0) {
            flagged.push({ from: dayMs(interval.from), to: dayMs(interval.to) + DAY_MS })
        }
    })
    const last = intervals[intervals.length - 1]
    if (last) points.push({ t: dayMs(last.to), ...valuesOf(last) })
    return { points, flagged }
}

/** The interval containing `day`, or `undefined` outside the range. */
export function intervalOn(progression: TariffProgression, day: string): TariffProgressionInterval | undefined {
    return progression.intervals.find((interval) => interval.from <= day && day <= interval.to)
}

/** `day` moved into `[from, to]`. */
export function clampDay(day: string, from: string, to: string): string {
    return day < from ? from : day > to ? to : day
}

export type Composition = {
    interval: TariffProgressionInterval
    slot: TariffProgressionSlot
}

/** The slot of `lineKey` in force on `day`, with the interval it belongs to. */
export function compositionOn(progression: TariffProgression, day: string, lineKey: string): Composition | null {
    const interval = intervalOn(progression, day)
    const slot = interval?.slots.find((candidate) => candidate.line === lineKey)
    return interval && slot ? { interval, slot } : null
}

/** The line to show on `day`: the chosen one if it exists there, else the first the interval has. */
export function lineOn(progression: TariffProgression, day: string, preferred: string | null): string | null {
    const interval = intervalOn(progression, day)
    if (!interval || interval.slots.length === 0) return preferred
    return interval.slots.some((slot) => slot.line === preferred) ? preferred : interval.slots[0].line
}

const ALL_HOURS = { from: '00:00', to: '24:00' }

function isAllDay(rule: TariffProgressionRule): boolean {
    return rule.windows.length === 1
        && rule.windows[0].from === ALL_HOURS.from
        && rule.windows[0].to === ALL_HOURS.to
}

/**
 * How a line is named: when it applies, from its rules. `Mon–Fri 07:00–20:00`,
 * `Oct–Mar, Sat–Sun`, or "All hours" for a line that always applies.
 */
export function lineLabel(
    rules: TariffProgressionRule[],
    t: Translate,
    dayNames: string[],
    monthNames: string[],
): string {
    if (rules.length === 1 && rules[0].months.length === 12 && rules[0].weekdays.length === 7 && isAllDay(rules[0])) {
        return t('pages.tariffs.progression.allHours')
    }
    return rules
        .map((rule) => [
            formatSeason(rule.months.join(','), monthNames),
            formatWeekdays(rule.weekdays.join(','), dayNames),
            isAllDay(rule) ? '' : rule.windows.map((window) => `${window.from}–${window.to}`).join(', '),
        ].filter(Boolean).join(' '))
        .map((part) => part || t('pages.tariffs.progression.allHours'))
        .join('; ')
}

export type ProgressionIssue = {
    kind: 'missing' | TariffProgressionIncompleteReason
    /** The category (for `missing`) or tariff name. */
    subject: string
    from: string
    to: string
}

function dayAfter(isoDate: string): string {
    return new Date(dayMs(isoDate) + DAY_MS).toISOString().slice(0, 10)
}

/**
 * What is missing from the totals, merged across consecutive intervals: a
 * category with nothing in force, or a tariff that could not be priced here.
 * An understated total must never read as the real price.
 */
export function progressionIssues(progression: TariffProgression): ProgressionIssue[] {
    const open = new Map<string, ProgressionIssue>()
    const done: ProgressionIssue[] = []
    progression.intervals.forEach((interval) => {
        const present = new Set<string>()
        const found: Array<Pick<ProgressionIssue, 'kind' | 'subject'>> = [
            ...interval.missing_categories.map((category) => ({ kind: 'missing' as const, subject: category })),
            ...interval.incomplete.map((item) => ({ kind: item.reason, subject: item.name })),
        ]
        found.forEach(({ kind, subject }) => {
            const key = `${kind}|${subject}`
            present.add(key)
            const current = open.get(key)
            if (current && dayAfter(current.to) === interval.from) current.to = interval.to
            else {
                if (current) done.push(current)
                open.set(key, { kind, subject, from: interval.from, to: interval.to })
            }
        })
        open.forEach((issue, key) => {
            if (!present.has(key)) {
                done.push(issue)
                open.delete(key)
            }
        })
    })
    done.push(...open.values())
    return done.sort((left, right) => (left.from < right.from ? -1 : left.from > right.from ? 1 : 0))
}

export type FeeGroups = { month: TariffProgressionFixedFee[], year: TariffProgressionFixedFee[] }

export function groupFees(fees: TariffProgressionFixedFee[]): FeeGroups {
    return {
        month: fees.filter((fee) => fee.unit === 'month'),
        year: fees.filter((fee) => fee.unit === 'year'),
    }
}

/** The fee row in force on `day`, else the latest one that started before it, else the first. */
export function feeVersionOn(fee: TariffProgressionFixedFee, day: string): TariffProgressionFixedFee['versions'][number] {
    const inForce = fee.versions.find((version) => version.valid_from <= day && (!version.valid_to || version.valid_to >= day))
    if (inForce) return inForce
    const started = fee.versions.filter((version) => version.valid_from <= day)
    return started[started.length - 1] ?? fee.versions[0]
}
