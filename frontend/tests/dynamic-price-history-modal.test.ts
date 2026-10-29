import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import {
  applyMinimumPrice,
  defaultHistoryDateRange,
  intervalLabel,
  statsFromPoints,
  type TariffValidityContext,
} from '../src/features/tariffs/DynamicPriceHistoryModal'
import type { AppSettings, DynamicPricePoint, DynamicTariffSource } from '../src/types/api'

// defaultHistoryDateRange reads a BFE source's covers_from/covers_to (UTC
// instants marking Europe/Zurich civil-month boundaries) via formatIsoDate's
// local Date getters — the same "viewer's own timezone" convention every
// billing-period picker in this app uses (see lib/dates.ts). That only
// resolves to the intended calendar date for a Zurich-local viewer, so it is
// pinned here the same way date-utils.test.ts pins a fixed zone, rather than
// depending on whatever TZ the machine running the tests happens to have.
const SAVED_TZ = process.env.TZ

beforeAll(() => {
  process.env.TZ = 'Europe/Zurich'
})

afterAll(() => {
  if (SAVED_TZ === undefined) {
    delete process.env.TZ
  } else {
    process.env.TZ = SAVED_TZ
  }
})

const TODAY = '2026-09-14'

const VSE_SOURCE = {
  api_version: 'v1_0_5',
  covers_from: '2026-02-01T00:00:00Z',
  covers_to: '2026-02-28T00:00:00Z',
} as unknown as DynamicTariffSource

const BFE_SOURCE = {
  api_version: 'bfe_rmp',
  // A quarterly source's covered range spans years, in whole local-month
  // steps: Q3 2023 (starting 2023-07-01 Europe/Zurich, CEST = UTC+2) through
  // Q2 2026 (ending 2026-06-30 Europe/Zurich).
  covers_from: '2023-06-30T22:00:00Z',
  covers_to: '2026-06-30T22:00:00Z',
} as unknown as DynamicTariffSource

describe('defaultHistoryDateRange', () => {
  it('defaults a VSE source to the last week ending today', () => {
    expect(defaultHistoryDateRange(VSE_SOURCE, TODAY)).toEqual({
      dateFrom: '2026-09-08',
      dateTo: '2026-09-14',
    })
  })

  it('defaults a BFE reference-price source to its own covered range, not the last week', () => {
    // The last week ending today (2026-09-14) falls in Q3 2026, which BFE
    // has not published yet — that default would show nothing at all.
    expect(defaultHistoryDateRange(BFE_SOURCE, TODAY)).toEqual({
      dateFrom: '2023-07-01',
      dateTo: '2026-06-30',
    })
  })

  it('falls back to the last week for a BFE source with nothing fetched yet', () => {
    const unfetched = { ...BFE_SOURCE, covers_from: null, covers_to: null } as unknown as DynamicTariffSource

    expect(defaultHistoryDateRange(unfetched, TODAY)).toEqual({
      dateFrom: '2026-09-08',
      dateTo: '2026-09-14',
    })
  })

  it('clips a BFE source\'s default range to a tariff that started well after the source\'s history', () => {
    const tariff: TariffValidityContext = {
      valid_from: '2026-04-01', valid_to: null, minimum_price_chf_per_kwh: null,
    }

    expect(defaultHistoryDateRange(BFE_SOURCE, TODAY, tariff)).toEqual({
      dateFrom: '2026-04-01',
      dateTo: '2026-06-30',
    })
  })

  it('falls back to a closed tariff\'s own window when its validity predates the source default', () => {
    // The VSE source's default range (last week ending today) is entirely
    // after this tariff was closed — the tariff's own [valid_from, valid_to]
    // is what "this tariff's price history" actually means here.
    const tariff: TariffValidityContext = {
      valid_from: '2026-01-01', valid_to: '2026-02-15', minimum_price_chf_per_kwh: null,
    }

    expect(defaultHistoryDateRange(VSE_SOURCE, TODAY, tariff)).toEqual({
      dateFrom: '2026-01-01',
      dateTo: '2026-02-15',
    })
  })

  it('looks back a month inside an active, open-ended tariff, so an earlier hole shows', () => {
    const tariff: TariffValidityContext = {
      valid_from: '2026-01-01', valid_to: null, minimum_price_chf_per_kwh: null,
    }

    expect(defaultHistoryDateRange(VSE_SOURCE, TODAY, tariff)).toEqual({
      dateFrom: '2026-08-16',
      dateTo: '2026-09-14',
    })
  })

  it('clamps the default range to today for a not-yet-started tariff, not an empty window', () => {
    const tariff: TariffValidityContext = {
      valid_from: '2026-09-20', valid_to: null, minimum_price_chf_per_kwh: null,
    }

    expect(defaultHistoryDateRange(VSE_SOURCE, TODAY, tariff)).toEqual({
      dateFrom: '2026-09-20',
      dateTo: '2026-09-20',
    })
  })

})

