import { describe, expect, it } from 'vitest'
import { getMeteringPointCounts, getScopedAndFilteredMeteringPoints } from '../src/features/meteringPoints/useMeteringPointActions'
import type { MeteringPoint, MeteringPointAssignment } from '../src/types/api'

const meteringPoints = [
  {
    id: 'mp-1',
    zev: 'zev-1',
    meter_id: 'A-100',
    meter_type: 'consumption',
    is_active: true,
    location_description: 'Basement',
  },
  {
    id: 'mp-2',
    zev: 'zev-1',
    meter_id: 'B-200',
    meter_type: 'production',
    is_active: false,
    location_description: 'Roof',
  },
  {
    id: 'mp-3',
    zev: 'zev-2',
    meter_id: 'Solar-300',
    meter_type: 'bidirectional',
    is_active: true,
    location_description: 'Garage',
  },
] as MeteringPoint[]

describe('metering point action helpers', () => {
  it('scopes metering points to the selected ZEV when management is restricted', () => {
    const { scopedMeteringPoints } = getScopedAndFilteredMeteringPoints(meteringPoints, {
      selectedZevId: 'zev-1',
      canManageMeteringPoints: true,
      searchTerm: '',
      statusFilter: 'all',
      typeFilter: 'all',
    })

    expect(scopedMeteringPoints.map((point) => point.id)).toEqual(['mp-1', 'mp-2'])
  })

  it('filters by search term, status, and type', () => {
    const { meteringPoints: filteredMeteringPoints } = getScopedAndFilteredMeteringPoints(meteringPoints, {
      selectedZevId: null,
      canManageMeteringPoints: false,
      searchTerm: 'solar',
      statusFilter: 'active',
      typeFilter: 'bidirectional',
    })

    expect(filteredMeteringPoints).toHaveLength(1)
    expect(filteredMeteringPoints[0]).toMatchObject({
      id: 'mp-3',
      meter_id: 'Solar-300',
      meter_type: 'bidirectional',
      is_active: true,
    })
  })
})

describe('getMeteringPointCounts', () => {
  const today = '2026-05-08'

  function assignment(overrides: Partial<MeteringPointAssignment>): MeteringPointAssignment {
    return { valid_from: '2026-01-01', valid_to: null, ...overrides } as MeteringPointAssignment
  }

  it('counts active/inactive from the scoped list, independent of assignments', () => {
    const { activeCount, inactiveCount } = getMeteringPointCounts(meteringPoints, new Map(), today)
    expect(activeCount).toBe(2)
    expect(inactiveCount).toBe(1)
  })

  it('does not count a meter whose only assignment already ended', () => {
    const assignments = new Map([['mp-1', [assignment({ valid_from: '2025-01-01', valid_to: '2026-01-31' })]]])
    const { assignedCount } = getMeteringPointCounts(meteringPoints, assignments, today)
    expect(assignedCount).toBe(0)
  })

  it('does not count a meter whose only assignment has not started yet', () => {
    const assignments = new Map([['mp-1', [assignment({ valid_from: '2026-06-01', valid_to: null })]]])
    const { assignedCount } = getMeteringPointCounts(meteringPoints, assignments, today)
    expect(assignedCount).toBe(0)
  })

  it('counts a meter with an assignment in force today, even alongside ended ones', () => {
    const assignments = new Map([
      [
        'mp-1',
        [
          assignment({ valid_from: '2025-01-01', valid_to: '2025-12-31' }),
          assignment({ valid_from: '2026-01-01', valid_to: null }),
        ],
      ],
    ])
    const { assignedCount } = getMeteringPointCounts(meteringPoints, assignments, today)
    expect(assignedCount).toBe(1)
  })
})
