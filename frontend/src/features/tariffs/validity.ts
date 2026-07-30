import type { Tariff } from '../../types/api'

export type ValidityState = 'active' | 'scheduled' | 'expired'

/**
 * Today as `YYYY-MM-DD` in the viewer's own timezone.
 *
 * Deliberately not `new Date().toISOString().slice(0, 10)`: that yields the UTC
 * date, so anywhere east of UTC (Switzerland included) the first hour or two
 * after midnight reports yesterday — long enough for a tariff that starts today
 * to be treated as not yet in force.
 */
export function todayIso(): string {
    const now = new Date()
    const month = String(now.getMonth() + 1).padStart(2, '0')
    const day = String(now.getDate()).padStart(2, '0')
    return `${now.getFullYear()}-${month}-${day}`
}

/**
 * Where a tariff sits relative to `today`.
 *
 * Compared as ISO strings rather than `Date` objects: `new Date('2026-01-01')`
 * parses as UTC midnight, which reintroduces the offset that `todayIso` exists
 * to avoid. Lexicographic comparison of two `YYYY-MM-DD` strings is exact.
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
