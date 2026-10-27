import type { Tariff, TariffSeries, TariffVersion } from '../../types/api'

export type ValidityState = 'active' | 'scheduled' | 'expired'

/**
 * Where a tariff sits relative to `today`.
 *
 * Compared as ISO strings rather than `Date` objects: `new Date('2026-01-01')`
 * parses as UTC midnight, which reintroduces the offset that
 * `lib/dates.todayBusinessIso` exists to avoid. Lexicographic comparison of two
 * `YYYY-MM-DD` strings is exact.
 *
 * Both bounds are inclusive, so a tariff whose window opens or closes today is
 * active.
 */
export function validityState(tariff: Tariff, today: string): ValidityState {
    if (tariff.valid_from > today) return 'scheduled'
    if (tariff.valid_to && tariff.valid_to < today) return 'expired'
    return 'active'
}

export function isTariffCurrentlyValid(tariff: Tariff, today: string): boolean {
    return validityState(tariff, today) === 'active'
}

export function hasUpcomingVersion(versions: Tariff[], today: string): boolean {
    return versions.some((version) => validityState(version, today) === 'scheduled')
}

/**
 * The version a list row stands for. In the Upcoming view the next one to
 * start; otherwise the one in force, else the next to start, else the newest
 * one — a series with nothing in force shows what comes or what was, not its
 * oldest version. `versions` are newest first, as the series endpoint sends
 * them.
 */
export function listedVersion<T extends Tariff>(versions: T[], today: string, upcoming = false): T {
    const next = versions.findLast((version) => validityState(version, today) === 'scheduled')
    if (upcoming && next) return next
    return versions.find((version) => validityState(version, today) === 'active')
        ?? next
        ?? versions[0]
}

/**
 * A list row: the series, and the one version the row stands for. A row in
 * force also carries the version that follows it, so what changes and when
 * is read from the row rather than from a second one.
 */
export type TariffOverviewRow = { series: TariffSeries, version: TariffVersion, upcomingVersion?: TariffVersion }

export type TariffOverview = {
    current: TariffOverviewRow[]
    upcoming: TariffOverviewRow[]
    history: TariffOverviewRow[]
}

/**
 * The overview's three groups, one row per tariff series: in force (with its
 * next version, the nearest to start — `versions` are newest first, so the
 * last scheduled one); not in force yet (the nearest to start); and, in
 * History, ended with nothing in force or coming (the most recently ended
 * version). The older ended versions of a tariff are reached from the detail's
 * version history, not as rows of their own.
 */
export function tariffOverview(series: TariffSeries[], today: string): TariffOverview {
    const overview: TariffOverview = { current: [], upcoming: [], history: [] }
    for (const entry of series) {
        const active = entry.versions.find((version) => validityState(version, today) === 'active')
        const next = entry.versions.findLast((version) => validityState(version, today) === 'scheduled')
        const ended = entry.versions.find((version) => validityState(version, today) === 'expired')
        if (active) overview.current.push({ series: entry, version: active, upcomingVersion: next })
        else if (next) overview.upcoming.push({ series: entry, version: next })
        else if (ended) overview.history.push({ series: entry, version: ended })
    }
    return overview
}
