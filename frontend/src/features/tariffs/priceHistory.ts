import type { TariffPeriod, TariffSeries, TariffVersion } from '../../types/api'
import { parseMonths } from './recurrence'

/** What the y-axis of a series' price history is measured in. */
export type PriceUnit = 'chf_per_kwh' | 'chf' | 'percent'

export type BandKey = 'flat' | 'high' | 'low' | 'amount' | 'effective'

type PriceHistoryPoint = {
    /** Boundary as an epoch millisecond value, so the x-axis can be proportional. */
    t: number
    date: string
    /** Band value at this boundary; `null` means the band does not apply then. */
    values: Partial<Record<BandKey, number | null>>
    /** Extra context for the tooltip, e.g. the percentage behind a derived price. */
    note?: string
}

type PriceHistory = {
    unit: PriceUnit
    bands: BandKey[]
    points: PriceHistoryPoint[]
    /** Uncovered stretches, as epoch ms, for shading. */
    gaps: Array<{ from: number, to: number }>
    /** True when the values are computed rather than configured directly. */
    derived: boolean
}

const BAND_ORDER: BandKey[] = ['flat', 'high', 'low']
const DAY_MS = 24 * 60 * 60 * 1000

function ms(isoDate: string): number {
    // Parsed as UTC midnight on purpose: every boundary goes through the same
    // conversion, so the axis stays consistent regardless of the viewer's zone.
    return Date.parse(`${isoDate}T00:00:00Z`)
}

function isoFromMs(value: number): string {
    return new Date(value).toISOString().slice(0, 10)
}

function num(value: string | null | undefined): number | null {
    if (value === null || value === undefined || value === '') return null
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : null
}

function byValidFrom(left: { valid_from: string }, right: { valid_from: string }): number {
    return left.valid_from < right.valid_from ? -1 : left.valid_from > right.valid_from ? 1 : 0
}

/**
 * The one price that stands for a whole tariff version.
 *
 * Prefer the flat band, else the high band, else whatever comes first — the same
 * rule the invoice engine and the contract PDF use, so a charted grid base
 * matches what participants are actually billed against.
 */
function representativePrice(periods: TariffPeriod[]): number | null {
    if (periods.length === 0) return null
    const flat = periods.find((period) => period.period_type === 'flat')
    const high = periods.find((period) => period.period_type === 'high')
    return num((flat ?? high ?? periods[0]).price_chf_per_kwh)
}

/** Version of `versions` in force on `day`, or `undefined` inside a gap. */
function versionOn<T extends { valid_from: string, valid_to?: string | null }>(
    versions: T[], day: string,
): T | undefined {
    return versions.find(
        (version) => version.valid_from <= day && (!version.valid_to || version.valid_to >= day),
    )
}

/**
 * Sum of the representative prices of every grid-energy tariff in force on
 * `day` — the base a percentage-of-energy tariff is a fraction of.
 */
function gridBaseOn(allSeries: TariffSeries[], day: string): number {
    return allSeries
        .filter((series) => series.billing_mode === 'energy' && series.energy_type === 'grid')
        .reduce((total, series) => {
            const version = versionOn(series.versions, day)
            return total + (version ? representativePrice(version.periods) ?? 0 : 0)
        }, 0)
}

/** Where the last step should be drawn to, so an open-ended version is visible. */
function terminalBoundary(versions: TariffVersion[], today: string): number {
    const last = versions[versions.length - 1]
    if (last.valid_to) return ms(last.valid_to)
    return Math.max(ms(today), ms(last.valid_from))
}

/**
 * Turn a tariff series into a step-chart dataset.
 *
 * Every point is a boundary at which something changed; values hold until the
 * next boundary, which is why the chart must be stepped rather than
 * interpolated — a price does not drift between two Januaries.
 *
 * A gap inserts an all-`null` boundary so the line breaks rather than implying
 * the old price continued through a period nothing was billed at.
 *
 * `allSeries` is only needed for percentage-of-energy tariffs, whose own record
 * holds no price: their effective rate is a fraction of the grid tariffs in
 * force at the time, so it changes when *those* change too.
 */
