import { describe, expect, it } from 'vitest'
import {
  EXPIRY_WARNING_DAYS,
  apiKeyStatus,
  daysUntilExpiry,
  expiryFromDays,
} from '../src/features/account/apiKeyStatus'

const NOW = new Date('2026-08-03T12:00:00Z')

function inDays(days: number): string {
  return new Date(NOW.getTime() + days * 86_400_000).toISOString()
}

/**
 * Expiry that is optional-with-a-default only helps if it is visible before it
 * bites. Without the warning window, the default just moves the silent breakage
 * a year out — the script stops working and nothing said why.
 */
describe('apiKeyStatus', () => {
  it('treats a key with no expiry as active', () => {
    expect(apiKeyStatus({ expires_at: null }, NOW)).toBe('active')
    expect(daysUntilExpiry({ expires_at: null }, NOW)).toBeNull()
  })

  it('treats a key far from expiry as active', () => {
    expect(apiKeyStatus({ expires_at: inDays(90) }, NOW)).toBe('active')
  })

  it('flags a key inside the warning window', () => {
    expect(apiKeyStatus({ expires_at: inDays(EXPIRY_WARNING_DAYS - 1) }, NOW)).toBe('expiring')
  })

  it('flags a key that has already expired', () => {
    expect(apiKeyStatus({ expires_at: inDays(-1) }, NOW)).toBe('expired')
  })

  it('treats the moment of expiry as expired, not expiring', () => {
    expect(apiKeyStatus({ expires_at: NOW.toISOString() }, NOW)).toBe('expired')
  })

  it('counts whole days remaining, rounding up a partial day', () => {
    const inThirtySixHours = new Date(NOW.getTime() + 1.5 * 86_400_000).toISOString()
    expect(daysUntilExpiry({ expires_at: inThirtySixHours }, NOW)).toBe(2)
  })
})

describe('expiryFromDays', () => {
  it('maps a day count to an ISO timestamp the API accepts', () => {
    expect(expiryFromDays(30, NOW)).toBe('2026-09-02T12:00:00.000Z')
  })

  it('maps "never" to null rather than to a far-future date', () => {
    expect(expiryFromDays(null, NOW)).toBeNull()
  })

  it('produces an expiry the status helper reads back as active', () => {
    const expires_at = expiryFromDays(365, NOW)
    expect(apiKeyStatus({ expires_at }, NOW)).toBe('active')
  })
})
