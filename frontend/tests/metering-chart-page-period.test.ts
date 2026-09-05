import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import {
  filterAndRankQualityRows,
  meteringPointDataRange,
  peakChartPoint,
  readPeriodFromSearchParams,
  readSeverityFilter,
} from '../src/pages/MeteringChartPage'
import type { MeteringPointDataQuality } from '../src/types/api'

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
  it('reads the canonical period_start/period_end pair', () => {
    const params = new URLSearchParams({ period_start: '2026-01-01', period_end: '2026-03-31' })
    expect(readPeriodFromSearchParams(params)).toEqual({ from: '2026-01-01', to: '2026-03-31' })
  })

  it('reads a legacy from/to pair (#647)', () => {
    const params = new URLSearchParams({ from: '2026-01-01', to: '2026-03-31' })
    expect(readPeriodFromSearchParams(params)).toEqual({ from: '2026-01-01', to: '2026-03-31' })
  })

  it('prefers the canonical pair when both formats are present', () => {
    const params = new URLSearchParams({
      period_start: '2026-04-01',
      period_end: '2026-04-30',
      from: '2026-01-01',
      to: '2026-01-31',
    })
    expect(readPeriodFromSearchParams(params)).toEqual({ from: '2026-04-01', to: '2026-04-30' })
  })

  it('does not combine an incomplete canonical pair with legacy values', () => {
    const params = new URLSearchParams({
      period_start: '2026-04-01',
      from: '2026-01-01',
      to: '2026-01-31',
    })
    expect(readPeriodFromSearchParams(params)).toBeNull()
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

describe('peakChartPoint', () => {
  const data = [
    { bucket: '2026-01-01', in_kwh: 3, out_kwh: 1 },
    { bucket: '2026-01-02', in_kwh: 9, out_kwh: 5 },
    { bucket: '2026-01-03', in_kwh: 4, out_kwh: 2 },
  ]

  it('finds the bucket with the highest in_kwh (#651)', () => {
    expect(peakChartPoint(data, 'in_kwh')).toEqual(data[1])
  })

  it('finds the bucket with the highest out_kwh independently', () => {
    expect(peakChartPoint(data, 'out_kwh')).toEqual(data[1])
  })

  it('returns null for an empty chart', () => {
    expect(peakChartPoint([], 'in_kwh')).toBeNull()
  })

  it('returns the single bucket for a one-point chart', () => {
    expect(peakChartPoint([data[0]], 'in_kwh')).toEqual(data[0])
  })
})

describe('readSeverityFilter', () => {
  it('reads a valid severity (#648)', () => {
    expect(readSeverityFilter(new URLSearchParams({ quality_severity: 'red' }))).toBe('red')
    expect(readSeverityFilter(new URLSearchParams({ quality_severity: 'yellow' }))).toBe('yellow')
    expect(readSeverityFilter(new URLSearchParams({ quality_severity: 'green' }))).toBe('green')
  })

  it('falls back to "all" when absent or invalid', () => {
    expect(readSeverityFilter(new URLSearchParams())).toBe('all')
    expect(readSeverityFilter(new URLSearchParams({ quality_severity: 'purple' }))).toBe('all')
  })
})

describe('filterAndRankQualityRows', () => {
  const mp = (id: string, severity: MeteringPointDataQuality['severity']): MeteringPointDataQuality => ({
    id,
    meter_id: `CH-${id}`,
    participant_name: 'Someone',
    severity,
    data_completeness: severity === 'green' ? 100 : severity === 'yellow' ? 50 : 0,
    days_with_data: 0,
    total_days: 0,
    gaps: [],
    unassigned_days: 0,
    unassigned_readings: 0,
    assignment_overlap: false,
  })
  const points = [mp('1', 'green'), mp('2', 'red'), mp('3', 'yellow')]

  it('passes every row through unfiltered for "all", tagged with a severity rank (#648)', () => {
    const rows = filterAndRankQualityRows(points, 'all')
    expect(rows.map((r) => r.id)).toEqual(['1', '2', '3'])
    expect(rows.find((r) => r.id === '2')?.severityRank).toBe(0) // red: worst, sorts first
    expect(rows.find((r) => r.id === '3')?.severityRank).toBe(1) // yellow
    expect(rows.find((r) => r.id === '1')?.severityRank).toBe(2) // green: best, sorts last
  })

  it('narrows to exactly the selected severity', () => {
    expect(filterAndRankQualityRows(points, 'red').map((r) => r.id)).toEqual(['2'])
    expect(filterAndRankQualityRows(points, 'yellow').map((r) => r.id)).toEqual(['3'])
  })

  it('returns an empty array when nothing matches', () => {
    expect(filterAndRankQualityRows([mp('1', 'green')], 'red')).toEqual([])
  })
})
