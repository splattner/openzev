import { describe, expect, it } from 'vitest'
import { buildHourTable, dataBarPercent, dayAnomalyFlags, readingAnomalies } from '../src/components/RawMeteringTable'
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
    condition: '',
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

describe('dataBarPercent', () => {
  it('scales a value to the period max (#641)', () => {
    expect(dataBarPercent(5, 10)).toBe(50)
    expect(dataBarPercent(10, 10)).toBe(100)
    expect(dataBarPercent(0, 10)).toBe(0)
  })

  it('uses the magnitude of a negative value, not a blank bar', () => {
    expect(dataBarPercent(-5, 10)).toBe(50)
  })

  it('never exceeds 100 even if a value somehow exceeds the given max', () => {
    expect(dataBarPercent(15, 10)).toBe(100)
  })

  it('returns 0 rather than dividing by zero when every value in the period is zero', () => {
    expect(dataBarPercent(0, 0)).toBe(0)
    expect(dataBarPercent(5, 0)).toBe(0)
  })
})

describe('buildHourTable', () => {
  const at = (
    timestamp: string,
    energy_kwh = 1,
    direction: 'in' | 'out' = 'in',
    resolution = '15min',
  ): RawMeteringReading => ({ timestamp, direction, energy_kwh, resolution, import_source: 'csv', condition: '' })

  it('has one value column for an hourly day', () => {
    const table = buildHourTable([at('2026-01-15T11:00:00Z', 1, 'in', 'hourly'), at('2026-01-15T12:00:00Z', 2, 'in', 'hourly')], 'in')
    expect(table.slots).toEqual([0])
    expect(table.rows).toHaveLength(24)
    // 11:00Z and 12:00Z are 12:00 and 13:00 Swiss time.
    expect(table.rows[12].total).toBe(1)
    expect(table.rows[13].cells[0].total).toBe(2)
    expect(table.rows[0].total).toBeNull()
  })

  it('has the four quarter-hour columns for a 15-minute day and totals each hour', () => {
    const readings = ['00', '15', '30', '45'].map((m) => at(`2026-01-15T11:${m}:00Z`, 0.5))
    const table = buildHourTable(readings, 'in')
    expect(table.slots).toEqual([0, 15, 30, 45])
    expect(table.rows[12].total).toBe(2)
  })

  it('keeps a quarter-hour column that has no reading all day, so the gap shows', () => {
    const table = buildHourTable([at('2026-01-15T11:15:00Z'), at('2026-01-15T12:30:00Z')], 'in')
    expect(table.slots).toEqual([0, 15, 30, 45])
    expect(table.rows[12].cells[0].readings).toHaveLength(0)
    expect(table.rows[12].cells[1].total).toBe(1)
  })

  it('never hides a reading off the full hour, whatever its stored resolution', () => {
    const table = buildHourTable([at('2026-01-15T11:30:00Z', 1, 'in', 'hourly')], 'in')
    expect(table.slots).toEqual([0, 15, 30, 45])
    expect(table.rows[12].cells[2].total).toBe(1)
  })

  it('only counts the requested direction', () => {
    const table = buildHourTable([at('2026-01-15T11:15:00Z', 1, 'in'), at('2026-01-15T11:00:00Z', 3, 'out', 'hourly')], 'out')
    expect(table.slots).toEqual([0])
    expect(table.rows[12].total).toBe(3)
  })

  it('leaves the skipped spring hour empty', () => {
    // 00:45Z is 01:45 CET; 01:00Z is already 03:00 CEST on 29 March 2026.
    const table = buildHourTable([at('2026-03-29T00:45:00Z'), at('2026-03-29T01:00:00Z')], 'in')
    expect(table.rows[1].cells[3].total).toBe(1)
    expect(table.rows[2].total).toBeNull()
    expect(table.rows[3].cells[0].total).toBe(1)
  })

  it('combines each repeated autumn quarter-hour in one cell', () => {
    // 00:15Z and 01:15Z are both 02:15 Swiss local time on 25 October 2026.
    const table = buildHourTable([at('2026-10-25T00:15:00Z'), at('2026-10-25T01:15:00Z', 2)], 'in')
    expect(table.rows[2].cells[1].total).toBe(3)
    expect(table.rows[2].cells[1].readings).toHaveLength(2)
  })
})
