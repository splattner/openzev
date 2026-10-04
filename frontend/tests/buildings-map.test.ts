import { describe, expect, it } from 'vitest'
import {
  buildingMapAddress,
  countUnlocated,
  groupBuildingsByFootprint,
  toMapEntries,
  type BuildingMapEntry,
} from '../src/features/participants/BuildingsMap'
import type { Building } from '../src/types/api'

const footprintA = {
  type: 'Polygon' as const,
  coordinates: [[[8.54, 47.36], [8.541, 47.36], [8.5405, 47.3605], [8.54, 47.36]]],
}
const footprintB = {
  type: 'Polygon' as const,
  coordinates: [[[7.4, 46.9], [7.401, 46.9], [7.4005, 46.9005], [7.4, 46.9]]],
}

const entry = (id: string, footprint: BuildingMapEntry['footprint'] = null, participants: string[] = []): BuildingMapEntry => ({
  id, name: `Haus ${id}`, address: 'Weg 1, 3000 Bern', footprint, participants,
})

describe('groupBuildingsByFootprint', () => {
  it('groups buildings that share the exact same footprint into one entry', () => {
    const groups = groupBuildingsByFootprint([entry('1', footprintA), entry('2', footprintA)])
    expect(groups).toHaveLength(1)
    expect(groups[0].buildings.map((b) => b.id)).toEqual(['1', '2'])
  })

  it('keeps buildings with different footprints in separate groups', () => {
    expect(groupBuildingsByFootprint([entry('1', footprintA), entry('2', footprintB)])).toHaveLength(2)
  })

  it('omits buildings without a footprint', () => {
    const groups = groupBuildingsByFootprint([entry('1', footprintA), entry('2', null), entry('3')])
    expect(groups.map((g) => g.buildings.map((b) => b.id))).toEqual([['1']])
  })

  it('returns no groups when nothing is located', () => {
    expect(groupBuildingsByFootprint([entry('1', null)])).toEqual([])
  })
})

describe('countUnlocated', () => {
  it('counts buildings with no footprint (null or undefined)', () => {
    expect(countUnlocated([entry('1', footprintA), entry('2', null), entry('3')])).toBe(2)
  })

  it('is zero when every building is located', () => {
    expect(countUnlocated([entry('1', footprintA)])).toBe(0)
  })
})

describe('toMapEntries', () => {
  const building: Building = {
    id: 'b1', zev: 'z', name: 'Haus A', address_line1: 'Weg 1', address_line2: '', postal_code: '3000', city: 'Bern',
    egid: null, notes: '', metering_point_count: 2, building_footprint: footprintA,
    current_participants: [{ id: 'p1', display_name: 'Anna' }, { id: 'p2', display_name: 'Ben' }],
    created_at: '', updated_at: '',
  }

  it('carries the name, one-line address, footprint and current participants', () => {
    expect(toMapEntries([building])).toEqual([
      { id: 'b1', name: 'Haus A', address: 'Weg 1, 3000 Bern', footprint: footprintA, participants: ['Anna', 'Ben'] },
    ])
  })

  it('leaves a building without an address with an empty address', () => {
    expect(buildingMapAddress({ ...building, address_line1: '', postal_code: '', city: '' })).toBe('')
  })
})
