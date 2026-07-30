import { describe, expect, it } from 'vitest'
import { buildPriceHistory } from '../src/features/tariffs/priceHistory'
import type { TariffPeriod, TariffSeries, TariffVersion } from '../src/types/api'

const TODAY = '2026-07-30'

function ms(day: string): number {
  return Date.parse(`${day}T00:00:00Z`)
}

function period(period_type: TariffPeriod['period_type'], price: string): TariffPeriod {
  return { id: `${period_type}-${price}`, tariff: 't', period_type, price_chf_per_kwh: price }
}

function version(
  valid_from: string,
  valid_to: string | null,
  overrides: Partial<TariffVersion> = {},
): TariffVersion {
  return {
    id: `v-${valid_from}`,
    zev: 'z',
    name: 'T',
    category: 'energy',
    billing_mode: 'energy',
    energy_type: 'local',
    valid_from,
    valid_to,
    periods: [],
    ...overrides,
  }
}

function series(versions: TariffVersion[], overrides: Partial<TariffSeries> = {}): TariffSeries {
  return {
    zev: 'z',
    name: 'T',
    category: 'energy',
    billing_mode: 'energy',
    energy_type: 'local',
    version_count: versions.length,
    active_version_id: null,
    gaps: [],
    // The API returns newest first; the builder must not depend on that.
    versions: [...versions].reverse(),
    ...overrides,
  }
}

