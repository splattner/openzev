import MockAdapter from 'axios-mock-adapter'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { downloadAnnualStatement, downloadFinancialSummary } from '../src/lib/api/invoices'
import { api } from '../src/lib/api/client'

describe('reports api helpers', () => {
  let apiMock: MockAdapter

  beforeEach(() => {
    apiMock = new MockAdapter(api)
  })

  afterEach(() => {
    apiMock.restore()
  })

  it('returns the annual-statement blob for a bare year without a signal', async () => {
    const blob = new Blob(['statement'], { type: 'application/pdf' })
    apiMock.onGet('/invoices/invoices/annual-statement/').reply((config) => {
      expect(config.params).toEqual({ year: 2025 })
      expect(config.responseType).toBe('blob')
      return [200, blob]
    })

    const result = await downloadAnnualStatement({ year: 2025 })
    expect(result).toBe(blob)
  })

  it('forwards an abort signal for the annual statement', async () => {
    const blob = new Blob(['statement'], { type: 'application/pdf' })
    const controller = new AbortController()
    apiMock.onGet('/invoices/invoices/annual-statement/').reply((config) => {
      expect(config.signal).toBe(controller.signal)
      return [200, blob]
    })

    const result = await downloadAnnualStatement({ year: 2025 }, controller.signal)
    expect(result).toBe(blob)
  })

  it('returns the financial-summary blob and preserves optional manager parameters', async () => {
    const blob = new Blob(['tax'], { type: 'application/pdf' })
    apiMock.onGet('/invoices/invoices/financial-summary/').reply((config) => {
      expect(config.params).toEqual({ year: 2025, zev_id: 'zev-1' })
      expect(config.responseType).toBe('blob')
      return [200, blob]
    })

    const result = await downloadFinancialSummary({ year: 2025, zev_id: 'zev-1' })
    expect(result).toBe(blob)
  })

  it('forwards an abort signal for the financial summary without manager parameters', async () => {
    const blob = new Blob(['tax'], { type: 'application/pdf' })
    const controller = new AbortController()
    apiMock.onGet('/invoices/invoices/financial-summary/').reply((config) => {
      expect(config.params).toEqual({ year: 2025 })
      expect(config.signal).toBe(controller.signal)
      return [200, blob]
    })

    const result = await downloadFinancialSummary({ year: 2025 }, controller.signal)
    expect(result).toBe(blob)
  })
})
