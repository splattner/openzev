import MockAdapter from 'axios-mock-adapter'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { api } from '../src/lib/api/client'
import {
  clearDynamicSourcePrices,
  createDynamicTariffSource,
  deleteDynamicTariffSource,
  discoverDynamicTariffSource,
  fetchDynamicPriceHistory,
  fetchDynamicTariffSources,
  queueDynamicSourceFetch,
} from '../src/lib/api/tariffs'
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
    label: 'Example dynamic grid',
    url: 'https://prices.example.test/tariffs',
    api_version: 'v1_0_5',
    tariff_type: 'grid',
    tariff_name: 'vario',
    last_fetch_status: 'ok',
    last_fetch_at: '2026-09-11T12:00:00Z',
    last_success_at: '2026-09-11T12:00:00Z',
    last_fetch_error: '',
    covers_from: '2025-12-11T00:00:00Z',
    covers_to: '2026-09-12T00:00:00Z',
    point_count: 100,
    linked_tariff_count: 2,
    linked_zev_count: 1,
    supports_backfill: true,
    created_at: '2026-09-01T10:00:00Z',
    updated_at: '2026-09-11T12:00:00Z',
    ...overrides,
  }
}

describe('impliedEnergyType', () => {
  it('is grid for every VSE type except feed_in', () => {
    for (const type of ['electricity', 'grid', 'metering', 'national_fees', 'dso', 'dso_complete', 'integrated', 'integrated_complete', 'regional_fees'] as const) {
      expect(impliedEnergyType(source({ tariff_type: type }))).toBe('grid')
    }
  })

  it('is feed_in for a feed-in remuneration source', () => {
    expect(impliedEnergyType(source({ tariff_type: 'feed_in' }))).toBe('feed_in')
    expect(impliedEnergyType(source({ tariff_type: 'refund' }))).toBe('feed_in')
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

  it('creates a manually configured source', async () => {
    apiMock.onPost('/tariffs/dynamic-sources/').reply((config) => {
      expect(JSON.parse(config.data as string)).toEqual({
        label: 'Example grid',
        url: 'https://prices.example.test',
        api_version: 'v1_0_5',
        tariff_type: 'grid',
        tariff_name: 'standard',
      })
      return [201, source({ label: 'Example grid' })]
    })

    const result = await createDynamicTariffSource({
      label: 'Example grid',
      url: 'https://prices.example.test',
      api_version: 'v1_0_5',
      tariff_type: 'grid',
      tariff_name: 'standard',
    })

    expect(result.label).toBe('Example grid')
  })

  it('discovers an endpoint before source creation', async () => {
    apiMock.onPost('/tariffs/dynamic-sources/discover/').reply((config) => {
      expect(JSON.parse(config.data as string)).toEqual({ url: 'https://prices.example.test' })
      return [200, {
        api_version: 'v2_0_0',
        version_detected: true,
        components_discovered: true,
        components: [{ tariff_type: 'grid', tariff_name: 'standard' }],
      }]
    })

    await expect(discoverDynamicTariffSource('https://prices.example.test')).resolves.toEqual({
      api_version: 'v2_0_0',
      version_detected: true,
      components_discovered: true,
      components: [{ tariff_type: 'grid', tariff_name: 'standard' }],
    })
  })

  it('requests a bounded price-history window', async () => {
    apiMock.onGet('/tariffs/dynamic-sources/src-1/prices/').reply((config) => {
      expect(config.params).toEqual({ date_from: '2026-09-01', date_to: '2026-09-07' })
      return [200, { source: 'src-1', points: [], gaps: [], stats: {} }]
    })

    const result = await fetchDynamicPriceHistory('src-1', '2026-09-01', '2026-09-07')

    expect(result.source).toBe('src-1')
  })

  it('queues fetches and sends typed clear confirmation in the request body', async () => {
    apiMock.onPost('/tariffs/dynamic-sources/src-1/fetch/', { backfill: true }).reply(202, {
      task_id: 'task-1', correlation_id: 'corr-1', backfill: true, queued_at: '2026-09-11T12:00:00Z',
    })
    apiMock.onDelete('/tariffs/dynamic-sources/src-1/prices/').reply((config) => {
      // The typed-back label is the whole payload: no reason is asked for.
      expect(JSON.parse(config.data as string)).toEqual({ confirmation: 'Example' })
      return [200, { deleted_points: 10 }]
    })

    await expect(queueDynamicSourceFetch('src-1', true)).resolves.toMatchObject({ task_id: 'task-1' })
    await expect(clearDynamicSourcePrices('src-1', 'Example')).resolves.toEqual({ deleted_points: 10 })
  })

  it('deletes a source by id with the typed-back label', async () => {
    // A different endpoint from clearing: /{id}/ removes the source itself,
    // /{id}/prices/ only empties it.
    apiMock.onDelete('/tariffs/dynamic-sources/src-1/').reply((config) => {
      expect(JSON.parse(config.data as string)).toEqual({ confirmation: 'Example' })
      return [204]
    })

    await expect(deleteDynamicTariffSource('src-1', 'Example')).resolves.toBeUndefined()
  })
})
