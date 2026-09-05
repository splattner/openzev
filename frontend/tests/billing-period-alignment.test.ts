import { describe, expect, it } from 'vitest'
import {
    billingPeriodFromRange,
    billingRangeFromParams,
    firstAlignedBillingPeriod,
    getCurrentBillingPeriod,
    invoiceRangeFromParams,
    isBillingAlignedPeriod,
    recentBillingPeriods,
    shiftBillingPeriod,
} from '../src/lib/billingPeriod'

/**
 * The period selector disables its prev/next arrows when the active range is not
 * exactly one billing period, so this predicate decides whether navigation is offered.
 */
describe('isBillingAlignedPeriod', () => {
  it('accepts a range spanning exactly one billing period', () => {
    expect(isBillingAlignedPeriod('2026-05-01', '2026-05-31', 'monthly')).toBe(true)
    expect(isBillingAlignedPeriod('2026-04-01', '2026-06-30', 'quarterly')).toBe(true)
    expect(isBillingAlignedPeriod('2026-07-01', '2026-12-31', 'semi_annual')).toBe(true)
    expect(isBillingAlignedPeriod('2026-01-01', '2026-12-31', 'annual')).toBe(true)
  })

  it('rejects a range that stops short of the period end', () => {
    expect(isBillingAlignedPeriod('2026-05-01', '2026-05-30', 'monthly')).toBe(false)
  })

  it('rejects a range that starts after the period start', () => {
    expect(isBillingAlignedPeriod('2026-05-02', '2026-05-31', 'monthly')).toBe(false)
  })

  it('rejects a whole month when the interval is quarterly', () => {
    expect(isBillingAlignedPeriod('2026-05-01', '2026-05-31', 'quarterly')).toBe(false)
  })

  it('handles a leap-year February', () => {
    expect(isBillingAlignedPeriod('2024-02-01', '2024-02-29', 'monthly')).toBe(true)
    expect(isBillingAlignedPeriod('2024-02-01', '2024-02-28', 'monthly')).toBe(false)
  })

  it('rejects an empty range', () => {
    expect(isBillingAlignedPeriod('', '', 'monthly')).toBe(false)
    expect(isBillingAlignedPeriod('2026-05-01', '', 'monthly')).toBe(false)
  })
})

describe('billingPeriodFromRange (readiness/attention destination contract)', () => {
  it('accepts a range that exactly spans one billing period', () => {
    expect(billingPeriodFromRange('2026-08-01', '2026-08-31', 'monthly')).toEqual({
      from: '2026-08-01',
      to: '2026-08-31',
    })
    expect(billingPeriodFromRange('2026-10-01', '2026-12-31', 'quarterly')).toEqual({
      from: '2026-10-01',
      to: '2026-12-31',
    })
  })

  it('falls back to the page default when either bound is missing', () => {
    expect(billingPeriodFromRange(null, '2026-08-31', 'monthly')).toBeNull()
    expect(billingPeriodFromRange('2026-08-01', undefined, 'monthly')).toBeNull()
    expect(billingPeriodFromRange('', '', 'monthly')).toBeNull()
  })

  it('rejects a range that does not span the whole period', () => {
    expect(billingPeriodFromRange('2026-08-01', '2026-08-15', 'monthly')).toBeNull()
    expect(billingPeriodFromRange('2026-08-01', '2026-08-31', 'quarterly')).toBeNull()
  })

  it('rejects a period before the community existed (floor)', () => {
    expect(billingPeriodFromRange('2025-01-01', '2025-01-31', 'monthly', '2026-03-01')).toBeNull()
    expect(billingPeriodFromRange('2026-08-01', '2026-08-31', 'monthly', '2026-03-01')).not.toBeNull()
  })
})

describe('billingRangeFromParams (custom metering ranges survive the URL)', () => {
  it('accepts any well-formed range, aligned or not', () => {
    expect(billingRangeFromParams('2026-08-01', '2026-08-31')).toEqual({ from: '2026-08-01', to: '2026-08-31' })
    expect(billingRangeFromParams('2026-08-05', '2026-08-20')).toEqual({ from: '2026-08-05', to: '2026-08-20' })
  })

  it('rejects malformed or reversed ranges', () => {
    expect(billingRangeFromParams(null, '2026-08-31')).toBeNull()
    expect(billingRangeFromParams('2026-08-20', undefined)).toBeNull()
    expect(billingRangeFromParams('2026-08-31', '2026-08-01')).toBeNull()
    expect(billingRangeFromParams('not-a-date', '2026-08-31')).toBeNull()
  })

  it('rejects dates that do not exist on the calendar', () => {
    expect(billingRangeFromParams('2026-02-30', '2026-02-31')).toBeNull()
    expect(billingRangeFromParams('2026-02-29', '2026-03-01')).toBeNull() // 2026 not a leap year
    expect(billingRangeFromParams('2026-04-31', '2026-05-01')).toBeNull()
  })

  it('accepts real dates including leap-day February', () => {
    expect(billingRangeFromParams('2028-02-29', '2028-02-29')).toEqual({ from: '2028-02-29', to: '2028-02-29' })
    expect(billingRangeFromParams('2026-02-28', '2026-03-01')).not.toBeNull()
  })
})

