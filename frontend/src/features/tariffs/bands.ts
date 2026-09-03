import type { TariffPeriodType } from '../../types/api'

/**
 * What to call a price band.
 *
 * `flat`, `high` and `low` have names — they are the shapes a Swiss tariff has
 * always had. A `band` does not: it exists precisely because a tariff carries
 * more prices than there are conventional names, and the VSE/AES standard does
 * not label its bands either. So a band is called by its own label if one was
 * given, and otherwise by the window that tells it apart from its siblings.
 *
 * Mirrors `TariffPeriod.display_name` on the backend, which names the same
 * band on the contract PDF.
 */
type BandLike = {
    period_type: TariffPeriodType
    label?: string | null
    time_from?: string | null
    time_to?: string | null
}

/** `07:00` from either `07:00` or `07:00:00`. */
export function hhmm(value: string): string {
    return value.slice(0, 5)
}

export function bandWindow(period: BandLike): string | null {
    return period.time_from && period.time_to
        ? `${hhmm(period.time_from)}–${hhmm(period.time_to)}`
        : null
}

/** `translatedType` is the fallback: the period type's own translated name. */
export function bandName(period: BandLike, translatedType: string): string {
    if (period.period_type !== 'band') return translatedType
    return period.label || bandWindow(period) || translatedType
}
