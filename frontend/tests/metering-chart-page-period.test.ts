import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import { meteringPointDataRange, readPeriodFromSearchParams } from '../src/pages/MeteringChartPage'

const SAVED_TZ = process.env.TZ

beforeAll(() => {
  // West of UTC: local getters on a UTC-morning instant shift to the
  // previous day — exactly the drift meteringPointDataRange must avoid.
  process.env.TZ = 'America/New_York'
})

afterAll(() => {
  if (SAVED_TZ === undefined) {
    delete process.env.TZ
  } else {
    process.env.TZ = SAVED_TZ
  }
})

describe('readPeriodFromSearchParams', () => {
  it('reads a valid from/to pair (#647)', () => {
    const params = new URLSearchParams({ from: '2026-01-01', to: '2026-03-31' })
    expect(readPeriodFromSearchParams(params)).toEqual({ from: '2026-01-01', to: '2026-03-31' })
  })

  it('returns null when to is missing', () => {
    const params = new URLSearchParams({ from: '2026-01-01' })
    expect(readPeriodFromSearchParams(params)).toBeNull()
  })

  it('returns null when the range is reversed', () => {
    const params = new URLSearchParams({ from: '2026-03-31', to: '2026-01-01' })
    expect(readPeriodFromSearchParams(params)).toBeNull()
  })

  it('returns null for a malformed date', () => {
    const params = new URLSearchParams({ from: 'not-a-date', to: '2026-01-31' })
    expect(readPeriodFromSearchParams(params)).toBeNull()
  })

  it('accepts a single-day range (from === to)', () => {
    const params = new URLSearchParams({ from: '2026-01-01', to: '2026-01-01' })
    expect(readPeriodFromSearchParams(params)).toEqual({ from: '2026-01-01', to: '2026-01-01' })
  })
})

describe('meteringPointDataRange', () => {
  it('converts first/last reading timestamps to a civil-day range (#642)', () => {
    const range = meteringPointDataRange({
      first_reading_at: '2026-01-02T14:00:00Z',
      last_reading_at: '2026-03-15T23:45:00Z',
    })
    expect(range).toEqual({ from: '2026-01-02', to: '2026-03-15' })
  })

  it('uses UTC getters, not local ones, for the civil day (#635)', () => {
    const range = meteringPointDataRange({
      first_reading_at: '2026-01-02T00:30:00Z',
      last_reading_at: '2026-01-02T00:30:00Z',
    })
    expect(range).toEqual({ from: '2026-01-02', to: '2026-01-02' })
  })

  it('returns null when the meter has never received a reading', () => {
    expect(meteringPointDataRange({ first_reading_at: null, last_reading_at: null })).toBeNull()
  })

  it('returns null when passed undefined (no metering point selected yet)', () => {
    expect(meteringPointDataRange(undefined)).toBeNull()
  })
})