describe('invoiceRangeFromParams (invoices page URL bound)', () => {
  it('accepts a historical period from an earlier interval after the community start', () => {
    // Leftover monthly period (Dec 2025) under a quarterly ZEV that started
    // Nov 2025: unaligned but real, so the alert link must still open it.
    expect(invoiceRangeFromParams('2025-12-01', '2025-12-31', '2025-11-10')).toEqual({
      from: '2025-12-01',
      to: '2025-12-31',
    })
  })

  it('rejects a range that starts before the community existed', () => {
    expect(invoiceRangeFromParams('2025-01-01', '2025-01-31', '2026-03-01')).toBeNull()
  })

  it('accepts anything valid when the community start is unknown', () => {
    expect(invoiceRangeFromParams('2026-08-05', '2026-08-20', null)).toEqual({
      from: '2026-08-05',
      to: '2026-08-20',
    })
  })

  it('still rejects malformed or reversed ranges', () => {
    expect(invoiceRangeFromParams('not-a-date', '2026-08-31', '2026-01-01')).toBeNull()
    expect(invoiceRangeFromParams('2026-08-31', '2026-08-01', '2026-01-01')).toBeNull()
  })
})

describe('recentBillingPeriods (whole-period presets)', () => {
  it('lists the running period first, then older ones', () => {
    const list = recentBillingPeriods('monthly', 5)
    expect(list).toHaveLength(6)
    expect(list[0]).toEqual(getCurrentBillingPeriod('monthly'))
    expect(list[1]).toEqual(shiftBillingPeriod(list[0].from, 'monthly', -1))
  })

  it('never offers periods before the community floor', () => {
    const current = getCurrentBillingPeriod('monthly')
    const floor = shiftBillingPeriod(current.from, 'monthly', -3).from
    const list = recentBillingPeriods('monthly', 5, floor)
    expect(list).toHaveLength(4) // current −3 .. current
    expect(list[list.length - 1].from).toBe(floor)
  })

  it('drops every preset when the community has no completed period yet', () => {
    const farFuture = shiftBillingPeriod(getCurrentBillingPeriod('monthly').from, 'monthly', 12).from
    expect(recentBillingPeriods('monthly', 5, farFuture)).toEqual([])
  })
})

describe('firstAlignedBillingPeriod (community-start floor)', () => {
  it('returns the containing period when the start is aligned', () => {
    expect(firstAlignedBillingPeriod('2026-01-01', 'quarterly')).toEqual({ from: '2026-01-01', to: '2026-03-31' })
    expect(firstAlignedBillingPeriod('2026-02-01', 'monthly')).toEqual({ from: '2026-02-01', to: '2026-02-28' })
  })

  it('skips the partial containing period for a mid-period start', () => {
    expect(firstAlignedBillingPeriod('2026-02-15', 'quarterly')).toEqual({ from: '2026-04-01', to: '2026-06-30' })
    expect(firstAlignedBillingPeriod('2026-02-15', 'monthly')).toEqual({ from: '2026-03-01', to: '2026-03-31' })
  })

  it('covers semi-annual and annual boundaries', () => {
    expect(firstAlignedBillingPeriod('2026-01-01', 'semi_annual')).toEqual({ from: '2026-01-01', to: '2026-06-30' })
    expect(firstAlignedBillingPeriod('2026-03-15', 'semi_annual')).toEqual({ from: '2026-07-01', to: '2026-12-31' })
    expect(firstAlignedBillingPeriod('2026-01-01', 'annual')).toEqual({ from: '2026-01-01', to: '2026-12-31' })
    expect(firstAlignedBillingPeriod('2026-03-15', 'annual')).toEqual({ from: '2027-01-01', to: '2027-12-31' })
  })

  it('handles a missing or malformed start', () => {
    expect(firstAlignedBillingPeriod(null, 'monthly')).toBeNull()
    expect(firstAlignedBillingPeriod('2026-02-30', 'monthly')).toBeNull()
  })
})
