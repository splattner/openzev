import MockAdapter from 'axios-mock-adapter'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  bulkDeleteImportLogs,
  fetchChartData,
  fetchMeteringDataQualityStatus,
  uploadMeteringFile,
} from '../src/lib/api/metering'
import { api } from '../src/lib/api/client'

describe('metering api module', () => {
  let apiMock: MockAdapter

  beforeEach(() => {
    apiMock = new MockAdapter(api)
  })

  afterEach(() => {
    apiMock.restore()
    vi.restoreAllMocks()
  })

  it('maps bulk delete payload fields to backend shape', async () => {
    apiMock.onPost('/metering/import-logs/bulk-delete/').reply((config) => {
      const payload = JSON.parse(config.data as string)
      expect(payload).toEqual({
        mode: 'period',
        date_from: '2026-01-01',
        date_to: '2026-01-31',
        zev_id: 'zev-1',
      })
      return [200, { deleted_logs: 4, deleted_readings: 120 }]
    })

    const result = await bulkDeleteImportLogs({
      mode: 'period',
      dateFrom: '2026-01-01',
      dateTo: '2026-01-31',
      zevId: 'zev-1',
    })

    expect(result).toEqual({ deleted_logs: 4, deleted_readings: 120 })
  })

  it('builds quality-status query string with optional filters', async () => {
    apiMock.onGet(/\/metering\/readings\/data-quality-status\/\?.*/).reply((config) => {
      expect(config.url).toContain('date_from=2026-01-01')
      expect(config.url).toContain('date_to=2026-01-31')
      expect(config.url).toContain('zev_id=zev-1')
      expect(config.url).toContain('metering_point=mp-1')
      return [200, { overall_status: 'ok', days: [] }]
    })

    const result = await fetchMeteringDataQualityStatus({
      dateFrom: '2026-01-01',
      dateTo: '2026-01-31',
      zevId: 'zev-1',
      meteringPointId: 'mp-1',
    })

    expect(result.overall_status).toBe('ok')
  })

  it('requests chart data for a single metering point', async () => {
    apiMock.onGet('/metering/readings/chart-data/').reply((config) => {
      expect(config.params).toEqual({
        metering_point: 'mp-1',
        zev_id: undefined,
        date_from: '2026-01-01',
        date_to: '2026-01-31',
        bucket: 'day',
      })
      return [200, [{ bucket: '2026-01-01T00:00:00+00:00', in_kwh: 1, out_kwh: 0 }]]
    })

    const result = await fetchChartData({
      meteringPoint: 'mp-1',
      dateFrom: '2026-01-01',
      dateTo: '2026-01-31',
    })

    expect(result).toHaveLength(1)
  })

  it('requests chart data aggregated by zevId instead of a single meter (#650)', async () => {
    apiMock.onGet('/metering/readings/chart-data/').reply((config) => {
      expect(config.params).toEqual({
        metering_point: undefined,
        zev_id: 'zev-1',
        date_from: '2026-01-01',
        date_to: '2026-01-31',
        bucket: 'hour',
      })
      return [200, []]
    })

    await fetchChartData({
      zevId: 'zev-1',
      dateFrom: '2026-01-01',
      dateTo: '2026-01-31',
      bucket: 'hour',
    })
  })

  it('sends csv upload settings as multipart form-data fields', async () => {
    apiMock.onPost('/metering/import/csv/').reply((config) => {
      const formData = config.data as FormData
      expect(formData.get('zev_id')).toBe('zev-1')
      expect(formData.get('col_meter_id')).toBe('meter')
      expect(formData.get('col_timestamp')).toBe('time')
      expect(formData.get('col_energy_kwh')).toBe('value')
      expect(formData.get('delimiter')).toBe(';')
      expect(formData.get('has_header')).toBe('true')
      expect(formData.get('format_profile')).toBe('daily_15min')
      expect(formData.get('interval_minutes')).toBe('15')
      expect(formData.get('values_count')).toBe('96')
      expect(formData.get('overwrite_existing')).toBe('true')
      return [200, { id: 'import-1' }]
    })

    const file = new File(['meter,data'], 'readings.csv', { type: 'text/csv' })
    const result = await uploadMeteringFile({
      source: 'csv',
      zevId: 'zev-1',
      file,
      columnMap: {
        meter_id: 'meter',
        timestamp: 'time',
        energy_kwh: 'value',
      },
      delimiter: ';',
      hasHeader: true,
      formatProfile: 'daily_15min',
      intervalMinutes: 15,
      valuesCount: 96,
      overwriteExisting: true,
    })

    expect(result.id).toBe('import-1')
  })
})
