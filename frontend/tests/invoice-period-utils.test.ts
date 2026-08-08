import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  endOfBillingPeriod,
  getPreviousBillingPeriod,
  isBillingAlignedPeriod,
  shiftBillingPeriod,
  startOfBillingPeriod,
} from '../src/lib/billingPeriod'
import { formatIsoDate } from '../src/lib/dates'

describe('invoice period utilities', () => {
  it('formats date as iso', () => {
    expect(formatIsoDate(new Date(2026, 4, 8))).toBe('2026-05-08')
  })

  it('computes start of period for each billing interval', () => {
    const date = new Date(2026, 4, 15)

    expect(formatIsoDate(startOfBillingPeriod(date, 'monthly'))).toBe('2026-05-01')
    expect(formatIsoDate(startOfBillingPeriod(date, 'quarterly'))).toBe('2026-04-01')
    expect(formatIsoDate(startOfBillingPeriod(date, 'semi_annual'))).toBe('2026-01-01')
    expect(formatIsoDate(startOfBillingPeriod(date, 'annual'))).toBe('2026-01-01')
  })

  it('computes end of period for each billing interval', () => {
    expect(formatIsoDate(endOfBillingPeriod(new Date(2026, 4, 1), 'monthly'))).toBe('2026-05-31')
    expect(formatIsoDate(endOfBillingPeriod(new Date(2026, 3, 1), 'quarterly'))).toBe('2026-06-30')
    expect(formatIsoDate(endOfBillingPeriod(new Date(2026, 0, 1), 'semi_annual'))).toBe('2026-06-30')
    expect(formatIsoDate(endOfBillingPeriod(new Date(2026, 0, 1), 'annual'))).toBe('2026-12-31')
  })

  it('shifts period backward and forward', () => {
    expect(shiftBillingPeriod('2026-05-01', 'monthly', -1)).toEqual({
      from: '2026-04-01',
      to: '2026-04-30',
    })

    expect(shiftBillingPeriod('2026-04-01', 'quarterly', 1)).toEqual({
      from: '2026-07-01',
      to: '2026-09-30',
    })
  })
})

/**
 * The invoices page opens on the last complete period. The current one is still
 * running, so it carries partial metering data and no invoices — defaulting to
 * it made every billing run begin by stepping back one period.
 */
describe('getPreviousBillingPeriod', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('returns the period before the one containing today', () => {
    vi.setSystemTime(new Date(2026, 4, 8)) // 8 May 2026, mid-period

    expect(getPreviousBillingPeriod('monthly')).toEqual({ from: '2026-04-01', to: '2026-04-30' })
    expect(getPreviousBillingPeriod('quarterly')).toEqual({ from: '2026-01-01', to: '2026-03-31' })
    expect(getPreviousBillingPeriod('semi_annual')).toEqual({ from: '2025-07-01', to: '2025-12-31' })
    expect(getPreviousBillingPeriod('annual')).toEqual({ from: '2025-01-01', to: '2025-12-31' })
  })

  it('crosses the year boundary', () => {
    vi.setSystemTime(new Date(2026, 0, 5)) // 5 January 2026

    expect(getPreviousBillingPeriod('monthly')).toEqual({ from: '2025-12-01', to: '2025-12-31' })
    expect(getPreviousBillingPeriod('quarterly')).toEqual({ from: '2025-10-01', to: '2025-12-31' })
  })

  it('returns the period just ended on its first day', () => {
    vi.setSystemTime(new Date(2026, 6, 1)) // 1 July 2026, first day of Q3

    expect(getPreviousBillingPeriod('quarterly')).toEqual({ from: '2026-04-01', to: '2026-06-30' })
  })

  it('yields a range the period selector treats as navigable', () => {
    vi.setSystemTime(new Date(2026, 4, 8))

    const previous = getPreviousBillingPeriod('quarterly')
    expect(isBillingAlignedPeriod(previous.from, previous.to, 'quarterly')).toBe(true)
  })
})
