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
      needsAttentionByMeteringPoint: new Map(),
      selectedZevId: 'zev-1',
      isManagedScope: true,
      searchTerm: '',
      typeFilter: 'all',
    })

    expect(scopedMeteringPoints.map((point) => point.id)).toEqual(['mp-1', 'mp-2'])
  })

  it('does not show an unscoped management inventory without a selection', () => {
    const { scopedMeteringPoints } = getScopedAndFilteredMeteringPoints(meteringPoints, {
      needsAttentionByMeteringPoint: new Map(),
      selectedZevId: null, isManagedScope: true, searchTerm: '', typeFilter: 'all',
    })
    expect(scopedMeteringPoints).toEqual([])
  })

  it('filters by search term, view, and type', () => {
    const { meteringPoints: filteredMeteringPoints } = getScopedAndFilteredMeteringPoints(meteringPoints, {
      needsAttentionByMeteringPoint: new Map(),
      selectedZevId: null,
      isManagedScope: false,
      searchTerm: 'solar',
      view: 'active',
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

  it('leaves every meter in in the "all" view', () => {
    const { meteringPoints: allViewPoints } = getScopedAndFilteredMeteringPoints(meteringPoints, {
      needsAttentionByMeteringPoint: new Map(),
      selectedZevId: null,
      isManagedScope: false,
      searchTerm: '',
      typeFilter: 'all',
    })
    expect(allViewPoints).toHaveLength(3)
  })

  it('matches search against an assigned participant\'s name, not just meter ID or location', () => {
    const { meteringPoints: filteredMeteringPoints } = getScopedAndFilteredMeteringPoints(meteringPoints, {
      needsAttentionByMeteringPoint: new Map(),
      selectedZevId: null,
      isManagedScope: false,
      searchTerm: 'anna',
      typeFilter: 'all',
      participantNamesByMeteringPoint: new Map([['mp-1', 'Anna Consumer']]),
    })

    expect(filteredMeteringPoints.map((point) => point.id)).toEqual(['mp-1'])
  })

  it('leaves every meter in in the "all" view, whatever the assignments', () => {
    const { meteringPoints: filteredMeteringPoints } = getScopedAndFilteredMeteringPoints(meteringPoints, {
      needsAttentionByMeteringPoint: new Map(),
      selectedZevId: null,
      isManagedScope: false,
      searchTerm: '',
      typeFilter: 'all',
      isAssignedByMeteringPoint: new Map([['mp-1', true]]),
    })
    expect(filteredMeteringPoints).toHaveLength(3)
  })

  it('narrows to meters without a current holder in the "unassigned" view', () => {
    const { meteringPoints: filteredMeteringPoints } = getScopedAndFilteredMeteringPoints(meteringPoints, {
      needsAttentionByMeteringPoint: new Map(),
      selectedZevId: null,
      isManagedScope: false,
      searchTerm: '',
      typeFilter: 'all',
      view: 'unassigned',
      isAssignedByMeteringPoint: new Map([
        ['mp-1', true],
        ['mp-2', false],
      ]),
    })

    // mp-3 has unknown assignment status, so it is excluded.
    expect(filteredMeteringPoints.map((point) => point.id).sort()).toEqual(['mp-2'])
  })
})

it('combines attention with community and type filters, ignoring missing attention entries', () => {
  const needsAttentionByMeteringPoint = new Map([['mp-1', true], ['mp-3', true]])
  const { meteringPoints: filtered } = getScopedAndFilteredMeteringPoints(meteringPoints, {
    selectedZevId: 'zev-1', isManagedScope: true, searchTerm: '', typeFilter: 'consumption',
    view: 'attention', needsAttentionByMeteringPoint,
  })
  expect(filtered.map((point) => point.id)).toEqual(['mp-1'])
  expect(getMeteringPointCounts(meteringPoints.slice(0, 2), new Map(), '2026-05-08', needsAttentionByMeteringPoint).needsAttentionCount).toBe(1)
})

describe('getMeteringPointCounts', () => {
  const today = '2026-05-08'

  function assignment(overrides: Partial<MeteringPointAssignment>): MeteringPointAssignment {
    return { valid_from: '2026-01-01', valid_to: null, ...overrides } as MeteringPointAssignment
  }

  it('counts active/inactive from the scoped list, independent of assignments', () => {
    const { activeCount, inactiveCount } = getMeteringPointCounts(meteringPoints, new Map(), today, new Map())
    expect(activeCount).toBe(2)
    expect(inactiveCount).toBe(1)
  })

  it('does not count a meter whose only assignment already ended', () => {
    const assignments = new Map([['mp-1', [assignment({ valid_from: '2025-01-01', valid_to: '2026-01-31' })]]])
    const { assignedCount } = getMeteringPointCounts(meteringPoints, assignments, today, new Map())
    expect(assignedCount).toBe(0)
  })

  it('does not count a meter whose only assignment has not started yet', () => {
    const assignments = new Map([['mp-1', [assignment({ valid_from: '2026-06-01', valid_to: null })]]])
    const { assignedCount } = getMeteringPointCounts(meteringPoints, assignments, today, new Map())
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
    const { assignedCount } = getMeteringPointCounts(meteringPoints, assignments, today, new Map())
    expect(assignedCount).toBe(1)
  })
})

it('does not count unavailable assignments as unassigned', () => {
  expect(getMeteringPointCounts(meteringPoints, undefined, '2026-05-08', new Map()).unassignedCount).toBe(0)
  expect(getMeteringPointCounts(meteringPoints, new Map(), '2026-05-08', new Map()).unassignedCount).toBe(3)
})

it('combines attention with search and building filters', () => {
  const points = meteringPoints.map(point => ({ ...point, building: point.id === 'mp-1' ? 'building-1' : 'building-2' }))
  const filter = { selectedZevId: 'zev-1', isManagedScope: true, searchTerm: 'basement', typeFilter: 'all' as const,
    view: 'attention' as const, buildingFilter: 'building-1', needsAttentionByMeteringPoint: new Map([['mp-1', true]]) }
  expect(getScopedAndFilteredMeteringPoints(points, filter).meteringPoints.map(point => point.id)).toEqual(['mp-1'])
  expect(getScopedAndFilteredMeteringPoints(points, { ...filter, searchTerm: 'roof' }).meteringPoints).toEqual([])
  expect(getScopedAndFilteredMeteringPoints(points, { ...filter, buildingFilter: 'building-2' }).meteringPoints).toEqual([])
})
