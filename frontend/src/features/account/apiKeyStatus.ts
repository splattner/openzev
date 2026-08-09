import type { ApiKey } from '../../types/api'

type ApiKeyStatus = 'active' | 'expiring' | 'expired'

/**
 * Days before expiry at which a key starts being flagged.
 *
 * Optional-with-a-default expiry only works if it is visible before it bites;
 * otherwise the default just moves the silent breakage a year out.
 */
export const EXPIRY_WARNING_DAYS = 14

export function daysUntilExpiry(key: Pick<ApiKey, 'expires_at'>, now: Date = new Date()): number | null {
    if (!key.expires_at) return null
    const expiry = new Date(key.expires_at).getTime()
    return Math.ceil((expiry - now.getTime()) / 86_400_000)
}

export function apiKeyStatus(key: Pick<ApiKey, 'expires_at'>, now: Date = new Date()): ApiKeyStatus {
    const days = daysUntilExpiry(key, now)
    if (days === null) return 'active'
    if (days <= 0) return 'expired'
    return days <= EXPIRY_WARNING_DAYS ? 'expiring' : 'active'
}

/**
 * ``expires_at`` for a key that should last ``days`` more days, as the ISO
 * string the API expects. Returns null for "no expiry".
 */
export function expiryFromDays(days: number | null, now: Date = new Date()): string | null {
    if (days === null) return null
    return new Date(now.getTime() + days * 86_400_000).toISOString()
}
