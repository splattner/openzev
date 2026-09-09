import { describe, expect, it } from 'vitest'
import { dayAnomalyFlags, readingAnomalies } from '../src/components/RawMeteringTable'
import type { MeteringPointAssignment, RawMeteringReading } from '../src/types/api'

function assignment(overrides: Partial<MeteringPointAssignment> = {}): MeteringPointAssignment {
  return {
    id: 'a-1',
    metering_point: 'mp-1',
    participant: 'p-1',
    valid_from: '2026-01-01',
    valid_to: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    allocation_mode: 'personal',
    ...overrides,
  }
}

describe('dayAnomalyFlags', () => {
  it('flags zero consumption only when an assignment covers that day (#652)', () => {
    const zeroDay = { date: '2026-01-15', in_kwh: 0, out_kwh: 0 }
    const assignments = [assignment({ valid_from: '2026-01-01', valid_to: '2026-01-31' })]
    expect(dayAnomalyFlags(zeroDay, assignments).zeroConsumptionWithHolder).toBe(true)
  })

  it('does not flag zero consumption on a holder-less meter', () => {
    const zeroDay = { date: '2026-01-15', in_kwh: 0, out_kwh: 0 }
    expect(dayAnomalyFlags(zeroDay, []).zeroConsumptionWithHolder).toBe(false)
  })

  it('does not flag zero consumption outside the assignment window', () => {
    const zeroDay = { date: '2026-02-01', in_kwh: 0, out_kwh: 0 }
    const assignments = [assignment({ valid_from: '2026-01-01', valid_to: '2026-01-31' })]
    expect(dayAnomalyFlags(zeroDay, assignments).zeroConsumptionWithHolder).toBe(false)
  })

  it('does not flag a day with any consumption, even with a holder', () => {
    const day = { date: '2026-01-15', in_kwh: 0.001, out_kwh: 0 }
    const assignments = [assignment()]
    expect(dayAnomalyFlags(day, assignments).zeroConsumptionWithHolder).toBe(false)
  })

  it('flags a negative day total regardless of assignment', () => {
    expect(dayAnomalyFlags({ date: '2026-01-15', in_kwh: -1, out_kwh: 0 }, []).negativeTotal).toBe(true)
    expect(dayAnomalyFlags({ date: '2026-01-15', in_kwh: 0, out_kwh: -1 }, []).negativeTotal).toBe(true)
    expect(dayAnomalyFlags({ date: '2026-01-15', in_kwh: 1, out_kwh: 1 }, []).negativeTotal).toBe(false)
  })

  it('treats an open-ended assignment as covering every later day', () => {
    const assignments = [assignment({ valid_from: '2026-01-01', valid_to: null })]
    expect(dayAnomalyFlags({ date: '2027-06-01', in_kwh: 0, out_kwh: 0 }, assignments).zeroConsumptionWithHolder).toBe(true)
  })
})

describe('readingAnomalies', () => {
  const reading = (overrides: Partial<RawMeteringReading> = {}): RawMeteringReading => ({
    timestamp: '2026-01-15T12:00:00Z',
    direction: 'in',
    energy_kwh: 1.5,
    resolution: 'fifteen_min',
    import_source: 'csv',
    ...overrides,
  })

  it('counts negative readings (#652)', () => {
    const readings = [reading({ energy_kwh: 1 }), reading({ energy_kwh: -0.5 }), reading({ energy_kwh: -2 })]
    expect(readingAnomalies(readings).negativeCount).toBe(2)
  })

  it('counts duplicate (timestamp, direction) pairs, not total duplicate readings', () => {
    const readings = [
      reading({ timestamp: '2026-01-15T12:00:00Z', direction: 'in' }),
      reading({ timestamp: '2026-01-15T12:00:00Z', direction: 'in' }),
      reading({ timestamp: '2026-01-15T12:00:00Z', direction: 'in' }),
      reading({ timestamp: '2026-01-15T12:15:00Z', direction: 'in' }),
    ]
    // Three readings share one (timestamp, direction) pair — that's 1 duplicated pair, not 3.
    expect(readingAnomalies(readings).duplicateCount).toBe(1)
  })

  it('does not flag the same timestamp on two different directions as a duplicate', () => {
    const readings = [
      reading({ timestamp: '2026-01-15T12:00:00Z', direction: 'in' }),
      reading({ timestamp: '2026-01-15T12:00:00Z', direction: 'out' }),
    ]
    expect(readingAnomalies(readings).duplicateCount).toBe(0)
  })

  it('reports nothing for clean readings', () => {
    const readings = [reading({ timestamp: '2026-01-15T12:00:00Z' }), reading({ timestamp: '2026-01-15T12:15:00Z' })]
    expect(readingAnomalies(readings)).toEqual({ negativeCount: 0, duplicateCount: 0 })
  })

  it('reports nothing for an empty list', () => {
    expect(readingAnomalies([])).toEqual({ negativeCount: 0, duplicateCount: 0 })
  })
})
