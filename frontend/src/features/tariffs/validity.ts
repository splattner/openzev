import type { Tariff } from '../../types/api'

export type ValidityState = 'active' | 'scheduled' | 'expired'

/**
 * Where a tariff sits relative to `today`.
 *
 * Compared as ISO strings rather than `Date` objects: `new Date('2026-01-01')`
 * parses as UTC midnight, which reintroduces the offset that
 * `lib/dates.todayLocalIso` exists to avoid. Lexicographic comparison of two
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
