import type { PvPlaneInput } from '../types/api'

export const PLANE_LIMITS = { maxPerPoint: 4, maxKwp: 10_000 } as const

/** A roof plane as typed into the form: strings, parsed by `planeInput`. */
export interface PlaneDraft {
    label: string
    kwp: string
    tilt: string
    azimuth: string
}

/** The API input for a draft, or `null` when a value is missing or out of range. */
export function planeInput(draft: PlaneDraft): PvPlaneInput | null {
    const kwp = Number(draft.kwp)
    const tilt = Number(draft.tilt)
    const azimuth = Number(draft.azimuth)
    if (draft.kwp.trim() === '' || !Number.isFinite(kwp) || kwp < 0.01 || kwp > PLANE_LIMITS.maxKwp) return null
    if (draft.tilt.trim() === '' || !Number.isInteger(tilt) || tilt < 0 || tilt > 90) return null
    if (draft.azimuth.trim() === '' || !Number.isInteger(azimuth) || azimuth < -180 || azimuth > 180) return null
    return { label: draft.label.trim(), peak_power_kwp: kwp.toFixed(2), tilt_deg: tilt, azimuth_deg: azimuth }
}

// Whole keys, not built from a name: the dead-key check finds them as literals.
const DIRECTION_KEYS = [
    'pages.meteringPoints.planes.direction.south',
    'pages.meteringPoints.planes.direction.southWest',
    'pages.meteringPoints.planes.direction.west',
    'pages.meteringPoints.planes.direction.northWest',
    'pages.meteringPoints.planes.direction.north',
    'pages.meteringPoints.planes.direction.northEast',
    'pages.meteringPoints.planes.direction.east',
    'pages.meteringPoints.planes.direction.southEast',
] as const

/** i18n key of the compass direction an azimuth (0 south, 90 west, -90 east, ±180 north) is closest to. */
export function azimuthLabelKey(azimuth: number): (typeof DIRECTION_KEYS)[number] {
    // Eight 45° sectors, counted from south towards west.
    const normalised = ((azimuth % 360) + 360) % 360
    return DIRECTION_KEYS[Math.round(normalised / 45) % 8]
}

/**
 * A typed coordinate as the API string (five decimals), `null` when empty and `undefined` when it is
 * not a number within `±limit`.
 */
export function coordinateInput(text: string, limit: number): string | null | undefined {
    const trimmed = text.trim().replace(',', '.')
    if (trimmed === '') return null
    const value = Number(trimmed)
    if (!Number.isFinite(value) || Math.abs(value) > limit) return undefined
    return value.toFixed(5)
}