export function buildPriceHistory(
    series: TariffSeries,
    allSeries: TariffSeries[],
    today: string,
): PriceHistory {
    const versions = [...series.versions].sort(byValidFrom)
    const gaps = series.gaps.map((gap) => ({ from: ms(gap.start), to: ms(gap.end) }))

    if (series.billing_mode === 'percentage_of_energy') {
        const points = percentagePoints(versions, allSeries, today)
        return {
            unit: 'chf_per_kwh',
            bands: ['effective'],
            derived: true,
            // A percentage tariff with no grid tariff behind it prices at zero —
            // the engine's base sum is zero, so it genuinely bills nothing. That
            // is faithful but reads like a crash, so those stretches are shaded
            // like the tariff's own gaps.
            gaps: [...gaps, ...zeroBaseStretches(points)],
            points,
        }
    }

    if (series.billing_mode !== 'energy') {
        return {
            unit: 'chf',
            bands: ['amount'],
            derived: false,
            gaps,
            points: assemble(versions, ['amount'], today,
                (version) => ({ amount: num(version.fixed_price_chf) })),
        }
    }

    // A seasonal tariff really does charge different prices at different times
    // of year, so it belongs on a time series as a step. Splitting each version
    // at its season boundaries lets the existing step-chart assembly draw that
    // without knowing seasons exist; a tariff with no seasonal band is handed
    // through untouched.
    const segments = versions.flatMap((version) => seasonalSegments(version, today))

    const bands = BAND_ORDER.filter(
        (band) => segments.some((version) => version.periods.some((period) => period.period_type === band)),
    )

    const points = assemble(segments, bands, today, (version) => {
        const values: Partial<Record<BandKey, number | null>> = {}
        bands.forEach((band) => {
            const period = version.periods.find((entry) => entry.period_type === band)
            values[band] = period ? num(period.price_chf_per_kwh) : null
        })
        return values
    })

    return { unit: 'chf_per_kwh', bands: bands.length ? bands : ['flat'], derived: false, gaps, points }
}

/** Bands of `version` that apply in `month` (1-12). Blank months = every month. */
function bandsInMonth(version: TariffVersion, month: number): TariffPeriod[] {
    return version.periods.filter((period) => {
        const months = parseMonths(period.months)
        return months.length === 0 || months.includes(month)
    })
}

function bandSignature(version: TariffVersion, month: number): string {
    return bandsInMonth(version, month).map((period) => period.id).sort().join('|')
}

function isoDay(year: number, month: number, day: number): string {
    return new Date(Date.UTC(year, month - 1, day)).toISOString().slice(0, 10)
}

/**
 * One version split into the stretches over which its set of bands is constant.
 *
 * Boundaries can only fall on the first of a month, so the months where the
 * active set changes are worked out once and then projected across the years
 * the version spans. A version with no seasonal band produces itself, which is
 * both the fast path and the guarantee that nothing predating seasons moved.
 */
function seasonalSegments(version: TariffVersion, today: string): TariffVersion[] {
    if (!version.periods.some((period) => parseMonths(period.months).length > 0)) {
        return [version]
    }

    const changeMonths = Array.from({ length: 12 }, (_, index) => index + 1).filter(
        (month) => bandSignature(version, month) !== bandSignature(version, month === 1 ? 12 : month - 1),
    )
    if (changeMonths.length === 0) return [version]

    const end = version.valid_to ?? (today > version.valid_from ? today : version.valid_from)
    const boundaries: string[] = []
    for (let year = Number(version.valid_from.slice(0, 4)); year <= Number(end.slice(0, 4)); year += 1) {
        changeMonths.forEach((month) => {
            const day = isoDay(year, month, 1)
            if (day > version.valid_from && day <= end) boundaries.push(day)
        })
    }
    boundaries.sort()

    const segments: TariffVersion[] = []
    let from = version.valid_from
    const close = (to: string | null | undefined) => {
        segments.push({
            ...version,
            valid_from: from,
            valid_to: to ?? null,
            periods: bandsInMonth(version, Number(from.slice(5, 7))),
        })
    }
    boundaries.forEach((boundary) => {
        // The day before the boundary: the last day of the preceding month.
        close(isoDay(Number(boundary.slice(0, 4)), Number(boundary.slice(5, 7)), 0))
        from = boundary
    })
    close(version.valid_to)
    return segments
}

