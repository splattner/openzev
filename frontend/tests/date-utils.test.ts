import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import {
  BUSINESS_TIME_ZONE,
  businessDayStartMs,
  daysInPeriod,
  formatBusinessIsoDate,
  formatIsoDate,
  formatUtcIsoDate,
  isValidIsoDate,
  nextIsoDate,
  todayBusinessIso,
  zonedParts,
} from '../src/lib/dates'

const SAVED_TZ = process.env.TZ

beforeAll(() => {
  // West of UTC: local getters on a UTC-midnight instant shift to the previous
  // day, which is exactly the drift the chart used to show.
  process.env.TZ = 'America/New_York'
})

afterAll(() => {
  if (SAVED_TZ === undefined) {
    delete process.env.TZ
  } else {
    process.env.TZ = SAVED_TZ
  }
})

describe('formatUtcIsoDate', () => {
  it('renders UTC-midnight instants without shifting the date west of UTC', () => {
    const utcMidnight = new Date('2026-01-01T00:00:00Z')
    expect(formatIsoDate(utcMidnight)).toBe('2025-12-31') // the local-getter drift
    expect(formatUtcIsoDate(utcMidnight)).toBe('2026-01-01')
  })

  it('preserves the date even when the instant falls late on the UTC day', () => {
    expect(formatUtcIsoDate(new Date('2026-06-30T23:59:59Z'))).toBe('2026-06-30')
  })
})

describe('todayBusinessIso', () => {
  it('returns today in the business timezone', () => {
    expect(todayBusinessIso()).toBe(formatBusinessIsoDate(new Date()))
  })
})

describe('business timezone', () => {
  it('is Europe/Zurich, like the backend settings.TIME_ZONE', () => {
    expect(BUSINESS_TIME_ZONE).toBe('Europe/Zurich')
  })

  it('reads instants in Swiss time in winter and summer, whatever the viewer zone', () => {
    expect(zonedParts(new Date('2026-01-15T13:30:00Z'))).toEqual({ year: 2026, month: 1, day: 15, hours: 14, minutes: 30 })
    expect(zonedParts(new Date('2026-07-15T22:15:00Z'))).toEqual({ year: 2026, month: 7, day: 16, hours: 0, minutes: 15 })
  })

  it('finds Swiss midnight on ordinary and DST days', () => {
    expect(new Date(businessDayStartMs('2026-01-15')).toISOString()).toBe('2026-01-14T23:00:00.000Z')
    expect(new Date(businessDayStartMs('2026-07-15')).toISOString()).toBe('2026-07-14T22:00:00.000Z')
    expect(new Date(businessDayStartMs('2026-03-29')).toISOString()).toBe('2026-03-28T23:00:00.000Z')
    expect(new Date(businessDayStartMs('2026-03-30')).toISOString()).toBe('2026-03-29T22:00:00.000Z')
    expect(new Date(businessDayStartMs('2026-10-25')).toISOString()).toBe('2026-10-24T22:00:00.000Z')
    expect(new Date(businessDayStartMs('2026-10-26')).toISOString()).toBe('2026-10-25T23:00:00.000Z')
  })

  it('steps to the next civil date across month and year ends', () => {
    expect(nextIsoDate('2026-01-31')).toBe('2026-02-01')
    expect(nextIsoDate('2026-12-31')).toBe('2027-01-01')
    expect(nextIsoDate('2026-03-29')).toBe('2026-03-30')
  })
})

describe('daysInPeriod', () => {
  it('counts a single day as 1', () => {
    expect(daysInPeriod('2026-01-01', '2026-01-01')).toBe(1)
  })

  it('counts a whole month inclusively', () => {
    expect(daysInPeriod('2026-01-01', '2026-01-31')).toBe(31)
  })

  it('is unaffected by a DST transition in the viewer timezone', () => {
    // America/New_York springs forward on 2026-03-08; a local-time diff
    // would lose an hour here and risk an off-by-one day count.
    expect(daysInPeriod('2026-03-01', '2026-03-31')).toBe(31)
  })

  it('returns 0 for missing or unparseable bounds', () => {
    expect(daysInPeriod('', '2026-01-31')).toBe(0)
    expect(daysInPeriod('2026-01-01', '')).toBe(0)
    expect(daysInPeriod('not-a-date', '2026-01-31')).toBe(0)
  })
})

describe('isValidIsoDate', () => {
  it('accepts a well-formed calendar date', () => {
    expect(isValidIsoDate('2026-01-31')).toBe(true)
  })

  it('rejects a date-shaped string that is not a real calendar date', () => {
    expect(isValidIsoDate('2026-02-30')).toBe(false)
  })

  it('rejects malformed, empty, and missing values', () => {
    expect(isValidIsoDate('2026-1-1')).toBe(false)
    expect(isValidIsoDate('not-a-date')).toBe(false)
    expect(isValidIsoDate('')).toBe(false)
    expect(isValidIsoDate(null)).toBe(false)
    expect(isValidIsoDate(undefined)).toBe(false)
  })
})