describe('buildPriceHistory — energy tariffs', () => {
  it('emits one boundary per version plus a terminal point for the last step', () => {
    const history = buildPriceHistory(series([
      version('2025-01-01', '2025-12-31', { periods: [period('flat', '0.10000')] }),
      version('2026-01-01', null, { periods: [period('flat', '0.12000')] }),
    ]), [], TODAY)

    expect(history.unit).toBe('chf_per_kwh')
    expect(history.bands).toEqual(['flat'])
    expect(history.points.map((point) => point.date)).toEqual(['2025-01-01', '2026-01-01', TODAY])
    expect(history.points.map((point) => point.values.flat)).toEqual([0.1, 0.12, 0.12])
  })

  it('sorts oldest first even though the API returns newest first', () => {
    const history = buildPriceHistory(series([
      version('2024-01-01', '2024-12-31', { periods: [period('flat', '0.08000')] }),
      version('2025-01-01', '2025-12-31', { periods: [period('flat', '0.10000')] }),
      version('2026-01-01', null, { periods: [period('flat', '0.12000')] }),
    ]), [], TODAY)

    expect(history.points.map((point) => point.values.flat)).toEqual([0.08, 0.1, 0.12, 0.12])
  })

  it('keeps HT and NT as separate bands', () => {
    const history = buildPriceHistory(series([
      version('2025-01-01', '2025-12-31', { periods: [period('high', '0.28000'), period('low', '0.18000')] }),
      version('2026-01-01', null, { periods: [period('high', '0.30000'), period('low', '0.19000')] }),
    ]), [], TODAY)

    expect(history.bands).toEqual(['high', 'low'])
    expect(history.points.map((point) => point.values.high)).toEqual([0.28, 0.3, 0.3])
    expect(history.points.map((point) => point.values.low)).toEqual([0.18, 0.19, 0.19])
  })

  it('orders bands flat, high, low regardless of how the periods arrive', () => {
    const history = buildPriceHistory(series([
      version('2025-01-01', null, {
        periods: [period('low', '0.18000'), period('flat', '0.20000'), period('high', '0.28000')],
      }),
      version('2026-01-01', null, { periods: [period('flat', '0.21000')] }),
    ]), [], TODAY)

    expect(history.bands).toEqual(['flat', 'high', 'low'])
  })

  it('nulls a band that a later version dropped, so its line stops', () => {
    const history = buildPriceHistory(series([
      version('2025-01-01', '2025-12-31', { periods: [period('high', '0.28000'), period('low', '0.18000')] }),
      version('2026-01-01', null, { periods: [period('flat', '0.24000')] }),
    ]), [], TODAY)

    expect(history.points.map((point) => point.values.high)).toEqual([0.28, null, null])
    expect(history.points.map((point) => point.values.flat)).toEqual([null, 0.24, 0.24])
  })

  it('breaks the line across a gap instead of implying the old price continued', () => {
    const history = buildPriceHistory(series([
      version('2026-01-01', '2026-03-31', { periods: [period('flat', '0.10000')] }),
      version('2026-05-01', null, { periods: [period('flat', '0.12000')] }),
    ], { gaps: [{ start: '2026-04-01', end: '2026-04-30' }] }), [], TODAY)

    // The run is closed at its real end date, then a null breaks the line.
    expect(history.points.map((point) => [point.date, point.values.flat])).toEqual([
      ['2026-01-01', 0.1],
      ['2026-03-31', 0.1],
      ['2026-04-01', null],
      ['2026-05-01', 0.12],
      [TODAY, 0.12],
    ])
    expect(history.gaps).toEqual([{ from: ms('2026-04-01'), to: ms('2026-04-30') }])
  })

  it('draws a version before a gap across its whole window, not as a dot', () => {
    // Regression: with connectNulls disabled a chart will not draw a segment
    // *into* a null, so without a closing point at the version's real end a
    // nine-month version collapsed to a single dot on its start date.
    const history = buildPriceHistory(series([
      version('2024-01-01', '2024-09-30', { periods: [period('flat', '0.26000')] }),
      version('2025-01-01', null, { periods: [period('flat', '0.31000')] }),
    ], { gaps: [{ start: '2024-10-01', end: '2024-12-31' }] }), [], TODAY)

    const run = history.points.filter((point) => point.values.flat === 0.26)
    expect(run.map((point) => point.date)).toEqual(['2024-01-01', '2024-09-30'])
  })

  it('adds no redundant point between contiguous versions', () => {
    const history = buildPriceHistory(series([
      version('2025-01-01', '2025-12-31', { periods: [period('flat', '0.10000')] }),
      version('2026-01-01', '2026-12-31', { periods: [period('flat', '0.12000')] }),
    ]), [], TODAY)

    expect(history.points.map((point) => point.date)).toEqual([
      '2025-01-01', '2026-01-01', '2026-12-31',
    ])
  })

  it('does not fabricate a terminal point before a version that starts in the future', () => {
    const history = buildPriceHistory(series([
      version('2026-01-01', '2026-06-30', { periods: [period('flat', '0.10000')] }),
      version('2026-08-01', null, { periods: [period('flat', '0.12000')] }),
    ]), [], TODAY)

    // TODAY is 2026-07-30, before the last version opens, so the timeline must
    // stop at that version rather than doubling back to today.
    expect(history.points[history.points.length - 1].date).toBe('2026-08-01')
    expect(history.points.every((point) => point.t <= ms('2026-08-01'))).toBe(true)
  })

  it('does not break the line when versions are exactly contiguous', () => {
    const history = buildPriceHistory(series([
      version('2026-01-01', '2026-06-30', { periods: [period('flat', '0.10000')] }),
      version('2026-07-01', null, { periods: [period('flat', '0.12000')] }),
    ]), [], TODAY)

    expect(history.points.map((point) => point.values.flat)).toEqual([0.1, 0.12, 0.12])
  })

  it('ends at the last version\'s end date rather than today when the series is retired', () => {
    const history = buildPriceHistory(series([
      version('2024-01-01', '2024-06-30', { periods: [period('flat', '0.10000')] }),
      version('2024-07-01', '2024-12-31', { periods: [period('flat', '0.11000')] }),
    ]), [], TODAY)

    expect(history.points[history.points.length - 1].date).toBe('2024-12-31')
  })

  it('treats a version with no price bands as an absent value, not zero', () => {
    const history = buildPriceHistory(series([
      version('2025-01-01', '2025-12-31', { periods: [period('flat', '0.10000')] }),
      version('2026-01-01', null, { periods: [] }),
    ]), [], TODAY)

    expect(history.points.map((point) => point.values.flat)).toEqual([0.1, null, null])
  })
})

describe('buildPriceHistory — fixed fees', () => {
  it('charts the configured amount in CHF', () => {
    const history = buildPriceHistory(series([
      version('2025-01-01', '2025-12-31', { billing_mode: 'monthly_fee', energy_type: null, fixed_price_chf: '5.00' }),
      version('2026-01-01', null, { billing_mode: 'monthly_fee', energy_type: null, fixed_price_chf: '6.50' }),
    ], { billing_mode: 'monthly_fee', energy_type: null }), [], TODAY)

    expect(history.unit).toBe('chf')
    expect(history.bands).toEqual(['amount'])
    expect(history.derived).toBe(false)
    expect(history.points.map((point) => point.values.amount)).toEqual([5, 6.5, 6.5])
  })

  it('handles a negative amount, which is a credit rather than a charge', () => {
    const history = buildPriceHistory(series([
      version('2025-01-01', '2025-12-31', { billing_mode: 'shared_monthly_fee', energy_type: null, fixed_price_chf: '-100.00' }),
      version('2026-01-01', null, { billing_mode: 'shared_monthly_fee', energy_type: null, fixed_price_chf: '-120.00' }),
    ], { billing_mode: 'shared_monthly_fee', energy_type: null }), [], TODAY)

    expect(history.points.map((point) => point.values.amount)).toEqual([-100, -120, -120])
  })
})

