import { describe, expect, it } from 'vitest'
import { readPeriodFromSearchParams } from '../src/pages/MeteringChartPage'

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
