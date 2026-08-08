import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import { formatIsoDate, formatUtcIsoDate, todayLocalIso } from '../src/lib/dates'

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

describe('todayLocalIso', () => {
  it('returns today in the local timezone', () => {
    expect(todayLocalIso()).toBe(formatIsoDate(new Date()))
  })
})