describe('buildPriceHistory — percentage of energy', () => {
  const gridSeries = series([
    version('2025-01-01', '2025-12-31', {
      name: 'Grid', energy_type: 'grid', periods: [period('flat', '0.20000')],
    }),
    version('2026-01-01', null, {
      name: 'Grid', energy_type: 'grid', periods: [period('flat', '0.30000')],
    }),
  ], { name: 'Grid', energy_type: 'grid' })

  const pctSeries = series([
    version('2025-01-01', null, {
      name: 'Local', billing_mode: 'percentage_of_energy', percentage: '50.00', periods: [],
    }),
  ], { name: 'Local', billing_mode: 'percentage_of_energy', version_count: 1 })

  it('derives the effective price from the grid tariffs in force at the time', () => {
    const history = buildPriceHistory(pctSeries, [pctSeries, gridSeries], TODAY)

    expect(history.unit).toBe('chf_per_kwh')
    expect(history.bands).toEqual(['effective'])
    expect(history.derived).toBe(true)
    expect(history.points.map((point) => [point.date, point.values.effective])).toEqual([
      ['2025-01-01', 0.1],
      ['2026-01-01', 0.15],
      [TODAY, 0.15],
    ])
  })

  it('steps when the grid price changes even though the percentage never did', () => {
    const history = buildPriceHistory(pctSeries, [pctSeries, gridSeries], TODAY)
    const values = history.points.map((point) => point.values.effective)

    expect(new Set(values).size).toBeGreaterThan(1)
  })

  it('sums several simultaneous grid tariffs, as the engine does', () => {
    const secondGrid = series([
      version('2025-01-01', null, {
        name: 'Netznutzung', energy_type: 'grid', periods: [period('flat', '0.10000')],
      }),
    ], { name: 'Netznutzung', energy_type: 'grid', version_count: 1 })

    const history = buildPriceHistory(pctSeries, [pctSeries, gridSeries, secondGrid], TODAY)

    // 2025: (0.20 + 0.10) x 50% = 0.15
    expect(history.points[0].values.effective).toBe(0.15)
  })

  it('prefers the flat band, then HT, when a grid version has several', () => {
    const htNtGrid = series([
      version('2025-01-01', null, {
        name: 'Grid', energy_type: 'grid',
        periods: [period('high', '0.28000'), period('low', '0.18000')],
      }),
    ], { name: 'Grid', energy_type: 'grid', version_count: 1 })

    const history = buildPriceHistory(pctSeries, [pctSeries, htNtGrid], TODAY)

    // HT is used when no flat band exists: 0.28 x 50% = 0.14
    expect(history.points[0].values.effective).toBe(0.14)
  })

  it('reports the percentage and base in a note for the tooltip', () => {
    const history = buildPriceHistory(pctSeries, [pctSeries, gridSeries], TODAY)

    expect(history.points[0].note).toBe('50% × 0.20000')
  })

  it('yields zero rather than crashing when no grid tariff exists', () => {
    const history = buildPriceHistory(pctSeries, [pctSeries], TODAY)

    expect(history.points.every((point) => point.values.effective === 0)).toBe(true)
  })

  it('shades stretches where the price is zero because nothing backs it', () => {
    // The engine's grid base sum is zero there, so zero really is what would be
    // billed — but unshaded it reads as a price collapse rather than a missing
    // basis.
    const history = buildPriceHistory(pctSeries, [pctSeries], TODAY)

    expect(history.gaps.length).toBeGreaterThan(0)
    expect(history.gaps[0].from).toBe(ms('2025-01-01'))
  })

  it('shades a grid-tariff gap, during which the derived price falls to zero', () => {
    const gappyGrid = series([
      version('2025-01-01', '2025-06-30', {
        name: 'Grid', energy_type: 'grid', periods: [period('flat', '0.20000')],
      }),
      version('2025-09-01', null, {
        name: 'Grid', energy_type: 'grid', periods: [period('flat', '0.30000')],
      }),
    ], { name: 'Grid', energy_type: 'grid' })

    const history = buildPriceHistory(pctSeries, [pctSeries, gappyGrid], TODAY)
    const zeroPoint = history.points.find((point) => point.values.effective === 0)

    expect(zeroPoint?.date).toBe('2025-07-01')
    expect(history.gaps.some((gap) => gap.from === ms('2025-07-01'))).toBe(true)
  })
})
