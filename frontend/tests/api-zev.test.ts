import MockAdapter from 'axios-mock-adapter'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  downloadParticipantContractPdf,
  fetchMeteringPointAssignments,
} from '../src/lib/api/zev'
import { api } from '../src/lib/api/client'

describe('zev api module', () => {
  let apiMock: MockAdapter

  beforeEach(() => {
    apiMock = new MockAdapter(api)
  })

  afterEach(() => {
    apiMock.restore()
    vi.restoreAllMocks()
  })

  it('fetches metering point assignments without filter by default', async () => {
    apiMock.onGet('/zev/metering-point-assignments/').reply((config) => {
      expect(config.params).toEqual({})
      return [200, { count: 0, next: null, previous: null, results: [] }]
    })

    const result = await fetchMeteringPointAssignments()
    expect(result).toEqual([])
  })

  it('fetches metering point assignments with metering_point filter', async () => {
    apiMock.onGet('/zev/metering-point-assignments/').reply((config) => {
      expect(config.params).toEqual({ metering_point: 'mp-1' })
      return [200, { count: 1, next: null, previous: null, results: [{ id: 'a-1' }] }]
    })

    const result = await fetchMeteringPointAssignments('mp-1')
    expect(result).toEqual([{ id: 'a-1' }])
  })

  it('downloads participant contract and revokes generated object URL', async () => {
    const blob = new Blob(['pdf-data'], { type: 'application/pdf' })
    // POST, not GET: issuing the contract is a write, so it must stay under
    // CSRF protection (see #448).
    const postSpy = vi.spyOn(api, 'post').mockResolvedValue({ data: blob } as any)
    const objectUrl = 'blob:contract-url'

    const createUrlSpy = vi.spyOn(URL, 'createObjectURL').mockReturnValue(objectUrl)
    const revokeUrlSpy = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
    const appendSpy = vi.spyOn(document.body, 'appendChild')
    const removeSpy = vi.spyOn(document.body, 'removeChild')
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})

    await downloadParticipantContractPdf('participant-1', 'contract.pdf')

    expect(postSpy).toHaveBeenCalledWith('/zev/participants/participant-1/contract-pdf/', null, { responseType: 'blob' })
    expect(createUrlSpy).toHaveBeenCalledWith(blob)
    expect(appendSpy).toHaveBeenCalledTimes(1)
    expect(clickSpy).toHaveBeenCalledTimes(1)
    expect(removeSpy).toHaveBeenCalledTimes(1)
    expect(revokeUrlSpy).toHaveBeenCalledWith(objectUrl)
  })
})