describe('applyMinimumPrice', () => {
  const points: DynamicPricePoint[] = [
    { valid_from: '2026-04-01T00:00:00Z', valid_to: '2026-07-01T00:00:00Z', price_chf_per_kwh: '0.03896' },
    { valid_from: '2026-01-01T00:00:00Z', valid_to: '2026-04-01T00:00:00Z', price_chf_per_kwh: '0.10266' },
  ]

  it('floors a price below the minimum', () => {
    expect(applyMinimumPrice(points, '0.08000')[0].price_chf_per_kwh).toBe('0.08000')
  })

  it('leaves a price at or above the minimum untouched', () => {
    expect(applyMinimumPrice(points, '0.08000')[1].price_chf_per_kwh).toBe('0.10266')
  })

  it('returns the points unchanged when there is no minimum', () => {
    expect(applyMinimumPrice(points, null)).toBe(points)
    expect(applyMinimumPrice(points, '')).toBe(points)
  })
})

describe('statsFromPoints', () => {
  it('computes count, average and negative count from the given points', () => {
    const points: DynamicPricePoint[] = [
      { valid_from: 'a', valid_to: 'b', price_chf_per_kwh: '0.10000' },
      { valid_from: 'b', valid_to: 'c', price_chf_per_kwh: '-0.02000' },
    ]

    expect(statsFromPoints(points, 3)).toEqual({
      point_count: 2,
      minimum_chf_per_kwh: '-0.02000',
      maximum_chf_per_kwh: '0.10000',
      average_chf_per_kwh: '0.04000',
      negative_count: 1,
      gap_count: 3,
    })
  })

  it('reports an empty series without dividing by zero', () => {
    expect(statsFromPoints([], 1)).toEqual({
      point_count: 0,
      minimum_chf_per_kwh: null,
      maximum_chf_per_kwh: null,
      average_chf_per_kwh: null,
      negative_count: 0,
      gap_count: 1,
    })
  })
})

describe('intervalLabel', () => {
  const settings = { date_format_short: 'dd.MM.yyyy', date_time_format: 'dd.MM.yyyy HH:mm' } as AppSettings

  it('names the day once when an interval ends on the day it starts', () => {
    expect(intervalLabel('2026-10-01T00:00:00+02:00', '2026-10-01T00:15:00+02:00', settings))
      .toBe('01.10.2026 00:00 – 00:15')
  })

  it('repeats the date when the interval ends on another day', () => {
    expect(intervalLabel('2026-10-01T23:45:00+02:00', '2026-10-02T00:00:00+02:00', settings))
      .toBe('01.10.2026 23:45 – 02.10.2026 00:00')
  })

  it('compares days in the business timezone, not UTC', () => {
    // 22:00Z and 22:15Z are both on 2 October in Zurich (CEST).
    expect(intervalLabel('2026-10-01T22:00:00Z', '2026-10-01T22:15:00Z', settings))
      .toBe('02.10.2026 00:00 – 00:15')
  })

  it('follows the configured date format', () => {
    expect(intervalLabel('2026-10-01T00:00:00+02:00', '2026-10-01T00:15:00+02:00', { ...settings, date_time_format: 'yyyy-MM-dd HH:mm' }))
      .toBe('2026-10-01 00:00 – 00:15')
  })
})
