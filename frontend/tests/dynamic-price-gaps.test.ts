import { describe, expect, it } from 'vitest'
import {
  dynamicChartData,
  elapsedPriceGaps,
  missingPriceDates,
} from '../src/features/tariffs/dynamicPriceGaps'
import { defaultHistoryDateRange } from '../src/features/tariffs/DynamicPriceHistoryModal'
import type { DynamicTariffSource } from '../src/types/api'

// Europe/Zurich is UTC+2 in October (CEST), so local midnight is 22:00Z the day before.
const gap = (from: string, to: string) => ({ from, to })

describe('elapsedPriceGaps', () => {
  const now = Date.parse('2026-10-10T12:00:00Z')

  it('keeps a gap that is entirely in the past', () => {
    const past = gap('2026-10-02T22:00:00Z', '2026-10-05T22:00:00Z')
    expect(elapsedPriceGaps([past], now)).toEqual([past])
  })

  it('ignores a gap that has not started yet — prices may not be published', () => {
    expect(elapsedPriceGaps([gap('2026-10-11T22:00:00Z', '2026-10-12T22:00:00Z')], now)).toEqual([])
  })

  it('cuts a gap that runs into the future off at now', () => {
    const [clipped] = elapsedPriceGaps([gap('2026-10-10T10:00:00Z', '2026-10-12T22:00:00Z')], now)
    expect(clipped).toEqual({ from: '2026-10-10T10:00:00Z', to: new Date(now).toISOString() })
  })

  it('ignores a gap that starts exactly now', () => {
    expect(elapsedPriceGaps([gap(new Date(now).toISOString(), '2026-10-12T22:00:00Z')], now)).toEqual([])
  })
})

describe('missingPriceDates', () => {
  it('names the civil dates in the business timezone, the end being exclusive', () => {
    // 03.10. 00:00 local until 06.10. 00:00 local → 03.10. to 05.10.
    expect(missingPriceDates([gap('2026-10-02T22:00:00Z', '2026-10-05T22:00:00Z')]))
      .toEqual([{ from: '2026-10-03', to: '2026-10-05' }])
  })

  it('reports an hour-long hole as its single date', () => {
    expect(missingPriceDates([gap('2026-10-03T10:00:00Z', '2026-10-03T11:00:00Z')]))
      .toEqual([{ from: '2026-10-03', to: '2026-10-03' }])
  })

  it('merges holes on the same day and on adjacent days', () => {
    expect(missingPriceDates([
      gap('2026-10-03T10:00:00Z', '2026-10-03T11:00:00Z'),
      gap('2026-10-03T14:00:00Z', '2026-10-03T15:00:00Z'),
      gap('2026-10-04T10:00:00Z', '2026-10-04T11:00:00Z'),
    ])).toEqual([{ from: '2026-10-03', to: '2026-10-04' }])
  })

  it('keeps ranges apart when a day lies between them', () => {
    expect(missingPriceDates([
      gap('2026-10-07T10:00:00Z', '2026-10-07T11:00:00Z'),
      gap('2026-10-03T10:00:00Z', '2026-10-03T11:00:00Z'),
    ])).toEqual([
      { from: '2026-10-03', to: '2026-10-03' },
      { from: '2026-10-07', to: '2026-10-07' },
    ])
  })

  it('folds a range contained in an earlier one into it', () => {
    expect(missingPriceDates([
      gap('2026-10-02T22:00:00Z', '2026-10-09T22:00:00Z'),
      gap('2026-10-04T10:00:00Z', '2026-10-04T11:00:00Z'),
    ])).toEqual([{ from: '2026-10-03', to: '2026-10-09' }])
  })

  it('is empty without gaps', () => {
    expect(missingPriceDates([])).toEqual([])
  })
})

describe('dynamicChartData', () => {
  const point = (from: string, to: string, price: string) => ({
    valid_from: from, valid_to: to, price_chf_per_kwh: price,
  })

  it('holds each price across its interval and breaks the line at a gap', () => {
    const rows = dynamicChartData(
      [point('2026-10-01T00:00:00Z', '2026-10-01T01:00:00Z', '0.10000'), point('2026-10-01T02:00:00Z', '2026-10-01T03:00:00Z', '0.20000')],
      [gap('2026-10-01T01:00:00Z', '2026-10-01T02:00:00Z')],
      Date.parse('2026-10-01T00:00:00Z'),
      Date.parse('2026-10-01T03:00:00Z'),
    )
    expect(rows.map((row) => row.price)).toEqual([0.1, 0.1, null, null, 0.2, 0.2])
    expect(rows.map((row) => row.timestamp)).toEqual([...rows.map((row) => row.timestamp)].sort((a, b) => a - b))
  })

  it('clips a price to the window and drops one outside it', () => {
    const rows = dynamicChartData(
      [point('2026-09-30T23:00:00Z', '2026-10-01T01:00:00Z', '0.1'), point('2026-10-05T00:00:00Z', '2026-10-05T01:00:00Z', '0.3')],
      [],
      Date.parse('2026-10-01T00:00:00Z'),
      Date.parse('2026-10-02T00:00:00Z'),
    )
    expect(rows).toHaveLength(2)
    expect(rows[0].timestamp).toBe(Date.parse('2026-10-01T00:00:00Z'))
  })
})

describe('defaultHistoryDateRange for the tariff pane', () => {
  const source = { api_version: 'v1.0.5', covers_from: null, covers_to: null } as DynamicTariffSource
  const tariff = { valid_from: '2026-01-01', valid_to: null, minimum_price_chf_per_kwh: null }

  it('looks back a month, so a hole from earlier in the month is found', () => {
    expect(defaultHistoryDateRange(source, '2026-10-28', tariff)).toEqual({ dateFrom: '2026-09-29', dateTo: '2026-10-28' })
  })

  it('stays within the 31-day request cap', () => {
    const { dateFrom, dateTo } = defaultHistoryDateRange(source, '2026-10-28', tariff)
    expect((Date.parse(dateTo) - Date.parse(dateFrom)) / 86_400_000).toBeLessThan(31)
  })

  it('keeps the week for the source admin, which has no tariff', () => {
    expect(defaultHistoryDateRange(source, '2026-10-28')).toEqual({ dateFrom: '2026-10-22', dateTo: '2026-10-28' })
  })

  it('does not reach before the tariff starts', () => {
    expect(defaultHistoryDateRange(source, '2026-10-28', { ...tariff, valid_from: '2026-10-20' }).dateFrom).toBe('2026-10-20')
  })
})
