import MockAdapter from 'axios-mock-adapter'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { api } from '../src/lib/api/client'
import { fetchDynamicTariffSources } from '../src/lib/api/tariffs'
import { dynamicSourceOptions, impliedEnergyType } from '../src/features/tariffs/dynamicSources'
import type { DynamicTariffSource } from '../src/types/api'

/**
 * The tariff form's "dynamic price source" picker: which energy type a
 * source implies, and which sources are worth offering once that energy
 * type is already locked (editing an existing version).
 */
function source(overrides: Partial<DynamicTariffSource> = {}): DynamicTariffSource {
  return {
    id: 'src-1',
    label: 'Groupe E vario — grid',
    url: 'https://api.tariffs.groupe-e.ch/v2/tariffs',
    adapter: 'groupe_e',
    tariff_type: 'grid',
    tariff_name: 'vario',
    last_fetch_status: 'ok',
    last_fetch_at: '2026-09-11T12:00:00Z',
    last_success_at: '2026-09-11T12:00:00Z',
    last_fetch_error: '',
    covers_from: '2025-12-11T00:00:00Z',
    covers_to: '2026-09-12T00:00:00Z',
    ...overrides,
  }
}

describe('impliedEnergyType', () => {
  it('is grid for every VSE type except feed_in', () => {
    for (const type of ['electricity', 'grid', 'integrated', 'regional_fees'] as const) {
      expect(impliedEnergyType(source({ tariff_type: type }))).toBe('grid')
    }
  })

  it('is feed_in for a feed-in remuneration source', () => {
    expect(impliedEnergyType(source({ tariff_type: 'feed_in' }))).toBe('feed_in')
  })
})

describe('dynamicSourceOptions', () => {
  const grid = source({ id: 'grid-src', tariff_type: 'grid' })
  const feedIn = source({ id: 'feed-in-src', tariff_type: 'feed_in', label: 'BKW feed-in' })

  it('offers every source when nothing is locked yet — a brand-new tariff', () => {
    expect(dynamicSourceOptions([grid, feedIn])).toEqual([grid, feedIn])
  })

  it('filters to sources matching the locked energy type — an existing version', () => {
    expect(dynamicSourceOptions([grid, feedIn], 'grid')).toEqual([grid])
    expect(dynamicSourceOptions([grid, feedIn], 'feed_in')).toEqual([feedIn])
  })

  it('offers nothing for a locked energy type no source can serve', () => {
    // 'local' (onsite solar) has no dynamic counterpart at all — no operator
    // publishes a fetchable price for a ZEV's own production.
    expect(dynamicSourceOptions([grid, feedIn], 'local')).toEqual([])
  })

  it('treats a missing lock the same as none — null or undefined', () => {
    expect(dynamicSourceOptions([grid, feedIn], null)).toEqual([grid, feedIn])
    expect(dynamicSourceOptions([grid, feedIn], undefined)).toEqual([grid, feedIn])
  })
})

describe('fetchDynamicTariffSources', () => {
  let apiMock: MockAdapter

  beforeEach(() => {
    apiMock = new MockAdapter(api)
  })

  afterEach(() => {
    apiMock.restore()
  })

  it('reads the global, paginated list to the end', () => {
    apiMock.onGet('/tariffs/dynamic-sources/').reply(200, {
      count: 1, next: null, previous: null, results: [source()],
    })

    return expect(fetchDynamicTariffSources()).resolves.toEqual([source()])
  })
})