/**
 * Stretches where a derived price sits at zero because nothing backs it.
 *
 * Reported as gaps rather than left as a plunge to the axis: the number is what
 * would really be billed, but without shading it looks like the price collapsed
 * rather than like its basis went missing.
 */
function zeroBaseStretches(points: PriceHistoryPoint[]): Array<{ from: number, to: number }> {
    const stretches: Array<{ from: number, to: number }> = []
    points.forEach((point, index) => {
        const next = points[index + 1]
        if (!next) return
        if (point.values.effective === 0) {
            stretches.push({ from: point.t, to: next.t })
        }
    })
    return stretches
}

/**
 * Lay versions out as step-chart boundaries.
 *
 * Two versions that meet exactly need no point between them: with `stepAfter`
 * the earlier point already holds its value up to the later one.
 *
 * A version followed by a gap needs *two* extra points — its value repeated at
 * its real end date, then a null. Without the first, nothing draws the run at
 * all, because a chart with `connectNulls={false}` will not draw a segment into
 * a null: a nine-month version would collapse to a dot on its start date.
 */
function assemble(
    versions: TariffVersion[],
    bands: BandKey[],
    today: string,
    valuesFor: (version: TariffVersion) => Partial<Record<BandKey, number | null>>,
): PriceHistoryPoint[] {
    const points: PriceHistoryPoint[] = []
    const nulls = () => Object.fromEntries(bands.map((band) => [band, null]))

    versions.forEach((version, index) => {
        const values = valuesFor(version)
        points.push({ t: ms(version.valid_from), date: version.valid_from, values })

        const next = versions[index + 1]
        const endsOn = version.valid_to ? ms(version.valid_to) : null
        if (next && endsOn !== null && ms(next.valid_from) === endsOn + DAY_MS) {
            return // contiguous: the next point continues this step
        }

        const runEnd = endsOn ?? Math.max(ms(today), ms(version.valid_from))
        if (runEnd > ms(version.valid_from)) {
            points.push({ t: runEnd, date: isoFromMs(runEnd), values })
        }
        if (next && endsOn !== null) {
            const uncoveredFrom = endsOn + DAY_MS
            points.push({ t: uncoveredFrom, date: isoFromMs(uncoveredFrom), values: nulls() })
        }
    })

    return points
}

/**
 * Effective CHF/kWh for a percentage tariff, stepping at every boundary of
 * *either* timeline: the percentage can change, and so can the grid tariffs it
 * is a fraction of.
 */
function percentagePoints(
    versions: TariffVersion[], allSeries: TariffSeries[], today: string,
): PriceHistoryPoint[] {
    const gridSeries = allSeries.filter(
        (series) => series.billing_mode === 'energy' && series.energy_type === 'grid',
    )
    const boundaries = new Set<string>()
    versions.forEach((version) => {
        boundaries.add(version.valid_from)
        // The day after a version ends is a boundary too, so a gap in the
        // percentage tariff's own timeline breaks the line.
        if (version.valid_to) boundaries.add(isoFromMs(ms(version.valid_to) + DAY_MS))
    })
    gridSeries.forEach((series) => series.versions.forEach((version) => {
        boundaries.add(version.valid_from)
        if (version.valid_to) boundaries.add(isoFromMs(ms(version.valid_to) + DAY_MS))
    }))

    const first = versions[0]?.valid_from
    const end = versions.length ? isoFromMs(terminalBoundary(versions, today)) : today
    const relevant = [...boundaries]
        .filter((day) => first !== undefined && day >= first && day <= end)
        .sort()
    if (first !== undefined && !relevant.includes(end)) relevant.push(end)

    return relevant.map((day) => {
        const version = versionOn(versions, day)
        if (!version) {
            return { t: ms(day), date: day, values: { effective: null } }
        }
        const percentage = num(version.percentage) ?? 0
        const base = gridBaseOn(allSeries, day)
        return {
            t: ms(day),
            date: day,
            values: { effective: Number(((base * percentage) / 100).toFixed(5)) },
            note: `${percentage}% × ${base.toFixed(5)}`,
        }
    })
}
