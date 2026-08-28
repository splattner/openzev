import MockAdapter from 'axios-mock-adapter'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { api } from '../src/lib/api/client'
import { fetchAllPages } from '../src/lib/api/pagination'

describe('fetchAllPages', () => {
  let apiMock: MockAdapter

  beforeEach(() => {
    apiMock = new MockAdapter(api)
  })

  afterEach(() => {
    apiMock.restore()
  })

  it('walks every page until next is null', async () => {
    apiMock
      .onGet('/zev/zevs/')
      .reply(200, { count: 150, next: 'http://testserver/api/v1/zev/zevs/?page=2', previous: null, results: [{ id: 'a' }] })
    apiMock
      .onGet('/zev/zevs/?page=2')
      .reply(200, { count: 150, next: '/zev/zevs/?page=3', previous: '…', results: [{ id: 'b' }] })
    apiMock
      .onGet('/zev/zevs/?page=3')
      .reply(200, { count: 150, next: null, previous: '…', results: [{ id: 'c' }] })

    const result = await fetchAllPages<{ id: string }>('/zev/zevs/')

    expect(result).toEqual([{ id: 'a' }, { id: 'b' }, { id: 'c' }])
    expect(apiMock.history.get).toHaveLength(3)
  })

  it('returns a single page when there is no next link', async () => {
    apiMock
      .onGet('/auth/users/')
      .reply(200, { count: 2, next: null, previous: null, results: [{ id: 1 }, { id: 2 }] })

    const result = await fetchAllPages<{ id: number }>('/auth/users/')

    expect(result).toEqual([{ id: 1 }, { id: 2 }])
    expect(apiMock.history.get).toHaveLength(1)
  })

  it('returns a bare array as-is when the endpoint is not DRF-paginated', async () => {
    apiMock
      .onGet('/tariffs/tariffs/series/')
      .reply(200, [{ id: 'a' }, { id: 'b' }])

    const result = await fetchAllPages<{ id: string }>('/tariffs/tariffs/series/')

    expect(result).toEqual([{ id: 'a' }, { id: 'b' }])
    expect(apiMock.history.get).toHaveLength(1)
  })

  it('passes params through and keeps them on later pages via the embedded next query', async () => {
    apiMock.onGet('/invoices/invoices/').reply((config) => {
      expect(config.params).toEqual({ zev_id: 'zev-1', status: 'draft' })
      return [
        200,
        {
          count: 2,
          next: 'http://backend:8000/api/v1/invoices/invoices/?zev_id=zev-1&status=draft&page=2',
          previous: null,
          results: [{ id: 'inv-1' }],
        },
      ]
    })
    apiMock
      .onGet('/invoices/invoices/?zev_id=zev-1&status=draft&page=2')
      .reply((config) => {
        // DRF embeds the original filters in `next`; pages 2+ must keep them.
        expect(config.url).toContain('?zev_id=zev-1&status=draft&page=2')
        return [200, { count: 2, next: null, previous: '…', results: [{ id: 'inv-2' }] }]
      })

    const result = await fetchAllPages<{ id: string }>('/invoices/invoices/', {
      zev_id: 'zev-1',
      status: 'draft',
    })

    expect(result).toEqual([{ id: 'inv-1' }, { id: 'inv-2' }])
  })

  it('rewrites an absolute next link into the base-relative path with its query preserved', async () => {
    apiMock
      .onGet('/zev/zevs/')
      .reply(200, {
        count: 51,
        next: 'http://backend:8000/api/v1/zev/zevs/?page=2&ordering=-created_at',
        previous: null,
        results: [{ id: 'a' }],
      })
    apiMock
      .onGet('/zev/zevs/?page=2&ordering=-created_at')
      .reply(200, { count: 51, next: null, previous: '…', results: [{ id: 'b' }] })

    await fetchAllPages<{ id: string }>('/zev/zevs/')

    expect(apiMock.history.get).toHaveLength(2)
    const followUp = apiMock.history.get[1].url ?? ''
    expect(followUp.startsWith('http')).toBe(false)
    expect(followUp).toBe('/zev/zevs/?page=2&ordering=-created_at')
  })

  it('propagates an error raised mid-walk', async () => {
    apiMock
      .onGet('/zev/participants/')
      .reply(200, { count: 100, next: 'http://testserver/api/v1/zev/participants/?page=2', previous: null, results: [{ id: 'a' }] })
    apiMock
      .onGet('/zev/participants/?page=2')
      .reply(500, { detail: 'boom' })

    await expect(fetchAllPages<{ id: string }>('/zev/participants/')).rejects.toMatchObject({
      response: { status: 500 },
    })
  })

  it('enforces the page-request cap against an endless next chain', async () => {
    // Every page hands back the same next URL — the walker must bail out at the cap.
    apiMock.onGet(/zev\/metering-points\//).reply(() => [
      200,
      { count: 1, next: 'http://testserver/api/v1/zev/metering-points/?page=1', previous: null, results: [{ id: 'a' }] },
    ])

    await expect(fetchAllPages<{ id: string }>('/zev/metering-points/')).rejects.toThrow(
      /exceeded 200 page requests/,
    )
  })
})
